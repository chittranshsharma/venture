import hashlib
import re
from typing import Any, Dict
from core.db_manager import compute_dedup_key

def split_of(row: Dict[str, Any]) -> str:
    """
    Deterministic 70/30 split derived from MD5(dedup_key).
    Prevents cross-platform duplicates of the same job from straddling tune/holdout.
    """
    k = row.get("dedup_key")
    if not k:
        k = compute_dedup_key(row.get("company", ""), row.get("title", ""), row.get("location", ""))
    if not k:
        k = row.get("url", "")
    return "tune" if int(hashlib.md5(k.encode("utf-8")).hexdigest(), 16) % 10 < 7 else "holdout"


def truncate_jd(text: str, n: int = 2500) -> str:
    """Shared truncation helper used across labeler, evaluator, and harness."""
    if not text:
        return ""
    return text[:n]


def get_dedup_key(row: Dict[str, Any]) -> str:
    """Return explicit or computed dedup_key for a row."""
    k = row.get("dedup_key")
    if not k:
        k = compute_dedup_key(row.get("company", ""), row.get("title", ""), row.get("location", ""))
    return k or ""


def profile_hash(cfg: Dict[str, Any], resume_text: str) -> str:
    """Computes a deterministic hash of candidate skills, QA profile, and resume text."""
    import json
    cand = cfg.get("candidate", {})
    blob = json.dumps({
        "skills": sorted(cand.get("skills", [])),
        "qa": cand.get("qa_vault", {}),
        "resume": resume_text or "",
    }, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:8]

