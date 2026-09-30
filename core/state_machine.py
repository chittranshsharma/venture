"""
core/state_machine.py — Authoritative Application Finite State Machine & Checkpoint Recovery.

Lifecycle:
DISCOVERED → EVALUATED → PREPARING → READY_FOR_APPROVAL → APPROVED → EXECUTING → SUBMITTED → (INTERVIEW | OFFER | GHOSTED | REJECTED)
Error states: FAILED, RETRYABLE (reachable from active processing states).
"""

from typing import Any, Dict, List, Optional, Tuple
import core.db_manager as db


class JobState:
    DISCOVERED         = "DISCOVERED"
    EVALUATED          = "EVALUATED"
    PREPARING          = "PREPARING"
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
    APPROVED           = "APPROVED"
    EXECUTING          = "EXECUTING"
    SUBMITTED          = "SUBMITTED"
    SUBMITTED_UNVERIFIED = "SUBMITTED_UNVERIFIED"
    FAILED             = "FAILED"
    RETRYABLE          = "RETRYABLE"
    REJECTED           = "REJECTED"
    INTERVIEW          = "INTERVIEW"
    OFFER              = "OFFER"
    GHOSTED            = "GHOSTED"

    # Legacy aliases for backward compatibility
    QUALIFIED          = "EVALUATED"
    FORM_OPENED        = "EXECUTING"
    RESUME_UPLOADED    = "EXECUTING"
    FIELDS_FILLED      = "EXECUTING"
    NEEDS_RETRY        = "RETRYABLE"
    REJECTED_POST      = "REJECTED"


class IllegalStateTransitionError(ValueError):
    """Raised when an illegal FSM state jump is attempted (e.g. DISCOVERED -> SUBMITTED)."""
    pass


VALID_TRANSITIONS: Dict[str, List[str]] = {
    "DISCOVERED":           ["EVALUATED", "QUALIFIED", "PREPARING", "REJECTED", "FAILED"],
    "EVALUATED":            ["PREPARING", "READY_FOR_APPROVAL", "APPROVED", "REJECTED", "FAILED"],
    "QUALIFIED":            ["PREPARING", "READY_FOR_APPROVAL", "APPROVED", "REJECTED", "FAILED"],
    "PREPARING":            ["READY_FOR_APPROVAL", "APPROVED", "FAILED", "RETRYABLE"],
    "READY_FOR_APPROVAL":   ["APPROVED", "REJECTED", "FAILED"],
    "APPROVED":             ["EXECUTING", "FORM_OPENED", "FAILED"],
    "EXECUTING":            ["SUBMITTED", "SUBMITTED_UNVERIFIED", "FAILED", "RETRYABLE", "RESUME_UPLOADED", "FIELDS_FILLED"],
    "FORM_OPENED":          ["EXECUTING", "RESUME_UPLOADED", "FIELDS_FILLED", "FAILED"],
    "RESUME_UPLOADED":      ["EXECUTING", "FIELDS_FILLED", "FAILED"],
    "FIELDS_FILLED":        ["SUBMITTED", "SUBMITTED_UNVERIFIED", "RETRYABLE", "FAILED"],
    "SUBMITTED":            ["INTERVIEW", "OFFER", "GHOSTED", "REJECTED", "REJECTED_POST", "FAILED"],
    "SUBMITTED_UNVERIFIED": ["SUBMITTED", "INTERVIEW", "OFFER", "GHOSTED", "REJECTED", "FAILED"],
    "INTERVIEW":            ["OFFER", "GHOSTED", "REJECTED", "REJECTED_POST", "FAILED"],
    "OFFER":                ["REJECTED", "SUBMITTED"],
    "GHOSTED":              ["INTERVIEW", "OFFER", "REJECTED"],
    "FAILED":               ["RETRYABLE", "NEEDS_RETRY", "EXECUTING", "PREPARING", "APPROVED"],
    "RETRYABLE":            ["EXECUTING", "PREPARING", "FORM_OPENED", "FAILED"],
    "NEEDS_RETRY":          ["EXECUTING", "PREPARING", "FORM_OPENED", "FAILED"],
    "REJECTED":             ["DISCOVERED", "EVALUATED"],  # can re-evaluate on genuine JD revisions
    "REJECTED_POST":        ["INTERVIEW", "OFFER", "FAILED"],
}

