"""
automation/specialists/ashby_adapter.py — Ashby ATS Adapter.
Implements inspect, fill, validate, and submit for jobs.ashbyhq.com.
"""

import os
from typing import Any, Dict, List
from automation.specialists.adapter_base import ATSAdapter
from automation.form_autofiller import _react_safe_fill
import core.db_manager as db


class AshbyAdapter(ATSAdapter):
    platform_name = "ashby"

    def can_handle(self, url: str, dom_text: str = "") -> bool:
        u = (url or "").lower()
        if "ashbyhq.com" in u:
            return True
        if "ashby" in (dom_text or "").lower():
            return True
        return False

    async def inspect(self, page) -> Dict[str, Any]:
        info = {
            "has_name": await page.locator("input[name='name'], input[name='full_name'], input[name='firstName']").count() > 0,
            "has_email": await page.locator("input[name='email']").count() > 0,
            "has_phone": await page.locator("input[name='phoneNumber'], input[name='phone']").count() > 0,
            "has_resume": await page.locator("input[type='file']").count() > 0,
            "has_submit": await page.locator("button[type='submit'], button:has-text('Submit Application')").count() > 0,
        }
        db.log_message(f"AshbyAdapter [Inspect]: {info}")
        return info

    async def fill(self, page, package: Any, profile: Dict[str, Any]) -> bool:
        url = page.url
        db.log_message(f"AshbyAdapter: Starting fill for {url[:45]}...")
        answers = getattr(package, "form_answers", {}) if package else profile

        fields = {
            "input[name='name'], input[name='full_name']": answers.get("full_name", ""),
            "input[name='firstName'], input[name='first_name']": answers.get("first_name", ""),
            "input[name='lastName'], input[name='last_name']": answers.get("last_name", ""),
            "input[name='email']": answers.get("email", ""),
            "input[name='phoneNumber'], input[name='phone']": answers.get("phone", ""),
            "input[name*='linkedIn'], input[name*='linkedin']": answers.get("linkedin", ""),
            "input[name*='github'], input[name*='GitHub']": answers.get("github", ""),
            "input[name*='portfolio'], input[name*='website']": answers.get("portfolio", ""),
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

        db.set_checkpoint(url, "fields_filled")

        resume_path = getattr(package, "resume_path", "") or profile.get("resume_path", "")
        if resume_path and os.path.exists(resume_path):
            try:
                upload = page.locator("input[type='file']")
                if await upload.count() > 0:
                    await upload.first.set_input_files(resume_path)
                    db.log_message(f"AshbyAdapter: Attached resume ({os.path.basename(resume_path)})")
                    db.set_checkpoint(url, "resume_uploaded")
            except Exception as e:
                db.log_message(f"AshbyAdapter: Resume upload warning: {e}")

        # Step 3: Work Authorization Questions
        auth_status = answers.get("work_authorization", "Yes")
        sponsorship = answers.get("sponsorship_required", "No")
        try:
            auth_selects = page.locator("select[name*='authorized'], select[name*='authorization'], select[name*='sponsorship'], select[name*='visa']")
            auth_count = await auth_selects.count()
            for idx in range(auth_count):
                sel = auth_selects.nth(idx)
                name_attr = (await sel.get_attribute("name") or "").lower()
                target_val = "No" if ("sponsorship" in name_attr or "visa" in name_attr) else "Yes"
                try:
                    await sel.select_option(label=target_val)
                except Exception:
                    pass
        except Exception:
            pass

        db.set_checkpoint(url, "work_authorization")
        return filled_count > 0

    async def validate(self, page) -> Dict[str, Any]:
        missing = []
        for name, sel in [("Email", "input[name='email']")]:
            el = page.locator(sel)
            if await el.count() > 0:
                val = await el.first.input_value()
                if not val.strip():
                    missing.append(name)

        is_valid = len(missing) == 0
        db.log_message(f"AshbyAdapter [Validate]: valid={is_valid}, missing={missing}")
        return {"valid": is_valid, "missing_required": missing}

    async def submit(self, page, dry_run: bool = False) -> bool:
        url = page.url
        submit_btn = page.locator("button[type='submit'], button:has-text('Submit Application'), button:has-text('Submit')")
        if await submit_btn.count() == 0:
            db.log_message("AshbyAdapter: Submit button not located.")
            return False

        if dry_run:
            db.log_message(f"[DRY RUN] AshbyAdapter: Form valid. Would submit {url[:45]}.")
            db.set_checkpoint(url, "dry_run_validated")
            return True

        db.log_message(f"AshbyAdapter: Submitting application for {url[:45]}...")
        await submit_btn.first.click()
        db.set_checkpoint(url, "submitted")
        return True
