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

# 3. Uniform random sample (seed=1 for reproducibility, up to 120 rows)
# Avoids conditioning / bias on LLM scores
random.seed(1)
pool = random.sample(rows, min(len(rows), 120))

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
            print("Reason for skip? [1]seniority [2]stack [3]location [4]domain [5]company [6]pay [Enter to skip]: ", end="", flush=True)
            r_in = input().strip()
            reasons = {"1": "seniority", "2": "stack", "3": "location", "4": "domain", "5": "company", "6": "pay"}
            reason_tag = reasons.get(r_in, r_in)

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
