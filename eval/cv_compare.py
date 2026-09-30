# eval/cv_compare.py
import os
import sys
import json
import hashlib
import numpy as np

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.model_selection import StratifiedKFold, StratifiedGroupKFold, cross_val_predict
from sklearn.metrics import roc_auc_score
from core.resume_parser import extract_resume_text
from automation.composite_scorer import evaluate_opportunity

cand_resume = extract_resume_text() or ""
resume_sha8 = hashlib.sha256(cand_resume.encode("utf-8")).hexdigest()[:8] if cand_resume else "none"
embedding_model = "sentence-transformers/all-MiniLM-L6-v2"

print(f"eval/cv_compare.py | resume_sha8: {resume_sha8} | embedding_model: {embedding_model}")

rows = [json.loads(l) for l in open("eval/labels.jsonl", encoding="utf-8") if l.strip()]
rows = [r for r in rows if r.get("human_label") != "borderline"]
res  = [evaluate_opportunity(r["title"], r.get("company", ""), r["jd_text"]) for r in rows]
y = np.array([r["human_label"] == "apply" for r in rows], int)

groups = [r.get("company", "").strip().lower() or r.get("dedup_key", f"row_{i}") for i, r in enumerate(rows)]

F = {
    "rag":        np.array([x.rag_score for x in res], float),
    "penalty":    np.array([x.total_penalty for x in res], float),
    "matched":    np.array([len(x.matched_skills) for x in res], float),
    "stretch":    np.array([float(x.is_stretch) for x in res]),
    "title_clean": np.array([x.title_clean for x in res], float),
    "composite":  np.array([x.deterministic_score for x in res], float),
}

def cv(cols, reps=30, grouped=False):
    X = np.column_stack([F[c] for c in cols])
    a = []
    for sd in range(reps):
        if grouped:
            splitter = StratifiedGroupKFold(5, shuffle=True, random_state=sd)
            p = cross_val_predict(
                make_pipeline(StandardScaler(), LogisticRegression(C=0.3, class_weight="balanced", max_iter=1000)),
                X, y, cv=splitter, groups=groups, method="predict_proba"
            )[:, 1]
        else:
            splitter = StratifiedKFold(5, shuffle=True, random_state=sd)
            p = cross_val_predict(
                make_pipeline(StandardScaler(), LogisticRegression(C=0.3, class_weight="balanced", max_iter=1000)),
                X, y, cv=splitter, method="predict_proba"
            )[:, 1]
        a.append(roc_auc_score(y, p))
    return np.mean(a), np.percentile(a, [5, 95])

print("=" * 80)
print(f"5-FOLD CV COMPARISON: STANDARD vs GROUPED (30 REPEATS, N={len(y)}, APPLIES={y.sum()}, GROUPS={len(set(groups))})")
print("=" * 80)
feature_sets = {
    "rag":                 ["rag"],
    "rag+matched":         ["rag", "matched"],
    "rag+matched+penalty": ["rag", "matched", "penalty"],
    "all":                 ["rag", "matched", "penalty", "stretch"],
    "all+title_clean":     ["rag", "matched", "penalty", "stretch", "title_clean"],
}

print(f"{'Feature Set':22s} | {'Stratified CV':24s} | {'Grouped CV (Company)':24s}")
print("-" * 80)
for name, cols in feature_sets.items():
    m_s, (lo_s, hi_s) = cv(cols, grouped=False)
    m_g, (lo_g, hi_g) = cv(cols, grouped=True)
    print(f"{name:22s} | AUC={m_s:.3f} [{lo_s:.3f}, {hi_s:.3f}]   | AUC={m_g:.3f} [{lo_g:.3f}, {hi_g:.3f}]")

print("-" * 80)
comp_auc = roc_auc_score(y, F["composite"])
print(f"{'hand_composite (raw)':22s} | AUC={comp_auc:.3f} (heuristic weights + language rule, in-sample)")
print("=" * 80)
