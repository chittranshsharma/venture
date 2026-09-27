import os
import csv
import json
import sqlite3
import shutil
import threading
from datetime import datetime
import core.state as state

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQLITE_DB_PATH = os.path.join(BASE_DIR, "venture.db")
APPLIED_DB_PATH = os.path.join(BASE_DIR, "applied_jobs.csv")
RECRUITER_DB_PATH = os.path.join(BASE_DIR, "recruiter_contacts.csv")
LOG_FILE_PATH = os.path.join(BASE_DIR, "bot_logs.txt")

DB_LOCK = threading.Lock()
RECRUITER_CACHE_SET = set()
APPLIED_URLS_SET = set()

# P2.2 — Application Status Lifecycle (5 States)
class AppStatus:
    APPLIED   = "Applied"
    REJECTED  = "Rejected"
    INTERVIEW = "Interview"
    OFFER     = "Offer"
    WITHDRAWN = "Withdrawn"

def _get_connection():
    """Create a thread-safe connection to the SQLite database with WAL mode."""
    conn = sqlite3.connect(SQLITE_DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def _init_db_schema():
    """Initialize SQLite tables and indices as specified in Phase 2."""
    with DB_LOCK:
        try:
            with _get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS applications (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    url         TEXT NOT NULL UNIQUE,
                    title       TEXT,
                    company     TEXT,
                    platform    TEXT,
                    status      TEXT DEFAULT 'Applied',
                    score       INTEGER DEFAULT 0,
                    reason      TEXT,
                    strengths   TEXT,  -- stored as JSON array string
                    gaps        TEXT,  -- stored as JSON array string
                    applied_at  TEXT,
                    updated_at  TEXT
                );
                """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_url     ON applications(url);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_status  ON applications(status);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_company ON applications(company);")

                cursor.execute("""
                CREATE TABLE IF NOT EXISTS recruiter_contacts (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    company         TEXT,
                    role            TEXT,
                    recruiter_name  TEXT,
                    email           TEXT,
                    phone           TEXT,
                    platform        TEXT,
                    job_url         TEXT,
                    found_at        TEXT
                );
                """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_recruiter_url   ON recruiter_contacts(job_url);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_recruiter_email ON recruiter_contacts(email);")

                cursor.execute("""
                CREATE TABLE IF NOT EXISTS logs (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    message   TEXT,
                    logged_at TEXT DEFAULT (datetime('now'))
                );
                """)
                conn.commit()
        except Exception as e:
            print(f"Error initializing SQLite database: {e}")

def _migrate_csv_to_sqlite():
    """
    P2.1 Migration logic — On first run:
    1. Check if applied_jobs.csv exists.
    2. Read all rows and INSERT OR IGNORE into applications table.
    3. Move CSVs to backups/applied_jobs_backup.csv.
    4. Migrate recruiter_contacts.csv if present to backups/recruiter_contacts_backup.csv.
    5. Set migrated = true flag in config file.
    """
    backups_dir = os.path.join(BASE_DIR, "backups")
    
    # 1. Migrate applied_jobs.csv
    if os.path.exists(APPLIED_DB_PATH):
        try:
            os.makedirs(backups_dir, exist_ok=True)
            with open(APPLIED_DB_PATH, mode='r', encoding='utf-8') as f:
                reader = csv.reader(f)
                next(reader, None)  # skip header
                rows_to_insert = []
                for row in reader:
                    if row and len(row) >= 5:
                        url = row[0].strip()
                        if not url:
                            continue
                        title = row[1] if len(row) > 1 else ""
                        company = row[2] if len(row) > 2 else ""
                        platform = row[3] if len(row) > 3 else ""
                        status = row[4] if len(row) > 4 else "Applied"
                        detail = row[5] if len(row) > 5 else ""
                        ts = row[6] if len(row) > 6 else datetime.now().isoformat()
                        rows_to_insert.append((url, title, company, platform, status, 0, detail, "[]", "[]", ts, ts))
                
                if rows_to_insert:
                    with _get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.executemany("""
                            INSERT OR IGNORE INTO applications 
                            (url, title, company, platform, status, score, reason, strengths, gaps, applied_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, rows_to_insert)
                        conn.commit()
            
            backup_applied = os.path.join(backups_dir, "applied_jobs_backup.csv")
            if os.path.exists(backup_applied):
                os.remove(backup_applied)
            shutil.move(APPLIED_DB_PATH, backup_applied)
            print("[Migration] applied_jobs.csv migrated to SQLite and moved to backups/applied_jobs_backup.csv")
        except Exception as e:
            print(f"[Migration Error] applied_jobs.csv: {e}")

    # 2. Migrate recruiter_contacts.csv
    if os.path.exists(RECRUITER_DB_PATH):
        try:
            os.makedirs(backups_dir, exist_ok=True)
            with open(RECRUITER_DB_PATH, mode='r', encoding='utf-8') as f:
                reader = csv.reader(f)
                next(reader, None)
                recruiter_rows = []
                for row in reader:
                    if row and len(row) >= 7:
                        comp = row[0]
                        role = row[1]
                        name = row[2]
                        email = row[3]
                        phone = row[4]
                        platform = row[5]
                        url = row[6]
                        ts = row[7] if len(row) > 7 else datetime.now().isoformat()
                        recruiter_rows.append((comp, role, name, email, phone, platform, url, ts))
                
                if recruiter_rows:
                    with _get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.executemany("""
                            INSERT INTO recruiter_contacts
                            (company, role, recruiter_name, email, phone, platform, job_url, found_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, recruiter_rows)
                        conn.commit()

            backup_recruiter = os.path.join(backups_dir, "recruiter_contacts_backup.csv")
            if os.path.exists(backup_recruiter):
                os.remove(backup_recruiter)
            shutil.move(RECRUITER_DB_PATH, backup_recruiter)
            print("[Migration] recruiter_contacts.csv migrated to SQLite and moved to backups/recruiter_contacts_backup.csv")
        except Exception as e:
            print(f"[Migration Error] recruiter_contacts.csv: {e}")

    # 3. Set migrated = true in config.json
    try:
        config_file = os.path.join(BASE_DIR, "config.json")
        if os.path.exists(config_file):
            with open(config_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if not cfg.get("migrated", False):
                cfg["migrated"] = True
                with open(config_file, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=4)
                print("[Migration] Set migrated = true in config.json")
    except Exception as e:
        print(f"[Migration Error] Setting migrated flag: {e}")

def _init_recruiter_cache():
    if not RECRUITER_CACHE_SET:
        try:
            with _get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT company, email, job_url FROM recruiter_contacts")
                for row in cursor.fetchall():
                    c_comp, c_email, c_url = row[0], row[1], row[2]
                    if c_url:
                        RECRUITER_CACHE_SET.add(f"url:{c_url}")
                    if c_comp and c_email:
                        RECRUITER_CACHE_SET.add(f"comp:{c_comp}:email:{c_email}")
        except Exception:
            pass

def save_recruiter_contact(company, role, recruiter_name, email, phone, platform, url):
    """Save extracted recruiter contact details to recruiter_contacts table in SQLite."""
    if not (email or phone or recruiter_name):
        return
    
    with DB_LOCK:
        _init_recruiter_cache()
        cache_key_url = f"url:{url}" if url else None
        cache_key_comp_email = f"comp:{company}:email:{email}" if company and email else None
        
        if (cache_key_url and cache_key_url in RECRUITER_CACHE_SET) or \
           (cache_key_comp_email and cache_key_comp_email in RECRUITER_CACHE_SET):
            return

        now = datetime.now().isoformat()
        try:
            with _get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO recruiter_contacts 
                    (company, role, recruiter_name, email, phone, platform, job_url, found_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (company, role, recruiter_name, email, phone, platform, url, now))
                conn.commit()
            if cache_key_url:
                RECRUITER_CACHE_SET.add(cache_key_url)
            if cache_key_comp_email:
                RECRUITER_CACHE_SET.add(cache_key_comp_email)
            log_message(f"📇 RECRUITER CONTACT FOUND: {company} ({role}) -> Email: '{email}', Phone: '{phone}'")
        except Exception as e:
            log_message(f"Error saving recruiter contact: {e}")

def load_recruiter_contacts():
    """Load all recruiter contacts from SQLite database."""
    with DB_LOCK:
        contacts = []
        try:
            with _get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT company, role, recruiter_name, email, phone, platform, job_url, found_at 
                    FROM recruiter_contacts 
                    ORDER BY id DESC
                """)
                for row in cursor.fetchall():
                    contacts.append({
                        "company": row[0] or "",
                        "role": row[1] or "",
                        "recruiter_name": row[2] or "",
                        "email": row[3] or "",
                        "phone": row[4] or "",
                        "platform": row[5] or "",
                        "url": row[6] or "",
                        "timestamp": row[7] or ""
                    })
        except Exception as e:
            log_message(f"Error loading recruiter contacts: {e}")
        return contacts

def init_applied_urls():
    """Load all applied URLs from SQLite into the shared in-memory set."""
    global APPLIED_URLS_SET
    APPLIED_URLS_SET = load_applied_urls()

def log_message(msg):
    """Write log to in-memory queue, file, and SQLite logs table."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_msg = f"[{timestamp}] {msg}"
    state.LOG_QUEUE.append(full_msg)
    try:
        with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
            f.write(full_msg + "\n")
    except Exception as e:
        print(f"Error writing log file: {e}")
    try:
        with _get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO logs (message, logged_at) VALUES (?, ?)", (msg, timestamp))
            conn.commit()
    except Exception:
        pass

def save_to_db(url, title, company, platform, status, detail="", score=0, strengths=None, gaps=None):
    """
    Save application to SQLite database. Keeps exact same call signature with optional score/strengths/gaps.
    Atomic insert with update on conflict.
    """
    if not url:
        return
    now = datetime.now().isoformat()
    strengths_json = json.dumps(strengths) if isinstance(strengths, list) else (str(strengths) if strengths else "[]")
    gaps_json = json.dumps(gaps) if isinstance(gaps, list) else (str(gaps) if gaps else "[]")

    with DB_LOCK:
        try:
            with _get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO applications (url, title, company, platform, status, score, reason, strengths, gaps, applied_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(url) DO UPDATE SET
                        title = CASE WHEN excluded.title != '' THEN excluded.title ELSE applications.title END,
                        company = CASE WHEN excluded.company != '' THEN excluded.company ELSE applications.company END,
                        platform = CASE WHEN excluded.platform != '' THEN excluded.platform ELSE applications.platform END,
                        status = excluded.status,
                        score = CASE WHEN excluded.score != 0 THEN excluded.score ELSE applications.score END,
                        reason = CASE WHEN excluded.reason != '' THEN excluded.reason ELSE applications.reason END,
                        strengths = CASE WHEN excluded.strengths != '[]' THEN excluded.strengths ELSE applications.strengths END,
                        gaps = CASE WHEN excluded.gaps != '[]' THEN excluded.gaps ELSE applications.gaps END,
                        updated_at = excluded.updated_at
                """, (url, title, company, platform, status, score or 0, detail or "", strengths_json, gaps_json, now, now))
                conn.commit()

            APPLIED_URLS_SET.add(url)
            
            # Increment daily session counter for safety cap enforcement
            if status in [AppStatus.APPLIED, "Manual Approval Apply", "SUBMITTED"]:
                state.SESSION_STATS["applied_today"] = state.SESSION_STATS.get("applied_today", 0) + 1
            if status in [AppStatus.INTERVIEW, "Interviewing"]:
                state.SESSION_STATS["interviews"] = state.SESSION_STATS.get("interviews", 0) + 1
            if status in [AppStatus.OFFER, "Offer Received"]:
                state.SESSION_STATS["offers"] = state.SESSION_STATS.get("offers", 0) + 1
            if status == "Suggested":
                state.SUGGESTION_COUNT += 1
                
            recalculate_metrics_unlocked()
        except Exception as e:
            log_message(f"Error saving to DB: {e}")

