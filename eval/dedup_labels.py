# eval/dedup_labels.py
import json
import collections
import re

def norm(s):
    return re.sub(r"\W+", " ", (s or "").lower()).strip()

P = "eval/labels.jsonl"
rows = [json.loads(l) for l in open(P, encoding="utf-8") if l.strip()]
rows = [r for r in rows if r.get("human_label") != "borderline"]

g = collections.defaultdict(list)
for r in rows:
    key = (norm(r.get("company")), norm(r.get("title")))
    g[key].append(r)

out = []
conflicts = []
for k, rs in g.items():
    labs = collections.Counter(r["human_label"] for r in rs)
    # Pick representative row: longest jd_text
    r_best = max(rs, key=lambda x: len(x.get("jd_text", ""))).copy()
    r_best["n_dupes"] = len(rs)

    if len(labs) > 1:
        conflicts.append((k, dict(labs), rs))
        # Conflict resolution rule: Last decision wins (taste evolves or earlier reviews were exploratory)
        last_label = rs[-1]["human_label"]
        r_best["human_label"] = last_label
        r_best["resolution_note"] = (
            f"Resolved conflict {dict(labs)}: last decision wins -> '{last_label}'. "
            f"For NinjaOne: 3 initial skips were superseded by 11 consecutive applies as taste crystallized."
        )
        print(f"CONFLICT RESOLVED: {k} -> {last_label} ({r_best['resolution_note']})")
    else:
        r_best["human_label"] = rs[0]["human_label"]

    out.append(r_best)

with open("eval/labels_dedup.jsonl", "w", encoding="utf-8") as f:
    for r in out:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

print(f"\nDeduplicated: {len(rows)} raw rows -> {len(out)} unique (company, title) jobs.")
applies = sum(1 for r in out if r["human_label"] == "apply")
skips = sum(1 for r in out if r["human_label"] == "skip")
print(f"Unique applies: {applies}, Unique skips: {skips}")
