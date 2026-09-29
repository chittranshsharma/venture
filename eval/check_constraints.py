import json
import os
import sys

# Ensure workspace root is in sys.path
WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from automation.constraint_checker import evaluate_constraints
from core.config_manager import load_config

cfg = load_config()
rows = [json.loads(l) for l in open("eval/labels.jsonl", encoding="utf-8") if l.strip()]

apply_results = []
skip_results = []

for r in rows:
    lbl = r.get("human_label")
    if lbl not in ("apply", "skip"):
        continue
    tit = r.get("title", "")
    jd = r.get("jd_text", "")
    comp = r.get("company", "")
    res = evaluate_constraints(tit, jd, cfg)
    if lbl == "apply":
        apply_results.append((r, res))
    else:
        skip_results.append((r, res))

hard_blocked_apply = [r for r, res in apply_results if res.hard_block]
hard_blocked_skip = [r for r, res in skip_results if res.hard_block]

print("=" * 65)
print(" 3-TIER CONSTRAINT ENGINE AUDIT")
print("=" * 65)
print(f"Total Apply Rows: {len(apply_results)}")
print(f"Total Skip Rows:  {len(skip_results)}")
print("-" * 65)
print(f"Tier 1 Hard Block on APPLY: {len(hard_blocked_apply)} / {len(apply_results)} (False Reject %: {len(hard_blocked_apply)/len(apply_results)*100:.1f}%)")
print(f"Tier 1 Hard Block on SKIP:  {len(hard_blocked_skip)} / {len(skip_results)} (True Rejection %: {len(hard_blocked_skip)/len(skip_results)*100:.1f}%)")
print("-" * 65)

if hard_blocked_apply:
    print("\n== FALSE REJECTS (Hard Blocked Apply Rows) ==")
    for r, res in [(r, res) for r, res in apply_results if res.hard_block]:
        print(f"  [{res.hard_reason}] {r.get('title')} @ {r.get('company')}")
else:
    print("\n[PASSED] ZERO FALSE REJECTS on Apply Rows! Hard invariants are 100% safe.")

print("\n== TIER 2 & 3: SOFT PENALTIES & STRETCH SIGNALS SUMMARY ==")
avg_pen_apply = sum(res.total_penalty for _, res in apply_results) / max(len(apply_results), 1)
avg_pen_skip = sum(res.total_penalty for _, res in skip_results) / max(len(skip_results), 1)
avg_boost_apply = sum(res.total_stretch_boost for _, res in apply_results) / max(len(apply_results), 1)
avg_boost_skip = sum(res.total_stretch_boost for _, res in skip_results) / max(len(skip_results), 1)

print(f"Apply Rows: Mean Soft Penalty = {avg_pen_apply:.1f} pts | Mean Stretch Boost = {avg_boost_apply:.1f} pts")
print(f"Skip Rows:  Mean Soft Penalty = {avg_pen_skip:.1f} pts | Mean Stretch Boost = {avg_boost_skip:.1f} pts")

sample_stretches = [(r, res) for r, res in apply_results if res.stretch_signals][:3]
if sample_stretches:
    print("\nSample Stretch Signals on Desired Roles:")
    for r, res in sample_stretches:
        boost_str = "; ".join(f"{s.type} (+{s.value:.0f} pts: {s.evidence})" for s in res.stretch_signals)
        print(f"  - {r.get('title')} @ {r.get('company')}: {boost_str}")
print("=" * 65)
