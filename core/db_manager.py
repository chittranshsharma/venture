import os
import csv
import json
import sqlite3
import shutil
import threading
import re
import hashlib
import random
from datetime import datetime
import core.state as state

def normalize_jd(t: str) -> str:
    """Normalize JD text, removing volatile scrape artifacts while preserving numbers and YOE."""
    t = (t or "").lower()
    t = re.sub(r"\b(posted|reposted|updated)\b[^.\n]{0,40}\bago\b", " ", t)
    t = re.sub(r"\b\d[\d,]*\+?\s+(applicants?|applications?|views?|clicks?|people)\b", " ", t)
    t = re.sub(r"\b(be among the first|over)\s+\d+\s+applicants?\b", " ", t)
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"[^\w\s+#.$-]", " ", t)
    return re.sub(r"\s+", " ", t).strip()

def normalize_company(c: str) -> str:
    """Strip legal suffixes (inc, ltd, llc, pvt) and punctuation for cross-platform dedup."""
    if not c:
        return ""
    c = c.lower().strip()
    c = re.sub(r"\b(inc\.?|incorporated|ltd\.?|limited|llc|pvt\.?|private|corp\.?|corporation|co\.?|gmbh)\b", "", c)
    return re.sub(r"[^a-z0-9]", "", c)

def normalize_location(loc: str) -> str:
    """Standardize location strings, grouping remote and hybrid variants."""
    if not loc:
        return ""
    loc = loc.lower().strip()
    if "remote" in loc:
        return "remote"
    if "hybrid" in loc:
        return "hybrid"
    return re.sub(r"[^a-z0-9]", "", loc)

def compute_dedup_key(company: str, title: str, location: str = "") -> str:
    """Canonical cross-platform job key: sha256(norm_company|norm_title|norm_loc)[:16]."""
    norm_c = normalize_company(company)
    norm_t = re.sub(r'[^a-z0-9]', '', (title or "").lower())
    norm_l = normalize_location(location)
    raw = f"{norm_c}|{norm_t}|{norm_l}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]

def compute_content_hash(text: str) -> str:
    """Normalized JD content hash to detect genuine revisions, ignoring dynamic scrape artifacts."""
    norm = normalize_jd(text)
    return hashlib.sha256(norm.encode('utf-8')).hexdigest()[:16]

def _u(url: str, content_hash: str) -> float:
    """Deterministic pseudo-random float in [0.0, 1.0) derived from SHA256(url|content_hash)."""
    if not url and not content_hash:
        return random.random()
    h = hashlib.sha256(f"{url}|{content_hash}".encode('utf-8')).digest()
    return int.from_bytes(h[:4], "big") / 2**32

def route(score: int, min_score: int, url: str = "", content_hash: str = "", explore_rate: float = 0.15, band: int = 20) -> tuple[str, float]:
    """
    Deterministic exploration routing using SHA256(url|content_hash).
    Returns (routing_action, propensity).
    - score >= min_score: ('queue', 1.0)
    - score in [min_score - band, min_score): ('explore', explore_rate) if _u < explore_rate else ('reject', explore_rate)
    - score < min_score - band: ('reject', 0.0)
    """
    if score >= min_score:
        return "queue", 1.0
    if score >= min_score - band:
        sampled = _u(url, content_hash) < explore_rate
        return ("explore" if sampled else "reject"), explore_rate
    return "reject", 0.0


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
            conn = _get_connection()
            try:
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

                # Versioned column migrations — run while we already hold the lock and connection
                _run_schema_migrations_locked(conn)
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            print(f"Error initializing SQLite database: {e}")


def _backfill_hashes_locked(conn, force_all: bool = False):
    """Backfill or re-normalize dedup_key and content_hash for application rows."""
    try:
        cursor = conn.cursor()
        cols = [r[1] for r in cursor.execute("PRAGMA table_info(applications)").fetchall()]
        has_jd = "jd_text" in cols
        jd_select = "jd_text" if has_jd else "reason AS jd_text"
        query = f"SELECT id, company, title, {jd_select}, reason FROM applications"
        if not force_all:
            query += " WHERE dedup_key IS NULL OR content_hash IS NULL"
        rows = cursor.execute(query).fetchall()
        for row_id, comp, tit, jdt, reas in rows:
            dk = compute_dedup_key(comp or "", tit or "")
            ch = compute_content_hash(jdt or reas or tit or "")
            cursor.execute(
                "UPDATE applications SET dedup_key = ?, content_hash = ? WHERE id = ?",
                (dk, ch, row_id)
            )
        if rows:
            print(f"[DB Migration] Computed normalized dedup_key and content_hash for {len(rows)} application rows.")
    except Exception as e:
        print(f"[DB Migration] Warning during hash backfill: {e}")


