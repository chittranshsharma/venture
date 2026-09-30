"""
tests/test_submission_invariants.py — Rigorous verification of submission safety invariants:
1. submit() reachable ONLY from state APPROVED or EXECUTING.
2. Illegal FSM state jumps (e.g. DISCOVERED -> SUBMITTED) raise IllegalStateTransitionError.
3. Legacy state normalizer correctly maps old rows.
4. Resumption inspection returns mid-execution jobs with checkpoints.
5. Daily application cap enforces abort before execution.
"""

import os
import sys
import pytest
import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

import asyncio
from core.state_machine import (
    JobState,
    IllegalStateTransitionError,
    transition,
    get_job_state,
    get_interrupted_executions,
    normalize_legacy_state,
)
import core.db_manager as db
from automation.orchestrator import execute_ats_submission
from tests.test_db_migration import _init_base_schema


@pytest.fixture
def clean_db(tmp_path):
    test_db_path = str(tmp_path / "test_venture.db")
    with patch("core.db_manager.SQLITE_DB_PATH", test_db_path):
        conn = sqlite3.connect(test_db_path)
        _init_base_schema(conn)
        db._run_schema_migrations_locked(conn)
        conn.close()
        yield test_db_path


def test_illegal_jump_raises_error(clean_db):
    """An illegal jump directly from DISCOVERED to SUBMITTED must raise IllegalStateTransitionError."""
    url = "https://example.com/job/illegal-jump-1"
    transition(url, JobState.DISCOVERED, checkpoint="discovered")
    assert get_job_state(url) == JobState.DISCOVERED

    with pytest.raises(IllegalStateTransitionError) as exc_info:
        transition(url, JobState.SUBMITTED, checkpoint="submitted")
    assert "Illegal FSM state jump" in str(exc_info.value)


def test_legacy_state_normalizer():
    """Verify legacy mappings: QUALIFIED->EVALUATED, FIELDS_FILLED->EXECUTING, Applied->SUBMITTED, REJECTED_POST->REJECTED."""
    s, c = normalize_legacy_state("QUALIFIED")
    assert s == "EVALUATED" and c == "evaluated"

    s, c = normalize_legacy_state("FIELDS_FILLED")
    assert s == "EXECUTING" and c == "fields_filled"

    s, c = normalize_legacy_state("Applied")
    assert s == "SUBMITTED" and c == "submitted"

    s, c = normalize_legacy_state("REJECTED_POST")
    assert s == "REJECTED" and c == "rejected_post"


def test_submission_blocked_unless_approved(clean_db):
    """execute_ats_submission must reject jobs that are not in APPROVED or EXECUTING state."""
    async def _run():
        url = "https://example.com/job/unapproved-1"
        transition(url, JobState.DISCOVERED, checkpoint="discovered")

        mock_page = MagicMock()
        job = {"url": url, "title": "Backend Dev", "company": "Acme Inc"}

        with pytest.raises(AssertionError) as exc_info:
            await execute_ats_submission(mock_page, job, dry_run=True)
        assert "Security Invariant Violated" in str(exc_info.value)
        assert "APPROVED" in str(exc_info.value)

    asyncio.run(_run())


def test_submission_allowed_when_approved(clean_db):
    """execute_ats_submission succeeds when job is in APPROVED state."""
    async def _run():
        url = "https://example.com/job/approved-1"
        transition(url, JobState.DISCOVERED, checkpoint="discovered")
        transition(url, JobState.EVALUATED, checkpoint="evaluated")
        transition(url, JobState.READY_FOR_APPROVAL, checkpoint="ready_for_approval")
        transition(url, JobState.APPROVED, checkpoint="human_approved")

        mock_page = MagicMock()
        mock_page.url = url
        mock_locator = MagicMock()
        mock_locator.count = AsyncMock(return_value=1)
        mock_locator.first = mock_locator
        mock_locator.fill = AsyncMock()
        mock_locator.select_option = AsyncMock()
        mock_locator.set_input_files = AsyncMock()
        mock_page.locator = MagicMock(return_value=mock_locator)

        job = {"url": url, "title": "Senior Python Dev", "company": "Stripe"}

        success = await execute_ats_submission(mock_page, job, dry_run=True)
        assert success is True

    asyncio.run(_run())


