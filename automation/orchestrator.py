"""
automation/orchestrator.py — The Central VENTURE Pipeline Orchestrator.

One authoritative flow: process_job(job, ...)
Enforces the lifecycle:
DISCOVERED
  ↓
NORMALIZE + DEDUP
  ↓
DETERMINISTIC EVALUATION (3-Tier Invariants + Signals)
  ├── HARD BLOCK → ARCHIVE (0 LLM)
  ├── LOW FIT → SKIP (0 LLM)
  ├── UNCERTAIN / STRETCH → LOCAL LLM (Ambiguity Resolution)
  └── HIGH FIT → PREPARE
              ↓
      APPLICATION PREP (Versioned Package: Resume, Cover Letter, Answers)
              ↓
      READY FOR APPROVAL
              ↓
      (HUMAN APPROVAL)
              ↓
      ATS EXECUTION (Greenhouse / Lever / Ashby Specialist Adapters)
              ↓
          SUBMITTED
              ↓
       OUTCOME TRACKING
"""

import asyncio
from dataclasses import dataclass, asdict
from datetime import datetime
import json
import logging
from typing import Any, Dict, Optional

from core.config_manager import CONFIG, load_config
import core.db_manager as db
from core.state_machine import JobState, transition, is_job_completed, get_job_state
import core.state as state
from automation.composite_scorer import evaluate_opportunity, should_invoke_llm, EvaluationSignals
from automation.llm_evaluator import evaluate_job_with_qwen
from automation.prep_engine import prepare_application_package, ApplicationPackage
from automation.specialists.registry import get_ats_adapter

logger = logging.getLogger(__name__)


