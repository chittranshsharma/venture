# eval/fill_tags.py
import json

P = "eval/labels.jsonl"
rows = [json.loads(l) for l in open(P, encoding="utf-8") if l.strip()]
TAGS = "s=seniority k=stack q=qa d=domain c=company p=pay l=location o=other"

updated_count = 0
for r in rows:
    if r.get("human_label") == "skip" and not r.get("reason_tag"):
        print(f"\n{r['title']} @ {r.get('company', 'Unknown')}\n{TAGS}")
        t = input("> ").strip().lower()
        tag_map = {
            "s": "seniority",
            "k": "stack",
            "q": "qa",
            "d": "domain",
            "c": "company",
            "p": "pay",
            "l": "location",
            "o": "other"
        }
        r["reason_tag"] = tag_map.get(t, t or "other")
        updated_count += 1

if updated_count > 0:
    with open(P, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nSuccessfully updated {updated_count} rows with reason tags in {P}.")
else:
    print("All skip rows already have reason tags populated.")
