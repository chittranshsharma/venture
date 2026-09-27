"""
automation/specialists/ashby.py — Ashby ATS Specialist (P4.2)
Targeted zero-LLM filler for Ashby job boards (jobs.ashbyhq.com).
"""

import os
from core.db_manager import log_message
from automation.form_autofiller import _react_safe_fill


async def fill(page, profile: dict) -> bool:
    """
    Directly fills standard Ashby application fields and uploads resume.
    Returns True on success, False otherwise.
    """
    log_message("ATS Specialist: Running Ashby handler...")
    filled_any = False

    name_parts = profile.get("name", " ").split()
    first_name = name_parts[0] if name_parts else ""
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

    fields = {
        "input[name='name'], input[name='full_name']": profile.get("name", ""),
        "input[name='firstName'], input[name='first_name']": first_name,
        "input[name='lastName'], input[name='last_name']": last_name,
        "input[name='email']": profile.get("email", ""),
        "input[name='phoneNumber'], input[name='phone']": profile.get("phone", ""),
        "input[name*='linkedIn'], input[name*='linkedin']": profile.get("linkedin", ""),
        "input[name*='github'], input[name*='GitHub']": profile.get("github", ""),
        "input[name*='portfolio'], input[name*='website']": profile.get("portfolio", ""),
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
            upload = page.locator("input[type='file']")
            if await upload.count() > 0:
                await upload.first.set_input_files(resume_path)
                log_message(f"Ashby Specialist: Uploaded resume ({os.path.basename(resume_path)})")
                filled_any = True
        except Exception as e:
            log_message(f"Ashby Specialist: Resume upload error: {e}")

    return filled_any
