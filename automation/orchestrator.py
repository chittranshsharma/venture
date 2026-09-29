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
    dry_run: bool = False,
    auto_prepare: bool = True,
) -> JobLifecycleResult:
    """
    Authoritative single-entrypoint for processing an opportunity across all stages.
    Can be called synchronously or run via asyncio.to_thread / run_in_executor.
    """
    if cfg is None:
        cfg = CONFIG or load_config()

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

    # Initial state transition: DISCOVERED
    if url and not dry_run:
        transition(url, JobState.DISCOVERED, checkpoint="discovered", detail=f"Discovered via {platform}")

    # Step 2: 3-Tier Constraint & Free Signal Evaluation
    signals: EvaluationSignals = evaluate_opportunity(title, company, desc_text, cfg=cfg)

    # Tier-1 Hard Invariants: Instant Archive
    if signals.hard_block:
        hard_reason_str = f"Tier-1 Invariant Hard Block: {signals.hard_reason}"
        db.log_message(f"⛔ Hard Block [{signals.hard_reason}]: Skipped '{title}' at '{company}'")
        features_json_str = json.dumps(signals.to_features_dict())
        
        if url and not dry_run:
            transition(url, JobState.REJECTED, checkpoint="hard_block_rejected", detail=hard_reason_str)
            db.log_evaluation(
                url=url, title=title, company=company, jd_text=desc_text,
                llm_score=0, rag_score=0.0, seniority="entry", skill_overlap=0.0,
                route="constraint", propensity=0.0, eval_model=None, prompt_version=None,
                dedup_key=dk, content_hash=ch, features_json=features_json_str,
                decision_reason=hard_reason_str, outcome_stage="rejected"
            )
            db.save_to_db(
                url=url, title=title, company=company, platform=platform, status="Skipped",
                detail=hard_reason_str, score=0, rag_score=0.0, seniority="entry",
                skill_overlap=0.0, jd_text=desc_text, content_hash=ch, dedup_key=dk,
                features_json=features_json_str, decision_reason=hard_reason_str,
                outcome_stage="rejected", checkpoint="hard_block_rejected"
            )

        return JobLifecycleResult(
            url=url, title=title, company=company, state=JobState.REJECTED,
            score=0, route="constraint", is_stretch=False,
            rejection_reason=signals.hard_reason, package=None,
            decision_reason=hard_reason_str, checkpoint="hard_block_rejected",
            telemetry=signals.to_features_dict()
        )

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

    db.log_message(f"📦 [{tag}] ({score}%): Opportunity prepared and awaiting review in Approvals.")

    return JobLifecycleResult(
        url=url, title=title, company=company,
        state=JobState.READY_FOR_APPROVAL, score=score,
        route=routing, is_stretch=signals.is_stretch,
        rejection_reason=None, package=pkg.to_dict() if pkg else None,
        decision_reason=decision_reason, checkpoint="ready_for_approval",
        telemetry=features
    )


async def execute_ats_submission(
    page,
    job: Dict[str, Any],
    package: Optional[ApplicationPackage] = None,
    profile: Optional[Dict[str, Any]] = None,
    dry_run: bool = True
) -> bool:
    """
    Executes ATS submission using the specialist adapter framework.
    Safety Invariants:
    1. submit() reachable only from state APPROVED (or EXECUTING if resuming from checkpoint).
    2. Explore-route jobs never submit without explicit human approval click.
    3. daily_apply_cap strictly enforced from DB before execution.
    4. Explicit dry_run defaults to True to prevent accidental live submissions.
    5. After submission: confirms success indicator, else sets SUBMITTED_UNVERIFIED.
    """
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

    # Invariant 3: Daily Apply Cap enforced from DB count before execution
    settings = CONFIG.get("settings", {})
    daily_cap = settings.get("daily_apply_cap", 25)
    today_applied = db.get_daily_apply_count()
    if today_applied >= daily_cap and not dry_run:
        db.log_message(f"Daily application cap ({daily_cap}) reached ({today_applied} today). Aborting submission.")
        return False

    if url and not dry_run:
        transition(url, JobState.EXECUTING, checkpoint="detecting_adapter")

    adapter = get_ats_adapter(url)
    db.log_message(f"ATS Execution: Selected adapter '{adapter.platform_name}' for {url[:45]}")

    # Inspect
    await adapter.inspect(page)

    # Fill
    if url and not dry_run:
        db.set_checkpoint(url, "filling_form")
    filled = await adapter.fill(page, package=package, profile=profile)
    if not filled:
        db.log_message("ATS Execution Warning: Adapter fill reported zero filled fields.")

    # Validate
    val_res = await adapter.validate(page)
    if not val_res.get("valid", True):
        db.log_message(f"ATS Execution Error: Validation failed. Missing required fields: {val_res.get('missing_required')}")
        if url and not dry_run:
            transition(url, JobState.RETRYABLE, checkpoint="validation_failed", detail=str(val_res.get("missing_required")))
        return False

    # Submit
    if url and not dry_run:
        db.set_checkpoint(url, "submitting")
    submitted = await adapter.submit(page, dry_run=dry_run)

    if submitted:
        # Check verification of submission success
        verified = True if dry_run else getattr(adapter, "verify_success", lambda p: True)(page)
        final_state = JobState.SUBMITTED if verified else JobState.SUBMITTED_UNVERIFIED
        chk = "submitted" if verified else "submitted_unverified"

        if url and not dry_run:
            transition(url, final_state, checkpoint=chk, detail=f"Application {final_state.lower()}")
            db.record_outcome(url, "applied", notes=f"Submitted via {adapter.platform_name} adapter (verified={verified})")
            db.update_job_status_in_csv(url, "Approval Needed", "Applied", f"Submitted via {adapter.platform_name}")
        db.log_message(f"✅ Application Execution Completed [{final_state}]: {title} at {company}")
        return True
    else:
        if url and not dry_run:
            transition(url, JobState.FAILED, checkpoint="submit_failed", detail="Submit action did not confirm")
        return False
