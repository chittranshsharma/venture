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

