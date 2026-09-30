import sys, os
sys.path.insert(0, os.path.abspath("."))
import sqlite3, itertools, collections
import core.db_manager as db

conn = sqlite3.connect("venture.db")
rows = conn.execute("""
    SELECT dedup_key, url, title, company, jd_text FROM evaluations
    WHERE jd_text IS NOT NULL AND length(jd_text) >= 300
    GROUP BY url""").fetchall()
g = collections.defaultdict(list)
for k, u, t, c, jd in rows:
    g[k].append((u, t, c, jd))

pairs = []
pair_by_key = collections.defaultdict(list)
for k, v in g.items():
    if len(v) < 2:
        continue
    for a, b in itertools.combinations(v, 2):
        s = db.jd_similarity(a[3], b[3])
        pairs.append((s, a[1], a[2], a[0][-40:], b[0][-40:]))
        pair_by_key[k].append(s)
pairs.sort(reverse=True)

bins = collections.Counter(min(int(p[0] * 10), 9) / 10 for p in pairs)
print(f"same-key pairs: {len(pairs)}")
for b in sorted(bins):
    print(f"sim {b:.1f}-{b+0.1:.1f}: {bins[b]}")
print("\nsamples in 0.5-0.85 band (eyeball: same job or not?):")
for p in [p for p in pairs if 0.5 <= p[0] < 0.85][:8]:
    print(f"{p[0]:.2f} | {p[1]} @ {p[2]}\n   {p[3]}\n   {p[4]}")

per_key = {k: max(sims) for k, sims in pair_by_key.items() if sims}
print("\ncluster-weighted view:")
print(f"{len(per_key)} keys; {sum(v >= 0.9 for v in per_key.values())} at >=0.9; {sum(v < 0.85 for v in per_key.values())} below 0.85")
for k, v in per_key.items():
    if v < 0.85:
        sample = g[k][0]
        print(f"  key max_sim={v:.2f}: {sample[2]} @ {sample[1]}")
