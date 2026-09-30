import os
import sys
import sqlite3
import pytest

# Ensure workspace root is in python path
WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

import core.db_manager as db_mod
from core.db_manager import (
    _run_schema_migrations_locked,
    compute_dedup_key,
    compute_content_hash,
    normalize_jd,
    normalize_company,
    normalize_location,
    route,
    log_approval_decision,
    log_evaluation,
)
from core.state_machine import can_transition
from automation.llm_evaluator import (
    extract_seniority,
    compute_skill_overlap,
    compute_skill_overlaps,
    prompt_version,
)


@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    """
    Hermetic test isolation: Guarantees tests NEVER touch the real venture.db.
    Patches SQLITE_DB_PATH for each test function to a pristine temporary database.
    """
    test_db = str(tmp_path / "test_venture.db")
    orig_path = db_mod.SQLITE_DB_PATH
    db_mod.SQLITE_DB_PATH = test_db
    yield test_db
    db_mod.SQLITE_DB_PATH = orig_path


def _init_base_schema(conn):
    """Simulate legacy database prior to versioned migrations (user_version = 0)."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE applications (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            url         TEXT NOT NULL UNIQUE,
            title       TEXT,
            company     TEXT,
            platform    TEXT,
            status      TEXT DEFAULT 'Applied',
            score       INTEGER DEFAULT 0,
            reason      TEXT,
            strengths   TEXT,
            gaps        TEXT,
            applied_at  TEXT,
            updated_at  TEXT
        )
    """)
    conn.commit()


def test_fresh_database_migration_full(isolated_db):
    """A fresh DB should migrate sequentially to user_version = 7 with all tables, columns, and indexes."""
    conn = sqlite3.connect(isolated_db)
    try:
        _init_base_schema(conn)
        _run_schema_migrations_locked(conn)

        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == 7, "user_version must be 7 after full migration"

        # Check applications columns
        app_cols = [r[1] for r in conn.execute("PRAGMA table_info(applications)").fetchall()]
        assert "rag_score" in app_cols
        assert "seniority" in app_cols
        assert "skill_overlap" in app_cols
        assert "dedup_key" in app_cols
        assert "content_hash" in app_cols
        assert "approval_label" in app_cols
        assert "prompt_version" in app_cols
        assert "eval_model" in app_cols
        assert "features_json" in app_cols
        assert "decision_reason" in app_cols
        assert "checkpoint" in app_cols
        assert "package_path" in app_cols

        # Check tables exist
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "processed_emails" in tables
        assert "decisions" in tables
        assert "evaluations" in tables

        # Check evaluations columns including embedding_model
        eval_cols = [r[1] for r in conn.execute("PRAGMA table_info(evaluations)").fetchall()]
        assert "embedding_model" in eval_cols
        assert "route" in eval_cols
        assert "propensity" in eval_cols

        # Check unique index on evaluations
        indexes = [r[1] for r in conn.execute("PRAGMA index_list(evaluations)").fetchall()]
        assert "ux_eval_dedupe" in indexes
    finally:
        conn.close()


def test_log_evaluation_idempotent_on_duplicate(isolated_db):
    """Evaluations table must deduplicate repeated radar/scraper runs on (url, content_hash, model, prompt)."""
    conn = sqlite3.connect(isolated_db)
    _init_base_schema(conn)
    _run_schema_migrations_locked(conn)
    conn.commit()
    conn.close()

    url = "https://example.com/job/radar-poll-1"
    desc = "Python and FastAPI engineer for cloud backend systems."

    # Call log_evaluation 3 consecutive times with same job
    for _ in range(3):
        log_evaluation(
            url=url,
            title="Python Dev",
            company="Radar Corp",
            jd_text=desc,
            llm_score=75,
            rag_score=0.8,
            seniority="mid",
            skill_overlap=0.9,
            route="queue",
            propensity=1.0,
            eval_model="qwen2.5:7b",
            prompt_version="abc12345",
        )

    conn = sqlite3.connect(isolated_db)
    rows = conn.execute("SELECT COUNT(*) FROM evaluations WHERE url = ?", (url,)).fetchone()[0]
    conn.close()
    assert rows == 1, "Duplicate evaluation polling must be ignored by ux_eval_dedupe"


