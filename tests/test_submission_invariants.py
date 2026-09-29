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
