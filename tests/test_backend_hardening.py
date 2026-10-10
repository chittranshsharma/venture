"""Run with Python directly; fixtures never touch the user's database or config."""
import asyncio
import atexit
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import os
from pathlib import Path
import smtplib
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if __name__ == "__main__":
    bootstrap = tempfile.TemporaryDirectory(prefix="venture-tests-")
    os.environ["VENTURE_DATA_DIR"] = bootstrap.name
    atexit.register(bootstrap.cleanup)

import core.db_manager as db
import core.config_manager as config_manager
from core.config_manager import CONFIG
from core import credential_store
from core.email_smtp import send_smtp_email
from core.state_machine import JobState, get_job_state, is_job_completed, transition
from automation.orchestrator import execute_ats_submission
from automation.prep_engine import _build_form_answers, _generate_cover_letter
from automation.form_autofiller import _match_vault


class FakeAdapter:
    platform_name = "test"

    def __init__(self, filled=True, valid=True, verified=True):
        self.fill = AsyncMock(return_value=filled)
        self.inspect = AsyncMock(return_value={})
        self.validate = AsyncMock(return_value={"valid": valid, "missing_required": []})
        self.submit = AsyncMock(return_value=True)
        self.verify_success = AsyncMock(return_value=verified)


class BackendHardeningTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="venture-case-")
        self.addCleanup(self.directory.cleanup)
        self.path_patch = patch.object(db, "SQLITE_DB_PATH", str(Path(self.directory.name) / "test.db"))
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.log_patch = patch.object(db, "log_message")
        self.log_patch.start()
        self.addCleanup(self.log_patch.stop)
        db._init_db_schema()
        settings = patch.dict(CONFIG, {"settings": {"daily_apply_cap": 25, "confirm_before_submit": False},
                                       "candidate": {"name": "Test Candidate", "email": "test@example.com"},
                                       "smtp": {"server": "mail.example.com", "port": 587, "email": "test@example.com"}})
        settings.start()
        self.addCleanup(settings.stop)
        self.job = {"url": "https://example.com/job/1", "title": "Backend Engineer", "company": "Example",
                    "description": "An example role using Python. " * 15}
        self.package = SimpleNamespace(form_answers={}, evaluation_snapshot={})

    def approve_job(self, job=None):
        job = job or self.job
        db.save_to_db(job["url"], job["title"], job["company"], "test", "APPROVED", jd_text=job["description"])

    def execute(self, adapter, **kwargs):
        return asyncio.run(execute_ats_submission(None, self.job, package=self.package, adapter=adapter, **kwargs))

    def test_schema_v8_is_idempotent(self):
        db._init_db_schema()
        with db._get_connection() as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 8)
            self.assertIn("submitted_at", {row[1] for row in conn.execute("PRAGMA table_info(applications)")})

    def test_live_submission_rejects_missing_approval(self):
        adapter = FakeAdapter()
        with self.assertRaises(AssertionError):
            self.execute(adapter, dry_run=False)
        adapter.submit.assert_not_called()
        self.assertEqual(db.get_submission_attempts(), [])

    def test_dry_run_never_calls_submit_or_reserves_slot(self):
        adapter = FakeAdapter()
        result = self.execute(adapter, dry_run=True)
        self.assertTrue(result)
        self.assertFalse(result.verified)
        self.assertEqual(result.state, "DRY_RUN_VALIDATED")
        adapter.submit.assert_not_called()
        self.assertEqual(db.get_submission_attempts(), [])
        self.assertEqual(db.get_application(self.job["url"]), {})

    def test_verified_receipt_preserves_canonical_state(self):
        self.approve_job()
        result = self.execute(FakeAdapter(), dry_run=False)
        self.assertTrue(result.verified)
        self.assertEqual(get_job_state(self.job["url"]), JobState.SUBMITTED)
        self.assertEqual(db.get_daily_apply_count(), 1)
        self.assertIsNotNone(db.get_application(self.job["url"])["submitted_at"])

    def test_async_false_verification_stays_unverified(self):
        self.approve_job()
        result = self.execute(FakeAdapter(verified=False), dry_run=False)
        self.assertFalse(result.verified)
        self.assertEqual(get_job_state(self.job["url"]), JobState.SUBMITTED_UNVERIFIED)
        self.assertTrue(is_job_completed(self.job["url"]))
        self.assertEqual(db.get_submission_attempts()[0]["status"], "unverified")

    def test_missing_verifier_does_not_imply_success(self):
        self.approve_job()
        adapter = FakeAdapter()
        del adapter.verify_success
        result = self.execute(adapter, dry_run=False)
        self.assertEqual(result.state, JobState.SUBMITTED_UNVERIFIED)

    def test_failed_fill_never_submits_and_releases_slot(self):
        self.approve_job()
        adapter = FakeAdapter(filled=False)
        result = self.execute(adapter, dry_run=False)
        self.assertFalse(result)
        adapter.submit.assert_not_called()
        self.assertEqual(db.get_daily_apply_count(), 0)
        self.assertEqual(get_job_state(self.job["url"]), JobState.RETRYABLE)

    def test_invalid_form_never_submits(self):
        self.approve_job()
        adapter = FakeAdapter(valid=False)
        self.assertFalse(self.execute(adapter, dry_run=False))
        adapter.submit.assert_not_called()

    def test_eof_never_confirms_submission(self):
        self.approve_job()
        CONFIG["settings"]["confirm_before_submit"] = True
        adapter = FakeAdapter()
        with patch("builtins.input", side_effect=EOFError):
            result = self.execute(adapter, dry_run=False)
        adapter.submit.assert_not_called()
        self.assertFalse(result)
        self.assertEqual(db.get_submission_attempts()[0]["status"], "aborted")

    def test_confirmation_callback_and_screenshot_are_awaited(self):
        self.approve_job()
        CONFIG["settings"]["confirm_before_submit"] = True
        page = SimpleNamespace(screenshot=AsyncMock())
        adapter = FakeAdapter()
        confirm = MagicMock(return_value=True)
        result = asyncio.run(execute_ats_submission(page, self.job, package=self.package,
            adapter=adapter, dry_run=False, confirm_submit=confirm))
        self.assertTrue(result)
        page.screenshot.assert_awaited_once()
        confirm.assert_called_once()

    def test_uncertain_click_cannot_retry_even_after_manual_status_reset(self):
        self.approve_job()
        adapter = FakeAdapter()
        adapter.submit.side_effect = TimeoutError("connection lost after click")
        result = self.execute(adapter, dry_run=False)
        self.assertFalse(result)
        self.assertEqual(result.state, JobState.SUBMITTED_UNVERIFIED)
        db.update_state(self.job["url"], "APPROVED")
        with self.assertRaises(db.SubmissionBlockedError):
            db.reserve_submission(self.job["url"], 25)

    def test_same_job_has_only_one_concurrent_reservation(self):
        self.approve_job()

        def reserve(_):
            try:
                return db.reserve_submission(self.job["url"], 25)
            except db.SubmissionBlockedError:
                return None

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(reserve, range(4)))
        self.assertEqual(sum(token is not None for token in results), 1)
        self.assertEqual(db.get_daily_apply_count(), 1)

    def test_different_jobs_share_atomic_daily_cap(self):
        other = dict(self.job, url="https://example.com/job/2", title="Data Engineer")
        self.approve_job()
        self.approve_job(other)
        token = db.reserve_submission(self.job["url"], 1)
        with self.assertRaises(db.SubmissionBlockedError):
            db.reserve_submission(other["url"], 1)
        db.finish_submission(token, "aborted")
        self.assertTrue(db.reserve_submission(other["url"], 1))

    def test_duplicate_role_cannot_reserve_different_urls_concurrently(self):
        other = dict(self.job, url="https://example.com/job/2")
        self.approve_job()
        self.approve_job(other)
        db.reserve_submission(self.job["url"], 25)
        with self.assertRaises(db.SubmissionBlockedError):
            db.reserve_submission(other["url"], 25)

    def test_submission_date_not_discovery_date_controls_daily_cap(self):
        self.approve_job()
        with db._get_connection() as conn:
            conn.execute("UPDATE applications SET applied_at='2001-01-01' WHERE url=?", (self.job["url"],))
        self.execute(FakeAdapter(), dry_run=False)
        self.assertEqual(db.get_daily_apply_count(), 1)

    def test_error_after_submit_boundary_never_becomes_retryable(self):
        self.approve_job()
        token = db.reserve_submission(self.job["url"], 25)
        db.mark_submission_started(token)
        db.finish_submission(token, "failed")
        self.assertEqual(get_job_state(self.job["url"]), JobState.SUBMITTED_UNVERIFIED)

    def test_backup_preserves_data_and_refuses_overwrite(self):
        self.approve_job()
        path = str(Path(self.directory.name) / "backup.db")
        db.backup_database(path)
        with closing(sqlite3.connect(path)) as conn:
            self.assertEqual(conn.execute("SELECT url FROM applications").fetchone()[0], self.job["url"])
        with self.assertRaises(FileExistsError):
            db.backup_database(path)
        with self.assertRaises(ValueError):
            db.backup_database(db.SQLITE_DB_PATH)

    def test_illegal_transition_does_not_change_checkpoint(self):
        db.save_to_db(self.job["url"], "Engineer", "Example", "test", "DISCOVERED", checkpoint="discovered")
        with self.assertRaises(ValueError):
            transition(self.job["url"], JobState.SUBMITTED, checkpoint="submitted")
        self.assertEqual(db.get_application(self.job["url"])["checkpoint"], "discovered")

    def test_migration_preserves_secret_if_keyring_unavailable(self):
        config = {"smtp": {"password": "test-secret"}}
        with patch.object(credential_store, "_keyring_available", False):
            self.assertFalse(credential_store.migrate_plaintext_credentials(config))
            self.assertEqual(config["smtp"]["password"], "test-secret")
            with self.assertRaises(credential_store.CredentialStoreError):
                credential_store.store_credential("smtp.password", "test-secret")

    def test_legal_answers_are_explicit_and_sponsorship_is_not_authorization(self):
        candidate = {"name": "Test Candidate", "qa_vault": {"work_authorization": "Yes", "require_sponsorship": "No"}}
        answers = _build_form_answers(candidate, candidate["qa_vault"])
        self.assertEqual(answers["sponsorship_required"], "No")
        self.assertEqual(_match_vault("Do you require visa sponsorship?", candidate), "No")
        self.assertIsNone(_match_vault("Are you a citizen?", candidate))
        self.assertEqual(_build_form_answers({}, {})["work_authorization"], "")
        self.assertEqual(_build_form_answers({}, {})["sponsorship_required"], "")

    def test_cover_letter_does_not_invent_experience_or_skills(self):
        text = _generate_cover_letter({"name": "Test", "skills": ["Python"]}, "Engineer", "Example", ["Kubernetes"], [])
        self.assertNotIn("Kubernetes", text)
        self.assertNotIn("built scalable", text)
        self.assertNotIn("high-performance", text)

    def test_smtp_failure_propagates(self):
        with patch("core.email_smtp.get_credential", return_value="secret"), patch("core.email_smtp.smtplib.SMTP") as smtp:
            smtp.return_value.__enter__.return_value.login.side_effect = smtplib.SMTPAuthenticationError(535, b"denied")
            with self.assertRaises(smtplib.SMTPAuthenticationError):
                send_smtp_email("recipient@example.com", "Subject", "Body", "")

    def test_smtp_rejected_recipient_is_not_success(self):
        with patch("core.email_smtp.get_credential", return_value="secret"), patch("core.email_smtp.smtplib.SMTP") as smtp:
            smtp.return_value.__enter__.return_value.send_message.return_value = {"recipient@example.com": (550, b"denied")}
            with self.assertRaises(smtplib.SMTPRecipientsRefused):
                send_smtp_email("recipient@example.com", "Subject", "Body", "")

    def test_smtp_missing_attachment_aborts_before_connection(self):
        with patch("core.email_smtp.get_credential", return_value="secret"), patch("core.email_smtp.smtplib.SMTP") as smtp:
            with self.assertRaises(FileNotFoundError):
                send_smtp_email("recipient@example.com", "Subject", "Body", "missing-resume.pdf")
            smtp.assert_not_called()

    def test_zero_and_false_are_explicit_vault_values(self):
        candidate = {"qa_vault": {"experience_years": 0, "current_ctc": 0, "require_sponsorship": False}}
        self.assertEqual(_match_vault("Years of experience", candidate), "0")
        self.assertEqual(_match_vault("Current salary", candidate), "0")

    def test_duplicate_completed_after_precheck_is_blocked_at_reservation(self):
        other = dict(self.job, url="https://example.com/job/2")
        self.approve_job()
        self.approve_job(other)
        token = db.reserve_submission(self.job["url"], 25)
        db.mark_submission_started(token)
        db.finish_submission(token, "submitted")
        with self.assertRaises(db.SubmissionBlockedError):
            db.reserve_submission(other["url"], 25)

    def test_reserved_yesterday_rechecks_today_cap_before_click(self):
        other = dict(self.job, url="https://example.com/job/2", title="Data Engineer")
        self.approve_job()
        self.approve_job(other)
        token = db.reserve_submission(self.job["url"], 1)
        with db._get_connection() as conn:
            conn.execute("UPDATE submission_attempts SET attempt_day='2001-01-01' WHERE token=?", (token,))
        db.reserve_submission(other["url"], 1)
        with self.assertRaises(db.SubmissionBlockedError):
            db.mark_submission_started(token, 1)

    def test_revoked_reservation_cannot_start_submission(self):
        self.approve_job()
        token = db.reserve_submission(self.job["url"], 25)
        db.finish_submission(token, "aborted")
        with self.assertRaises(db.SubmissionBlockedError):
            db.mark_submission_started(token)

    def test_discovery_does_not_reset_existing_approval(self):
        from automation.orchestrator import process_job
        self.approve_job()
        with patch("automation.orchestrator.evaluate_opportunity") as evaluate:
            result = process_job(self.job, dry_run=False)
        evaluate.assert_not_called()
        self.assertEqual(result.state, JobState.APPROVED)
        self.assertEqual(get_job_state(self.job["url"]), JobState.APPROVED)

    def test_database_failure_does_not_pass_duplicate_checks(self):
        with patch.object(db, "_get_connection", side_effect=sqlite3.OperationalError("unavailable")):
            with self.assertRaises(RuntimeError):
                db.suppression_verdict(None, "Example", "Engineer", "description")

    def test_failed_atomic_config_save_preserves_original_file(self):
        path = Path(self.directory.name) / "config.json"
        original = '{"saved": true}'
        path.write_text(original, encoding="utf-8")
        with patch.object(config_manager, "BASE_DIR", self.directory.name), patch.object(config_manager, "CONFIG_PATH", str(path)), \
             patch("core.config_manager.os.replace", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                config_manager.save_config()
        self.assertEqual(path.read_text(encoding="utf-8"), original)
        self.assertEqual(list(Path(self.directory.name).glob(".config-*.tmp")), [])

    def test_corrupt_config_is_not_replaced_with_defaults(self):
        path = Path(self.directory.name) / "config.json"
        path.write_text("broken JSON", encoding="utf-8")
        with patch.object(config_manager, "CONFIG_PATH", str(path)):
            with self.assertRaises(ValueError):
                config_manager.load_config()
        self.assertEqual(path.read_text(encoding="utf-8"), "broken JSON")


if __name__ == "__main__":
    unittest.main()
