import os
import sys
import json
import re
from pathlib import Path
from typing import Any, Dict, List
import numpy as np
from sklearn.metrics import roc_auc_score

# Ensure workspace root is in sys.path
WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from core.config_manager import load_config
from core.resume_parser import extract_resume_text
from core.rag_scorer import get_top_k_bullets_and_score, get_model
from automation.llm_evaluator import TECH_VOCABULARY
from automation.skill_normalizer import compute_skill_metrics
from eval.common import split_of, truncate_jd, get_dedup_key, profile_hash

NEG_TITLE = re.compile(
    r"\b(test|qa|quality assurance|sdet|support|sales|recruit|manager|"
    r"consultant|analyst|designer|devops|sap|salesforce|mainframe)\b",
    re.I
)
POS_TITLE = re.compile(
    r"\b(full[- ]?stack|backend|back[- ]end|python|react|node|software (engineer|developer)|web developer)\b",
    re.I
)


def compute_title_features(title: str, queries: List[str], model) -> Dict[str, float]:
    """Compute dense semantic similarity to queries and regex family matches."""
    t_clean = (title or "").strip()
    if not t_clean:
        return {"title_sim_max": 0.0, "title_pos": 0.0, "title_neg": 0.0}

    pos = 1.0 if POS_TITLE.search(t_clean) else 0.0
    neg = 1.0 if NEG_TITLE.search(t_clean) else 0.0

    if model is not None and queries:
        t_vec = model.encode([t_clean], normalize_embeddings=True)[0]
        q_vecs = model.encode(queries, normalize_embeddings=True)
        sim_max = float(np.max(q_vecs @ t_vec))
    else:
        sim_max = 0.5

    return {
        "title_sim_max": round(sim_max, 4),
        "title_pos": pos,
        "title_neg": neg,
    }


def run_baselines():
    cfg = load_config()
    queries = cfg.get("settings", {}).get("queries", ["Full Stack Developer", "Software Engineer", "Python Developer"])
    skills = cfg.get("candidate", {}).get("skills", ["Python", "C++", "JavaScript", "React", "Node.js", "Git"])
    resume_text = extract_resume_text() or ""

    assert len(resume_text) > 500, f"Resume text is too short ({len(resume_text)} chars). Check candidate.resume_path."

    labels_path = Path("eval/labels.jsonl")
    if not labels_path.exists():
        print(f"Error: {labels_path} does not exist.")
        return

    raw_rows = [json.loads(l) for l in labels_path.open(encoding="utf-8") if l.strip()]
    rows = [r for r in raw_rows if r.get("human_label") != "borderline"]

    if not rows:
        print("No definitive (apply/skip) labels found.")
        return

    # Check dedup keys and collisions
    dks = [get_dedup_key(r) for r in rows]
    unique_dks = set(dks)

    print("=" * 65)
    print(" VENTURE DATASET & DEDUP INTEGRITY")
    print("=" * 65)
    print(f"Total Rows:           {len(rows)}")
    print(f"Unique dedup_keys:    {len(unique_dks)} (Collisions/Duplicates: {len(rows) - len(unique_dks)})")
    print(f"Candidate Resume:     {len(resume_text)} chars (Profile Hash: {profile_hash(cfg, resume_text)})")
    print(f"Candidate Skills:     {skills}")
    print(f"Target Queries:       {queries}")

    y = np.array([1 if r["human_label"] == "apply" else 0 for r in rows])
    mask = np.array([split_of(r) == "tune" for r in rows])

    embed_model = get_model()

    print("\nComputing RAG, Title, and Vocabulary features...")
    rag_scores = []
    title_sims = []
    title_poses = []
    title_negs = []
    jd_coverages = []
    cand_coverages = []
    n_missings = []

    for r in rows:
        tit = r.get("title", "")
        jd = truncate_jd(r.get("jd_text", ""), 3000)

        # 1. Real RAG cosine score using candidate base resume
        _, rag_sc = get_top_k_bullets_and_score(resume_text, jd)
        rag_scores.append(rag_sc)

        # 2. Title semantic + regex features
        tf = compute_title_features(tit, queries, embed_model)
        title_sims.append(tf["title_sim_max"])
        title_poses.append(tf["title_pos"])
        title_negs.append(tf["title_neg"])

        # 3. JD vocabulary coverage & missing gaps
        sm = compute_skill_metrics(skills, jd, TECH_VOCABULARY)
        jd_coverages.append(sm["jd_coverage"])
        cand_coverages.append(sm["cand_coverage"])
        n_missings.append(len(sm["missing_skills"]))

    feats = {
        "rag_score":     rag_scores,
        "title_sim_max": title_sims,
        "title_pos":     title_poses,
        "title_neg":     title_negs,           # Note: negative feature (expected < 0.5 un-inverted)
        "title_clean":   [p - n for p, n in zip(title_poses, title_negs)], # pos minus neg
        "jd_coverage":   jd_coverages,
        "cand_coverage": cand_coverages,
        "fewer_missing": [-m for m in n_missings], # inverted so higher is better
    }

    print("\n" + "=" * 65)
    print(" FREE NON-LLM BASELINES EVALUATION (REAL BASE RESUME)")
    print("=" * 65)
    print(f"Total labeled: {len(y)} | Apply rate: {y.mean():.2f} (Apply={y.sum()}, Skip={len(y)-y.sum()})")
    print(f"Tune split:    n={mask.sum()} (Apply={y[mask].sum()}, Skip={len(y[mask])-y[mask].sum()})")
    print(f"Holdout split: n={(~mask).sum()} (Apply={y[~mask].sum()}, Skip={len(y[~mask])-y[~mask].sum()})")
    print("-" * 65)
    print(f"{'Feature':16s} {'AUC All':10s} {'AUC Tune':10s} {'AUC Hold':10s} {'Apply Mean':12s} {'Skip Mean':12s}")
    print("-" * 65)

    for name, s in feats.items():
        s_arr = np.array(s, dtype=float)
        auc_all = roc_auc_score(y, s_arr) if len(set(y)) > 1 else 0.5
        auc_tune = roc_auc_score(y[mask], s_arr[mask]) if len(set(y[mask])) > 1 else 0.5
        auc_holdout = roc_auc_score(y[~mask], s_arr[~mask]) if len(set(y[~mask])) > 1 else 0.5

        app_m = float(np.mean(s_arr[y == 1])) if (y == 1).any() else 0.0
        sk_m = float(np.mean(s_arr[y == 0])) if (y == 0).any() else 0.0

        print(f"{name:16s} {auc_all:9.3f}  {auc_tune:9.3f}  {auc_holdout:9.3f}  {app_m:11.3f}  {sk_m:11.3f}")

    print("-" * 65)
    print(f"{'majority_base':16s}   0.500      0.500      0.500       (always-apply baseline)")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    run_baselines()
