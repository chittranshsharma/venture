"""
core/rag_scorer.py — Local RAG Scoring Engine (P3.1)
Embeds candidate resume bullets into 384-dimensional vector space, embeds the target JD,
and returns the top-k most semantically relevant bullets via cosine similarity ranking.
"""

import logging
import numpy as np

logger = logging.getLogger(__name__)

_model = None

def get_model():
    """Lazy-load the SentenceTransformer embedding model."""
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            # First run: ~80MB download, then cached in ~/.cache/huggingface
            _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        except Exception as e:
            logger.warning(f"Could not load SentenceTransformer: {e}")
            return None
    return _model

def get_top_k_bullets(resume_text: str, job_description: str, k: int = 5) -> list[str]:
    """Return the k resume lines most semantically similar to the target JD."""
    if not resume_text or not resume_text.strip():
        return ["Candidate experienced in software development, architecture, and engineering."]
    
    # Extract substantive bullet lines (skip short headers, dates, page numbers)
    raw_lines = [l.strip().lstrip("•-* \t") for l in resume_text.split('\n')]
    lines = [l for l in raw_lines if len(l) > 20]
    
    if not lines:
        lines = [l for l in raw_lines if len(l) > 10]
    if not lines:
        return [resume_text[:500]]
    
    model = get_model()
    if model is None:
        return lines[:k]
        
    try:
        line_vecs = model.encode(lines)
        target_jd = job_description[:1000] if (job_description and job_description.strip()) else "Software Engineer"
        jd_vec = model.encode([target_jd])[0]
        
        # Cosine similarity via normalized dot product
        norm_lines = np.linalg.norm(line_vecs, axis=1, keepdims=True)
        norm_lines[norm_lines == 0] = 1e-10
        line_vecs = line_vecs / norm_lines
        
        norm_jd = np.linalg.norm(jd_vec)
        if norm_jd == 0:
            norm_jd = 1e-10
        jd_vec = jd_vec / norm_jd
        
        scores = line_vecs @ jd_vec
        
        top_k = min(k, len(lines))
        top_idx = np.argsort(scores)[-top_k:][::-1]
        return [lines[i] for i in top_idx]
    except Exception as e:
        logger.warning(f"RAG ranking fallback: {e}")
        return lines[:k]
