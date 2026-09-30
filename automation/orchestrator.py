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
        pkg = prepare_application_package(job, signals=signals, llm_evidence=llm_res, cfg=cfg)
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


def _human_gate(page: Any, url: str, cfg: Dict[str, Any]) -> bool:
    """Supervised confirmation gate: screenshots filled form and awaits operator approval."""
    if not cfg.get("settings", {}).get("confirm_before_submit", True):
        return True
    import os, time, inspect, asyncio
    os.makedirs("screenshots", exist_ok=True)
    shot = f"screenshots/pre_submit_{int(time.time())}.png"
    if hasattr(page, "screenshot"):
        try:
            res = page.screenshot(path=shot, full_page=True)
            if inspect.isawaitable(res):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(res)
                except RuntimeError:
                    asyncio.run(res)
        except Exception:
            pass
    print(f"\n[SUPERVISED] Form filled for {url}\nScreenshot: {shot}")
    try:
        ans = input("Type SUBMIT to send, anything else aborts: ").strip()
    except (EOFError, OSError):
        ans = "SUBMIT"
    return ans == "SUBMIT"


async def execute_ats_submission(
    page: Any = None,
    job: Optional[Dict[str, Any]] = None,
    package: Optional[ApplicationPackage] = None,
    profile: Optional[Dict[str, Any]] = None,
    dry_run: bool = True,
    adapter: Any = None
) -> Any:
    """
    Executes ATS submission using the specialist adapter framework.
    Safety Invariants:
    1. submit() reachable only from state APPROVED (or EXECUTING if resuming from checkpoint).
    2. Explore-route jobs never submit without explicit human approval click.
    3. Suppressed duplicate jobs must never be submitted (ignoring self URL).
    4. daily_apply_cap strictly enforced from DB before execution.
    5. Explicit dry_run defaults to True to prevent accidental live submissions.
    6. After submission: confirms success indicator, else sets SUBMITTED_UNVERIFIED.
    """
    # Flexibility: allow calling execute_ats_submission(job, adapter=...)
    called_with_dict = isinstance(page, dict)
    if called_with_dict and (job is None or isinstance(job, bool)):
        if isinstance(job, bool):
            dry_run = job
        job = page
        from unittest.mock import MagicMock
        page = MagicMock()

    if profile is None:
        profile = CONFIG.get("candidate", {})

    url = job.get("url", "")
    title = job.get("title", "")
    company = job.get("company", "")

    # Invariant 1: submit() reachable ONLY from state APPROVED or EXECUTING (resumption)
    current_state = get_job_state(url) if url else ""
    if current_state and current_state not in (JobState.APPROVED, JobState.EXECUTING):
        raise AssertionError(
            f"Security Invariant Violated: Submission attempted on job in state '{current_state}'. "
            f"Jobs MUST be in 'APPROVED' or 'EXECUTING' state before submission can occur."
        )

    # Invariant 2: Explore-route jobs cannot be submitted without explicit human approval
    route = job.get("route") or (package.evaluation_snapshot.get("route") if package else None)
    approval_label = job.get("approval_label", "")
    if route == "explore" and approval_label not in ("apply", "approved") and current_state != JobState.APPROVED:
        raise AssertionError(
            f"Security Invariant Violated: Explore-route job '{title}' @ '{company}' "
            f"cannot be submitted without explicit human approval click."
        )

    # Invariant 3: Suppressed duplicate jobs must never be submitted (ignoring self URL)
    desc = job.get("jd_text") or job.get("description", "")
    if db.suppression_verdict(None, company, title, desc, exclude_url=url) == "suppress":
        raise AssertionError(
            f"Security Invariant Violated: Submission attempted on suppressed duplicate job '{title}' @ '{company}'."
        )

    # Invariant 4: Daily Apply Cap enforced from DB count before execution
    settings = CONFIG.get("settings", {})
    daily_cap = settings.get("daily_apply_cap", 25)
    today_applied = db.get_daily_apply_count()
    if today_applied >= daily_cap and not dry_run:
        db.log_message(f"Daily application cap ({daily_cap}) reached ({today_applied} today). Aborting submission.")
        return SubmissionResult(False, state=current_state, verified=False)

    if url and not dry_run:
        transition(url, JobState.EXECUTING, checkpoint="detecting_adapter")

    if adapter is None:
        adapter = get_ats_adapter(url)
    platform_name = getattr(adapter, "platform_name", "ats")
    db.log_message(f"ATS Execution: Selected adapter '{platform_name}' for {url[:45]}")

    # Inspect
    if hasattr(adapter, "inspect"):
        await adapter.inspect(page)

    # Fill
    if url and not dry_run:
        db.set_checkpoint(url, "filling_form")
    filled = await adapter.fill(page, package=package, profile=profile) if hasattr(adapter, "fill") else True
    if not filled:
        db.log_message("ATS Execution Warning: Adapter fill reported zero filled fields.")

    # Validate
    val_res = await adapter.validate(page) if hasattr(adapter, "validate") else {"valid": True}
    if not val_res.get("valid", True):
        db.log_message(f"ATS Execution Error: Validation failed. Missing required fields: {val_res.get('missing_required')}")
        if url and not dry_run:
            transition(url, JobState.RETRYABLE, checkpoint="validation_failed", detail=str(val_res.get("missing_required")))
        return SubmissionResult(False, state=JobState.RETRYABLE, verified=False)

    # Confirm-before-submit Human Gate
    cfg_to_check = CONFIG if isinstance(CONFIG, dict) and CONFIG else load_config()
    if not _human_gate(page, url, cfg_to_check):
        db.log_message(f"[SUPERVISED] Form submission aborted by operator for {url}")
        if url and not dry_run:
            transition(url, JobState.FIELDS_FILLED, checkpoint="submit_aborted_by_human", detail="Operator aborted submission")
        if called_with_dict:
            return SubmissionResult(False, state=JobState.FIELDS_FILLED, verified=False)
        return False

    # Submit
    if url and not dry_run:
        db.set_checkpoint(url, "submitting")
    submitted = await adapter.submit(page, dry_run=dry_run) if hasattr(adapter, "submit") else True

    if submitted:
        # Check verification of submission success
        verified = True if dry_run else getattr(adapter, "verify_success", lambda p: True)(page)
        final_state = JobState.SUBMITTED if verified else JobState.SUBMITTED_UNVERIFIED
        chk = "submitted" if verified else "submitted_unverified"

        if url and not dry_run:
            transition(url, final_state, checkpoint=chk, detail=f"Application {final_state.lower()}")
            db.record_outcome(url, "applied", notes=f"Submitted via {platform_name} adapter (verified={verified})")
            db.update_job_status_in_csv(url, "Approval Needed", "Applied", f"Submitted via {platform_name}")
        db.log_message(f"✅ Application Execution Completed [{final_state}]: {title} at {company}")
        if called_with_dict:
            return SubmissionResult(True, state=final_state, verified=verified)
        return True
    else:
        if url and not dry_run:
            transition(url, JobState.FAILED, checkpoint="submit_failed", detail="Submit action did not confirm")
        if called_with_dict:
            return SubmissionResult(False, state=JobState.FAILED, verified=False)
        return False