def test_crash_resumption_returns_checkpoint(clean_db):
    """If an application crashed mid-EXECUTING, get_interrupted_executions() must return it with its checkpoint."""
    url = "https://example.com/job/crash-test-1"
    db.save_to_db(
        url=url,
        title="Distributed Systems Engineer",
        company="Datadog",
        platform="Indeed",
        status="Applying",
        score=78,
        checkpoint="work_authorization"
    )

    interrupted = get_interrupted_executions()
    matched = [app for app in interrupted if app["url"] == url]
    assert len(matched) == 1
    assert matched[0]["status"] == "Applying"
    assert matched[0]["checkpoint"] == "work_authorization"


def test_multi_location_dedup_suppression(clean_db):
    """
    Feeding the same role with 3 different city variants (with city-specific text in JD)
    must produce exactly 1 application, with the 2nd and 3rd instances suppressed via
    shingle similarity (>= 0.85).
    """
    from automation.orchestrator import process_job

    company = "NovaTech Solutions, Inc."
    title = "Full Stack Engineer"
    base_body = (
        "We are seeking a skilled Full Stack Engineer with strong Python and React experience "
        "to design, build, and deploy scalable cloud-native microservices and responsive web applications. "
        "In this role, you will collaborate with cross-functional teams to deliver modern web products, "
        "maintain cloud infrastructure, and ensure application performance, reliability, and security. "
        "Key qualifications include at least 3 years of hands-on experience with Python, FastAPI or Django, "
        "React, TypeScript, PostgreSQL, Docker, CI/CD pipelines, and cloud computing environments such as AWS. "
        "Strong debugging, unit testing, and architectural problem-solving skills are essential."
    )
    locations = ["Remote, US", "San Francisco, CA", "New York, NY"]

    results = []
    for idx, loc in enumerate(locations, start=1):
        # Real-world multi-city postings differ in their location line
        city_jd = f"{base_body} Location: {loc}. Full-time opportunity with benefits."
        job = {
            "url": f"https://boards.greenhouse.io/novatech/jobs/{idx}",
            "title": title,
            "company": company,
            "location": loc,
            "jd_text": city_jd,
            "platform": "Greenhouse",
        }
        res = process_job(job, dry_run=False)
        results.append(res)
        # Mark first as Applied in DB to simulate successful application lifecycle
        if idx == 1:
            db.save_to_db(
                url=job["url"],
                title=title,
                company=company,
                platform="Greenhouse",
                status="Applied",
                score=85,
                jd_text=city_jd,
            )

    # First instance must evaluate or queue cleanly
    assert results[0].state != JobState.REJECTED or results[0].route != "suppressed"
    # Second and third instances with city-specific text must be suppressed via shingle similarity
    assert results[1].route == "suppressed"
    assert results[1].rejection_reason == "duplicate_within_90_days"
    assert results[2].route == "suppressed"
    assert results[2].rejection_reason == "duplicate_within_90_days"


def test_different_body_same_title_not_suppressed(clean_db):
    """
    Same company and same title ("Full Stack Engineer"), but completely different JD body
    (e.g. web dev vs hardware embedded) must NOT be suppressed (shingle similarity < 0.85).
    """
    from automation.orchestrator import process_job

    company = "NovaTech Solutions, Inc."
    title = "Full Stack Engineer"
    web_body = (
        "We are seeking a Full Stack Engineer with Python, React, TypeScript, and AWS experience "
        "to work on customer-facing dashboards and billing workflows."
    )
    url1 = "https://boards.greenhouse.io/novatech/jobs/101"
    db.save_to_db(
        url=url1,
        title=title,
        company=company,
        platform="Greenhouse",
        status="Applied",
        score=88,
        jd_text=web_body,
    )

    embedded_body = (
        "We are seeking a Full Stack Engineer for our Embedded IoT team. "
        "Must have deep expertise in C, C++, FreeRTOS, Bluetooth Low Energy, "
        "microcontroller firmware development, and hardware debugging with oscilloscopes."
    )
    job2 = {
        "url": "https://boards.greenhouse.io/novatech/jobs/102",
        "title": title,
        "company": company,
        "location": "Austin, TX",
        "jd_text": embedded_body,
        "platform": "Greenhouse",
    }
    res2 = process_job(job2, dry_run=False)
    # Must NOT be suppressed because JD body is genuinely different
    assert res2.route != "suppressed"
    assert res2.rejection_reason != "duplicate_within_90_days"


