# Backend safety and operations

Discovery now saves reviewable opportunities even when **Preview only** is enabled. Preview controls submission, not discovery.
In Settings, leave Preview only on until your profile and work authorization answers are accurate.
Turning it off enables live execution after approval; final confirmation remains enabled by default.

## Submission guarantees

- All application execution uses the same ATS executor. Autofill never clicks final Submit.
- SQLite schema v8 atomically reserves the approved application and a daily slot. Concurrent workers cannot claim the same role.
- Reservations and attempted submissions count toward the daily cap. Aborted/failed pre-submit attempts release their slot.
- Submission date is recorded separately from discovery date. Existing historical rows retain their original timestamps.
- A visible receipt is required for `SUBMITTED`. Missing confirmation or an error after the click boundary becomes `SUBMITTED_UNVERIFIED`.
- Unverified submissions suppress another attempt at that URL, including after a manual status change. Check the employer portal instead of retrying.
- Validation failures and operator aborts return to the approval queue. A new review is required before retrying.
- Unknown form questions, missing legal answers, and ambiguous visa questions require human input. The model does not invent answers.
- Prepared packages are reloaded from disk and checked against the approved job URL.

These guards do not promise support for every employer's custom form. Unsupported forms stop for review rather than claim success.
Receipt detection currently recognizes common English confirmation messages. Other messages remain unverified.

## Audit and backup

Use the project's Python environment:

```powershell
.\venv\Scripts\python.exe scripts\submission_audit.py
.\venv\Scripts\python.exe scripts\submission_audit.py --url "https://example.com/job/123"
.\venv\Scripts\python.exe scripts\submission_audit.py --backup "venture-backup.db"
```

The audit shows the latest 200 attempts, their statuses, and current daily slots used.
The backup uses SQLite's backup API, includes WAL data, and refuses to overwrite an existing file.
Backups and review screenshots contain personal information. Store them privately.

After a crash, stop the agent and other Venture instances before revoking an interrupted reservation:

```powershell
.\venv\Scripts\python.exe scripts\submission_audit.py --abort-reservation "TOKEN_FROM_AUDIT"
```

If the final click had started, revocation quarantines the attempt as unverified. It does not make the job safe to resubmit.
No automatic retry occurs after an uncertain external side effect.

## Configuration and credentials

Configuration saves use a flushed temporary file and atomic replacement. Invalid JSON is preserved and reported, not silently replaced.
Credentials must persist in the OS keyring. Failed migration preserves the original value; failed saving reports an error.
If an old config contains plaintext credentials and keyring is unavailable, fix secure storage and restart to complete migration.
SMTP uses verified TLS, bounded network timeouts, and reports authentication or recipient failures to the caller.
Requested attachments must exist before sending.

Set `VENTURE_DATA_DIR` before starting Python to isolate config, database, packages, logs, and screenshots from the normal project directory.
The path should be a private, writable directory. This is also how tests avoid touching personal data.

## Verification

```powershell
.\venv\Scripts\python.exe tests\test_backend_hardening.py
.\venv\Scripts\python.exe tests\test_ui_presentation.py
```

The hardening suite uses temporary databases, mock ATS adapters, and mock SMTP. It never submits a real application or sends email.
The older pytest suite additionally covers scoring, migrations, and synthetic browser fixtures; run it after installing the existing requirements.
