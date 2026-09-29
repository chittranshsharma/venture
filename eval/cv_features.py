import os
import sys
import json
import re
from pathlib import Path
from typing import Any, Dict, List
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.metrics import roc_auc_score
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
from eval.common import truncate_jd, get_dedup_key

NEG_TITLE = re.compile(
    r"\b(test|qa|quality assurance|sdet|support|sales|recruit|manager|"
    r"consultant|analyst|designer|devops|sap|salesforce|mainframe)\b",
    re.I
)
POS_TITLE = re.compile(
    r"\b(full[- ]?stack|backend|back[- ]end|python|react|node|software (engineer|developer)|web developer)\b",
    re.I
)


def cv_auc(X: np.ndarray, y: np.ndarray, reps: int = 20) -> tuple[float, tuple[float, float], np.ndarray]:
    """Repeated stratified 5-fold CV to evaluate generalization stability without 70/30 split noise."""
    aucs = []
    coefs = []
    for seed in range(reps):
        pipe = make_pipeline(
            StandardScaler(),
            LogisticRegression(C=0.3, class_weight="balanced", max_iter=1000, random_state=seed)
        )
        p = cross_val_predict(
            pipe,
            X,
            y,
            cv=StratifiedKFold(5, shuffle=True, random_state=seed),
            method="predict_proba"
        )[:, 1]
        aucs.append(roc_auc_score(y, p))

        # Fit on full data to inspect coefficients
        pipe.fit(X, y)
        coefs.append(pipe.named_steps["logisticregression"].coef_[0])

    mean_coefs = np.mean(coefs, axis=0)
    return float(np.mean(aucs)), (float(np.percentile(aucs, 5)), float(np.percentile(aucs, 95))), mean_coefs


def run_cv():
    cfg = load_config()
    queries = cfg.get("settings", {}).get("queries", ["Full Stack Developer", "Software Engineer", "Python Developer"])
    skills = cfg.get("candidate", {}).get("skills", ["Python", "C++", "JavaScript", "React", "Node.js", "Git"])
    resume_text = extract_resume_text() or ""

    labels_path = Path("eval/labels.jsonl")
    raw_rows = [json.loads(l) for l in labels_path.open(encoding="utf-8") if l.strip()]
    rows = [r for r in raw_rows if r.get("human_label") != "borderline"]

    y = np.array([1 if r["human_label"] == "apply" else 0 for r in rows])
    embed_model = get_model()

    print("Extracting features across all definitive labels (n=%d)..." % len(y))
    rag_scores = []
    title_sims = []
    title_poses = []
    title_negs = []
    jd_coverages = []

    for r in rows:
        tit = r.get("title", "")
        jd = truncate_jd(r.get("jd_text", ""), 3000)

        # 1. RAG
        _, rag_sc = get_top_k_bullets_and_score(resume_text, jd)
        rag_scores.append(rag_sc)

        # 2. Title
        t_clean = (tit or "").strip()
        pos = 1.0 if POS_TITLE.search(t_clean) else 0.0
        neg = 1.0 if NEG_TITLE.search(t_clean) else 0.0

        if embed_model is not None and queries:
            t_vec = embed_model.encode([t_clean], normalize_embeddings=True)[0]
            q_vecs = embed_model.encode(queries, normalize_embeddings=True)
            sim_max = float(np.max(q_vecs @ t_vec))
        else:
            sim_max = 0.5

        title_sims.append(sim_max)
        title_poses.append(pos)
        title_negs.append(neg)

        # 3. JD Coverage
        sm = compute_skill_metrics(skills, jd, TECH_VOCABULARY)
        jd_coverages.append(sm["jd_coverage"])

    F = {
        "rag":           np.array(rag_scores, dtype=float),
        "title_sim_max": np.array(title_sims, dtype=float),
        "title_pos":     np.array(title_poses, dtype=float),
        "title_neg":     np.array(title_negs, dtype=float),
        "jd_coverage":   np.array(jd_coverages, dtype=float),
    }

    sets = {
        "rag":           ["rag"],
        "title":         ["title_sim_max", "title_pos", "title_neg"],
        "rag+title":     ["rag", "title_sim_max", "title_pos", "title_neg"],
        "rag+title+cov": ["rag", "title_sim_max", "title_pos", "title_neg", "jd_coverage"],
    }

    print("\n" + "=" * 65)
    print(" 5-FOLD REPEATED STRATIFIED CV EVALUATION (20 SEEDS)")
    print("=" * 65)
    print(f"Total samples: {len(y)} (Apply={y.sum()}, Skip={len(y)-y.sum()})")
    print("-" * 65)

    for name, cols in sets.items():
        X = np.column_stack([F[c] for c in cols])
        m, (lo, hi), coefs = cv_auc(X, y)
        coef_str = ", ".join(f"{c}: {w:+.2f}" for c, w in zip(cols, coefs))
        print(f"{name:16s} CV-AUC={m:.3f} [{lo:.3f}, {hi:.3f}]")
        print(f"                 Coefficients: [{coef_str}]")

    print("-" * 65)
    print(f"{'majority_base':16s} CV-AUC=0.500 [0.500, 0.500]")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    run_cv()
