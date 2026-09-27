"""
automation/specialists/lever.py — Lever ATS Specialist (P4.2)
Targeted zero-LLM filler for Lever job boards (jobs.lever.co).
"""

import os
from core.db_manager import log_message
from automation.form_autofiller import _react_safe_fill


async def fill(page, profile: dict) -> bool:
    """
    Directly fills standard Lever application fields and uploads resume.
    Returns True on success, False otherwise.
    """
    log_message("ATS Specialist: Running Lever handler...")
    filled_any = False

    fields = {
        "input[name='name']": profile.get("name", ""),
        "input[name='email']": profile.get("email", ""),
        "input[name='phone']": profile.get("phone", ""),
        "input[name='org']": profile.get("company", "Independent"),
        "input[name='urls[LinkedIn]'], input[name*='LinkedIn']": profile.get("linkedin", ""),
        "input[name='urls[GitHub]'], input[name*='GitHub']": profile.get("github", ""),
        "input[name='urls[Portfolio]'], input[name*='Portfolio']": profile.get("portfolio", ""),
        "input[name='urls[Other]']": profile.get("portfolio", "") or profile.get("github", ""),
    }

    for sel_group, value in fields.items():
        if not value:
            continue
        for sel in sel_group.split(", "):
            try:
                el = page.locator(sel)
                if await el.count() > 0:
                    await _react_safe_fill(page, el.first, value)
                    filled_any = True
                    break
            except Exception:
                continue

    # Resume upload
    resume_path = profile.get("resume_path", "")
    if resume_path and os.path.exists(resume_path):
        try:
            upload = page.locator("input[type='file'][name='resume'], input[type='file']")
            if await upload.count() > 0:
                await upload.first.set_input_files(resume_path)
                log_message(f"Lever Specialist: Uploaded resume ({os.path.basename(resume_path)})")
                filled_any = True
        except Exception as e:
            log_message(f"Lever Specialist: Resume upload error: {e}")

    return filled_any
