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
from sklearn.model_selection import StratifiedKFold, cross_val_predict
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

F = {
    "rag":        np.array([x.rag_score for x in res], float),
    "penalty":    np.array([x.total_penalty for x in res], float),
    "matched":    np.array([len(x.matched_skills) for x in res], float),
    "stretch":    np.array([float(x.is_stretch) for x in res]),
    "title_clean": np.array([x.title_clean for x in res], float),
    "composite":  np.array([x.deterministic_score for x in res], float),
}

def cv(cols, reps=30):
    X = np.column_stack([F[c] for c in cols])
    a = []
    for sd in range(reps):
        p = cross_val_predict(
            make_pipeline(StandardScaler(), LogisticRegression(C=0.3, class_weight="balanced", max_iter=1000)),
            X, y, cv=StratifiedKFold(5, shuffle=True, random_state=sd), method="predict_proba"
        )[:, 1]
        a.append(roc_auc_score(y, p))
    return np.mean(a), np.percentile(a, [5, 95])

print("=" * 65)
print(f"5-FOLD STRATIFIED CV COMPARISON (30 REPEATS, N={len(y)}, APPLIES={y.sum()})")
print("=" * 65)
feature_sets = {
    "rag":                 ["rag"],
    "rag+matched":         ["rag", "matched"],
    "rag+matched+penalty": ["rag", "matched", "penalty"],
    "all":                 ["rag", "matched", "penalty", "stretch"],
    "all+title_clean":     ["rag", "matched", "penalty", "stretch", "title_clean"],
}

for name, cols in feature_sets.items():
    m, (lo, hi) = cv(cols)
    print(f"{name:24s} CV-AUC={m:.3f} [{lo:.3f}, {hi:.3f}]")

print("-" * 65)
comp_auc = roc_auc_score(y, F["composite"])
print(f"{'hand_composite (raw)':24s}     AUC={comp_auc:.3f} (heuristic weights + language rule)")
print("=" * 65)
