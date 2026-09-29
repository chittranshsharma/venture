"""
eval/decision_metrics.py — Decision-Centric Evaluation for VENTURE.
Evaluates ranking and decision metrics: Precision@K, False Reject %, and Top-K utility,
aligning with the career command center's true objective (quality of top-recommended opportunities).
"""

import os
import sys
import json
import re
from pathlib import Path
from typing import Any, Dict, List
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

# Ensure workspace root is in sys.path
WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from core.config_manager import load_config
from core.resume_parser import extract_resume_text
from core.rag_scorer import get_top_k_bullets_and_score, get_model
from automation.llm_evaluator import TECH_VOCABULARY
from automation.skill_normalizer import compute_skill_metrics
from eval.common import truncate_jd

NEG_TITLE = re.compile(
    r"\b(test|qa|quality assurance|sdet|support|sales|recruit|manager|"
    r"consultant|analyst|designer|devops|sap|salesforce|mainframe)\b",
    re.I
)
POS_TITLE = re.compile(
    r"\b(full[- ]?stack|backend|back[- ]end|python|react|node|software (engineer|developer)|web developer)\b",
    re.I
)


def compute_precision_at_k(y_true: np.ndarray, y_score: np.ndarray, k: int) -> float:
    """Fraction of the top-k ranked opportunities that are true Apply targets."""
    top_k_idx = np.argsort(y_score)[-k:][::-1]
    return float(np.mean(y_true[top_k_idx]))


def compute_false_apply_at_k(y_true: np.ndarray, y_score: np.ndarray, k: int) -> float:
    """Fraction of the top-k ranked opportunities that were skips (bad recommendations)."""
    return 1.0 - compute_precision_at_k(y_true, y_score, k)


def run_decision_eval():
    cfg = load_config()
    queries = cfg.get("settings", {}).get("queries", ["Full Stack Developer", "Software Engineer", "Python Developer"])
    skills = cfg.get("candidate", {}).get("skills", ["Python", "C++", "JavaScript", "React", "Node.js", "Git"])
    resume_text = extract_resume_text() or ""

    labels_path = Path("eval/labels.jsonl")
    raw_rows = [json.loads(l) for l in labels_path.open(encoding="utf-8") if l.strip()]
    rows = [r for r in raw_rows if r.get("human_label") != "borderline"]

    y = np.array([1 if r["human_label"] == "apply" else 0 for r in rows])
    embed_model = get_model()

    print("Computing features for decision metrics across %d samples..." % len(y))
    rag_scores = []
    title_cleans = []
    title_poses = []
    title_negs = []
    title_sims = []
    jd_coverages = []

    for r in rows:
        tit = (r.get("title") or "").strip()
        jd = truncate_jd(r.get("jd_text", ""), 3000)

        # 1. RAG
        _, rag_sc = get_top_k_bullets_and_score(resume_text, jd)
        rag_scores.append(rag_sc)

        # 2. Title
        pos = 1.0 if POS_TITLE.search(tit) else 0.0
        neg = 1.0 if NEG_TITLE.search(tit) else 0.0
        title_poses.append(pos)
        title_negs.append(neg)
        title_cleans.append(pos - neg)

        if embed_model is not None and queries:
            t_vec = embed_model.encode([tit], normalize_embeddings=True)[0]
            q_vecs = embed_model.encode(queries, normalize_embeddings=True)
            title_sims.append(float(np.max(q_vecs @ t_vec)))
        else:
            title_sims.append(0.5)

        # 3. Coverage
        sm = compute_skill_metrics(skills, jd, TECH_VOCABULARY)
        jd_coverages.append(sm["jd_coverage"])

    rag_arr = np.array(rag_scores)
    title_clean_arr = np.array(title_cleans)
    jd_cov_arr = np.array(jd_coverages)

    # Composite fit score fitted via logistic regression (out-of-fold cross-validated probabilities)
    from sklearn.model_selection import cross_val_predict, StratifiedKFold
    X_comp = np.column_stack([rag_arr, title_sims, title_poses, title_negs, jd_cov_arr])
    pipe = make_pipeline(StandardScaler(), LogisticRegression(C=0.3, class_weight="balanced", random_state=42))
    comp_probs = cross_val_predict(pipe, X_comp, y, cv=StratifiedKFold(5, shuffle=True, random_state=42), method="predict_proba")[:, 1]

    models = {
        "RAG Cosine Only":        rag_arr,
        "Title Clean (Pos-Neg)":  title_clean_arr,
        "JD Skill Coverage":      jd_cov_arr,
        "Composite Free Scorer":  comp_probs,
    }

    base_rate = float(np.mean(y))

    print("\n" + "=" * 70)
    print(" DECISION & RANKING METRICS (n=%d, Natural Base Apply Rate = %.1f%%)" % (len(y), base_rate * 100))
    print("=" * 70)
    print(f"{'Scoring Model':24s} {'P@5':8s} {'P@10':8s} {'P@15':8s} {'False Apply@10':16s}")
    print("-" * 70)

    for name, scores in models.items():
        p5 = compute_precision_at_k(y, scores, k=5)
        p10 = compute_precision_at_k(y, scores, k=10)
        p15 = compute_precision_at_k(y, scores, k=15)
        fa10 = compute_false_apply_at_k(y, scores, k=10)

        print(f"{name:24s} {p5*100:5.1f}%  {p10*100:5.1f}%  {p15*100:5.1f}%     {fa10*100:5.1f}%")

    print("-" * 70)
    print(f"{'Random / Unranked':24s} {base_rate*100:5.1f}%  {base_rate*100:5.1f}%  {base_rate*100:5.1f}%     {(1-base_rate)*100:5.1f}%")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    run_decision_eval()
