"""
automation/specialists/lever_adapter.py — Lever ATS Adapter.
Implements inspect, fill, validate, and submit for jobs.lever.co.
"""

import os
from typing import Any, Dict, List
from automation.specialists.adapter_base import ATSAdapter
from automation.form_autofiller import _react_safe_fill
import core.db_manager as db


class LeverAdapter(ATSAdapter):
    platform_name = "lever"

    def can_handle(self, url: str, dom_text: str = "") -> bool:
        u = (url or "").lower()
        if "lever.co" in u:
            return True
        if "lever" in (dom_text or "").lower():
            return True
        return False

    async def inspect(self, page) -> Dict[str, Any]:
        info = {
            "has_name": await page.locator("input[name='name']").count() > 0,
            "has_email": await page.locator("input[name='email']").count() > 0,
            "has_phone": await page.locator("input[name='phone']").count() > 0,
            "has_resume": await page.locator("input[type='file'][name='resume'], input[type='file']").count() > 0,
            "has_submit": await page.locator("button#btn-submit, button:has-text('Submit Application')").count() > 0,
        }
        db.log_message(f"LeverAdapter [Inspect]: {info}")
        return info

    async def fill(self, page, package: Any, profile: Dict[str, Any]) -> bool:
        url = page.url
        db.log_message(f"LeverAdapter: Starting fill for {url[:45]}...")
        answers = getattr(package, "form_answers", {}) if package else profile

        fields = {
            "input[name='name']": answers.get("full_name") or f"{answers.get('first_name', '')} {answers.get('last_name', '')}".strip(),
            "input[name='email']": answers.get("email", ""),
            "input[name='phone']": answers.get("phone", ""),
            "input[name='org']": profile.get("company", "Independent"),
            "input[name='urls[LinkedIn]'], input[name*='LinkedIn']": answers.get("linkedin", ""),
            "input[name='urls[GitHub]'], input[name*='GitHub']": answers.get("github", ""),
            "input[name='urls[Portfolio]'], input[name*='Portfolio']": answers.get("portfolio", ""),
            "input[name='urls[Other]']": answers.get("portfolio", "") or answers.get("github", ""),
        }

        filled_count = 0
        for sel_group, val in fields.items():
            if not val:
                continue
            for sel in sel_group.split(", "):
                try:
                    el = page.locator(sel)
                    if await el.count() > 0:
                        await _react_safe_fill(page, el.first, str(val))
                        filled_count += 1
                        break
                except Exception:
                    continue


        resume_path = getattr(package, "resume_path", "") or profile.get("resume_path", "")
        if resume_path and os.path.exists(resume_path):
            try:
                upload = page.locator("input[type='file'][name='resume'], input[type='file']")
                if await upload.count() > 0:
                    await upload.first.set_input_files(resume_path)
                    db.log_message(f"LeverAdapter: Attached resume ({os.path.basename(resume_path)})")
            except Exception as e:
                db.log_message(f"LeverAdapter: Resume upload warning: {e}")

        # Additional information / cover letter
        cl_text = getattr(package, "cover_letter_text", "")
        if cl_text:
            try:
                comments = page.locator("textarea[name='comments'], textarea[name*='additional']")
                if await comments.count() > 0:
                    await comments.first.fill(cl_text)
                    db.log_message("LeverAdapter: Injected cover letter into additional info.")
            except Exception:
                pass

        # Step 4: Work Authorization & Sponsorship Questions
        legal_answers_complete = await self.fill_work_authorization(page, answers)
        return filled_count > 0 and legal_answers_complete

    async def validate(self, page) -> Dict[str, Any]:
        missing = []
        for name, sel in [("Name", "input[name='name']"), ("Email", "input[name='email']")]:
            el = page.locator(sel)
            if await el.count() > 0:
                val = await el.first.input_value()
                if not val.strip():
                    missing.append(name)

        is_valid = len(missing) == 0
        db.log_message(f"LeverAdapter [Validate]: valid={is_valid}, missing={missing}")
        browser_validation = await self.validate_required_fields(page)
        missing.extend(browser_validation.get("missing_required", []))
        return {"valid": is_valid and browser_validation.get("valid") is True, "missing_required": missing}

    async def submit(self, page, dry_run: bool = False) -> bool:
        url = page.url
        submit_btn = page.locator("button#btn-submit, button:has-text('Submit Application'), button:has-text('Apply')")
        if await submit_btn.count() == 0:
            db.log_message("LeverAdapter: Submit button not located.")
            return False

        if dry_run:
            db.log_message(f"[DRY RUN] LeverAdapter: Form valid. Would submit {url[:45]}.")
            return True

        db.log_message(f"LeverAdapter: Submitting application for {url[:45]}...")
        await submit_btn.first.click()
        return True
