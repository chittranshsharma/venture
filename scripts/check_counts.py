import sqlite3

conn = sqlite3.connect("venture.db")
c_total = conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0]
c_coll = conn.execute("SELECT COUNT(*) FROM evaluations WHERE route = 'collected'").fetchone()[0]
c_qual = conn.execute("SELECT COUNT(*) FROM evaluations WHERE length(jd_text) >= 300").fetchone()[0]
print(f"Total: {c_total} | Collected: {c_coll} | Qualified (>=300 chars): {c_qual}")
conn.close()