def update_job_status_in_csv(url_key, old_status, new_status, new_detail=""):
    """
    Backwards-compatible helper to update a job's status in SQLite applications table.
    Returns True if updated.
    """
    now = datetime.now().isoformat()
    updated = False
    with DB_LOCK:
        try:
            with _get_connection() as conn:
                cursor = conn.cursor()
                if old_status:
                    if new_detail:
                        cursor.execute("""
                            UPDATE applications 
                            SET status = ?, reason = ?, updated_at = ? 
                            WHERE url = ? AND status = ?
                        """, (new_status, new_detail, now, url_key, old_status))
                    else:
                        cursor.execute("""
                            UPDATE applications 
                            SET status = ?, updated_at = ? 
                            WHERE url = ? AND status = ?
                        """, (new_status, now, url_key, old_status))
                else:
                    if new_detail:
                        cursor.execute("""
                            UPDATE applications 
                            SET status = ?, reason = ?, updated_at = ? 
                            WHERE url = ?
                        """, (new_status, new_detail, now, url_key))
                    else:
                        cursor.execute("""
                            UPDATE applications 
                            SET status = ?, updated_at = ? 
                            WHERE url = ?
                        """, (new_status, now, url_key))
                
                if cursor.rowcount > 0:
                    updated = True
                    conn.commit()
            if updated:
                recalculate_metrics_unlocked()
        except Exception as e:
            log_message(f"Error updating job status: {e}")
    return updated

