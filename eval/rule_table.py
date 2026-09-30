# eval/rule_table.py
import json
import re

rows = [json.loads(l) for l in open("eval/labels_dedup.jsonl", encoding="utf-8") if l.strip()]
rows = [r for r in rows if r.get("human_label") != "borderline"]

RULES = {
    "qa_test":    r"\b(qa|sdet|quality assurance|test engineer|software tester|performance test(ing)?)\b",
    "senior":     r"\b(senior|sr\.?|lead|staff|principal|consultant)\b",
    "level_ii":   r"\b(engineer|developer)\s+(ii|iii|2|3)\b",
    "java_net":   r"\b(java|\.net|c#|php)\b",
    "data_cloud": r"\b(data engineer|azure|aws|search|devops|sre)\b",
}

ns = sum(r["human_label"] == "skip" for r in rows)
na = len(rows) - ns
print(f"Total: {len(rows)} | Applies: {na} | Skips: {ns}")
print("-" * 55)
print(f"{'rule':12s} {'skips_hit':10s} {'applies_hit':11s} {'precision':10s} {'skip_recall':11s}")
print("-" * 55)
for name, pat in RULES.items():
    hit = [r for r in rows if re.search(pat, r["title"], re.I)]
    s = sum(r["human_label"] == "skip" for r in hit)
    a = len(hit) - s
    prec = s / max(len(hit), 1)
    rec = s / max(ns, 1)
    print(f"{name:12s} {s:9d} {a:11d} {prec:10.2f} {rec:11.2f}")
