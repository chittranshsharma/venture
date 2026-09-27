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

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="RadarPollerThread")
        self._thread.start()
        log_message("📡 Radar Poller started: Background monitoring active.")

    def stop(self):
        self._running = False
        log_message("📡 Radar Poller stopped.")

    def is_running(self) -> bool:
        return self._running

    def get_stats(self) -> dict:
        queries = CONFIG.get("settings", {}).get("queries", [])
        return {
            "running": self._running,
            "queries_count": len(queries),
            "new_jobs_found": self.new_jobs_found,
            "interval": self._interval,
        }

    def _loop(self):
        while self._running:
            queries = CONFIG.get("settings", {}).get("queries", [])
            if not queries:
                queries = ["Software Engineer"]

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
                            title = job.get("title", "Opportunity")
                            company = job.get("company", "Company")
                            log_message(f"📡 Radar Match: Fresh job found -> '{title}' at '{company}'")

                            if self._callback:
                                try:
                                    self._callback(job)
                                except Exception as cb_err:
                                    log_message(f"Radar callback error: {cb_err}")
                except Exception as e:
                    log_message(f"Radar polling error for '{query}': {e}")

            # Sleep in 1-second ticks so stop() is responsive
            sleep_time = max(10, int(self._interval))
            for _ in range(sleep_time):
                if not self._running:
                    break
                time.sleep(1)


_GLOBAL_RADAR: RadarAgent | None = None


def get_radar_agent(callback=None) -> RadarAgent:
    global _GLOBAL_RADAR
    if _GLOBAL_RADAR is None:
        _GLOBAL_RADAR = RadarAgent(on_new_job=callback)
    elif callback and not _GLOBAL_RADAR._callback:
        _GLOBAL_RADAR._callback = callback
    return _GLOBAL_RADAR