def test_hash_normalization_resilience_and_yoe_sensitivity():
    """
    1. Dynamic scrape counters and timestamps must NOT change content_hash.
    2. Changing YOE requirements ('3+ years' -> '5+ years') MUST produce a different hash.
    """
    jd_base = "Senior Python engineer with experience in FastAPI and PostgreSQL. 3+ years experience required."
    jd_day1 = f"{jd_base}\nPosted 2 days ago • 145 applicants • https://indeed.com/track/123"
    jd_day2 = f"{jd_base}\nReposted 5 days ago • 389 applicants • https://indeed.com/track/999"

    h1 = compute_content_hash(jd_day1)
    h2 = compute_content_hash(jd_day2)
    assert h1 == h2, "Scrape counter noise must not invalidate content_hash"

    # Changing YOE requirement from 3+ years to 5+ years MUST change hash
    jd_modified_yoe = "Senior Python engineer with experience in FastAPI and PostgreSQL. 5+ years experience required."
    h_yoe = compute_content_hash(jd_modified_yoe)
    assert h1 != h_yoe, "Changing YOE requirement must produce a distinct content_hash for re-evaluation"

    # Dedup key normalization
    dk1 = compute_dedup_key("Stripe, Inc.", "Software Engineer", "Remote, US")
    dk2 = compute_dedup_key("Stripe LLC", "Software Engineer", "US (Remote)")
    assert dk1 == dk2, "Company suffixes and location variants must yield identical dedup_key"


@pytest.mark.parametrize("title,text,expected", [
    ("Junior Python Developer", "", "entry"),
    ("Software Engineer Intern", "", "entry"),
    ("Graduate Software Trainee", "", "entry"),
    ("Associate Backend Engineer", "", "entry"),
    ("Jr. Frontend Engineer", "", "entry"),
    ("Software Engineer", "Requirements: 0-1 years of programming experience.", "entry"),
    ("Senior Software Engineer", "", "senior"),
    ("Sr. Full Stack Engineer", "", "senior"),
    ("Lead Systems Architect", "", "senior"),
    ("Software Engineer", "Looking for 6+ years of production experience.", "senior"),
    ("Staff Infrastructure Engineer", "", "staff+"),
    ("Principal Data Scientist", "", "staff+"),
    ("Director of Engineering", "", "staff+"),
    ("VP of Product & Engineering", "", "staff+"),
    ("Software Developer", "You'll collaborate with senior engineers and staff architects. 3 years experience required.", "mid"),
])
def test_extract_seniority_fifteen_cases(title, text, expected):
    """extract_seniority must evaluate title first and prevent false positives from body text."""
    actual = extract_seniority(title, text)
    assert actual == expected, f"Failed for title='{title}', text='{text}'. Expected '{expected}', got '{actual}'"


def test_compute_skill_overlap_word_boundaries():
    """Skill overlap must use word boundaries to avoid false substring collisions."""
    # 'go' must not match 'good'
    overlap_good = compute_skill_overlap(["go"], "Must have good communication skills and teamwork.")
    assert overlap_good == 0.0, "'go' must not match inside 'good'"

    # 'go' matches 'Go'
    overlap_go = compute_skill_overlap(["go"], "Looking for a Go backend engineer.")
    assert overlap_go == 1.0, "'go' must match 'Go'"

    # 'java' must not match 'javascript'
    overlap_js = compute_skill_overlap(["java"], "Looking for Javascript and React developers.")
    assert overlap_js == 0.0, "'java' must not match inside 'Javascript'"

    # 'java' matches 'Java'
    overlap_java = compute_skill_overlap(["java"], "Looking for Java and Spring developers.")
    assert overlap_java == 1.0, "'java' must match 'Java'"

    # 'c++' matches 'C++'
    overlap_cpp = compute_skill_overlap(["c++"], "Low-latency systems in C++20.")
    assert overlap_cpp == 1.0, "'c++' must match 'C++'"

    # 'c' must not match 'c++'
    overlap_c_in_cpp = compute_skill_overlap(["c"], "Low-latency systems in C++20.")
    assert overlap_c_in_cpp == 0.0, "'c' must not falsely match 'c++'"


def test_propensity_positive_guard(isolated_db):
    """Decisions table must enforce propensity > 0 to prevent IPW division by zero."""
    conn = sqlite3.connect(isolated_db)
    _init_base_schema(conn)
    _run_schema_migrations_locked(conn)
    conn.commit()
    conn.close()

    # log_approval_decision clamps non-positive propensity to 0.001
    log_approval_decision(
        url="https://example.com/job/prop-test",
        label="reject",
        reject_reason="not_fit",
        score=25,
        propensity=0.0  # Pass 0.0
    )

    conn = sqlite3.connect(isolated_db)
    prop = conn.execute("SELECT propensity FROM decisions WHERE url = 'https://example.com/job/prop-test'").fetchone()[0]
    conn.close()
    assert prop > 0.0, "Propensity in decisions must be strictly positive (> 0) for IPW"


def test_post_submit_transitions():
    """FSM must allow post-submit transitions without raising ValueError."""
    transitions_to_test = [
        ("SUBMITTED", "INTERVIEW"),
        ("SUBMITTED", "OFFER"),
        ("SUBMITTED", "REJECTED_POST"),
        ("INTERVIEW", "OFFER"),
        ("INTERVIEW", "REJECTED_POST"),
        ("Interview", "Offer"),
        ("Interview", "Rejected"),
    ]
    for src, dst in transitions_to_test:
        assert can_transition(src, dst), f"Transition '{src}' -> '{dst}' must be permitted"


