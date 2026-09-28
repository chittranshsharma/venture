"""
automation/career_crawler.py — Direct Company Career Page Crawler
Scrapes raw company careers pages (career.company.com) for open roles,
supporting Greenhouse, Lever, Ashby JSON APIs and a generic HTML fallback.
Returns jobs in the same dict format as job_scraper.fast_scrape_jobs.
"""

import re
import json
import urllib.request
import urllib.parse
from core.db_manager import log_message


_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def _fetch(url: str, timeout: int = 12) -> str:
    """Fetch URL, return text. Raises on network error."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json, text/html"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="ignore")


# ── Platform-specific parsers ───────────────────────────────────────────────

def _try_greenhouse(url: str, company: str) -> list | None:
    """
    Greenhouse boards: boards.greenhouse.io/<slug>/jobs  OR
    company passes their board slug via a careers page embed.
    We detect the Greenhouse slug from the URL or HTML, then hit the JSON API.
    """
    slug = None
    # Direct boards.greenhouse.io URL
    m = re.search(r'boards\.greenhouse\.io/([^/?"#]+)', url)
    if m:
        slug = m.group(1)
    if not slug:
        return None

    api = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    try:
        data = json.loads(_fetch(api))
    except Exception:
        return None

    results = []
    for job in data.get("jobs", []):
        results.append({
            "title":       job.get("title", ""),
            "company":     company,
            "location":    job.get("location", {}).get("name", ""),
            "platform":    "CareerPage",
            "url":         job.get("absolute_url", ""),
            "description": job.get("content", "")[:800],
        })
    return results


def _try_lever(url: str, company: str) -> list | None:
    """
    Lever jobs: jobs.lever.co/<slug>  — JSON API at same path with ?mode=json
    """
    m = re.search(r'jobs\.lever\.co/([^/?"#]+)', url)
    if not m:
        return None
    slug = m.group(1)
    api = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    try:
        data = json.loads(_fetch(api))
    except Exception:
        return None

    results = []
    for job in data if isinstance(data, list) else []:
        results.append({
            "title":       job.get("text", ""),
            "company":     company,
            "location":    job.get("categories", {}).get("location", ""),
            "platform":    "CareerPage",
            "url":         job.get("hostedUrl", ""),
            "description": job.get("descriptionPlain", "")[:800],
        })
    return results


def _try_ashby(url: str, company: str) -> list | None:
    """
    Ashby: jobs.ashbyhq.com/<slug> — GraphQL JSON API
    """
    m = re.search(r'jobs\.ashbyhq\.com/([^/?"#]+)', url)
    if not m:
        return None
    slug = m.group(1)
    api = f"https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobBoardWithTeams"
    payload = json.dumps({
        "operationName": "ApiJobBoardWithTeams",
        "variables": {"organizationHostedJobsPageName": slug},
        "query": "query ApiJobBoardWithTeams($organizationHostedJobsPageName:String!){jobBoard(organizationHostedJobsPageName:$organizationHostedJobsPageName){jobPostings{id title locationName jobLocation{locationName} externalLink descriptionHtml}}}"
    }).encode()
    try:
        req = urllib.request.Request(
            api, data=payload,
            headers={"User-Agent": _UA, "Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode("utf-8", errors="ignore"))
    except Exception:
        return None

    postings = (data.get("data") or {}).get("jobBoard", {}).get("jobPostings", [])
    results = []
    for job in postings:
        job_url = job.get("externalLink") or f"https://jobs.ashbyhq.com/{slug}/{job.get('id', '')}"
        results.append({
            "title":       job.get("title", ""),
            "company":     company,
            "location":    (job.get("jobLocation") or {}).get("locationName") or job.get("locationName", ""),
            "platform":    "CareerPage",
            "url":         job_url,
            "description": re.sub(r"<[^>]+>", " ", job.get("descriptionHtml", ""))[:800],
        })
    return results


def _try_workday(url: str, company: str) -> list | None:
    """
    Workday: <company>.wd*.myworkdayjobs.com/<tenant>/jobs — JSON API
    """
    m = re.match(r'(https?://[^/]+\.wd\d+\.myworkdayjobs\.com/[^/]+)', url)
    if not m:
        return None
    base = m.group(1).rstrip("/")
    api = f"{base}/jobs?limit=20&offset=0&format=json"
    try:
        data = json.loads(_fetch(api))
    except Exception:
        return None

    results = []
    for job in data.get("jobPostings", []):
        results.append({
            "title":       job.get("title", ""),
            "company":     company,
            "location":    job.get("locationsText", ""),
            "platform":    "CareerPage",
            "url":         f"{base}{job.get('externalPath', '')}",
            "description": job.get("bulletFields", [""])[0][:800] if job.get("bulletFields") else "",
        })
    return results


def _try_smartrecruiters(url: str, company: str) -> list | None:
    """
    SmartRecruiters: careers.smartrecruiters.com/<slug> or jobs.smartrecruiters.com/<slug>
    API: https://api.smartrecruiters.com/v1/companies/{slug}/postings
    """
    m = re.search(r'(?:careers|jobs)\.smartrecruiters\.com/([^/?"#]+)', url)
    if not m:
        return None
    slug = m.group(1)
    api = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
    try:
        data = json.loads(_fetch(api))
    except Exception:
        return None

    results = []
    for job in data.get("content", []):
        loc = job.get("location", {})
        loc_str = ", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country")]))
        job_id = job.get("id", "")
        results.append({
            "title":       job.get("name", ""),
            "company":     company or slug.capitalize(),
            "location":    loc_str,
            "platform":    "CareerPage",
            "url":         f"https://jobs.smartrecruiters.com/{slug}/{job_id}" if job_id else url,
            "description": f"{job.get('name', '')} at {company or slug}",
        })
    return results


def _try_bamboohr(url: str, company: str) -> list | None:
    """
    BambooHR: <subdomain>.bamboohr.com/careers or /jobs
    API: https://<subdomain>.bamboohr.com/careers/list
    """
    m = re.search(r'([a-zA-Z0-9\-]+)\.bamboohr\.com', url)
    if not m:
        return None
    slug = m.group(1)
    api = f"https://{slug}.bamboohr.com/careers/list"
    try:
        data = json.loads(_fetch(api))
    except Exception:
        return None

    results = []
    postings = data.get("result", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    for job in postings:
        loc = job.get("location", {})
        loc_str = loc.get("city", "") if isinstance(loc, dict) else str(loc)
        job_id = job.get("id", "")
        results.append({
            "title":       job.get("jobOpeningName", "") or job.get("title", ""),
            "company":     company or slug.capitalize(),
            "location":    loc_str,
            "platform":    "CareerPage",
            "url":         f"https://{slug}.bamboohr.com/careers/{job_id}" if job_id else url,
            "description": f"{job.get('jobOpeningName', '')} at {company or slug}",
        })
    return results


def _generic_html_parse(url: str, company: str) -> list:
    """
    Fallback: fetch the career page HTML and extract <a> links that look like job postings.
    Heuristic: anchor text >= 4 words and href contains /job/ /jobs/ /careers/ /position/ /opening/
    """
    try:
        html = _fetch(url)
    except Exception as e:
        log_message(f"CareerCrawler: Could not fetch {url}: {e}")
        return []

    base = urllib.parse.urlparse(url)
    base_url = f"{base.scheme}://{base.netloc}"

    results = []
    seen = set()
    # Find all anchors
    for m in re.finditer(r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL):
        href = m.group(1).strip()
        text = re.sub(r"<[^>]+>", "", m.group(2)).strip()

        # Filter: href must look like a job link
        if not any(kw in href.lower() for kw in ["/job", "/career", "/position", "/opening", "/role", "/apply", "/posting"]):
            continue

        # Text must have substance (not just "Click here" etc)
        if len(text.split()) < 3 or len(text) > 120:
            continue

        # Build absolute URL
        if href.startswith("http"):
            full_url = href
        elif href.startswith("/"):
            full_url = base_url + href
        else:
            continue

        if full_url in seen:
            continue
        seen.add(full_url)

        results.append({
            "title":       text,
            "company":     company,
            "location":    "",
            "platform":    "CareerPage",
            "url":         full_url,
            "description": f"{text} at {company}",
        })

        if len(results) >= 25:
            break

    return results


# ── Public API ──────────────────────────────────────────────────────────────

def crawl_company_career_page(url: str, company: str = "") -> list:
    """
    Crawl a single company career page URL.
    Tries known ATS platforms first (Greenhouse → Lever → Ashby → Workday → SmartRecruiters → BambooHR),
    then falls back to generic HTML parsing.

    Returns list of job dicts compatible with job_scraper format.
    """
    if not company:
        # Derive company name from hostname
        host = urllib.parse.urlparse(url).netloc
        company = host.replace("www.", "").split(".")[0].capitalize()

    log_message(f"🏢 CareerCrawler: Scanning {company} ({url})")

    for parser in [_try_greenhouse, _try_lever, _try_ashby, _try_workday, _try_smartrecruiters, _try_bamboohr]:
        try:
            result = parser(url, company)
            if result is not None:
                log_message(f"🏢 CareerCrawler: {parser.__name__} found {len(result)} roles at {company}")
                return result
        except Exception as e:
            log_message(f"🏢 CareerCrawler: {parser.__name__} error for {company}: {e}")

    # Generic fallback
    result = _generic_html_parse(url, company)
    log_message(f"🏢 CareerCrawler: HTML fallback found {len(result)} roles at {company}")
    return result


def crawl_all_company_pages(pages: list) -> list:
    """
    Crawl multiple company career pages.
    pages: list of dicts {"url": str, "company": str} or plain URL strings.
    Returns flat list of all discovered jobs.
    """
    all_jobs = []
    for entry in pages:
        if isinstance(entry, str):
            url, company = entry, ""
        else:
            url = entry.get("url", "")
            company = entry.get("company", "")
        if not url:
            continue
        try:
            jobs = crawl_company_career_page(url, company)
            all_jobs.extend(jobs)
        except Exception as e:
            log_message(f"🏢 CareerCrawler: Error crawling {url}: {e}")
    return all_jobs
