"""
automation/specialists/generalist_adapter.py — Generalist ATS / Job Board Adapter.
Fallback adapter for Indeed, Naukri, LinkedIn, and generic career portals.
"""

from typing import Any, Dict
from automation.specialists.adapter_base import ATSAdapter
from automation.form_autofiller import auto_fill_playwright_form
import core.db_manager as db


class GeneralistAdapter(ATSAdapter):
    platform_name = "generalist"

    def can_handle(self, url: str, dom_text: str = "") -> bool:
        return True  # Fallback for all URLs

    async def inspect(self, page) -> Dict[str, Any]:
        has_inputs = await page.locator("input, textarea, select").count() > 0
        has_submit = await page.locator("button:has-text('Submit'), button:has-text('Apply'), input[type='submit']").count() > 0
        return {"has_inputs": has_inputs, "has_submit": has_submit}

    async def fill(self, page, package: Any, profile: Dict[str, Any]) -> bool:
        url = page.url
        db.log_message(f"GeneralistAdapter: Running auto_fill_playwright_form for {url[:45]}...")
        job_title = getattr(package, "job_snapshot", {}).get("title", "") if package else ""
        company = getattr(package, "job_snapshot", {}).get("company", "") if package else ""

        try:
            await auto_fill_playwright_form(page, job_title=job_title, company=company, job_url=url)
            db.set_checkpoint(url, "fields_filled")
            return True
        except Exception as e:
            db.log_message(f"GeneralistAdapter fill error: {e}")
            return False

    async def validate(self, page) -> Dict[str, Any]:
        return {"valid": True, "missing_required": []}

    async def submit(self, page, dry_run: bool = False) -> bool:
        url = page.url
        if dry_run:
            db.log_message(f"[DRY RUN] GeneralistAdapter: Simulated submission for {url[:45]}.")
            db.set_checkpoint(url, "dry_run_validated")
            return True

        submit_btn = page.locator("button:has-text('Submit'), button:has-text('Apply now'), input[type='submit']")
        if await submit_btn.count() > 0:
            await submit_btn.first.click()
            db.set_checkpoint(url, "submitted")
            return True
        return False