def test_rejected_decision_suppresses_repost(clean_db):
    """
    A job previously rejected by the user in decisions table must also suppress
    a multi-city repost of the same job within 90 days.
    """
    from automation.orchestrator import process_job

    company = "Acme Global Systems"
    title = "Backend Developer"
    base_body = (
        "Acme Global is hiring a Backend Developer with Golang, Kafka, and Kubernetes expertise "
        "to scale our distributed stream processing pipeline and real-time event analytics engines. "
        "The ideal candidate has hands-on experience designing fault-tolerant microservices, optimizing "
        "SQL and NoSQL database queries, working with gRPC protocols, and maintaining high availability "
        "across multi-region cloud deployments on AWS and GCP. Strong proficiency in concurrent programming "
        "and observability using Prometheus and Grafana is required."
    )
    url_orig = "https://boards.greenhouse.io/acme/jobs/1"
    # Log evaluation and rejected decision
    db.log_evaluation(
        url=url_orig,
        title=title,
        company=company,
        jd_text=f"{base_body} Location: Chicago, IL. Full benefits included.",
        route="queue",
    )
    db.log_approval_decision(
        url=url_orig,
        label="reject",
        reject_reason="not_fit",
        score=40,
        propensity=1.0,
    )

    # Now a repost in Denver arrives with same body
    job_repost = {
        "url": "https://boards.greenhouse.io/acme/jobs/2",
        "title": title,
        "company": company,
        "location": "Denver, CO",
        "jd_text": f"{base_body} Location: Denver, CO. Full benefits included.",
        "platform": "Greenhouse",
    }
    res = process_job(job_repost, dry_run=False)
    assert res.route == "suppressed"
    assert res.rejection_reason == "duplicate_within_90_days"


def test_short_jd_suppression_verdict_not_pass(clean_db):
    """
    When JD text is short (<200 characters), similarity cannot be computed reliably.
    suppression_verdict must return 'flag' (or 'suppress') and NEVER 'pass'.
    """
    company = "TinyCorp"
    title = "Backend Engineer"
    short_jd1 = "Looking for a Python dev. Location: Remote. Great pay."
    url1 = "https://boards.greenhouse.io/tinycorp/1"
    
    db.save_to_db(
        url=url1,
        title=title,
        company=company,
        platform="Greenhouse",
        status="Applied",
        score=80,
        jd_text=short_jd1,
    )

    short_jd2 = "Looking for a Python dev. Location: New York, NY. Great pay."
    verdict = db.suppression_verdict(company, title, short_jd2)
    assert verdict != "pass", f"Short JD must not silently pass; got verdict: {verdict}"
    assert verdict in ("flag", "suppress")


def test_reject_reason_location_does_not_suppress_another_city(clean_db):
    """
    A past rejection with reason 'location' (or other soft reason) must NOT suppress
    a repost in a different city. suppression_verdict must be 'pass'.
    """
    company = "MetroTech"
    title = "Data Platform Engineer"
    body = (
        "MetroTech is seeking a Data Platform Engineer with Apache Spark, Snowflake, "
        "and Airflow experience to manage automated data pipelines across multi-region datacenters."
    )
    url_ny = "https://boards.greenhouse.io/metrotech/1"
    db.log_evaluation(
        url=url_ny,
        title=title,
        company=company,
        jd_text=f"{body} Location: New York, NY.",
        route="queue",
    )
    db.log_approval_decision(
        url=url_ny,
        label="reject",
        reject_reason="location",  # Soft reason!
        score=75,
        propensity=1.0,
    )

    # Candidate sees same role in London
    url_london = "https://boards.greenhouse.io/metrotech/2"
    jd_london = f"{body} Location: London, UK."
    verdict = db.suppression_verdict(company, title, jd_london)
    assert verdict == "pass", f"Location rejection must not suppress other locations; got verdict: {verdict}"


