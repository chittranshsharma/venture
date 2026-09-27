"""
automation/specialists/greenhouse.py — Greenhouse ATS Specialist (P4.2)
Targeted zero-LLM filler for Greenhouse job boards (boards.greenhouse.io / app.greenhouse.io).
"""

import os
from core.db_manager import log_message
from automation.form_autofiller import _react_safe_fill


async def fill(page, profile: dict) -> bool:
    """
    Directly fills standard Greenhouse application fields and uploads resume.
    Returns True on success, False otherwise.
    """
    log_message("ATS Specialist: Running Greenhouse handler...")
    filled_any = False
    name_parts = profile.get("name", " ").split()
    first_name = name_parts[0] if name_parts else ""
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else (name_parts[0] if name_parts else "")

    fields = {
        "input#first_name, input[name*='first_name']": first_name,
        "input#last_name, input[name*='last_name']": last_name,
        "input#email, input[name*='email']": profile.get("email", ""),
        "input#phone, input[name*='phone']": profile.get("phone", ""),
        "input#job_application_location, input[name*='location']": profile.get("location", ""),
    }

    # Online presence / links
    if profile.get("linkedin"):
        fields["input[name*='linkedin'], input#job_application_answers_attributes_0_text_value"] = profile["linkedin"]
    if profile.get("github"):
        fields["input[name*='github'], input[name*='website']"] = profile["github"]
    if profile.get("portfolio"):
        fields["input[name*='portfolio']"] = profile["portfolio"]

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
            upload = page.locator("input[type='file'], input#resume[type='file']")
            if await upload.count() > 0:
                await upload.first.set_input_files(resume_path)
                log_message(f"Greenhouse Specialist: Uploaded resume ({os.path.basename(resume_path)})")
                filled_any = True
        except Exception as e:
            log_message(f"Greenhouse Specialist: Resume upload error: {e}")

    return filled_any
