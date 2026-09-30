import os
import sys
import time

# Ensure workspace root in path
WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from automation.job_scraper import fast_scrape_jobs
from core.db_manager import log_evaluation, compute_content_hash, compute_dedup_key, _init_db_schema, _get_connection
from core.config_manager import CONFIG

def collect_jds_cycle(max_per_query=20):
    print("=" * 70)
    print("[*] VENTURE: COLLECT-ONLY RUNNER")
    print("   Harvesting raw JDs into evaluations table without LLM eval or apply")
    print("=" * 70)

    _init_db_schema()

    queries = CONFIG.get("settings", {}).get("queries", ["Full Stack Developer", "Software Engineer", "Frontend Developer"])
    # Broaden queries slightly to ensure diverse candidate pool for labeling
    expanded_queries = list(dict.fromkeys(queries + [
        "Python Developer", "Backend Engineer", "React Developer", "Data Engineer", "Node.js Developer"
    ]))

    locations = ["India", "Remote", "Bangalore", "Mumbai"]

    total_added = 0
    total_skipped = 0

    conn = _get_connection()
    existing_urls = set(r[0] for r in conn.execute("SELECT url FROM evaluations").fetchall())
    conn.close()

    print(f"Starting collection with {len(existing_urls)} existing evaluations in DB.")

    for q in expanded_queries:
        for loc in locations:
            print(f"\n[>] Scraping '{q}' in '{loc}' (limit={max_per_query})...")
            try:
                jobs = fast_scrape_jobs(query=q, location=loc, limit=max_per_query)
                print(f"   Received {len(jobs)} jobs.")
                for job in jobs:
                    url = job.get("url", "")
                    desc = job.get("description", "")
                    title = job.get("title", "")
                    company = job.get("company", "")

                    if not url or not desc or len(desc) < 300:
                        total_skipped += 1
                        continue

                    dk = compute_dedup_key(company, title)
                    ch = compute_content_hash(desc)

                    log_evaluation(
                        url=url,
                        title=title,
                        company=company,
                        jd_text=desc,
                        llm_score=None,
                        rag_score=None,
                        seniority=None,
                        skill_overlap=None,
                        route="collected",
                        propensity=None,
                        eval_model=None,
                        prompt_version=None,
                        dedup_key=dk,
                        content_hash=ch
                    )
                    total_added += 1
                time.sleep(1.5)  # Friendly delay
            except Exception as e:
                print(f"   Notice during scrape for '{q}' in '{loc}': {e}")

    conn = _get_connection()
    final_count = conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0]
    collected_count = conn.execute("SELECT COUNT(*) FROM evaluations WHERE route = 'collected'").fetchone()[0]
    conn.close()

    print("\n" + "=" * 70)
    print("[SUCCESS] COLLECTION CYCLE COMPLETE")
    print(f"   Processed attempts:  {total_added}")
    print(f"   Skipped (<300 chars): {total_skipped}")
    print(f"   Total evaluations in DB: {final_count} (collected={collected_count})")
    print("=" * 70)

if __name__ == "__main__":
    collect_jds_cycle(max_per_query=20)
