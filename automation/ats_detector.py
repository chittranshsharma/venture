"""
automation/ats_detector.py — ATS Platform Detector (P4.1)
Identifies the Applicant Tracking System (ATS) platform from URL patterns and DOM signatures.
Supports Greenhouse, Lever, Ashby, Workday, BambooHR, SmartRecruiters, Indeed, LinkedIn, Naukri.
"""

import logging

logger = logging.getLogger(__name__)

ATS_URL_PATTERNS = {
    "greenhouse":      ["boards.greenhouse.io", "app.greenhouse.io"],
    "lever":           ["jobs.lever.co"],
    "ashby":           ["jobs.ashbyhq.com"],
    "workday":         [".myworkdayjobs.com"],
    "bamboohr":        [".bamboohr.com/jobs"],
    "smartrecruiters": ["jobs.smartrecruiters.com"],
    "indeed":          ["indeed.com"],
    "linkedin":        ["linkedin.com"],
    "naukri":          ["naukri.com"],
}


def detect_from_url(url: str) -> str | None:
    """Return ATS name if URL matches known ATS URL patterns, else None."""
    if not url or not isinstance(url, str):
        return None
    url_lower = url.lower()
    for name, patterns in ATS_URL_PATTERNS.items():
        if any(p in url_lower for p in patterns):
            return name
    return None


async def detect_from_dom(page) -> str | None:
    """Return ATS name by probing page DOM for characteristic platform signatures."""
    if not page:
        return None
    DOM_SIGNATURES = {
        "greenhouse": "div#application, form[action*='greenhouse'], div#main.job-board",
        "lever":      ".postings-sections, div.template-page, form#job-application-form",
        "ashby":      "div[data-ashby-widget], div#ashby-application-form",
        "workday":    "div[data-automation-id='applicationPage'], div[data-automation-id='jobPostingPage']",
        "bamboohr":   ".BambooHR-ATS-Jobs-List, #BambooHR-ATS-Job",
        "smartrecruiters": "form#application-form, div.smart-recruiters",
    }
    for name, selector in DOM_SIGNATURES.items():
        try:
            if await page.locator(selector).count() > 0:
                return name
        except Exception:
            continue
    return None


async def detect_ats(page, url: str = None) -> str | None:
    """Convenience helper: checks URL first, then falls back to DOM inspection."""
    target_url = url or (page.url if page else "")
    ats = detect_from_url(target_url)
    if ats:
        return ats
    if page:
        return await detect_from_dom(page)
    return None
