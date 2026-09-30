# eval/cv_title.py
import os
import sys
import json
import hashlib
import numpy as np

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.model_selection import StratifiedKFold, StratifiedGroupKFold, cross_val_predict
from sklearn.metrics import roc_auc_score
from automation.composite_scorer import evaluate_opportunity
from core.resume_parser import extract_resume_text
from core.rag_scorer import get_model

cand_resume = extract_resume_text() or ""
resume_sha8 = hashlib.sha256(cand_resume.encode("utf-8")).hexdigest()[:8] if cand_resume else "none"

print(f"eval/cv_title.py | resume_sha8: {resume_sha8}")

rows = [json.loads(l) for l in open("eval/labels.jsonl", encoding="utf-8") if l.strip()]
rows = [r for r in rows if r.get("human_label") != "borderline"]

titles = [r.get("title", "").strip() for r in rows]
companies = [r.get("company", "").strip().lower() or r.get("dedup_key", f"row_{i}") for i, r in enumerate(rows)]
y = np.array([r["human_label"] == "apply" for r in rows], int)

# Compute composite scorer features for baseline reference
res = [evaluate_opportunity(r["title"], r.get("company", ""), r["jd_text"]) for r in rows]
title_clean_vals = np.array([x.title_clean for x in res], float)
composite_vals = np.array([x.deterministic_score for x in res], float)

def cv_model(clf, X_data, reps=30, grouped=False):
    a = []
    for sd in range(reps):
        if grouped:
            splitter = StratifiedGroupKFold(5, shuffle=True, random_state=sd)
            p = cross_val_predict(clf, X_data, y, cv=splitter, groups=companies, method="predict_proba")[:, 1]
        else:
            splitter = StratifiedKFold(5, shuffle=True, random_state=sd)
            p = cross_val_predict(clf, X_data, y, cv=splitter, method="predict_proba")[:, 1]
        a.append(roc_auc_score(y, p))
    return np.mean(a), np.percentile(a, [5, 95])

def cv_feature_col(f_arr, reps=30, grouped=False):
    X = f_arr.reshape(-1, 1)
    pipe = make_pipeline(StandardScaler(), LogisticRegression(C=0.3, class_weight="balanced", max_iter=1000))
    return cv_model(pipe, X, reps=reps, grouped=grouped)

print("=" * 86)
print(f"5-FOLD CV: TITLE MODELS - STANDARD vs GROUPED (30 REPEATS, N={len(y)}, COMPANIES={len(set(companies))})")
print("=" * 86)
print(f"{'Model':30s} | {'Stratified CV':24s} | {'Grouped CV (Company)':24s}")
print("-" * 86)

models = {
    "title_tfidf_LR (C=0.3)": make_pipeline(
        TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True),
        LogisticRegression(C=0.3, class_weight="balanced", max_iter=1000)
    ),
    "title_tfidf_LR (C=1.0)": make_pipeline(
        TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True),
        LogisticRegression(C=1.0, class_weight="balanced", max_iter=1000)
    ),
    "title_tfidf_kNN (k=3)": make_pipeline(
        TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True),
        KNeighborsClassifier(n_neighbors=3, metric="cosine", weights="uniform")
    ),
    "title_tfidf_kNN (k=5)": make_pipeline(
        TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True),
        KNeighborsClassifier(n_neighbors=5, metric="cosine", weights="uniform")
    ),
    "title_tfidf_kNN (k=9)": make_pipeline(
        TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True),
        KNeighborsClassifier(n_neighbors=9, metric="cosine", weights="uniform")
    ),
}

for name, clf in models.items():
    m_s, (lo_s, hi_s) = cv_model(clf, titles, grouped=False)
    m_g, (lo_g, hi_g) = cv_model(clf, titles, grouped=True)
    print(f"{name:30s} | AUC={m_s:.3f} [{lo_s:.3f}, {hi_s:.3f}]   | AUC={m_g:.3f} [{lo_g:.3f}, {hi_g:.3f}]")

print("-" * 86)

# Dense Embeddings (MiniLM) models if available
embed_model = get_model()
if embed_model is not None:
    t_embeddings = embed_model.encode(titles, normalize_embeddings=True)
    dense_models = {
        "title_embed_LR (C=0.3)": LogisticRegression(C=0.3, class_weight="balanced", max_iter=1000),
        "title_embed_kNN (k=5)": KNeighborsClassifier(n_neighbors=5, metric="cosine"),
        "title_embed_kNN (k=9)": KNeighborsClassifier(n_neighbors=9, metric="cosine"),
    }
    for name, clf in dense_models.items():
        m_s, (lo_s, hi_s) = cv_model(clf, t_embeddings, grouped=False)
        m_g, (lo_g, hi_g) = cv_model(clf, t_embeddings, grouped=True)
        print(f"{name:30s} | AUC={m_s:.3f} [{lo_s:.3f}, {hi_s:.3f}]   | AUC={m_g:.3f} [{lo_g:.3f}, {hi_g:.3f}]")

print("-" * 86)

# Baselines for direct comparison
m_tc_s, (lo_tc_s, hi_tc_s) = cv_feature_col(title_clean_vals, grouped=False)
m_tc_g, (lo_tc_g, hi_tc_g) = cv_feature_col(title_clean_vals, grouped=True)
print(f"{'title_clean (regex rule)':30s} | AUC={m_tc_s:.3f} [{lo_tc_s:.3f}, {hi_tc_s:.3f}]   | AUC={m_tc_g:.3f} [{lo_tc_g:.3f}, {hi_tc_g:.3f}]")

comp_auc = roc_auc_score(y, composite_vals)
print(f"{'hand_composite (raw)':30s} | AUC={comp_auc:.3f} (heuristic weights + language rule, in-sample)")
print("=" * 86)