def _run_schema_migrations_locked(conn):
    """
    Versioned schema migrations using PRAGMA user_version.
    MUST be called while DB_LOCK is already held (called from _init_db_schema).
    Safe to run on every startup — each step is idempotent.

    Version 1: Feature columns for outcome learning, dedup, eval tracking,
               and the processed_emails dedup table for email-sync.
    Version 2: Append-only decisions table for ML training with feature snapshot,
               composite indexes, and hash backfill for existing rows.
    Version 3: Append-only evaluations table logging EVERY evaluated job across all routes,
               propensity column on decisions, and hash re-normalization.
    """
    try:
        v = conn.execute("PRAGMA user_version").fetchone()[0]

        if v < 1:
            new_cols = [
                ("rag_score",        "REAL"),
                ("seniority",        "TEXT"),
                ("skill_overlap",    "REAL"),
                ("jd_text",          "TEXT"),
                # dedup_key  = sha256(company|title|location) — cross-platform dedup
                ("dedup_key",        "TEXT"),
                # content_hash = sha256(normalized jd_text) — re-eval when JD content changes
                ("content_hash",     "TEXT"),
                # approval_label: 'approve'|'reject' from human decisions (primary LR label)
                ("approval_label",   "TEXT"),
                # eval harness: track which model+prompt produced each score
                ("prompt_version",   "TEXT"),
                ("eval_model",       "TEXT"),
                # rejection_source: 'constraint'|'llm'|'pre_filter' — exclude from score stats
                ("rejection_source", "TEXT"),
            ]
            for col, typ in new_cols:
                try:
                    conn.execute(f"ALTER TABLE applications ADD COLUMN {col} {typ}")
                except Exception:
                    pass  # column already exists — safe to ignore

            try:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_dedup        ON applications(dedup_key)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_content_hash ON applications(content_hash)")
            except Exception:
                pass

            # processed_emails: Message-ID dedup so email sync never double-processes
            conn.execute("""
                CREATE TABLE IF NOT EXISTS processed_emails (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id      TEXT NOT NULL UNIQUE,
                    matched_url     TEXT,
                    detected_status TEXT,
                    processed_at    TEXT DEFAULT (datetime('now'))
                )
            """)
            try:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_email_msgid ON processed_emails(message_id)")
            except Exception:
                pass

            conn.execute("PRAGMA user_version = 1")
            conn.commit()
            print("[DB Migration] Schema migrated to version 1.")

        if v < 2:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    content_hash TEXT,
                    label TEXT CHECK(label IN ('approve','reject')),
                    reject_reason TEXT,      -- not_fit|location|seniority|duplicate|company|other
                    llm_score INTEGER,
                    rag_score REAL,
                    seniority TEXT,
                    skill_overlap REAL,
                    eval_model TEXT,
                    prompt_version TEXT,
                    source TEXT,             -- queue|explore
                    decided_at TEXT DEFAULT (datetime('now'))
                )
            """)
            try:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_decisions_url ON decisions(url)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_applications_dedup ON applications(dedup_key)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_applications_chash ON applications(content_hash)")
            except Exception:
                pass

            _backfill_hashes_locked(conn)

            conn.execute("PRAGMA user_version = 2")
            conn.commit()
            print("[DB Migration] Schema migrated to version 2.")

        if v < 3:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS evaluations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    dedup_key TEXT,
                    content_hash TEXT,
                    title TEXT,
                    company TEXT,
                    jd_text TEXT,
                    llm_score INTEGER,
                    rag_score REAL,
                    seniority TEXT,
                    skill_overlap REAL,
                    route TEXT,              -- queue|explore|reject|prefilter|constraint
                    propensity REAL,         -- P(shown to human); 1.0 for queue
                    eval_model TEXT,
                    prompt_version TEXT,
                    evaluated_at TEXT DEFAULT (datetime('now'))
                )
            """)
            try:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_eval_url ON evaluations(url)")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE decisions ADD COLUMN propensity REAL")
            except Exception:
                pass

            _backfill_hashes_locked(conn, force_all=True)

            conn.execute("PRAGMA user_version = 3")
            conn.commit()
            print("[DB Migration] Schema migrated to version 3.")

        if v < 4:
            eval_cols = [r[1] for r in conn.execute("PRAGMA table_info(evaluations)").fetchall()]
            if "embedding_model" not in eval_cols:
                try:
                    conn.execute("ALTER TABLE evaluations ADD COLUMN embedding_model TEXT")
                except Exception:
                    pass

            try:
                conn.execute("""
                    DELETE FROM evaluations
                    WHERE id NOT IN (
                        SELECT MIN(id)
                        FROM evaluations
                        GROUP BY url, content_hash, IFNULL(eval_model, ''), IFNULL(prompt_version, '')
                    )
                """)
                conn.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS ux_eval_dedupe
                    ON evaluations(url, content_hash, IFNULL(eval_model, ''), IFNULL(prompt_version, ''))
                """)
            except Exception as e:
                print(f"[DB Migration] Note on ux_eval_dedupe: {e}")

            _backfill_hashes_locked(conn, force_all=True)

            conn.execute("PRAGMA user_version = 4")
            conn.commit()
            print("[DB Migration] Schema migrated to version 4.")

        if v < 5:
            # Telemetry for full explainability and closed-loop career outcome tracking
            for tbl in ["evaluations", "applications"]:
                cols = [r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()]
                if "features_json" not in cols:
                    try:
                        conn.execute(f"ALTER TABLE {tbl} ADD COLUMN features_json TEXT")
                    except Exception:
                        pass
                if "decision_reason" not in cols:
                    try:
                        conn.execute(f"ALTER TABLE {tbl} ADD COLUMN decision_reason TEXT")
                    except Exception:
                        pass
                if "outcome_stage" not in cols:
                    try:
                        conn.execute(f"ALTER TABLE {tbl} ADD COLUMN outcome_stage TEXT DEFAULT 'discovered'")
                    except Exception:
                        pass
                if "outcome_notes" not in cols:
                    try:
                        conn.execute(f"ALTER TABLE {tbl} ADD COLUMN outcome_notes TEXT")
                    except Exception:
                        pass

            conn.execute("PRAGMA user_version = 5")
            conn.commit()
            print("[DB Migration] Schema migrated to version 5 (Telemetry & Outcome Engine).")

        if v < 6:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(applications)").fetchall()]
            new_cols = [
                ("package_path",          "TEXT"),
                ("checkpoint",            "TEXT DEFAULT 'discovered'"),
                ("resume_version",        "TEXT"),
                ("cover_letter_version",  "TEXT"),
                ("answers_version",       "TEXT"),
            ]
            for col, typ in new_cols:
                if col not in cols:
                    try:
                        conn.execute(f"ALTER TABLE applications ADD COLUMN {col} {typ}")
                    except Exception:
                        pass

            conn.execute("PRAGMA user_version = 6")
            conn.commit()
            print("[DB Migration] Schema migrated to version 6 (Application Packaging & Checkpointing).")
    except Exception as e:
        print(f"[DB Migration] Error running migrations: {e}")


def log_evaluation(
    url: str,
    title: str,
    company: str,
    jd_text: str,
    llm_score: int = None,
    rag_score: float = None,
    seniority: str = None,
    skill_overlap: float = None,
    route: str = "queue",
    propensity: float = 1.0,
    eval_model: str = None,
    prompt_version: str = None,
    embedding_model: str = None,
    dedup_key: str = None,
    content_hash: str = None,
    features_json: str = None,
    decision_reason: str = None,
    outcome_stage: str = "discovered",
):
    """
    Log every evaluated job to the `evaluations` table regardless of outcome (queue, explore, reject, collected).
    Uses INSERT OR IGNORE against ux_eval_dedupe to eliminate radar poll duplication.
    """
    now = datetime.now().isoformat()
    dk = dedup_key or compute_dedup_key(company, title)
    ch = content_hash or compute_content_hash(jd_text)

    with DB_LOCK:
        conn = None
        try:
            conn = _get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO evaluations (
                    url, dedup_key, content_hash, title, company, jd_text,
                    llm_score, rag_score, seniority, skill_overlap,
                    route, propensity, eval_model, prompt_version, embedding_model,
                    features_json, decision_reason, outcome_stage, evaluated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                url, dk, ch, title, company, jd_text,
                llm_score, rag_score, seniority, skill_overlap,
                route, propensity, eval_model, prompt_version, embedding_model,
                features_json, decision_reason, outcome_stage, now
            ))
            conn.commit()
        except Exception as e:
            log_message(f"Error logging evaluation for {url}: {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass


def log_approval_decision(
    url: str,
    label: str,
    reject_reason: str = None,
    score: int = None,
    eval_model: str = None,
    prompt_version: str = None,
    rag_score: float = None,
    seniority: str = None,
    skill_overlap: float = None,
    content_hash: str = None,
    source: str = "queue",
    propensity: float = 1.0,
):
    """
    Record an append-only human approve/reject decision with full feature snapshot.
    Stored in `decisions` table for unbiased ML model training (logistic regression).
    Also updates `applications.approval_label` for current state visibility.
    """
    if propensity is None or propensity <= 0:
        propensity = 0.001  # IPW division-by-zero safety clamp
    assert propensity > 0, "Propensity must be strictly positive"
    now = datetime.now().isoformat()
    with DB_LOCK:
        conn = None
        try:
            conn = _get_connection()
            cursor = conn.cursor()

            # Fetch existing snapshot features from applications if missing
            try:
                row = cursor.execute("""
                    SELECT content_hash, score, rag_score, seniority, skill_overlap, eval_model, prompt_version
                    FROM applications WHERE url = ?
                """, (url,)).fetchone()
                if row:
                    if content_hash is None:
                        content_hash = row[0]
                    if score is None:
                        score = row[1]
                    if rag_score is None:
                        rag_score = row[2]
                    if seniority is None:
                        seniority = row[3]
                    if skill_overlap is None:
                        skill_overlap = row[4]
                    if eval_model is None:
                        eval_model = row[5]
                    if prompt_version is None:
                        prompt_version = row[6]
            except Exception as ex:
                log_message(f"Warning retrieving snapshot features for {url}: {ex}")

            # Insert immutable decision snapshot (including propensity for inverse propensity weighting)
            cursor.execute("""
                INSERT INTO decisions (
                    url, content_hash, label, reject_reason,
                    llm_score, rag_score, seniority, skill_overlap,
                    eval_model, prompt_version, source, propensity, decided_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                url, content_hash, label, reject_reason,
                score, rag_score, seniority, skill_overlap,
                eval_model, prompt_version, source, propensity, now
            ))

            # Update applications row for backwards compatibility and current-state queries
            cursor.execute(
                "UPDATE applications SET approval_label=?, updated_at=? WHERE url=?",
                (label, now, url)
            )
            conn.commit()
            log_message(f"[DECISION LOGGED] {label.upper()} for {url[:40]} (source={source}, reason={reject_reason or 'fit'}, score={score})")
        except Exception as e:
            log_message(f"Error logging approval decision for {url}: {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

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

def save_to_db(url, title, company, platform, status, detail="", score=0, strengths=None, gaps=None,
               dedup_key=None, content_hash=None, rag_score=None, seniority=None, skill_overlap=None,
               eval_model=None, prompt_version=None, jd_text=None,
               features_json=None, decision_reason=None, outcome_stage=None,
               package_path=None, checkpoint=None, resume_version=None,
               cover_letter_version=None, answers_version=None):
    """
    Save application to SQLite database. Keeps exact same call signature with optional score/strengths/gaps.
    Atomic insert with update on conflict, auto-populating dedup_key, content_hash, package_path, and checkpoint.
    """
    if not url:
        return
    now = datetime.now().isoformat()
    strengths_json = json.dumps(strengths) if isinstance(strengths, list) else (str(strengths) if strengths else "[]")
    gaps_json = json.dumps(gaps) if isinstance(gaps, list) else (str(gaps) if gaps else "[]")
    dk = dedup_key or compute_dedup_key(company, title)
    ch = content_hash or compute_content_hash(jd_text or detail or title)

    with DB_LOCK:
        try:
            with _get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO applications (
                        url, title, company, platform, status, score, reason, strengths, gaps,
                        applied_at, updated_at, dedup_key, content_hash,
                        rag_score, seniority, skill_overlap, eval_model, prompt_version, jd_text,
                        features_json, decision_reason, outcome_stage,
                        package_path, checkpoint, resume_version, cover_letter_version, answers_version
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(url) DO UPDATE SET
                        title = CASE WHEN excluded.title != '' THEN excluded.title ELSE applications.title END,
                        company = CASE WHEN excluded.company != '' THEN excluded.company ELSE applications.company END,
                        platform = CASE WHEN excluded.platform != '' THEN excluded.platform ELSE applications.platform END,
                        status = excluded.status,
                        score = CASE WHEN excluded.score != 0 THEN excluded.score ELSE applications.score END,
                        reason = CASE WHEN excluded.reason != '' THEN excluded.reason ELSE applications.reason END,
                        strengths = CASE WHEN excluded.strengths != '[]' THEN excluded.strengths ELSE applications.strengths END,
                        gaps = CASE WHEN excluded.gaps != '[]' THEN excluded.gaps ELSE applications.gaps END,
                        updated_at = excluded.updated_at,
                        dedup_key = COALESCE(excluded.dedup_key, applications.dedup_key),
                        content_hash = COALESCE(excluded.content_hash, applications.content_hash),
                        rag_score = COALESCE(excluded.rag_score, applications.rag_score),
                        seniority = COALESCE(excluded.seniority, applications.seniority),
                        skill_overlap = COALESCE(excluded.skill_overlap, applications.skill_overlap),
                        eval_model = COALESCE(excluded.eval_model, applications.eval_model),
                        prompt_version = COALESCE(excluded.prompt_version, applications.prompt_version),
                        jd_text = CASE WHEN excluded.jd_text IS NOT NULL AND excluded.jd_text != '' THEN excluded.jd_text ELSE applications.jd_text END,
                        features_json = COALESCE(excluded.features_json, applications.features_json),
                        decision_reason = COALESCE(excluded.decision_reason, applications.decision_reason),
                        outcome_stage = COALESCE(excluded.outcome_stage, applications.outcome_stage),
                        package_path = COALESCE(excluded.package_path, applications.package_path),
                        checkpoint = COALESCE(excluded.checkpoint, applications.checkpoint),
                        resume_version = COALESCE(excluded.resume_version, applications.resume_version),
                        cover_letter_version = COALESCE(excluded.cover_letter_version, applications.cover_letter_version),
                        answers_version = COALESCE(excluded.answers_version, applications.answers_version)
                """, (
                    url, title, company, platform, status, score or 0, detail or "", strengths_json, gaps_json,
                    now, now, dk, ch,
                    rag_score, seniority, skill_overlap, eval_model, prompt_version, jd_text,
                    features_json, decision_reason, outcome_stage or "discovered",
                    package_path, checkpoint or "discovered", resume_version or "v1",
                    cover_letter_version or "v1", answers_version or "v1"
                ))
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

def set_checkpoint(url: str, checkpoint: str):
    """Atomically record application execution checkpoint in SQLite."""
    now = datetime.now().isoformat()
    with DB_LOCK:
        try:
            with _get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE applications
                    SET checkpoint = ?, updated_at = ?
                    WHERE url = ?
                """, (checkpoint, now, url))
                conn.commit()
            log_message(f"[CHECKPOINT] {url[:35]} -> {checkpoint}")
        except Exception as e:
            log_message(f"Error setting checkpoint for {url}: {e}")

def get_checkpoint(url: str) -> str:
    """Retrieve last known execution checkpoint for crash-safe resumption."""
    with DB_LOCK:
        try:
            with _get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT checkpoint FROM applications WHERE url = ?", (url,))
                row = cursor.fetchone()
                return (row[0] if row and row[0] else "discovered")
        except Exception as e:
            log_message(f"Error getting checkpoint for {url}: {e}")
            return "discovered"

def update_application_package(url: str, package_path: str, resume_v: str = "v1", cl_v: str = "v1", answers_v: str = "v1"):
    """Link prepared application package directory and versions to application record."""
    now = datetime.now().isoformat()
    with DB_LOCK:
        try:
            with _get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE applications
                    SET package_path = ?, resume_version = ?, cover_letter_version = ?, answers_version = ?, updated_at = ?
                    WHERE url = ?
                """, (package_path, resume_v, cl_v, answers_v, now, url))
                conn.commit()
            log_message(f"[PACKAGE LINKED] {url[:35]} -> {package_path}")
        except Exception as e:
            log_message(f"Error updating application package for {url}: {e}")

def record_outcome(url: str, outcome_stage: str, notes: str = "", response_time_hours: float = None):
    """
    Ingest application outcome event (applied, interview, offer, rejected, ghosted).
    Updates application outcome_stage and outcome_notes for calibration learning loop.
    """
    now = datetime.now().isoformat()
    with DB_LOCK:
        try:
            with _get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE applications
                    SET outcome_stage = ?, outcome_notes = ?, updated_at = ?
                    WHERE url = ?
                """, (outcome_stage, notes, now, url))
                conn.commit()
            log_message(f"[OUTCOME INGESTED] {url[:35]} -> {outcome_stage.upper()} ({notes})")
            recalculate_metrics_unlocked()
        except Exception as e:
            log_message(f"Error recording outcome for {url}: {e}")


