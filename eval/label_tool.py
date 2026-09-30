import os
import json
import sqlite3
import random
import sys
from pathlib import Path
from eval.common import get_dedup_key, truncate_jd

DB = "venture.db"
OUT = Path("eval/labels.jsonl")
OUT.parent.mkdir(parents=True, exist_ok=True)

# 1. Load already completed URLs
done = set()
if OUT.exists():
    for line in OUT.open(encoding="utf-8"):
        line = line.strip()
        if line:
            try:
                rec = json.loads(line)
                if rec.get("url"):
                    done.add(rec["url"])
            except Exception:
                pass

if not os.path.exists(DB):
    print(f"Database '{DB}' not found. Please run the collector first.")
    sys.exit(0)

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

# 2. Fetch candidate JDs with >= 300 chars (excluding scrape failures), sampling across all routes
rows = []
try:
    rows = [r for r in conn.execute(
        """
        SELECT url, title, company, jd_text, route
        FROM evaluations
        WHERE jd_text IS NOT NULL AND length(jd_text) >= 300
        GROUP BY url
        """
    ) if r["url"] not in done]
except sqlite3.OperationalError:
    pass

if not rows:
    # Fallback to applications table if evaluations table has not accumulated rows yet
    try:
        rows = [r for r in conn.execute(
            """
            SELECT url, title, company, jd_text, 'application' AS route
            FROM applications
            WHERE jd_text IS NOT NULL AND length(jd_text) >= 300
            GROUP BY url
            """
        ) if r["url"] not in done]
    except Exception:
        pass

conn.close()

if not rows:
    print(f"No unlabeled candidate JDs (>= 300 chars) found in '{DB}'.")
    print("Run the bot in collect-only mode to rapidly harvest JDs across queries.")
    sys.exit(0)

def norm(s):
    return re.sub(r"\W+", " ", (s or "").lower()).strip()

seen_keys = set()
for path_str in ["eval/labels_dedup.jsonl", "eval/labels.jsonl", "eval/holdout_labels.jsonl"]:
    p = Path(path_str)
    if p.exists():
        for line in p.open(encoding="utf-8"):
            if line.strip():
                try:
                    rec = json.loads(line)
                    seen_keys.add((norm(rec.get("company", "")), norm(rec.get("title", ""))))
                except Exception:
                    pass

# 3. Filter rows to unique (company, title) jobs not seen in existing datasets
filtered_rows = []
seen_in_batch = set()
for r in rows:
    k = (norm(r["company"]), norm(r["title"]))
    if k not in seen_keys and k not in seen_in_batch:
        seen_in_batch.add(k)
        filtered_rows.append(r)

random.seed(1)
pool = random.sample(filtered_rows, min(len(filtered_rows), 120)) if filtered_rows else []

print(f"\n" + "=" * 80)
print(f" VENTURE HUMAN EVALUATION LABELING TOOL")
print(f"=" * 80)
print(f"Total available candidates: {len(rows)}")
print(f"Uniform sample size:       {len(pool)}")
print(f"Already labeled:           {len(done)}")
print(f"Saving progress to:        {OUT}")
print(f"Note: LLM scores are hidden to eliminate anchoring bias.\n")

# 4. Interactive labeling loop with crash-safe per-label flush
with OUT.open("a", encoding="utf-8") as f:
    for idx, r in enumerate(pool, start=1):
        print("\n" + "=" * 80)
        print(f"[{idx}/{len(pool)}] {r['title']} @ {r['company']} (Route: {r['route'] or 'unknown'})\n")
        # Show exactly the text length the LLM evaluator observes (2500 chars)
        print((r["jd_text"] or "")[:2500])
        print("-" * 80)

        while True:
            k = input("\n[a]pply  [s]kip  [b]orderline  [q]uit > ").strip().lower()
            if k in {"a", "s", "b", "q"}:
                break
            print("Invalid input. Press 'a' to apply, 's' to skip, 'b' for borderline, or 'q' to quit.")

        if k == "q":
            print(f"\nLabeling session paused at [{idx-1}/{len(pool)}]. Progress saved to {OUT}.")
            break

        mapping = {"a": "apply", "s": "skip", "b": "borderline"}
        chosen_label = mapping[k]
        reason_tag = ""
        if chosen_label == "skip":
            reasons = {
                "1": "seniority", "s": "seniority",
                "2": "stack",     "k": "stack",
                "3": "qa",        "q": "qa",
                "4": "location",  "l": "location",
                "5": "domain",    "d": "domain",
                "6": "company",   "c": "company",
                "7": "pay",       "p": "pay",
                "8": "other",     "o": "other",
            }
            while not reason_tag:
                print("Reason for skip REQUIRED: [s]eniority [k]stack [q]a [l]ocation [d]omain [c]ompany [p]ay [o]ther > ", end="", flush=True)
                r_in = input().strip().lower()
                if r_in in reasons:
                    reason_tag = reasons[r_in]
                elif r_in:
                    reason_tag = r_in
                else:
                    print("Empty tag rejected! You must specify a reason tag for skips.")


        record = {
            "url": r["url"],
            "dedup_key": get_dedup_key(dict(r)),
            "title": r["title"],
            "company": r["company"],
            "jd_text": r["jd_text"],
            "human_label": chosen_label,
            "reason_tag": reason_tag
        }
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()
        try:
            os.fsync(f.fileno())
        except Exception:
            pass
        print(f"Recorded: {chosen_label.upper()}" + (f" ({reason_tag})" if reason_tag else ""))

print(f"\nSession finished. Current labeled dataset has {len(done) + idx if k != 'q' else len(done) + idx - 1} records.")
