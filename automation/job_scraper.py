import re
import json
import threading
import urllib.request
import urllib.parse
from difflib import SequenceMatcher
from core.config_manager import CONFIG
from core.db_manager import log_message

# Fix 1.4: Session-level description cache so the same LinkedIn URL isn't re-fetched
_LI_DESC_CACHE: dict = {}
_LI_DESC_LOCK = threading.Lock()


def _fetch_linkedin_description(job_url: str, fallback: str) -> str:
    """Fix 1.4: Fetch full job description from LinkedIn job detail page."""
    if not job_url or "linkedin.com" not in job_url:
        return fallback
    with _LI_DESC_LOCK:
        if job_url in _LI_DESC_CACHE:
            return _LI_DESC_CACHE[job_url]
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
        req = urllib.request.Request(job_url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
        # Extract description from LinkedIn job detail page
        patterns = [
            r'<div[^>]*class="[^"]*show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>',
            r'<section[^>]*class="[^"]*description[^"]*"[^>]*>(.*?)</section>',
            r'<div[^>]*id="job-details"[^>]*>(.*?)</div>',
        ]
        for pat in patterns:
            m = re.search(pat, html, re.DOTALL | re.IGNORECASE)
            if m:
                raw = m.group(1)
                # Strip HTML tags and normalize whitespace
                text = re.sub(r'<[^>]+>', ' ', raw)
                text = re.sub(r'\s+', ' ', text).strip()
                if len(text) > 100:
                    with _LI_DESC_LOCK:
                        _LI_DESC_CACHE[job_url] = text[:3000]
                    return text[:3000]
    except Exception:
        pass
    with _LI_DESC_LOCK:
        _LI_DESC_CACHE[job_url] = fallback
    return fallback


def fast_scrape_jobs(query="Software Engineer", location="", limit=20):
    """
    Rapidly fetches job postings across multiple platforms using API/HTTP search endpoints.
    Returns list of dicts: [{"title": ..., "company": ..., "location": ..., "platform": ..., "url": ..., "description": ...}]
    """
    results = []
    log_message(f"\u26a1 FAST SCRAPER: Searching '{query}' in '{location if location else 'All'}'...")
    
    # 1. Scrape via JobSpy if available
    try:
        from jobspy import scrape_jobs
        loc_str = location if location else "India"
        site_names = ["linkedin", "indeed"]
        
        jobs_df = scrape_jobs(
            site_name=site_names,
            search_term=query,
            location=loc_str,
            results_wanted=min(limit, 20),
            hours_old=72,
            country_indeed='india' if 'india' in loc_str.lower() or 'chennai' in loc_str.lower() or 'bangalore' in loc_str.lower() else 'usa'
        )
        
        if not jobs_df.empty:
            for _, row in jobs_df.iterrows():
                results.append({
                    "title": str(row.get("title", "")),
                    "company": str(row.get("company", "")),
                    "location": str(row.get("location", "")),
                    "platform": str(row.get("site", "")).capitalize(),
                    "url": str(row.get("job_url", "")),
                    "description": str(row.get("description", ""))
                })
            log_message(f"\u26a1 JobSpy Scraper: Discovered {len(results)} jobs!")
            # B1 FIX: return after dedup+filter, don't fall through to LinkedIn scraper
            return _filter_jobs(results, query)
    except Exception as e:
        log_message(f"JobSpy direct scraper notice (using fallback): {e}")

    # 2. Fallback Direct Search Scraper (LinkedIn Public Guest API)
    seen_urls = set()  # B1 FIX: prevent duplicates from multiple passes
    try:
        q_enc = urllib.parse.quote(query)
        loc_enc = urllib.parse.quote(location) if location else "India"
        api_url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={q_enc}&location={loc_enc}&start=0"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
            
            titles = re.findall(r'<h3 class="base-search-card__title">\s*(.*?)\s*</h3>', html, re.DOTALL)
            companies = re.findall(r'<h4 class="base-search-card__subtitle">\s*<a[^>]*>\s*(.*?)\s*</a>', html, re.DOTALL)
            links = re.findall(r'<a class="base-card__full-link[^"]*" href="([^"?]*)', html)
            
            for i in range(min(len(titles), len(companies), len(links))):
                url = links[i].strip()
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                title_str = titles[i].strip()
                company_str = companies[i].strip()
                stub = f"Role: {title_str} at {company_str}."
                # Fix 1.4: fetch real description (cached per session)
                desc = _fetch_linkedin_description(url, stub)
                results.append({
                    "title": title_str,
                    "company": company_str,
                    "location": location if location else "India",
                    "platform": "LinkedIn",
                    "url": url,
                    "description": desc
                })
            log_message(f"\u26a1 Direct Scraper: Found {len(results)} fast LinkedIn job listings!")
    except Exception as e:
        log_message(f"Fast scraper fallback error: {e}")
        
    return _filter_jobs(results, query)


def _fuzzy_title_match(job_title: str, queries: list) -> bool:
    """Q2: Fuzzy title matching — substring OR SequenceMatcher ratio >= 0.7 OR word overlap >= 60%."""
    title_lower = job_title.lower()
    for q in queries:
        q_lower = q.lower()
        if q_lower in title_lower or title_lower in q_lower:
            return True
        if SequenceMatcher(None, q_lower, title_lower).ratio() >= 0.7:
            return True
        q_words = set(q_lower.split())
        t_words = set(title_lower.split())
        if q_words and t_words:
            if len(q_words & t_words) / max(len(q_words), len(t_words)) >= 0.6:
                return True
    return False


def _filter_jobs(jobs: list, query: str) -> list:
    """Apply Q2 fuzzy title filter, Q3 company blacklist, and skip keyword filter."""
    set_obj = CONFIG.get("settings", {}) if isinstance(CONFIG.get("settings"), dict) else {}
    queries = set_obj.get("queries") or [query]
    blacklist = [c.lower().strip() for c in set_obj.get("blacklist_companies", [])]
    skip_kw = [k.lower() for k in set_obj.get("skip_keywords", [])]

    filtered = []
    for job in jobs:
        company_lower = job.get("company", "").lower()
        title_lower = job.get("title", "").lower()
        desc_lower = job.get("description", "").lower()

        # Q3: Company blacklist
        if blacklist and any(bl in company_lower for bl in blacklist):
            log_message(f"\U0001f6ab Blacklisted company skipped: {job.get('company')}")
            continue

        # Skip keywords in title or description
        if skip_kw and any(kw in title_lower or kw in desc_lower for kw in skip_kw):
            log_message(f"\U0001f6ab Skip keyword matched in: {job.get('title')}")
            continue

        # Q2: Fuzzy title match
        if queries and not _fuzzy_title_match(job.get("title", ""), queries):
            log_message(f"\u26a0\ufe0f Title mismatch (fuzzy skip): '{job.get('title')}'")
            continue

        filtered.append(job)

    log_message(f"\u2705 After filters: {len(filtered)}/{len(jobs)} jobs passed")
    return filtered