def get_outcome_calibration_summary() -> dict:
    """
    Analyzes historical application outcomes to answer:
    'Which job characteristics actually produce interviews for this candidate?'
    Returns conversion metrics grouped by outcome stage, resume version, and score tiers.
    """
    with DB_LOCK:
        try:
            with _get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT 
                        IFNULL(outcome_stage, 'discovered') as stage,
                        COUNT(*) as total,
                        AVG(score) as avg_score,
                        AVG(rag_score) as avg_rag,
                        AVG(skill_overlap) as avg_overlap
                    FROM applications
                    GROUP BY outcome_stage
                """)
                stage_rows = cursor.fetchall()
                stage_stats = {}
                for r in stage_rows:
                    stage_stats[r[0]] = {
                        "count": r[1],
                        "avg_score": round(r[2] or 0.0, 1),
                        "avg_rag": round(r[3] or 0.0, 3),
                        "avg_overlap": round(r[4] or 0.0, 3),
                    }

                cursor.execute("""
                    SELECT 
                        IFNULL(resume_version, 'base') as r_ver,
                        COUNT(*) as total_apps,
                        SUM(CASE WHEN outcome_stage IN ('interview', 'offer') THEN 1 ELSE 0 END) as positive_outcomes
                    FROM applications
                    WHERE resume_version IS NOT NULL
                    GROUP BY resume_version
                """)
                ver_rows = cursor.fetchall()
                ver_stats = {}
                for r in ver_rows:
                    total = r[1]
                    pos = r[2]
                    rate = round((pos / total) * 100, 1) if total > 0 else 0.0
                    ver_stats[r[0]] = {"total": total, "interviews": pos, "interview_rate": rate}

                total_applied = stage_stats.get("applied", {}).get("count", 0) + stage_stats.get("interview", {}).get("count", 0) + stage_stats.get("offer", {}).get("count", 0) + stage_stats.get("rejected", {}).get("count", 0)
                interview_cnt = stage_stats.get("interview", {}).get("count", 0) + stage_stats.get("offer", {}).get("count", 0)
                overall_interview_rate = round((interview_cnt / total_applied) * 100, 1) if total_applied > 0 else 0.0

                return {
                    "stage_breakdown": stage_stats,
                    "resume_version_performance": ver_stats,
                    "total_applied": total_applied,
                    "interview_count": interview_cnt,
                    "interview_rate": overall_interview_rate,
                }
        except Exception as e:
            log_message(f"Error generating outcome calibration summary: {e}")
            return {"error": str(e)}

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
    """Load suggested jobs and evaluated opportunities for Suggestions View."""
    records = []
    with DB_LOCK:
        try:
            with _get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT url, company, title, reason, platform, score, strengths, gaps 
                    FROM applications 
                    ORDER BY score DESC, id DESC
                """)
                for row in cursor.fetchall():
                    strengths_list = []
                    if row[6]:
                        try:
                            strengths_list = json.loads(row[6]) if isinstance(row[6], str) else row[6]
                        except Exception:
                            strengths_list = []

                    gaps_list = []
                    if row[7]:
                        try:
                            gaps_list = json.loads(row[7]) if isinstance(row[7], str) else row[7]
                        except Exception:
                            gaps_list = []

                    records.append({
                        "url": row[0],
                        "company": row[1] or "Unknown Company",
                        "role": row[2] or "Unknown Role",
                        "detail": row[3] or "",
                        "platform": row[4] or "LinkedIn",
                        "score": row[5] or 0,
                        "strengths": strengths_list,
                        "gaps": gaps_list
                    })
        except Exception as e:
            log_message(f"Error fetching suggestions: {e}")
    return records