_ERROR_STATES = {"FAILED", "RETRYABLE", "NEEDS_RETRY"}

_TERMINAL_REAPPLICATION_STATES = {
    "SUBMITTED", "INTERVIEW", "OFFER", "REJECTED_POST", "REJECTED", "GHOSTED",
    "Applied", "Rejected", "Withdrawn", "Offer", "Offer Received",
    "Interview", "Interviewing", "Manual Approval Apply", "Auto-Archived",
}

FSM_TO_APP_STATUS = {
    "DISCOVERED":         "Discovered",
    "EVALUATED":          "Suggested",
    "QUALIFIED":          "Suggested",
    "PREPARING":          "Preparing",
    "READY_FOR_APPROVAL": "Approval Needed",
    "APPROVED":           "Approved",
    "EXECUTING":          "Applying",
    "FORM_OPENED":        "Applying",
    "RESUME_UPLOADED":    "Applying",
    "FIELDS_FILLED":      "Applying",
    "SUBMITTED":          "Applied",
    "INTERVIEW":          "Interview",
    "OFFER":              "Offer",
    "REJECTED":           "Rejected",
    "REJECTED_POST":      "Rejected",
    "GHOSTED":            "Ghosted",
    "FAILED":             "Failed",
    "RETRYABLE":          "Needs Retry",
    "NEEDS_RETRY":        "Needs Retry",
}

APP_STATUS_TO_FSM = {
    "Discovered":            "DISCOVERED",
    "Suggested":             "EVALUATED",
    "Qualified":             "EVALUATED",
    "Preparing":             "PREPARING",
    "Approval Needed":       "READY_FOR_APPROVAL",
    "Approved":              "APPROVED",
    "Applying":              "EXECUTING",
    "Applied":               "SUBMITTED",
    "Manual Approval Apply": "SUBMITTED",
    "Interview":             "INTERVIEW",
    "Interviewing":          "INTERVIEW",
    "Offer":                 "OFFER",
    "Offer Received":        "OFFER",
    "Rejected":              "REJECTED",
    "Withdrawn":             "REJECTED",
    "Ghosted":               "GHOSTED",
    "Skipped":               "REJECTED",
    "Failed":                "FAILED",
    "Needs Retry":           "RETRYABLE",
    "Auto-Archived":         "REJECTED",
}


def can_transition(current: str, new_state: str) -> bool:
    """Check if state transition is legally allowed by FSM rules."""
    if not current:
        return True
    if new_state in _ERROR_STATES:
        return True
    allowed = VALID_TRANSITIONS.get(current, [])
    if not allowed and current.upper() in VALID_TRANSITIONS:
        allowed = VALID_TRANSITIONS.get(current.upper(), [])
    return (
        new_state in allowed or
        new_state.upper() in allowed or
        new_state.capitalize() in allowed
    )


LEGACY_STATE_MAPPINGS: Dict[str, Tuple[str, str]] = {
    "QUALIFIED":       ("EVALUATED", "evaluated"),
    "FIELDS_FILLED":   ("EXECUTING", "fields_filled"),
    "RESUME_UPLOADED": ("EXECUTING", "resume_uploaded"),
    "FORM_OPENED":     ("EXECUTING", "form_opened"),
    "Applied":         ("SUBMITTED", "submitted"),
    "Manual Approval Apply": ("SUBMITTED", "submitted"),
    "REJECTED_POST":   ("REJECTED", "rejected_post"),
    "Rejected":        ("REJECTED", "rejected"),
}


