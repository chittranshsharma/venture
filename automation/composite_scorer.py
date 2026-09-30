"""
automation/composite_scorer.py — Deterministic feature extraction, 3-tier constraint integration,
and calibrated composite fit scoring for VENTURE.
"""

from dataclasses import dataclass
import math
import re
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from core.config_manager import CONFIG, load_config
from core.resume_parser import extract_resume_text
from core.rag_scorer import get_top_k_bullets_and_score, get_model
from automation.constraint_checker import evaluate_constraints, ConstraintResult
from automation.skill_normalizer import compute_skill_metrics
from automation.llm_evaluator import TECH_VOCABULARY

POS_TITLE = re.compile(
    r"\b(full[- ]?stack|backend|back[- ]end|python|react|node|software (engineer|developer)|web developer)\b",
    re.I
)
QA_BLOCK = re.compile(
    r"\b(qa|sdet|quality assurance|test engineer|software tester|performance test(ing)?)\b",
    re.I
)
NEG_TITLE = re.compile(
    r"\b(test|qa|quality assurance|sdet|support|sales|recruit|manager|consultant|analyst|designer|devops|sap|salesforce|mainframe)\b",
    re.I
)

ENGLISH_STOPWORDS = {
    "the", "and", "is", "in", "to", "with", "for", "of", "on", "at", "as",
    "this", "that", "from", "or", "an", "by", "be", "are", "we", "you", "our"
}


def is_english_jd(text: str) -> bool:
    """Fast check whether job description is in English to avoid false low-RAG rejections."""
    tokens = re.findall(r"\b[a-z]{2,}\b", (text or "").lower())
    if len(tokens) < 25:
        return True
    stop_count = sum(1 for t in tokens if t in ENGLISH_STOPWORDS)
    return (stop_count / len(tokens)) >= 0.07


@dataclass
class EvaluationSignals:
    title: str
    company: str
    jd_text: str
    deterministic_score: int
    raw_probability: float
    rag_score: float
    top_bullets: List[str]
    title_clean: float
    title_pos: float
    title_neg: float
    title_sim_max: float
    jd_coverage: float
    cand_coverage: float
    matched_skills: List[str]
    missing_skills: List[str]
    hard_block: bool
    hard_reason: str
    penalties: List[Dict[str, Any]]
    stretch_signals: List[Dict[str, Any]]
    total_penalty: float
    total_stretch_boost: float
    net_adjustment: float
    is_stretch: bool
    route: str  # 'reject' | 'explore' | 'queue' | 'constraint'
    propensity: float

    def to_features_dict(self) -> Dict[str, Any]:
        return {
            "deterministic_score": self.deterministic_score,
            "raw_probability": round(self.raw_probability, 4),
            "rag_score": round(self.rag_score, 4),
            "title_clean": self.title_clean,
            "title_pos": self.title_pos,
            "title_neg": self.title_neg,
            "title_sim_max": round(self.title_sim_max, 4),
            "jd_coverage": round(self.jd_coverage, 4),
            "cand_coverage": round(self.cand_coverage, 4),
            "matched_skills": self.matched_skills,
            "missing_skills": self.missing_skills,
            "hard_block": self.hard_block,
            "hard_reason": self.hard_reason,
            "penalties": self.penalties,
            "stretch_signals": self.stretch_signals,
            "total_penalty": round(self.total_penalty, 2),
            "total_stretch_boost": round(self.total_stretch_boost, 2),
            "net_adjustment": round(self.net_adjustment, 2),
            "is_stretch": self.is_stretch,
            "route": self.route,
        }

    def generate_decision_reason(self, llm_reason: Optional[str] = None) -> str:
        if self.hard_block:
            return f"Hard Block: {self.hard_reason}"
        parts = [f"Score: {self.deterministic_score}%"]
        if self.is_stretch:
            boost_reasons = ", ".join(s.get("evidence", "") for s in self.stretch_signals)
            parts.append(f"STRETCH: +{self.total_stretch_boost:.1f} pts ({boost_reasons})")
        if self.total_penalty > 0:
            pen_reasons = ", ".join(p.get("evidence", "") for p in self.penalties)
            parts.append(f"PENALTY: -{self.total_penalty:.1f} pts ({pen_reasons})")
        parts.append(f"RAG: {self.rag_score:.2f}")
        parts.append(f"Cov: {self.jd_coverage * 100:.0f}%")
        if self.matched_skills:
            parts.append(f"Matched: {', '.join(self.matched_skills[:4])}")
        if self.missing_skills:
            parts.append(f"Missing: {', '.join(self.missing_skills[:4])}")
        if llm_reason:
            parts.append(f"LLM Evidence: {llm_reason}")
        return " | ".join(parts)


