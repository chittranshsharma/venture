"""
core/rag_scorer.py — Local RAG Scoring Engine (P3.1)
Embeds candidate resume bullets into 384-dimensional vector space, embeds the target JD,
and returns the top-k most semantically relevant bullets via cosine similarity ranking.

Upgrades applied:
- Fix 1.2: JD truncation raised from 1000 → 3000 chars (skills often appear mid-JD)
- Upgrade 2.4: Section-aware bullet weighting (Experience/Projects 2x over Education/Summary)
- Feature 4.3: Session-level resume embedding cache (avoids re-encoding same resume per job)
"""

import re
import hashlib
import logging
import numpy as np

logger = logging.getLogger(__name__)

_model = None
# Feature 4.3 — session-level cache: {resume_hash: (lines, line_vecs)}
_resume_cache: dict = {}

# Section headers that indicate high-value experience content
_EXPERIENCE_HEADERS = re.compile(
    r'^(experience|work experience|employment|projects|project experience|'
    r'professional experience|internship|key achievements|achievements|responsibilities)',
    re.IGNORECASE
)
_EDUCATION_HEADERS = re.compile(
    r'^(education|academics|certifications?|courses?|awards?|languages?|interests?|hobbies|references)',
    re.IGNORECASE
)


def get_model():
    """Lazy-load the SentenceTransformer embedding model."""
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        except Exception as e:
            logger.warning(f"Could not load SentenceTransformer: {e}")
            return None
    return _model


def _section_weight(line: str, current_section: str) -> float:
    """Upgrade 2.4: Return embedding weight multiplier based on resume section context."""
    if current_section in ("experience", "projects"):
        return 2.0
    if current_section in ("education", "other"):
        return 0.5
    return 1.0


def _parse_lines_with_weights(resume_text: str):
    """Extract (line, weight) pairs from resume text using section-aware parsing."""
    raw_lines = resume_text.split('\n')
    result = []
    current_section = "summary"

    for raw in raw_lines:
        stripped = raw.strip().lstrip("•-* \t")
        if not stripped:
            continue
        # Detect section headers
        if _EXPERIENCE_HEADERS.match(stripped) and len(stripped) < 60:
            current_section = "experience"
            continue
        if _EDUCATION_HEADERS.match(stripped) and len(stripped) < 60:
            current_section = "education"
            continue
        # Only keep substantive lines
        if len(stripped) > 20:
            result.append((stripped, _section_weight(stripped, current_section)))

    if not result:
        # Fallback: any line > 10 chars with equal weight
        result = [(l.strip(), 1.0) for l in raw_lines if len(l.strip()) > 10]
    return result


def get_top_k_bullets_and_score(resume_text: str, job_description: str, k: int = 5) -> tuple[list[str], float]:
    """Return the k resume lines most semantically similar to the target JD along with the RAG cosine score."""
    if not resume_text or not resume_text.strip():
        return (["Candidate experienced in software development, architecture, and engineering."], 0.5)

    model = get_model()
    if model is None:
        lines = [l.strip() for l in resume_text.split('\n') if len(l.strip()) > 20]
        return (lines[:k] if lines else [resume_text[:500]], 0.5)

    # Feature 4.3 — cache embeddings per unique resume content
    resume_hash = hashlib.md5(resume_text.encode('utf-8', errors='ignore')).hexdigest()
    if resume_hash in _resume_cache:
        lines, line_vecs, weights = _resume_cache[resume_hash]
    else:
        parsed = _parse_lines_with_weights(resume_text)
        if not parsed:
            return ([resume_text[:500]], 0.5)
        lines = [p[0] for p in parsed]
        weights = np.array([p[1] for p in parsed], dtype=np.float32)
        try:
            line_vecs = model.encode(lines)
            _resume_cache[resume_hash] = (lines, line_vecs, weights)
        except Exception as e:
            logger.warning(f"Resume embedding error: {e}")
            return (lines[:k], 0.5)

    try:
        # Fix 1.2 — use up to 3000 chars of the JD (skills usually appear mid-document)
        target_jd = (job_description[:3000] if job_description and job_description.strip()
                     else "Software Engineer")
        jd_vec = model.encode([target_jd])[0]

        # Cosine similarity via normalized dot product
        norm_lines = np.linalg.norm(line_vecs, axis=1, keepdims=True)
        norm_lines[norm_lines == 0] = 1e-10
        normed_vecs = line_vecs / norm_lines

        norm_jd = np.linalg.norm(jd_vec)
        if norm_jd == 0:
            norm_jd = 1e-10
        jd_vec = jd_vec / norm_jd

        raw_sim = normed_vecs @ jd_vec
        # Upgrade 2.4 — weight scores by section relevance before ranking
        scores = raw_sim * weights

        top_k = min(k, len(lines))
        top_idx = np.argsort(scores)[-top_k:][::-1]
        bullets = [lines[i] for i in top_idx]
        avg_top_sim = float(np.clip(np.mean(raw_sim[top_idx]), 0.0, 1.0)) if len(top_idx) > 0 else 0.5
        return (bullets, round(avg_top_sim, 4))
    except Exception as e:
        logger.warning(f"RAG ranking fallback: {e}")
        return (lines[:k], 0.5)


def get_top_k_bullets(resume_text: str, job_description: str, k: int = 5) -> list[str]:
    """Return the k resume lines most semantically similar to the target JD."""
    bullets, _ = get_top_k_bullets_and_score(resume_text, job_description, k=k)
    return bullets