def normalize_legacy_state(state: str, checkpoint: str = "") -> Tuple[str, str]:
    """
    Normalizes legacy database states into the canonical FSM state and checkpoint.
    Example: 'QUALIFIED' -> ('EVALUATED', 'evaluated')
    """
    if state in LEGACY_STATE_MAPPINGS:
        canonical_state, default_chk = LEGACY_STATE_MAPPINGS[state]
        return canonical_state, checkpoint or default_chk
    return state, checkpoint


def transition(url: str, new_state: str, checkpoint: str = "", detail: str = "", strict: bool = True):
    """
    Atomically transition an application to a new state and checkpoint in SQLite.
    Raises IllegalStateTransitionError if strict=True and transition is illegal.
    """
    current = db.get_state(url)
    if current and not can_transition(current, new_state):
        msg = f"Illegal FSM state jump: cannot transition '{current}' -> '{new_state}'"
        db.log_message(f"FSM Error: {msg}")
        if strict:
            raise IllegalStateTransitionError(msg)
    
    db.update_state(url, new_state, detail=detail)
    if checkpoint:
        db.set_checkpoint(url, checkpoint)
    db.log_message(f"FSM [{url[:35]}]: {current or 'INIT'} -> {new_state} (chk={checkpoint or 'none'})")


def get_job_state(url: str) -> str:
    """Return the current FSM state of a job URL from SQLite."""
    return db.get_state(url) or ""


def get_job_checkpoint(url: str) -> str:
    """Return the current execution checkpoint of a job from SQLite."""
    return db.get_checkpoint(url)


def is_job_completed(url: str) -> bool:
    """Check if a job is in terminal application state (blocks scraper re-evaluation)."""
    state = get_job_state(url)
    return state in _TERMINAL_REAPPLICATION_STATES


def sync_application_status(url: str, new_status: str, detail: str = ""):
    """
    Synchronize both FSM state and SQLite application status string.
    """
    if new_status in APP_STATUS_TO_FSM:
        fsm_state = APP_STATUS_TO_FSM[new_status]
        app_status = new_status
    else:
        fsm_state = new_status.upper()
        app_status = FSM_TO_APP_STATUS.get(fsm_state, new_status)

    transition(url, fsm_state, detail=detail)
    db.update_job_status_in_csv(url, "", app_status, detail)


def get_interrupted_executions() -> List[Dict[str, Any]]:
    """
    Find applications that were interrupted during active execution or preparation,
    returning their last checkpoint for crash-safe resumption.
    """
    with db.DB_LOCK:
        try:
            with db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, url, title, company, status, checkpoint, package_path, updated_at
                    FROM applications
                    WHERE status IN ('Applying', 'Approved', 'Preparing')
                       OR (checkpoint NOT IN ('discovered', 'submitted', 'hard_block_rejected', 'low_fit_rejected', 'ready_for_approval')
                           AND status NOT IN ('Applied', 'Rejected', 'Skipped', 'Withdrawn'))
                    ORDER BY id DESC
                """)
                rows = cursor.fetchall()
                results = []
                for r in rows:
                    results.append({
                        "id": r[0],
                        "url": r[1],
                        "title": r[2] or "Unknown Role",
                        "company": r[3] or "Unknown Company",
                        "status": r[4],
                        "checkpoint": r[5] or "discovered",
                        "package_path": r[6] or "",
                        "updated_at": r[7],
                    })
                return results
        except Exception as e:
            db.log_message(f"Error fetching interrupted executions: {e}")
            return []


def format_interrupted_status(app: Dict[str, Any]) -> str:
    """Format an interrupted application record into the canonical crash-resumption string."""
    app_id = app.get("id", "?")
    company = app.get("company", "Company")
    title = app.get("title", "Role")
    status = app.get("status", "EXECUTING").upper()
    checkpoint = app.get("checkpoint", "unknown")
    return f"Application #{app_id} — {company} ({title}) — {status} — last checkpoint: {checkpoint}"

