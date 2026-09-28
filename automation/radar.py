"""
automation/radar.py — Background Radar Poller (P5.1)
Continuously monitors job platforms in a lightweight daemon thread to discover
fresh job openings within minutes of posting, maximizing recruiter response rates.
"""

import time
import threading
from core.config_manager import CONFIG
from core.db_manager import log_message, APPLIED_URLS_SET
from automation.job_scraper import fast_scrape_jobs


from core.notifier import notify


class RadarAgent:
    """
    Background daemon poller that periodically scrapes job openings
    for target queries, deduplicating against known URLs and notifying the pipeline.
    """

    def __init__(self, on_new_job=None):
        self._interval = CONFIG.get("settings", {}).get("radar_interval_seconds", 60)
        self._seen: set = set(APPLIED_URLS_SET)  # Pre-seed from SQLite DB
        self._callback = on_new_job
        self._running = False
        self._thread = None
        self.new_jobs_found = 0
        self.cycle_jobs_found = 0
        self.seconds_remaining = 0
        self.status_phase = "Idle"

    def start(self):
        if self._running:
            return
        self._running = True
        self.status_phase = "Starting..."
        self._thread = threading.Thread(target=self._loop, daemon=True, name="RadarPollerThread")
        self._thread.start()
        log_message("📡 Radar Poller started: Background monitoring active.")

    def stop(self):
        self._running = False
        self.status_phase = "Stopped"
        self.seconds_remaining = 0
        log_message("📡 Radar Poller stopped.")

    def is_running(self) -> bool:
        return self._running

    def get_stats(self) -> dict:
        queries = CONFIG.get("settings", {}).get("queries", [])
        career_pages = CONFIG.get("settings", {}).get("company_career_pages", [])
        return {
            "running": self._running,
            "queries_count": len(queries),
            "career_pages_count": len(career_pages),
            "new_jobs_found": self.new_jobs_found,
            "cycle_jobs_found": self.cycle_jobs_found,
            "seconds_remaining": self.seconds_remaining,
            "status_phase": self.status_phase,
            "interval": self._interval,
        }

    def _loop(self):
        while self._running:
            # Fix 1.3: Read interval fresh each cycle so Settings changes apply immediately
            self._interval = CONFIG.get("settings", {}).get("radar_interval_seconds", 60)
            self.cycle_jobs_found = 0
            self.status_phase = "Scanning boards..."
            queries = CONFIG.get("settings", {}).get("queries", [])
            if not queries:
                queries = ["Software Engineer"]

            # ── 1. Standard job board polling ──
            for query in queries:
                if not self._running:
                    break
                try:
                    jobs = fast_scrape_jobs(query=query, limit=5)
                    for job in jobs:
                        if not self._running:
                            break
                        url = job.get("url", "")
                        if url and url not in self._seen:
                            self._seen.add(url)
                            self.new_jobs_found += 1
                            self.cycle_jobs_found += 1
                            title = job.get("title", "Opportunity")
                            company = job.get("company", "Company")
                            log_message(f"📡 Radar Match: Fresh job found -> '{title}' at '{company}'")
                            notify("VENTURE Radar Match", f"Found: {title} at {company}")
                            if self._callback:
                                try:
                                    self._callback(job)
                                except Exception as cb_err:
                                    log_message(f"Radar callback error: {cb_err}")
                except Exception as e:
                    log_message(f"Radar polling error for '{query}': {e}")

            # ── 2. Company career page polling ──
            career_pages = CONFIG.get("settings", {}).get("company_career_pages", [])
            if career_pages and self._running:
                self.status_phase = "Scanning career pages..."
                try:
                    from automation.career_crawler import crawl_all_company_pages
                    jobs = crawl_all_company_pages(career_pages)
                    for job in jobs:
                        if not self._running:
                            break
                        url = job.get("url", "")
                        if url and url not in self._seen:
                            self._seen.add(url)
                            self.new_jobs_found += 1
                            self.cycle_jobs_found += 1
                            title = job.get("title", "Opportunity")
                            company = job.get("company", "Company")
                            log_message(f"🏢 Career Page: New role found -> '{title}' at '{company}'")
                            notify("VENTURE Career Match", f"Found: {title} at {company}")
                            if self._callback:
                                try:
                                    self._callback(job)
                                except Exception as cb_err:
                                    log_message(f"Career page callback error: {cb_err}")
                except Exception as e:
                    log_message(f"Career page crawl error: {e}")

            # Notify cycle summary if multiple jobs found
            if self.cycle_jobs_found > 1:
                notify("VENTURE Radar Cycle Done", f"{self.cycle_jobs_found} fresh jobs found. Total: {self.new_jobs_found}")

            # Sleep in 1-second ticks so stop() is responsive and banner countdown updates
            sleep_time = max(10, int(self._interval))
            self.status_phase = "Waiting"
            for rem in range(sleep_time, 0, -1):
                if not self._running:
                    break
                self.seconds_remaining = rem
                time.sleep(1)
            self.seconds_remaining = 0



_GLOBAL_RADAR: RadarAgent | None = None


def get_radar_agent(callback=None) -> RadarAgent:
    global _GLOBAL_RADAR
    if _GLOBAL_RADAR is None:
        _GLOBAL_RADAR = RadarAgent(on_new_job=callback)
    elif callback and not _GLOBAL_RADAR._callback:
        _GLOBAL_RADAR._callback = callback
    return _GLOBAL_RADAR