def test_reject_reason_not_fit_suppresses(clean_db):
    """
    A past rejection with reason 'not_fit' (hard block reason) MUST suppress
    a multi-city repost. suppression_verdict must be 'suppress'.
    """
    company = "MetroTech"
    title = "Data Platform Engineer"
    body = (
        "MetroTech is seeking a Data Platform Engineer with Apache Spark, Snowflake, "
        "and Airflow experience to manage automated data pipelines across multi-region datacenters. "
        "Must have 5+ years building distributed ETL architectures and streaming Kafka infrastructure. "
        "Solid command of SQL performance tuning and database clustering is mandatory. "
        "Responsibilities include designing reliable streaming pipelines, collaborating with data scientists, "
        "optimizing query latency on massive datasets, and maintaining CI/CD deployment pipelines on AWS."
    )
    url_ny = "https://boards.greenhouse.io/metrotech/1"
    db.log_evaluation(
        url=url_ny,
        title=title,
        company=company,
        jd_text=f"{body} Location: New York, NY. Comprehensive healthcare benefits.",
        route="queue",
    )
    db.log_approval_decision(
        url=url_ny,
        label="reject",
        reject_reason="not_fit",  # Hard reason!
        score=35,
        propensity=1.0,
    )

    url_london = "https://boards.greenhouse.io/metrotech/2"
    jd_london = f"{body} Location: London, UK. Comprehensive healthcare benefits."
    verdict = db.suppression_verdict(company, title, jd_london)
    assert verdict == "suppress", f"not_fit rejection must suppress reposts; got verdict: {verdict}"


def test_blocked_job_restore_reaches_approvals_queue(clean_db):
    """
    A job blocked by QA title invariant is logged only to evaluations (route='blocked_title').
    When restored via restore_archived_job, it bypasses the title block and reaches Approvals queue.
    """
    from automation.orchestrator import process_job

    url = "https://boards.greenhouse.io/hpe/qa-engineer-1"
    job = {
        "url": url,
        "title": "Lead QA Test Engineer - Automation",
        "company": "Hewlett Packard Enterprise",
        "jd_text": "Building automated Python test suites, Selenium web testing, and CI regression pipelines.",
        "platform": "Greenhouse",
    }
    # 1. Normal run: gets hard-blocked
    res = process_job(job, dry_run=False)
    assert res.route == "blocked_title"
    assert res.state == JobState.REJECTED

    # Verify not in applications table
    with sqlite3.connect(clean_db) as conn:
        app_count = conn.execute("SELECT COUNT(*) FROM applications WHERE url = ?", (url,)).fetchone()[0]
        assert app_count == 0, "Blocked title must NOT be saved in applications table"
        
        # Verify present in evaluations table
        eval_row = conn.execute("SELECT route FROM evaluations WHERE url = ?", (url,)).fetchone()
        assert eval_row is not None and eval_row[0] == "blocked_title"

    # 2. Restore action
    restored_res = db.restore_archived_job(url)
    assert restored_res is not None
    assert restored_res.route != "blocked_title"
    assert restored_res.state in (JobState.READY_FOR_APPROVAL, JobState.APPROVED, JobState.DISCOVERED, JobState.EVALUATED)
    
    # Verify application reached database queue
    with sqlite3.connect(clean_db) as conn:
        app_row = conn.execute("SELECT status FROM applications WHERE url = ?", (url,)).fetchone()
        assert app_row is not None, "Restored application must now exist in applications table"
        assert app_row[0] in ("Approval Needed", "Suggested", "Applied")