def get_pending_approvals():
    """Load pending approval opportunities from applications table for ApprovalsView."""
    records = []
    with DB_LOCK:
        try:
            with _get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT url, company, title, platform, score, reason, strengths, gaps,
                           rag_score, seniority, skill_overlap, eval_model, prompt_version,
                           jd_text, features_json, decision_reason, outcome_stage, content_hash, dedup_key
                    FROM applications 
                    WHERE status IN ('Approval Needed', 'Qualified') AND (approval_label IS NULL OR approval_label = '')
                    ORDER BY score DESC, id DESC
                """)
                for row in cursor.fetchall():
                    strengths_list = []
                    if row[6]:
                        try:
                            strengths_list = json.loads(row[6]) if isinstance(row[6], str) else row[6]
                        except Exception:
                            strengths_list = []

                    gaps_list = []
                    if row[7]:
                        try:
                            gaps_list = json.loads(row[7]) if isinstance(row[7], str) else row[7]
                        except Exception:
                            gaps_list = []

                    features_dict = {}
                    if row[14]:
                        try:
                            features_dict = json.loads(row[14]) if isinstance(row[14], str) else row[14]
                        except Exception:
                            features_dict = {}

                    records.append({
                        "url": row[0],
                        "company": row[1] or "Unknown Company",
                        "title": row[2] or "Unknown Role",
                        "platform": row[3] or "Indeed",
                        "score": row[4] or 0,
                        "reason": row[5] or "",
                        "strengths": strengths_list,
                        "gaps": gaps_list,
                        "rag_score": row[8],
                        "seniority": row[9],
                        "skill_overlap": row[10],
                        "eval_model": row[11],
                        "prompt_version": row[12],
                        "description": row[13] or "",
                        "features_json": row[14] or "{}",
                        "features": features_dict,
                        "decision_reason": row[15] or "",
                        "outcome_stage": row[16] or "discovered",
                        "content_hash": row[17] or "",
                        "dedup_key": row[18] or "",
                        "is_stretch": features_dict.get("is_stretch", False),
                        "penalties": features_dict.get("penalties", []),
                        "stretch_signals": features_dict.get("stretch_signals", []),
                    })
        except Exception as e:
            log_message(f"Error fetching pending approvals: {e}")
    return records

def export_applications_to_csv(export_path: str) -> bool:
    """Export SQLite applications table including AI evaluation results to CSV file."""
    with DB_LOCK:
        try:
            with _get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT url, title, company, platform, status, score, strengths, gaps, reason, applied_at 
                    FROM applications 
                    ORDER BY id ASC
                """)
                rows = cursor.fetchall()
            with open(export_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    "URL", "Title", "Company", "Platform", "Status",
                    "Match Score (%)", "Strengths", "Gaps", "Reason / Detail", "Applied Timestamp"
                ])
                for r in rows:
                    writer.writerow(list(r))
            return True
        except Exception as e:
            log_message(f"Error exporting applications to CSV: {e}")
            return False