@dataclass
class JobLifecycleResult:
    url: str
    title: str
    company: str
    state: str
    score: int
    route: str
    is_stretch: bool
    rejection_reason: Optional[str]
    package: Optional[Dict[str, Any]]
    decision_reason: str
    checkpoint: str
    telemetry: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def process_job(
    job: Dict[str, Any],
    cfg: Optional[Dict[str, Any]] = None,
    dry_run: Optional[bool] = None,
    auto_prepare: bool = True,
    skip_title_block: bool = False,
) -> JobLifecycleResult:
    """
    Authoritative single-entrypoint for processing an opportunity across all stages.
    Can be called synchronously or run via asyncio.to_thread / run_in_executor.
    """
    if cfg is None:
        cfg = CONFIG or load_config()

    if dry_run is None:
        dry_run = bool(cfg.get("settings", {}).get("dry_run_mode", True))

    title = (job.get("title") or "Unknown Role").strip()
    raw_comp = str(job.get("company") or "").strip()
    company = "" if raw_comp.lower() in ("nan", "none", "null", "undefined") else raw_comp
    url = (job.get("url") or "").strip()
    desc_text = (job.get("description") or job.get("jd_text") or "").strip()
    platform = job.get("platform") or "Web"

    # Step 1: Normalize & Deduplicate
    dk = job.get("dedup_key") or db.compute_dedup_key(company, title)
    ch = job.get("content_hash") or db.compute_content_hash(desc_text or title)
    job["dedup_key"] = dk
    job["content_hash"] = ch

    if url and is_job_completed(url):
        current_state = db.get_state(url) or JobState.SUBMITTED
        chk = db.get_checkpoint(url)
        db.log_message(f"Dedup Skip: Job '{title}' at '{company}' already completed ({current_state}).")
        return JobLifecycleResult(
            url=url, title=title, company=company, state=current_state,
            score=0, route="completed", is_stretch=False,
            rejection_reason="already_completed", package=None,
            decision_reason="Job was already submitted or in terminal state.",
            checkpoint=chk, telemetry={"dedup_key": dk, "content_hash": ch}
        )

    if url:
        snapshot = db.get_application(url)
        current = get_job_state(url)
        if current in (JobState.READY_FOR_APPROVAL, JobState.APPROVED, JobState.EXECUTING,
                       JobState.FIELDS_FILLED, JobState.RETRYABLE, JobState.PREPARING):
            db.log_message(f"Discovery preserved existing application ({current}): {url}")
            return JobLifecycleResult(
                url=url, title=title, company=company, state=current, score=snapshot.get("score") or 0,
                route="pending", is_stretch=False, rejection_reason=None, package=None,
                decision_reason="Existing application awaits review or execution; discovery did not reset it.",
                checkpoint=snapshot.get("checkpoint") or "discovered", telemetry={"dedup_key": dk, "content_hash": ch},
            )

    verdict = db.suppression_verdict(None, company, title, desc_text, exclude_url=url)
    if verdict == "suppress":
        db.log_message(f"Dedup Suppression: Job '{title}' at '{company}' already applied or rejected within 90 days.")
        return JobLifecycleResult(
            url=url, title=title, company=company, state=JobState.REJECTED,
            score=0, route="suppressed", is_stretch=False,
            rejection_reason="duplicate_within_90_days", package=None,
            decision_reason="Suppressed: similar job applied or rejected within 90 days.",
            checkpoint="duplicate_suppressed", telemetry={"dedup_key": dk, "content_hash": ch}
        )
    is_duplicate_flag = (verdict == "flag")
    if is_duplicate_flag:
        db.log_message(f"Dedup Flag: Job '{title}' at '{company}' flagged as possible duplicate within 90 days.")

    # Step 2: 3-Tier Constraint & Free Signal Evaluation
    signals: EvaluationSignals = evaluate_opportunity(title, company, desc_text, cfg=cfg)

    # If restored from archive by human, bypass the title hard block
    if skip_title_block and signals.hard_block and signals.hard_reason == "qa_test_title":
        signals.hard_block = False
        signals.hard_reason = None
        min_sc = cfg.get("settings", {}).get("min_score", 70)
        signals.route = "queue" if signals.deterministic_score >= min_sc else ("explore" if signals.deterministic_score >= min_sc - 20 else "queue")

    # If flagged as possible duplicate, tag it clearly in reasons and telemetry
    if is_duplicate_flag:
        signals.penalties.append({"type": "duplicate_warning", "badge": f"[Possible duplicate of {company} / {title}]"})
        if signals.top_bullets is not None:
            signals.top_bullets.insert(0, f"[Possible duplicate of {company} / {title}]")

    # Tier-1 Hard Invariants: Instant Archive
    if signals.hard_block:
        route_name = signals.route or ("blocked_title" if signals.hard_reason == "qa_test_title" else "constraint")
        hard_reason_str = f"Tier-1 Invariant Hard Block: {signals.hard_reason}"
        db.log_message(f"⛔ Hard Block [{signals.hard_reason}]: Auto-Archived '{title}' at '{company}' (route={route_name})")
        features_json_str = json.dumps(signals.to_features_dict())
        
        if url and not dry_run:
            # Log blocked titles ONLY in evaluations table (route='blocked_title')
            # and NEVER in applications table to avoid dashboard metrics pollution.
            db.log_evaluation(
                url=url, title=title, company=company, jd_text=desc_text,
                llm_score=0, rag_score=0.0, seniority="entry", skill_overlap=0.0,
                route=route_name, propensity=0.0, eval_model=None, prompt_version=None,
                dedup_key=dk, content_hash=ch, features_json=features_json_str,
                decision_reason=hard_reason_str, outcome_stage="rejected"
            )

        return JobLifecycleResult(
            url=url, title=title, company=company, state=JobState.REJECTED,
            score=0, route=route_name, is_stretch=False,
            rejection_reason=signals.hard_reason, package=None,
            decision_reason=hard_reason_str, checkpoint="hard_block_rejected",
            telemetry=signals.to_features_dict()
        )

    # Initial state transition: DISCOVERED (only after passing hard invariants)
    if url and not dry_run:
        transition(url, JobState.DISCOVERED, checkpoint="discovered", detail=f"Discovered via {platform}")

    score = signals.deterministic_score
    routing = signals.route
    propensity = signals.propensity
    features = signals.to_features_dict()
    min_score = cfg.get("settings", {}).get("min_score", 70)

    # Low Fit: Instant Skip (Zero LLM)
    if routing == "reject":
        reason = signals.generate_decision_reason()
        db.log_message(f"{platform} skipped ({score}%): {reason}")
        features_json_str = json.dumps(features)

        if url and not dry_run:
            transition(url, JobState.REJECTED, checkpoint="low_fit_rejected", detail=reason)
            db.log_evaluation(
                url=url, title=title, company=company, jd_text=desc_text,
                llm_score=score, rag_score=signals.rag_score, seniority="mid",
                skill_overlap=signals.jd_coverage, route="reject", propensity=0.0,
                dedup_key=dk, content_hash=ch, features_json=features_json_str,
                decision_reason=reason, outcome_stage="rejected"
            )
            db.save_to_db(
                url=url, title=title, company=company, platform=platform, status="Skipped",
                detail=reason, score=score, rag_score=signals.rag_score, seniority="mid",
                skill_overlap=signals.jd_coverage, jd_text=desc_text, content_hash=ch,
                dedup_key=dk, features_json=features_json_str, decision_reason=reason,
                outcome_stage="rejected", checkpoint="low_fit_rejected"
            )

        return JobLifecycleResult(
            url=url, title=title, company=company, state=JobState.REJECTED,
            score=score, route="reject", is_stretch=signals.is_stretch,
            rejection_reason="low_fit_score", package=None,
            decision_reason=reason, checkpoint="low_fit_rejected",
            telemetry=features
        )

    # Step 3: Evaluated State & Selective LLM Ambiguity Resolution
    if url and not dry_run:
        transition(url, JobState.EVALUATED, checkpoint="evaluated")

    llm_res = {}
    llm_invoked = False
    if should_invoke_llm(signals, min_score=min_score):
        db.log_message(f"🧠 Ambiguity Resolver: Invoking local LLM for '{title}' at '{company}' (score={score}%, stretch={signals.is_stretch})...")
        try:
            llm_res = evaluate_job_with_qwen(title=title, description=desc_text) or {}
            llm_invoked = True
        except Exception as e:
            db.log_message(f"LLM evaluation warning for '{title}': {e}")
            llm_res = {}

    # VENTURE Invariant: LLM never silently overrides the deterministic score
    features["llm_invoked"] = llm_invoked
    features["llm_score"] = llm_res.get("score")
    features["score_adjustment"] = 0

    strengths = llm_res.get("strengths") or [f"Proficient in {s}" for s in signals.matched_skills] or ["Relevant technical stack"]
    gaps = llm_res.get("gaps") or [f"Missing required skill: {s}" for s in signals.missing_skills] or []
    if signals.total_penalty > 0:
        for p in signals.penalties:
            gaps.append(f"{p.get('type')}: {p.get('evidence')}")

    decision_reason = signals.generate_decision_reason(llm_reason=llm_res.get("reason") if llm_invoked else None)
    features["decision_reason"] = decision_reason
    features_json_str = json.dumps(features)

    # Persist evaluation record
    if url and not dry_run:
        db.log_evaluation(
            url=url, title=title, company=company, jd_text=desc_text,
            llm_score=score, rag_score=signals.rag_score,
            seniority=llm_res.get("seniority", "mid"), skill_overlap=signals.jd_coverage,
            route=routing, propensity=propensity,
            eval_model=llm_res.get("eval_model") or "deterministic+qwen",
            prompt_version=llm_res.get("prompt_version"),
            dedup_key=dk, content_hash=ch,
            features_json=features_json_str, decision_reason=decision_reason,
            outcome_stage="discovered"
        )

    # Step 4: Application Preparation (Resume tailoring, Cover Letter, Mapped Answers)
    pkg = None
    if auto_prepare:
        if url and not dry_run:
            transition(url, JobState.PREPARING, checkpoint="preparing_package")
        try:
            pkg = prepare_application_package(job, signals=signals, llm_evidence=llm_res, cfg=cfg, persist=not dry_run)
        except Exception as exc:
            if url and not dry_run:
                transition(url, JobState.RETRYABLE, checkpoint="package_failed", detail=str(exc))
            raise
        if url and not dry_run:
            transition(url, JobState.READY_FOR_APPROVAL, checkpoint="ready_for_approval")

    # Queue into human doubt queue for approvals review
    tag = "STRETCH OPPORTUNITY" if signals.is_stretch else ("BORDERLINE FIT" if routing == "explore" else "QUALIFIED MATCH")
    queue_item = {
        "title": title, "company": company, "url": url,
        "platform": platform, "score": score, "reason": f"[{tag}] {decision_reason}",
        "description": desc_text, "source": routing, "propensity": propensity,
        "rag_score": signals.rag_score, "seniority": llm_res.get("seniority", "mid"),
        "skill_overlap": signals.jd_coverage, "eval_model": llm_res.get("eval_model"),
        "prompt_version": llm_res.get("prompt_version"),
        "strengths": strengths, "gaps": gaps,
        "content_hash": ch, "dedup_key": dk,
        "features_json": features_json_str, "features": features,
        "decision_reason": decision_reason, "is_stretch": signals.is_stretch,
        "penalties": signals.penalties, "stretch_signals": signals.stretch_signals,
        "package_dir": pkg.package_dir if pkg else "",
    }

    if not dry_run:
        with state.DOUBT_LOCK:
            # Avoid duplicate entries in in-memory queue
            if not any(d.get("url") == url for d in state.DOUBT_QUEUE):
                state.DOUBT_QUEUE.append(queue_item)

        if url:
            db.save_to_db(
                url=url, title=title, company=company, platform=platform,
                status="Approval Needed", detail=f"[{tag}] {decision_reason}",
                score=score, rag_score=signals.rag_score, seniority=llm_res.get("seniority", "mid"),
                skill_overlap=signals.jd_coverage, eval_model=llm_res.get("eval_model"),
                prompt_version=llm_res.get("prompt_version"), jd_text=desc_text,
                content_hash=ch, dedup_key=dk, features_json=features_json_str,
                decision_reason=decision_reason, strengths=strengths, gaps=gaps,
                outcome_stage="discovered", checkpoint="ready_for_approval",
                package_path=pkg.package_dir if pkg else None
            )

    # Safety Invariant: Only route 'queue' with verdict 'pass' may skip human approval,
    # and ONLY when safe_mode=False AND dry_run_mode=False (and require_approval=False) set explicitly.
    settings = cfg.get("settings", {})
    safe_mode = settings.get("safe_mode", True)
    dry_run_mode = settings.get("dry_run_mode", True)
    require_approval = settings.get("require_approval", True)

    can_auto_approve = (
        safe_mode is False
        and dry_run_mode is False
        and require_approval is False
        and routing == "queue"
        and verdict == "pass"
        and getattr(signals, "language", "en") == "en"
        and not signals.is_stretch
        and score >= 85
    )

    final_state = JobState.READY_FOR_APPROVAL
    chk = "ready_for_approval"
    if can_auto_approve:
        if url and not dry_run:
            transition(url, JobState.APPROVED, checkpoint="auto_approved")
        final_state = JobState.APPROVED
        chk = "auto_approved"

    return JobLifecycleResult(
        url=url, title=title, company=company,
        state=final_state, score=score,
        route=routing, is_stretch=signals.is_stretch,
        rejection_reason=None, package=pkg.to_dict() if pkg else None,
        decision_reason=decision_reason, checkpoint=chk,
        telemetry=features
    )