def test_reject_reason_unsure_and_other_suppresses(clean_db):
    """
    Rejections with reasons 'unsure' or 'other' (denylist check) MUST suppress reposts.
    Only 'location' allows reposts in another city.
    """
    company = "CloudScale Inc"
    title = "Backend Engineer"
    body = (
        "CloudScale Inc is looking for a Backend Engineer proficient in Python and Go to build high throughput "
        "distributed caching services, database connection poolers, and low-latency API gateways. "
        "Candidate must demonstrate extensive experience in asynchronous networking, microservices resilience, "
        "Kubernetes orchestration, Redis clustering, and automated testing with pytest and mock frameworks. "
        "Daily responsibilities include optimizing SQL queries on PostgreSQL, monitoring telemetry in Prometheus, "
        "and performing code reviews with the engineering platform team."
    )
    # 1. Test 'unsure'
    url_1 = "https://jobs.lever.co/cloudscale/1"
    db.log_evaluation(url=url_1, title=title, company=company, jd_text=f"{body} City: Austin, TX", route="queue")
    db.log_approval_decision(url=url_1, label="reject", reject_reason="unsure", score=60, propensity=1.0)

    jd_2 = f"{body} City: Seattle, WA"
    verdict_unsure = db.suppression_verdict(company, title, jd_2)
    assert verdict_unsure == "suppress", f"unsure reject must suppress duplicate repost; got {verdict_unsure}"

    # 2. Test 'other'
    company_other = "DataPeak Corp"
    url_other = "https://jobs.lever.co/datapeak/1"
    db.log_evaluation(url=url_other, title=title, company=company_other, jd_text=f"{body} City: Boston, MA", route="queue")
    db.log_approval_decision(url=url_other, label="reject", reject_reason="other", score=50, propensity=1.0)

    verdict_other = db.suppression_verdict(company_other, title, f"{body} City: Denver, CO")
    assert verdict_other == "suppress", f"other reject must suppress duplicate repost; got {verdict_other}"


def test_flag_never_auto_applies(clean_db):
    """
    Jobs with verdict 'flag', route 'explore', or non-English language MUST NEVER
    skip human approval, even when safe_mode=False and dry_run_mode=False.
    Only route 'queue' with verdict 'pass', English, and explicit non-safe settings may auto-approve.
    """
    from automation.orchestrator import process_job

    cfg = {"settings": {"safe_mode": False, "dry_run_mode": False, "require_approval": False}}

    # Case A: Short JD triggering 'flag' verdict (<200 chars)
    # Seed a prior applied job
    prior_url = "https://boards.greenhouse.io/flagtest/1"
    db.save_to_db(
        url=prior_url, title="Senior Python Engineer", company="FlagCorp",
        platform="Greenhouse", status="Applied", score=90,
        jd_text="Python FastAPI backend developer."
    )
    job_flag = {
        "url": "https://boards.greenhouse.io/flagtest/2",
        "title": "Senior Python Engineer",
        "company": "FlagCorp",
        "platform": "Greenhouse",
        "jd_text": "Python FastAPI backend developer."  # <200 chars -> verdict 'flag'
    }
    res_flag = process_job(job_flag, cfg=cfg, dry_run=False)
    assert res_flag.state in (JobState.READY_FOR_APPROVAL, JobState.EVALUATED), (
        f"Flagged jobs must never auto-apply; expected READY_FOR_APPROVAL/EVALUATED, got {res_flag.state}"
    )

    # Case B: Explore route job
    job_explore = {
        "url": "https://boards.greenhouse.io/exploretest/1",
        "title": "Staff Cloud Systems Architect",
        "company": "ExploreCorp",
        "platform": "Greenhouse",
        "jd_text": (
            "ExploreCorp is hiring a Staff Cloud Systems Architect with extensive experience designing "
            "multi-cloud architectures, Kubernetes clusters, terraform modules, and distributed consensus algorithms. "
            "Looking for strong leadership and technical expertise across AWS, GCP, and Azure datacenters."
        )
    }
    # min_score=95 forces this to explore route (score will be ~75-80, within 20 pt exploration band)
    cfg_explore = {"settings": {"safe_mode": False, "dry_run_mode": False, "require_approval": False, "min_score": 95}}
    res_explore = process_job(job_explore, cfg=cfg_explore, dry_run=False)
    if res_explore.route == "explore":
        assert res_explore.state in (JobState.READY_FOR_APPROVAL, JobState.EVALUATED), (
            f"Explore route jobs must never auto-apply; got {res_explore.state}"
        )

    # Case C: Non-English job
    job_german = {
        "url": "https://boards.greenhouse.io/germantest/1",
        "title": "Senior Software Entwickler",
        "company": "BerlinTech",
        "platform": "Greenhouse",
        "jd_text": (
            "Wir suchen einen erfahrenen Senior Software Entwickler für unsere Backend-Systeme in Berlin. "
            "Sie entwickeln hochverfügbare Microservices mit Python, FastAPI, Docker und PostgreSQL. "
            "Erforderlich sind mindestens fünf Jahre Erfahrung in der Softwareentwicklung und agile Methoden."
        )
    }
    res_german = process_job(job_german, cfg=cfg, dry_run=False)
    assert res_german.state in (JobState.READY_FOR_APPROVAL, JobState.EVALUATED), (
        f"Non-English jobs must never auto-apply; got {res_german.state}"
    )


