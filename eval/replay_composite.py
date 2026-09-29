# eval/replay_composite.py
import os
import sys
import json
import numpy as np

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from collections import Counter
from sklearn.metrics import roc_auc_score
from automation.composite_scorer import evaluate_opportunity, should_invoke_llm

rows = [json.loads(l) for l in open("eval/labels.jsonl", encoding="utf-8") if l.strip()]
rows = [r for r in rows if r.get("human_label") != "borderline"]

print(f"Loaded {len(rows)} non-borderline labeled rows.")
res = [evaluate_opportunity(r["title"], r.get("company", ""), r["jd_text"]) for r in rows]
y = np.array([r["human_label"] == "apply" for r in rows], int)
s = np.array([x.deterministic_score for x in res], float)

auc = roc_auc_score(y, s)
print(f"n={len(y)} apply={y.sum()} AUC={auc:.3f}")

# Paired bootstrap CI against RAG score
rng = np.random.default_axis = np.random.RandomState(42)
boot_aucs = []
for _ in range(1000):
    idx = rng.randint(0, len(y), len(y))
    if len(np.unique(y[idx])) < 2:
        continue
    boot_aucs.append(roc_auc_score(y[idx], s[idx]))
ci_low, ci_high = np.percentile(boot_aucs, [2.5, 97.5])
print(f"Bootstrap AUC 95% CI: [{ci_low:.3f}, {ci_high:.3f}]")

# Check hard_blocks on APPLY rows (false rejects)
hard_blocks_on_apply = [
    (r["title"], r.get("company", ""), getattr(x, "hard_reason", ""))
    for r, x in zip(rows, res)
    if x.hard_block and r["human_label"] == "apply"
]
print(f"hard_block on APPLY rows ({len(hard_blocks_on_apply)}):", hard_blocks_on_apply)

# Route x Label table
tab = Counter((x.route, r["human_label"]) for r, x in zip(rows, res))
print("\nRoute x Label Contingency:")
for k in sorted(tab):
    print(f"  {k}: {tab[k]}")

# LLM invocation rate
llm_invocations = sum(should_invoke_llm(x) for x in res)
print(f"\nLLM invoked on: {llm_invocations} / {len(res)} ({llm_invocations / len(res) * 100:.1f}%)")
