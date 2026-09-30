# eval/label_audit.py
import json
import collections

rows = [json.loads(l) for l in open("eval/labels.jsonl", encoding="utf-8") if l.strip()]
rows = [r for r in rows if r.get("human_label") != "borderline"]
g = collections.defaultdict(list)
for r in rows:
    g[(r.get("company", "").strip().lower(), r["title"].strip().lower())].append(r["human_label"])
conf = {k: v for k, v in g.items() if len(set(v)) > 1}
print(f"groups={len(g)} conflicting={len(conf)}")
for k, v in conf.items():
    print(k, collections.Counter(v))