class SubmissionResult(int):
    """Boolean-compatible submission result that also exposes .state and .verified."""
    def __new__(cls, success: bool, state: str = "", verified: bool = False):
        obj = super().__new__(cls, 1 if success else 0)
        obj.success = bool(success)
        obj.state = state
        obj.verified = verified
        return obj

    def __bool__(self):
        return self.success


def approve(url: str):
    """Transition a job from READY_FOR_APPROVAL to APPROVED."""
    return transition(url, JobState.APPROVED, checkpoint="human_approved")


async def _human_gate(page: Any, url: str, cfg: Dict[str, Any], confirm_submit=None) -> bool:
    """Await the review screenshot and explicit operator confirmation; never approve on EOF."""
    if not cfg.get("settings", {}).get("confirm_before_submit", True):
        return True
    import inspect
    import os
    import uuid
    from core.config_manager import SCREENSHOTS_DIR
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
    shot = os.path.join(SCREENSHOTS_DIR, f"pre_submit_{uuid.uuid4().hex}.png")
    if page is not None and hasattr(page, "screenshot"):
        try:
            result = page.screenshot(path=shot, full_page=True)
            if inspect.isawaitable(result):
                await result
        except Exception:
            db.log_message("Pre-submit screenshot failed. Submission paused for review.")
            return False
    try:
        if confirm_submit is not None:
            answer = await asyncio.to_thread(confirm_submit, url, shot)
            if inspect.isawaitable(answer):
                answer = await answer
            return answer is True
        db.log_message(f"Review screenshot before submission: {shot}")
        answer = await asyncio.to_thread(input, f"Form ready for {url}. Type SUBMIT to send: ")
        return answer.strip() == "SUBMIT"
    except (EOFError, OSError, TimeoutError):
        db.log_message("No operator confirmation available. Submission aborted.")
        return False