def evaluate_opportunity(
    title: str,
    company: str,
    jd_text: str,
    cfg: Optional[Dict[str, Any]] = None,
    base_resume: Optional[str] = None,
    embed_model: Any = None,
) -> EvaluationSignals:
    """
    Computes all deterministic signals and 3-tier constraints for a job opportunity.
    Returns EvaluationSignals with complete feature telemetry and calibrated fit score.
    """
    if cfg is None:
        cfg = CONFIG or load_config()

    # 0. Narrow Title Hard Block (QA/SDET/Test Engineer only, zero false-rejects)
    if QA_BLOCK.search(title or ""):
        return EvaluationSignals(
            title=title,
            company=company,
            jd_text=jd_text,
            deterministic_score=0,
            raw_probability=0.0,
            rag_score=0.0,
            top_bullets=[],
            title_clean=-1.0,
            title_pos=0.0,
            title_neg=1.0,
            title_sim_max=0.0,
            jd_coverage=0.0,
            cand_coverage=0.0,
            matched_skills=[],
            missing_skills=[],
            hard_block=True,
            hard_reason="qa_test_title",
            penalties=[],
            stretch_signals=[],
            total_penalty=0.0,
            total_stretch_boost=0.0,
            net_adjustment=0.0,
            is_stretch=False,
            route="blocked_title",
            propensity=0.0,
        )

    # 1. Tier 1 Invariants: Hard Blocks
    c_res: ConstraintResult = evaluate_constraints(title, jd_text, cfg)
    if c_res.hard_block:
        penalties_list = [{"type": p.type, "value": p.value, "evidence": p.evidence} for p in c_res.penalties]
        stretch_list = [{"type": s.type, "value": s.value, "evidence": s.evidence} for s in c_res.stretch_signals]
        return EvaluationSignals(
            title=title,
            company=company,
            jd_text=jd_text,
            deterministic_score=0,
            raw_probability=0.0,
            rag_score=0.0,
            top_bullets=[],
            title_clean=0.0,
            title_pos=0.0,
            title_neg=1.0,
            title_sim_max=0.0,
            jd_coverage=0.0,
            cand_coverage=0.0,
            matched_skills=[],
            missing_skills=[],
            hard_block=True,
            hard_reason=c_res.hard_reason,
            penalties=penalties_list,
            stretch_signals=stretch_list,
            total_penalty=c_res.total_penalty,
            total_stretch_boost=c_res.total_stretch_boost,
            net_adjustment=c_res.net_adjustment,
            is_stretch=False,
            route="constraint",
            propensity=0.0,
        )

    # 2. Extract Candidate Profile & Base Resume
    cand_obj = cfg.get("candidate", {}) if isinstance(cfg.get("candidate"), dict) else {}
    set_obj = cfg.get("settings", {}) if isinstance(cfg.get("settings"), dict) else {}
    cand_skills = cand_obj.get("skills", ["Python", "C++", "JavaScript", "React", "Node.js", "Git"])
    target_queries = set_obj.get("queries", ["Full Stack Developer", "Software Engineer", "Python Developer"])
    min_score = set_obj.get("min_score", 70)

    if base_resume is None:
        base_resume = extract_resume_text() or ""

    if embed_model is None:
        embed_model = get_model()

    # 3. Compute RAG Cosine Relevance
    if base_resume and len(base_resume) > 200:
        top_bullets, rag_score_val = get_top_k_bullets_and_score(base_resume, jd_text, k=5)
    else:
        top_bullets, rag_score_val = [], 0.30

    # 4. Compute Title Clean and Semantic Similarity
    t_clean = (title or "").strip()
    pos = 1.0 if POS_TITLE.search(t_clean) else 0.0
    neg = 1.0 if NEG_TITLE.search(t_clean) else 0.0
    title_clean_val = pos - neg

    if embed_model is not None and target_queries:
        try:
            t_vec = embed_model.encode([t_clean], normalize_embeddings=True)[0]
            q_vecs = embed_model.encode(target_queries, normalize_embeddings=True)
            title_sim_max_val = float(np.max(q_vecs @ t_vec))
        except Exception:
            title_sim_max_val = 0.5
    else:
        title_sim_max_val = 0.5

    # 5. Compute Vocabulary Skill Coverage
    skill_metrics = compute_skill_metrics(cand_skills, jd_text, TECH_VOCABULARY)
    jd_coverage_val = skill_metrics["jd_coverage"]
    cand_coverage_val = skill_metrics["cand_coverage"]
    matched_skills = skill_metrics["matched_skills"]
    missing_skills = skill_metrics["missing_skills"]

    # 6. Calibrated Deterministic Scoring (Logistic Link)
    z = (0.04
         + 0.23 * ((rag_score_val - 0.301) / 0.041)
         + 0.05 * ((title_sim_max_val - 0.626) / 0.133)
         + 0.35 * ((pos - 0.857) / 0.350)
         - 0.71 * ((neg - 0.089) / 0.285)
         + 0.05 * ((jd_coverage_val - 0.135) / 0.156))

    raw_prob = 1.0 / (1.0 + math.exp(-z))
    base_score = raw_prob * 100.0

    # Tier 2 & Tier 3 Adjustments (Soft Penalties & Stretch Boosts)
    total_penalty = c_res.total_penalty
    total_stretch_boost = c_res.total_stretch_boost
    net_adj = c_res.net_adjustment
    is_stretch = len(c_res.stretch_signals) > 0

    final_score = int(round(max(0.0, min(100.0, base_score + net_adj))))

    is_non_eng = not is_english_jd(jd_text)

    # 7. Tri-State Routing (Low, Uncertain/Stretch, High Fit)
    if final_score >= min_score:
        route = "queue"
        propensity = 1.0
    elif final_score >= 48 or (is_stretch and final_score >= 38) or is_non_eng:
        route = "explore"
        propensity = 0.5
    else:
        route = "reject"
        propensity = 0.0

    penalties_list = [{"type": p.type, "value": p.value, "evidence": p.evidence} for p in c_res.penalties]
    stretch_list = [{"type": s.type, "value": s.value, "evidence": s.evidence} for s in c_res.stretch_signals]

    return EvaluationSignals(
        title=title,
        company=company,
        jd_text=jd_text,
        deterministic_score=final_score,
        raw_probability=raw_prob,
        rag_score=rag_score_val,
        top_bullets=top_bullets,
        title_clean=title_clean_val,
        title_pos=pos,
        title_neg=neg,
        title_sim_max=title_sim_max_val,
        jd_coverage=jd_coverage_val,
        cand_coverage=cand_coverage_val,
        matched_skills=matched_skills,
        missing_skills=missing_skills,
        hard_block=False,
        hard_reason="",
        penalties=penalties_list,
        stretch_signals=stretch_list,
        total_penalty=total_penalty,
        total_stretch_boost=total_stretch_boost,
        net_adjustment=net_adj,
        is_stretch=is_stretch,
        route=route,
        propensity=propensity,
    )


def should_invoke_llm(signals: EvaluationSignals, min_score: int = 70) -> bool:
    """
    Decides whether local LLM should be invoked for targeted ambiguity resolution.
    - Zero LLM on hard blocks.
    - Zero LLM on obvious low-fit rejects (score < 50).
    - Invoked only on narrow borderline ambiguity [min_score - 8, min_score) or high-value stretch (score >= 60).
    Ensures LLM invocation stays below 25-30% of pipeline volume.
    """
    if signals.hard_block:
        return False
    if signals.route == "reject":
        return False
    if signals.is_stretch and signals.deterministic_score >= 60:
        return True
    lower_bound = max(58, min_score - 8)
    if lower_bound <= signals.deterministic_score < min_score:
        return True
    return False
