# eval/rank_metrics.py
import os
import sys
import json
import hashlib
import numpy as np

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from core.resume_parser import extract_resume_text
from automation.composite_scorer import evaluate_opportunity

cand_resume = extract_resume_text() or ""
resume_sha8 = hashlib.sha256(cand_resume.encode("utf-8")).hexdigest()[:8] if cand_resume else "none"
embedding_model = "sentence-transformers/all-MiniLM-L6-v2"

print(f"eval/rank_metrics.py | resume_sha8: {resume_sha8} | embedding_model: {embedding_model}")

rows = [json.loads(l) for l in open("eval/labels.jsonl", encoding="utf-8") if l.strip()]
rows = [r for r in rows if r.get("human_label") != "borderline"]
res  = [evaluate_opportunity(r["title"], r.get("company", ""), r["jd_text"]) for r in rows]
y = np.array([r["human_label"] == "apply" for r in rows], int)
score = np.array([x.deterministic_score for x in res], float)

def prec_at_k(y, s, k):
    return y[np.argsort(-s)[:k]].mean()

base = y.mean()
print(f"Total rows: {len(y)} | Base apply rate: {base:.3f} ({y.sum()} apply / {len(y)-y.sum()} skip)")
print("-" * 50)
for k in (5, 10, 15, 20):
    p = prec_at_k(y, score, k)
    print(f"P@{k:02d}={p:.2f}  lift={p/base:.2f}x  (base {base:.2f})")

# bootstrap CI for P@10 lift
rng = np.random.default_rng(0)
lifts = []
for _ in range(3000):
    i = rng.integers(0, len(y), len(y))
    if y[i].mean() in (0, 1):
        continue
    lifts.append(prec_at_k(y[i], score[i], 10) / y[i].mean())

lo, hi = np.percentile(lifts, [2.5, 97.5])
print("-" * 50)
print(f"P@10 lift mean: {np.mean(lifts):.2f}x")
print(f"P@10 lift 95% CI: [{lo:.3f}, {hi:.3f}]")