async def execute_ats_submission(
    page: Any = None,
    job: Optional[Dict[str, Any]] = None,
    package: Optional[ApplicationPackage] = None,
    profile: Optional[Dict[str, Any]] = None,
    dry_run: bool = True,
    adapter: Any = None,
    confirm_submit=None,
) -> SubmissionResult:
    """
    Executes ATS submission using the specialist adapter framework.
    Safety Invariants:
    1. submit() reachable only from an approved, atomically reserved application.
    2. Explore-route jobs never submit without explicit human approval.
    3. Suppressed duplicate jobs must never be submitted (ignoring self URL).
    4. daily_apply_cap includes active reservations across app instances.
    5. Dry runs never invoke the final submit action or persist a submitted state.
    6. An uncertain click is SUBMITTED_UNVERIFIED and cannot be automatically retried.
    """
    # Flexibility: allow calling execute_ats_submission(job, adapter=...)
    if isinstance(page, dict) and (job is None or isinstance(job, bool)):
        if isinstance(job, bool):
            dry_run = job
        job, page = page, None
    if not isinstance(job, dict) or not job.get("url"):
        raise ValueError("A job with a URL is required.")
    if not isinstance(dry_run, bool):
        raise ValueError("dry_run must be True or False.")
    if adapter is None and page is None:
        raise ValueError("A browser page is required for ATS execution.")
    profile = profile if profile is not None else CONFIG.get("candidate", {})
    url = job["url"]
    title = job.get("title", "")
    company = job.get("company", "")

    # Invariant 1: submit() reachable ONLY from state APPROVED or EXECUTING (resumption)
    current_state = get_job_state(url)
    if (current_state and current_state not in (JobState.APPROVED, JobState.EXECUTING)) or (not dry_run and not current_state):
        raise AssertionError(f"Submission requires an approved job; current state is '{current_state or 'missing'}'.")

    # Invariant 2: Explore-route jobs cannot be submitted without explicit human approval
    route = job.get("route") or job.get("source") or (package.evaluation_snapshot.get("route") if package else None)
    if route == "explore" and current_state != JobState.APPROVED and job.get("approval_label") not in ("approve", "approved", "apply"):
        raise AssertionError("Explore-route jobs require explicit human approval.")

    # Invariant 3: Suppressed duplicate jobs must never be submitted (ignoring self URL)
    desc = job.get("jd_text") or job.get("description", "")
    if db.suppression_verdict(None, company, title, desc, exclude_url=url) == "suppress":
        raise AssertionError("Cannot submit a suppressed duplicate application.")

    # Invariant 4: Daily Apply Cap enforced from DB count before execution
    token = None
    if not dry_run:
        try:
            token = db.reserve_submission(url, CONFIG.get("settings", {}).get("daily_apply_cap", 25))
        except db.SubmissionBlockedError as exc:
            db.log_message(f"Submission blocked: {exc}")
            return SubmissionResult(False, state=current_state)

    clicked = False
    try:
        if adapter is None:
            adapter = get_ats_adapter(page.url)
        platform_name = getattr(adapter, "platform_name", "ats")
        db.log_message(f"ATS Execution: {platform_name} for {url[:80]}")
        if package is None:
            from types import SimpleNamespace
            from automation.prep_engine import _build_form_answers
            package = SimpleNamespace(form_answers=_build_form_answers(profile, profile.get("qa_vault", {})),
                                      resume_path=profile.get("resume_path", ""), cover_letter_text="",
                                      job_snapshot=job, evaluation_snapshot={})

        # Inspect
        await asyncio.wait_for(adapter.inspect(page), timeout=30)
        # Fill
        filled = await asyncio.wait_for(adapter.fill(page, package=package, profile=profile), timeout=300)
        # Validate
        validation = await asyncio.wait_for(adapter.validate(page), timeout=30)
        if not filled or not isinstance(validation, dict) or validation.get("valid") is not True:
            reason = f"Form requires review: {validation}"
            if token:
                db.finish_submission(token, "failed", reason)
            return SubmissionResult(False, state=JobState.RETRYABLE)

        if dry_run:
            db.log_message(f"[DRY RUN] Validated {title} at {company}. No submit action invoked.")
            return SubmissionResult(True, state="DRY_RUN_VALIDATED", verified=False)

        # Confirm-before-submit Human Gate
        if not await _human_gate(page, url, CONFIG, confirm_submit=confirm_submit):
            db.finish_submission(token, "aborted", "Operator did not confirm submission.")
            return SubmissionResult(False, state=JobState.FIELDS_FILLED)

        # Submit
        db.mark_submission_started(token, CONFIG.get("settings", {}).get("daily_apply_cap", 25))
        clicked = True
        submitted = await asyncio.wait_for(adapter.submit(page, dry_run=False), timeout=30)
        if not submitted:
            db.finish_submission(token, "unverified", "Submit returned no confirmation; check portal before retrying.")
            return SubmissionResult(False, state=JobState.SUBMITTED_UNVERIFIED)

        # Check verification of submission success
        import inspect
        verifier = getattr(adapter, "verify_success", None)
        verified = False
        if callable(verifier):
            try:
                result = verifier(page)
                if inspect.isawaitable(result):
                    result = await asyncio.wait_for(result, timeout=20)
                verified = result is True
            except Exception:
                verified = False
        status = "submitted" if verified else "unverified"
        final_state = JobState.SUBMITTED if verified else JobState.SUBMITTED_UNVERIFIED
        db.finish_submission(token, status, f"Submitted via {platform_name}; verified={verified}")
        db.log_message(f"Application [{final_state}]: {title} at {company}")
        return SubmissionResult(True, state=final_state, verified=verified)
    except asyncio.CancelledError:
        if token:
            db.finish_submission(token, "unverified" if clicked else "failed", "Execution cancelled; review last checkpoint.")
        raise
    except Exception as exc:
        final_state = JobState.SUBMITTED_UNVERIFIED if clicked else JobState.RETRYABLE
        if token:
            db.finish_submission(token, "unverified" if clicked else "failed", f"{type(exc).__name__}: {exc}")
        db.log_message(f"ATS execution stopped ({final_state}): {type(exc).__name__}: {exc}")
        return SubmissionResult(False, state=final_state)