# Alias for modern code
update_job_status = update_job_status_in_csv

def get_state(url: str):
    """P2.3 — Get current state/status of an application by URL."""
    with DB_LOCK:
        try:
            with _get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT status FROM applications WHERE url = ?", (url,))
                row = cursor.fetchone()
                return row[0] if row else None
        except Exception as e:
            log_message(f"Error getting state for {url}: {e}")
            return None

def update_state(url: str, new_state: str, detail: str = ""):
    """P2.3 — Atomically transition application to new state in SQLite."""
    now = datetime.now().isoformat()
    with DB_LOCK:
        try:
            with _get_connection() as conn:
                cursor = conn.cursor()
                if detail:
                    cursor.execute("""
                        UPDATE applications 
                        SET status = ?, reason = ?, updated_at = ? 
                        WHERE url = ?
                    """, (new_state, detail, now, url))
                else:
                    cursor.execute("""
                        UPDATE applications 
                        SET status = ?, updated_at = ? 
                        WHERE url = ?
                    """, (new_state, now, url))
                    
                if cursor.rowcount == 0:
                    # Application record not found yet, create initial entry
                    cursor.execute("""
                        INSERT INTO applications (url, status, reason, applied_at, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (url, new_state, detail, now, now))
                conn.commit()
            APPLIED_URLS_SET.add(url)
            recalculate_metrics_unlocked()
        except Exception as e:
            log_message(f"Error updating state for {url}: {e}")

def recalculate_metrics_unlocked():
    """Recalculate summary metrics from SQLite applications table."""
    applied = 0
    skipped = 0
    suggested = 0
    interview = 0
    offer = 0
    platforms = {"Indeed": 0, "Naukri": 0, "LinkedIn": 0}

    try:
        with _get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status, platform, COUNT(*) FROM applications GROUP BY status, platform")
            for status, platform, count in cursor.fetchall():
                status_str = status or ""
                if status_str in [AppStatus.APPLIED, "Manual Approval Apply", "SUBMITTED"]:
                    applied += count
                elif status_str in [AppStatus.REJECTED, "Skipped", "Manual User Disapproval", AppStatus.WITHDRAWN, "FAILED"]:
                    skipped += count
                elif status_str == "Suggested":
                    suggested += count
                elif status_str in [AppStatus.INTERVIEW, "Interviewing"]:
                    interview += count
                elif status_str in [AppStatus.OFFER, "Offer Received"]:
                    offer += count
                
                if platform in platforms:
                    platforms[platform] += count
    except Exception:
        pass

    state.METRICS["applied"] = applied
    state.METRICS["skipped"] = skipped
    state.METRICS["suggested"] = suggested
    state.METRICS["interview"] = interview
    state.METRICS["offer"] = offer
    state.METRICS["platforms"] = platforms
    state.SUGGESTION_COUNT = suggested

def recalculate_metrics():
    with DB_LOCK:
        recalculate_metrics_unlocked()

def load_applied_urls():
    """Return set of all URLs present in SQLite applications table for instant dedup."""
    urls = set()
    try:
        with DB_LOCK:
            with _get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT url FROM applications")
                for row in cursor.fetchall():
                    if row and row[0]:
                        urls.add(row[0])
    except Exception as e:
        log_message(f"Error loading applied URLs from SQLite: {e}")
    return urls

def get_applications_history():
    """Load application records for History View table."""
    records = []
    with DB_LOCK:
        try:
            with _get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT company, title, platform, status, reason, applied_at, url 
                    FROM applications 
                    ORDER BY id DESC
                """)
                for row in cursor.fetchall():
                    records.append({
                        "company": row[0] or "Unknown Company",
                        "role": row[1] or "Unknown Role",
                        "platform": row[2] or "",
                        "status": row[3] or "Applied",
                        "detail": row[4] or "",
                        "applied_at": row[5] or "",
                        "url": row[6] or ""
                    })
        except Exception as e:
            log_message(f"Error fetching history records: {e}")
    return records