def test_prompt_version_derivation():
    """prompt_version must deterministically produce an 8-char SHA256 hex string."""
    t1 = "Template v1 with {placeholder}"
    t2 = "Template v2 with {placeholder}"
    v1 = prompt_version(t1)
    v2 = prompt_version(t2)
    assert len(v1) == 8
    assert len(v2) == 8
    assert v1 != v2
    assert v1 == prompt_version(t1), "prompt_version must be deterministic for identical template"
 
 
def test_migration_v7_location_free_dedup_key(isolated_db):
    """
    On a database with legacy location-keyed rows (same job in 2 cities had different keys),
    running migration v7 updates both rows to share the exact same canonical dedup_key.
    """
    conn = sqlite3.connect(isolated_db)
    _init_base_schema(conn)
    _run_schema_migrations_locked(conn)  # Migrates to latest v7
    
    # Simulate legacy state: artificially set location-based keys and revert version to 6
    conn.execute("PRAGMA user_version = 6")
    legacy_key_ny = "legacy_key_ny123"
    legacy_key_sf = "legacy_key_sf456"
    
    conn.execute("""
        INSERT INTO applications (url, company, title, dedup_key, status)
        VALUES ('https://example.com/job/ny', 'NovaTech Solutions', 'Full Stack Engineer', ?, 'Applied')
    """, (legacy_key_ny,))
    conn.execute("""
        INSERT INTO applications (url, company, title, dedup_key, status)
        VALUES ('https://example.com/job/sf', 'NovaTech Solutions', 'Full Stack Engineer', ?, 'Applied')
    """, (legacy_key_sf,))
    
    conn.execute("""
        INSERT INTO evaluations (url, company, title, dedup_key, route)
        VALUES ('https://example.com/eval/ny', 'NovaTech Solutions', 'Full Stack Engineer', ?, 'queue')
    """, (legacy_key_ny,))
    conn.execute("""
        INSERT INTO evaluations (url, company, title, dedup_key, route)
        VALUES ('https://example.com/eval/sf', 'NovaTech Solutions', 'Full Stack Engineer', ?, 'queue')
    """, (legacy_key_sf,))
    conn.commit()
    
    # Run migration v7
    _run_schema_migrations_locked(conn)
    
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    assert v == 7
    
    app_keys = [r[0] for r in conn.execute("SELECT dedup_key FROM applications WHERE company='NovaTech Solutions'").fetchall()]
    assert len(app_keys) == 2
    assert app_keys[0] == app_keys[1], "Both city applications must now share the exact same canonical dedup_key"
    assert app_keys[0] == compute_dedup_key("NovaTech Solutions", "Full Stack Engineer")
    
    eval_keys = [r[0] for r in conn.execute("SELECT dedup_key FROM evaluations WHERE company='NovaTech Solutions'").fetchall()]
    assert len(eval_keys) == 2
    assert eval_keys[0] == eval_keys[1], "Both city evaluations must now share the exact same canonical dedup_key"
    assert eval_keys[0] == compute_dedup_key("NovaTech Solutions", "Full Stack Engineer")
    conn.close()


@pytest.mark.parametrize("start_version", [1, 2, 3, 4, 5, 6])
def test_upgrade_from_intermediate_version_to_v7(isolated_db, start_version):
    """Migrating from any intermediate user_version 1..6 must successfully reach v7."""
    conn = sqlite3.connect(isolated_db)
    _init_base_schema(conn)
    _run_schema_migrations_locked(conn)  # Migrates to latest v7
    
    # Artificially set user_version to start_version
    conn.execute(f"PRAGMA user_version = {start_version}")
    conn.commit()

    # Re-run migration
    _run_schema_migrations_locked(conn)
    final_v = conn.execute("PRAGMA user_version").fetchone()[0]
    assert final_v == 7, f"Migration from version {start_version} must reach user_version 7"
    conn.close()


def test_migration_failure_preserves_user_version(isolated_db):
    """If an unrecoverable SQL error occurs during a migration block, user_version remains unchanged."""
    conn = sqlite3.connect(isolated_db)
    _init_base_schema(conn)
    _run_schema_migrations_locked(conn)
    
    # Set to version 6
    conn.execute("PRAGMA user_version = 6")
    conn.commit()

    # Drop evaluations table so v7 migration fails when selecting from it
    conn.execute("DROP TABLE evaluations")
    conn.commit()

    # Run migrations; error will be logged and user_version must remain 6
    _run_schema_migrations_locked(conn)
    v_after = conn.execute("PRAGMA user_version").fetchone()[0]
    assert v_after == 6, f"Failed migration must not advance user_version (remains {v_after})"
    conn.close()
