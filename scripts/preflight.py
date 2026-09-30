import os
import shutil
import sqlite3
import sys
from datetime import datetime

# Ensure root workspace on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config_manager import load_config
from core.resume_parser import extract_resume_text

cfg = load_config()
s = cfg.get("settings", {})
ok = True

def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, detail)

check("dry_run_mode false (real submit)", s.get("dry_run_mode") is False)
check("safe_mode true", s.get("safe_mode", True) is True)
check("daily_apply_cap == 1", s.get("daily_apply_cap") == 1, str(s.get("daily_apply_cap")))
check("confirm_before_submit true", s.get("confirm_before_submit", True) is True)
try:
    t = extract_resume_text()
    check("resume >= 500 chars", len(t) >= 500, str(len(t)))
except Exception as e:
    check("resume readable", False, str(e))
check("resume is base, not tailored", "tailored_resumes" not in cfg.get("candidate", {}).get("resume_path", ""))
qa = cfg.get("candidate", {}).get("qa_vault", {})
for k in ("experience_years", "notice_period", "work_authorization", "require_sponsorship"):
    check(f"qa_vault.{k} set", bool(qa.get(k)))
check("email/phone set", bool(cfg.get("candidate", {}).get("email")) and bool(cfg.get("candidate", {}).get("phone")))

if ok:
    bak = f"venture_backup_{datetime.now():%Y%m%d_%H%M%S}.db"
    if os.path.exists("venture.db"):
        shutil.copy("venture.db", bak)
        print("DB backup:", bak)

sys.exit(0 if ok else 1)
