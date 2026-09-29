"""
core/state_machine.py — Application Finite State Machine (Crash Recovery)
Inspired by Liam-Frost/AutoApply/src/core/state_machine.py.

State flow:
DISCOVERED → QUALIFIED → APPROVED → FORM_OPENED
→ RESUME_UPLOADED → FIELDS_FILLED → SUBMITTED
Error states: FAILED, NEEDS_RETRY (reachable from any active state)
"""

import core.db_manager as db

class JobState:
    DISCOVERED       = "DISCOVERED"
    QUALIFIED        = "QUALIFIED"
    APPROVED         = "APPROVED"
    FORM_OPENED      = "FORM_OPENED"
    RESUME_UPLOADED  = "RESUME_UPLOADED"
    FIELDS_FILLED    = "FIELDS_FILLED"
    SUBMITTED        = "SUBMITTED"
    INTERVIEW        = "INTERVIEW"
    OFFER            = "OFFER"
    REJECTED_POST    = "REJECTED_POST"
    FAILED           = "FAILED"
    NEEDS_RETRY      = "NEEDS_RETRY"
    REJECTED         = "REJECTED"

VALID_TRANSITIONS = {
    "DISCOVERED":       ["QUALIFIED", "REJECTED", "FAILED"],
    "QUALIFIED":        ["APPROVED", "REJECTED", "FAILED"],
    "APPROVED":         ["FORM_OPENED", "FAILED"],
    "FORM_OPENED":      ["RESUME_UPLOADED", "FIELDS_FILLED", "FAILED"],
    "RESUME_UPLOADED":  ["FIELDS_FILLED", "FAILED"],
    "FIELDS_FILLED":    ["SUBMITTED", "NEEDS_RETRY", "FAILED"],
    "SUBMITTED":        ["INTERVIEW", "OFFER", "REJECTED_POST", "Interview", "Offer", "Rejected", "REJECTED", "FAILED"],
    "INTERVIEW":        ["OFFER", "REJECTED_POST", "Offer", "Rejected", "REJECTED", "FAILED"],
    "Interview":        ["OFFER", "REJECTED_POST", "Offer", "Rejected", "REJECTED", "FAILED"],
    "REJECTED_POST":    ["INTERVIEW", "OFFER", "FAILED"],
    "NEEDS_RETRY":      ["FORM_OPENED", "RESUME_UPLOADED", "FIELDS_FILLED", "FAILED"],
    "FAILED":           ["NEEDS_RETRY", "FORM_OPENED"],
}

_ERROR_STATES = {"FAILED", "NEEDS_RETRY"}

# Terminal states for re-application: once submitted/interviewing/offered, scraper should not re-evaluate
_TERMINAL_REAPPLICATION_STATES = {
    # FSM constants
    "SUBMITTED", "INTERVIEW", "OFFER", "REJECTED_POST", "REJECTED",
    # AppStatus display strings (stored in SQLite)
    "Applied", "Rejected", "Withdrawn", "Offer", "Offer Received",
    "Interview", "Interviewing",
    # Bot runner states
    "Manual Approval Apply",
}

# Status vocabulary mapping between FSM constants and applications.status display strings
FSM_TO_APP_STATUS = {
    "DISCOVERED":       "Suggested",
    "QUALIFIED":        "Suggested",
    "APPROVED":         "Approval Needed",
    "FORM_OPENED":      "Applying",
    "RESUME_UPLOADED":  "Applying",
    "FIELDS_FILLED":    "Applying",
    "SUBMITTED":        "Applied",
    "INTERVIEW":        "Interview",
    "OFFER":            "Offer",
    "REJECTED":         "Rejected",
    "REJECTED_POST":    "Rejected",
    "FAILED":           "Failed",
    "NEEDS_RETRY":      "Needs Retry",
}

APP_STATUS_TO_FSM = {
    "Suggested":             "QUALIFIED",
    "Approval Needed":       "APPROVED",
    "Applied":               "SUBMITTED",
    "Manual Approval Apply": "SUBMITTED",
    "Interview":             "INTERVIEW",
    "Interviewing":          "INTERVIEW",
    "Offer":                 "OFFER",
    "Offer Received":        "OFFER",
    "Rejected":              "REJECTED_POST",
    "Withdrawn":             "REJECTED_POST",
    "Skipped":               "REJECTED",
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
    return (new_state in allowed or 
            new_state.upper() in allowed or 
            new_state.capitalize() in allowed)

def transition(url: str, new_state: str, detail: str = ""):
    """
    Atomically transition an application to a new state in SQLite.
    Raises ValueError on illegal transition.
    """
    current = db.get_state(url)
    if current and not can_transition(current, new_state):
        raise ValueError(f"Illegal: {current} -> {new_state}")
    db.update_state(url, new_state, detail=detail)
    db.log_message(f"FSM [{url[:35]}]: {current or 'INIT'} -> {new_state}")

def get_job_state(url: str) -> str:
    """Return the current FSM state of a job URL from SQLite."""
    return db.get_state(url) or ""

_TERMINAL_STATES = _TERMINAL_REAPPLICATION_STATES

def sync_application_status(url: str, new_status: str, detail: str = ""):
    """
    Synchronize both FSM state and SQLite application status string.
    Ensures that dashboard, status tracker, and FSM never diverge.
    """
    if new_status in APP_STATUS_TO_FSM:
        fsm_state = APP_STATUS_TO_FSM[new_status]
        app_status = new_status
    else:
        fsm_state = new_status.upper()
        app_status = FSM_TO_APP_STATUS.get(fsm_state, new_status)

    transition(url, fsm_state, detail=detail)
    db.update_job_status_in_csv(url, "", app_status, detail)

def is_job_completed(url: str) -> bool:
    """Check if a job was already submitted or in terminal application state (blocks scraper re-evaluation)."""
    state = get_job_state(url)
    return state in _TERMINAL_REAPPLICATION_STATES

def get_resume_checkpoint(url: str) -> str:
    """
    Retrieve checkpoint state for crash recovery.
    If the bot crashed at RESUME_UPLOADED, on restart it skips re-doing that
    job and resumes from FIELDS_FILLED.
    """
    current = get_job_state(url)
    if current == JobState.RESUME_UPLOADED:
        return JobState.FIELDS_FILLED
    elif current == JobState.FIELDS_FILLED:
        return JobState.SUBMITTED
    return current

class ApplicationStateMachine:
    """Context manager / wrapper for tracking an application through FSM states."""
    def __init__(self, url: str, initial_state: str = JobState.DISCOVERED):
        self.url = url
        current = db.get_state(url)
        if not current:
            transition(url, initial_state)
            self.state = initial_state
        else:
            self.state = current

    def transition(self, new_state: str, detail: str = ""):
        transition(self.url, new_state, detail=detail)
        self.state = new_state

    def fail(self, error: str = ""):
        self.transition(JobState.FAILED, detail=error)

    def retry(self, reason: str = ""):
        self.transition(JobState.NEEDS_RETRY, detail=reason)