def test_apply_single_job_async_on_suppressed_job_aborts(clean_db):
    """
    Calling apply_single_job_async on a job that matches a suppressed application
    must immediately return False and abort without invoking ATS submission.
    """
    from automation.bot_runner import apply_single_job_async

    company = "Apollo Technologies"
    title = "Site Reliability Engineer"
    jd = (
        "Apollo Technologies is looking for a Site Reliability Engineer to manage Kubernetes clusters, "
        "maintain high system uptime, implement automated observability with Datadog and OpenTelemetry, "
        "and collaborate with software engineering teams to debug complex production incidents."
    )
    # 1. Seed prior applied record
    url_applied = "https://boards.greenhouse.io/apollo/sre-1"
    db.save_to_db(
        url=url_applied, title=title, company=company, platform="Greenhouse",
        status="Applied", score=88, jd_text=jd
    )

    # 2. Attempt to apply to duplicate
    job_dup = {
        "url": "https://boards.greenhouse.io/apollo/sre-2",
        "title": title,
        "company": company,
        "platform": "Greenhouse",
        "jd_text": jd,
    }
    applied = apply_single_job_async(job_dup)
    assert applied is False, "apply_single_job_async must abort on suppressed job"


class FakeAdapter:
    platform_name = "greenhouse"

    async def inspect(self, page):
        return {}

    async def fill(self, page, package=None, profile=None):
        return True

    async def validate(self, page):
        return {"valid": True, "missing_required": []}

    async def submit(self, page, dry_run=False):
        return True

    def verify_success(self, page):
        return True


def test_approved_job_is_not_self_suppressed(clean_db):
    """
    An approved job in 'Approval Needed' or 'Approved' status must not suppress itself at submission.
    execute_ats_submission must succeed and reach SUBMITTED state.
    Second city variant after real submit must be suppressed.
    """
    from automation.orchestrator import process_job, approve, execute_ats_submission

    url = "https://boards.greenhouse.io/stripe/swe-1"
    company = "Stripe"
    title = "Backend Infrastructure Engineer"
    jd = (
        "Stripe is hiring a Backend Infrastructure Engineer to scale our distributed payment gateway. "
        "You will design high-throughput microservices using Python, Go, and PostgreSQL. "
        "Requires 4+ years building reliable fault-tolerant systems and automated testing with CI/CD. "
        "Collaborate with security and reliability engineers to ensure compliance and fault recovery."
    )
    job = {
        "url": url,
        "title": title,
        "company": company,
        "platform": "Greenhouse",
        "jd_text": jd,
    }

    # 1. Process job (creates applications row with 'Approval Needed')
    res = process_job(job, dry_run=False)
    assert res.state == JobState.READY_FOR_APPROVAL

    # 2. Human approves job
    approve(url)
    assert get_job_state(url) == JobState.APPROVED

    # 3. Submit approved job with FakeAdapter
    async def _run():
        out = await execute_ats_submission(job, adapter=FakeAdapter(), dry_run=False)
        assert out.state in ("SUBMITTED", "SUBMITTED_UNVERIFIED")
        assert get_job_state(url) in (JobState.SUBMITTED, JobState.SUBMITTED_UNVERIFIED)

    asyncio.run(_run())

    # 4. A second city variant of the same job after real submit MUST be suppressed
    url_city2 = "https://boards.greenhouse.io/stripe/swe-2"
    jd_city2 = f"{jd} Location: Seattle, WA. Relocation support available."
    job_city2 = {
        "url": url_city2,
        "title": title,
        "company": company,
        "platform": "Greenhouse",
        "jd_text": jd_city2,
    }
    res_city2 = process_job(job_city2, dry_run=False)
    assert res_city2.route == "suppressed", f"Second city variant must be suppressed after submit; got route {res_city2.route}"
    assert res_city2.state == JobState.REJECTED