def export_applications_to_json(export_path: str) -> bool:
    """Export SQLite applications table including full AI evaluation results to JSON file."""
    with DB_LOCK:
        try:
            with _get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT url, title, company, platform, status, score, strengths, gaps, reason, applied_at, updated_at
                    FROM applications 
                    ORDER BY id ASC
                """)
                rows = cursor.fetchall()
            records = []
            for r in rows:
                strengths_val = r[6]
                gaps_val = r[7]
                try:
                    strengths_parsed = json.loads(strengths_val) if strengths_val else []
                except Exception:
                    strengths_parsed = strengths_val or []
                try:
                    gaps_parsed = json.loads(gaps_val) if gaps_val else []
                except Exception:
                    gaps_parsed = gaps_val or []

                records.append({
                    "url": r[0] or "",
                    "title": r[1] or "",
                    "company": r[2] or "",
                    "platform": r[3] or "",
                    "status": r[4] or "",
                    "score": r[5] or 0,
                    "strengths": strengths_parsed,
                    "gaps": gaps_parsed,
                    "reason": r[8] or "",
                    "applied_at": r[9] or "",
                    "updated_at": r[10] or ""
                })
            with open(export_path, 'w', encoding='utf-8') as f:
                json.dump(records, f, indent=2)
            return True
        except Exception as e:
            log_message(f"Error exporting applications to JSON: {e}")
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
_init_db_schema()          # also calls _run_schema_migrations() internally
_migrate_csv_to_sqlite()
APPLIED_URLS_SET = load_applied_urls()
