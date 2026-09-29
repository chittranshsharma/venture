# eval/ablate.py
import os
import sys
import json
import numpy as np

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from sklearn.metrics import roc_auc_score
from automation.composite_scorer import evaluate_opportunity

rows = [json.loads(l) for l in open("eval/labels.jsonl", encoding="utf-8") if l.strip()]
rows = [r for r in rows if r.get("human_label") != "borderline"]
res  = [evaluate_opportunity(r["title"], r.get("company", ""), r["jd_text"]) for r in rows]
y = np.array([r["human_label"] == "apply" for r in rows], int)

score     = np.array([x.deterministic_score for x in res], float)
penalty   = np.array([x.total_penalty for x in res], float)
rag       = np.array([x.rag_score for x in res], float)
prepen    = score + penalty                     # score with penalties removed

for name, s in [("rag", rag), ("composite", score), ("composite_no_penalty", prepen)]:
    print(f"{name:22s} AUC={roc_auc_score(y, s):.3f}")

def paired(a, b, n=3000, seed=0):
    rng = np.random.default_rng(seed)
    d = []
    for _ in range(n):
        i = rng.integers(0, len(y), len(y))
        if len(set(y[i])) < 2:
            continue
        d.append(roc_auc_score(y[i], a[i]) - roc_auc_score(y[i], b[i]))
    return float(np.mean(d)), [float(v) for v in np.percentile(d, [2.5, 97.5])]

print("composite - rag:       ", paired(score, rag))
print("no_penalty - composite:", paired(prepen, score))

# review-load curve: review top k% by score, how many applies found?
order = np.argsort(-score)
print("\nload  apply_recall  skip_removed")
for load in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
    k = int(load * len(y))
    top = order[:k]
    print(f"{load:.0%}   {y[top].sum()/y.sum():.2f}          {1 - (1-y[top]).sum()/max((1-y).sum(),1):.2f}")
