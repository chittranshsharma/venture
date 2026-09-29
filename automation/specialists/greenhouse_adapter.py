"""
automation/specialists/greenhouse_adapter.py — Greenhouse ATS Adapter.
Implements inspect, fill, validate, and submit for boards.greenhouse.io.
"""

import os
from typing import Any, Dict, List
from automation.specialists.adapter_base import ATSAdapter
from automation.form_autofiller import _react_safe_fill
import core.db_manager as db


class GreenhouseAdapter(ATSAdapter):
    platform_name = "greenhouse"

    def can_handle(self, url: str, dom_text: str = "") -> bool:
        u = (url or "").lower()
        if "greenhouse.io" in u:
            return True
        if "greenhouse" in (dom_text or "").lower():
            return True
        return False

    async def inspect(self, page) -> Dict[str, Any]:
        info = {
            "has_first_name": await page.locator("input#first_name, input[name*='first_name']").count() > 0,
            "has_last_name": await page.locator("input#last_name, input[name*='last_name']").count() > 0,
            "has_email": await page.locator("input#email, input[name*='email']").count() > 0,
            "has_phone": await page.locator("input#phone, input[name*='phone']").count() > 0,
            "has_resume": await page.locator("input[type='file'], input#resume[type='file']").count() > 0,
            "has_submit": await page.locator("button#submit_app, input[type='submit'], button:has-text('Submit Application')").count() > 0,
        }
        db.log_message(f"GreenhouseAdapter [Inspect]: {info}")
        return info

    async def fill(self, page, package: Any, profile: Dict[str, Any]) -> bool:
        url = page.url
        db.log_message(f"GreenhouseAdapter: Starting fill for {url[:45]}...")
        answers = getattr(package, "form_answers", {}) if package else profile

        # Step 1: Contact Information
        fields = {
            "input#first_name, input[name*='first_name']": answers.get("first_name", ""),
            "input#last_name, input[name*='last_name']": answers.get("last_name", ""),
            "input#email, input[name*='email']": answers.get("email", ""),
            "input#phone, input[name*='phone']": answers.get("phone", ""),
            "input#job_application_location, input[name*='location']": answers.get("location", ""),
            "input[name*='linkedin'], input#job_application_answers_attributes_0_text_value": answers.get("linkedin", ""),
            "input[name*='github'], input[name*='website']": answers.get("github", ""),
            "input[name*='portfolio']": answers.get("portfolio", ""),
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

        # Step 2: Resume Attachment
        resume_path = getattr(package, "resume_path", "") or profile.get("resume_path", "")
        if resume_path and os.path.exists(resume_path):
            try:
                upload = page.locator("input[type='file'], input#resume[type='file']")
                if await upload.count() > 0:
                    await upload.first.set_input_files(resume_path)
                    db.log_message(f"GreenhouseAdapter: Attached resume ({os.path.basename(resume_path)})")
                    db.set_checkpoint(url, "resume_uploaded")
            except Exception as e:
                db.log_message(f"GreenhouseAdapter: Resume attachment warning: {e}")

        # Step 3: Cover Letter (if requested)
        cl_text = getattr(package, "cover_letter_text", "")
        if cl_text:
            try:
                cl_el = page.locator("textarea[name*='cover_letter'], textarea#cover_letter_text")
                if await cl_el.count() > 0:
                    await cl_el.first.fill(cl_text)
                    db.log_message("GreenhouseAdapter: Injected tailored cover letter.")
            except Exception:
                pass

        # Step 4: Work Authorization & Sponsorship Questions
        auth_status = answers.get("work_authorization", "Yes")
        sponsorship = answers.get("sponsorship_required", "No")
        try:
            auth_selects = page.locator("select[name*='authorized'], select[name*='authorization'], select[name*='sponsorship'], select[name*='visa'], select[id*='authorized'], select[id*='sponsorship']")
            auth_count = await auth_selects.count()
            for idx in range(auth_count):
                sel = auth_selects.nth(idx)
                name_attr = (await sel.get_attribute("name") or "").lower()
                id_attr = (await sel.get_attribute("id") or "").lower()
                target_val = "No" if ("sponsorship" in name_attr or "sponsorship" in id_attr or "visa" in name_attr) else "Yes"
                try:
                    await sel.select_option(label=target_val)
                except Exception:
                    try:
                        await sel.select_option(value=target_val.lower())
                    except Exception:
                        pass
        except Exception:
            pass

        db.set_checkpoint(url, "work_authorization")
        return filled_count > 0

    async def validate(self, page) -> Dict[str, Any]:
        missing = []
        for name, sel in [("First Name", "input#first_name"), ("Last Name", "input#last_name"), ("Email", "input#email")]:
            el = page.locator(sel)
            if await el.count() > 0:
                val = await el.first.input_value()
                if not val.strip():
                    missing.append(name)

        is_valid = len(missing) == 0
        db.log_message(f"GreenhouseAdapter [Validate]: valid={is_valid}, missing={missing}")
        return {"valid": is_valid, "missing_required": missing}

    async def submit(self, page, dry_run: bool = False) -> bool:
        url = page.url
        submit_btn = page.locator("button#submit_app, input[type='submit'], button:has-text('Submit Application')")
        if await submit_btn.count() == 0:
            db.log_message("GreenhouseAdapter: Submit button not located.")
            return False

        if dry_run:
            db.log_message(f"[DRY RUN] GreenhouseAdapter: Form valid. Would submit {url[:45]}.")
            db.set_checkpoint(url, "dry_run_validated")
            return True

        db.log_message(f"GreenhouseAdapter: Submitting application for {url[:45]}...")
        await submit_btn.first.click()
        db.set_checkpoint(url, "submitted")
        return True