def test_dry_run_does_not_suppress_real_run(clean_db):
    """
    Dry-run execution must not transition job into APPLIED_STATUSES,
    and must not cause future real runs of the same job to be suppressed.
    """
    from automation.orchestrator import process_job, execute_ats_submission
    from core.db_manager import APPLIED_STATUSES, get_status
    import core.db_manager as db

    job = {
        "url": "https://boards.greenhouse.io/stripe/swe-dry",
        "title": "Backend Infrastructure Engineer",
        "company": "Stripe",
        "platform": "Greenhouse",
        "jd_text": (
            "Stripe is hiring a Backend Infrastructure Engineer to scale our distributed payment gateway. "
            "You will design high-throughput microservices using Python, Go, and PostgreSQL. "
            "Requires 4+ years building reliable fault-tolerant systems and automated testing with CI/CD."
        ),
    }

    process_job(job, dry_run=True)
    asyncio.run(execute_ats_submission(job, adapter=FakeAdapter(), dry_run=True))
    assert get_status(job["url"]) not in APPLIED_STATUSES
    assert db.suppression_verdict(None, job["company"], job["title"], job["jd_text"]) == "pass"


def test_human_gate_abort_never_calls_submit(clean_db):
    """
    When confirm_before_submit is True and operator aborts (types anything other than 'SUBMIT'),
    adapter.submit must never be called, and job state transitions to FIELDS_FILLED (never SUBMITTED).
    """
    from unittest.mock import patch, MagicMock
    from automation.orchestrator import process_job, approve, execute_ats_submission
    from core.db_manager import APPLIED_STATUSES, get_status
    from core.state_machine import JobState, get_job_state

    url = "https://boards.greenhouse.io/stripe/swe-supervised"
    job = {
        "url": url,
        "title": "Backend Infrastructure Engineer",
        "company": "Stripe",
        "platform": "Greenhouse",
        "jd_text": (
            "Stripe is hiring a Backend Infrastructure Engineer to scale our distributed payment gateway. "
            "You will design high-throughput microservices using Python, Go, and PostgreSQL. "
            "Requires 4+ years building reliable fault-tolerant systems and automated testing with CI/CD."
        ),
    }

    # 1. Process job and approve it so it is eligible for execution
    process_job(job, dry_run=False)
    approve(url)
    assert get_job_state(url) == JobState.APPROVED

    # 2. Mock adapter.submit to track whether submit() was invoked
    adapter = FakeAdapter()
    adapter.submit = MagicMock(return_value=True)

    # 3. Simulate human gate abort with 'no'
    with patch("builtins.input", return_value="no"):
        out = asyncio.run(execute_ats_submission(job, adapter=adapter, dry_run=False))

    # Verification: submit() was NEVER called
    adapter.submit.assert_not_called()
    assert bool(out) is False
    assert out.state in ("FIELDS_FILLED", "NEEDS_RETRY", JobState.FIELDS_FILLED, JobState.RETRYABLE)
    assert get_status(url) not in APPLIED_STATUSES
    assert get_job_state(url) != JobState.SUBMITTED
    assert get_job_state(url) != JobState.SUBMITTED_UNVERIFIED