def get_suggested_jobs():
    """Load suggested jobs for Suggestions View table."""
    records = []
    with DB_LOCK:
        try:
            with _get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT url, company, title, reason 
                    FROM applications 
                    WHERE status = 'Suggested'
                    ORDER BY id DESC
                """)
                for row in cursor.fetchall():
                    records.append({
                        "url": row[0],
                        "company": row[1] or "Unknown Company",
                        "role": row[2] or "Unknown Role",
                        "detail": row[3] or ""
                    })
        except Exception as e:
            log_message(f"Error fetching suggestions: {e}")
    return records

def export_applications_to_csv(export_path: str) -> bool:
    """Export SQLite applications table to CSV file."""
    with DB_LOCK:
        try:
            with _get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT url, title, company, platform, status, reason, applied_at 
                    FROM applications 
                    ORDER BY id ASC
                """)
                rows = cursor.fetchall()
            with open(export_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["URL", "Title", "Company", "Platform", "Status", "Detail", "Timestamp"])
                for r in rows:
                    writer.writerow(list(r))
            return True
        except Exception as e:
            log_message(f"Error exporting applications to CSV: {e}")
            return False

def get_recent_history_text(limit=10) -> str:
    """Return formatted recent history summary string for LLM evaluator."""
    with DB_LOCK:
        try:
            with _get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT title, company, platform, status, applied_at 
                    FROM applications 
                    ORDER BY id DESC LIMIT ?
                """, (limit,))
                rows = cursor.fetchall()
                if not rows:
                    return "No previous applications recorded."
                lines = [f"- {r[0]} at {r[1]} ({r[2]}) - Status: {r[3]} ({r[4][:10] if r[4] else ''})" for r in rows]
                return "\n".join(lines)
        except Exception:
            return ""

# Auto-initialize schema and perform migration check on module import
_init_db_schema()
_migrate_csv_to_sqlite()
APPLIED_URLS_SET = load_applied_urls()
