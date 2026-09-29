import os
import sys
import time

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from automation.job_scraper import fast_scrape_jobs
from core.db_manager import log_evaluation, compute_content_hash, compute_dedup_key, _init_db_schema, _get_connection

def collect_jds_cycle_2(max_per_query=25):
    print("=" * 70)
    print("[*] JOBPILOT-AI: COLLECT-ONLY RUNNER (Cycle 2)")
    print("=" * 70)

    _init_db_schema()

    queries = [
        "DevOps Engineer", "Cloud Engineer", "Machine Learning Engineer",
        "Golang Developer", "Java Developer", "Full Stack Engineer",
        "Systems Engineer", "AI Engineer"
    ]
    locations = ["India", "Remote", "Bangalore", "Hyderabad", "Pune"]

    total_added = 0
    total_skipped = 0

    for q in queries:
        for loc in locations:
            try:
                jobs = fast_scrape_jobs(query=q, location=loc, limit=max_per_query)
                for job in jobs:
                    url = job.get("url", "")
                    desc = job.get("description", "")
                    title = job.get("title", "")
                    company = job.get("company", "")

                    if not url or not desc or len(desc) < 300:
                        total_skipped += 1
                        continue

                    dk = compute_dedup_key(company, title, loc)
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
                time.sleep(1.0)
            except Exception as e:
                print(f"Notice: {e}")

    conn = _get_connection()
    final_count = conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0]
    conn.close()

    print("\n" + "=" * 70)
    print(f"[SUCCESS] Total evaluations in DB now: {final_count}")
    print("=" * 70)

if __name__ == "__main__":
    collect_jds_cycle_2()
