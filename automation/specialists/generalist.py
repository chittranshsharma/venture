"""
automation/specialists/generalist.py — Universal ATS Fallback & Action Trace Recorder (P4.2 & P4.3)
Universal fallback filler for unknown career portals. Records the action trace of filled
fields and triggers the Self-Compiling ATS Specialist Generator (generator.py) upon success.
"""

import os
import urllib.parse
from core.db_manager import log_message
from automation.form_autofiller import _react_safe_fill, _match_vault
from automation.ats_detector import detect_from_url, detect_from_dom


async def fill(page, profile: dict) -> bool:
    """
    Fills general application forms by inspecting input fields, recording
    an action trace, and optionally compiling a new ATS specialist.
    """
    log_message("ATS Specialist: Running Generalist fallback handler...")
    action_trace = []
    filled_count = 0

    try:
        # Detect ATS name for future compilation (from URL or domain)
        page_url = page.url if page else ""
        ats_name = detect_from_url(page_url) or await detect_from_dom(page)
        if not ats_name and page_url:
            domain = urllib.parse.urlparse(page_url).netloc.lower()
            parts = domain.split(".")
            ats_name = parts[-2] if len(parts) >= 2 and parts[-2] not in ("co", "com", "org", "net", "io") else parts[0]
            ats_name = "".join(c for c in ats_name if c.isalnum() or c == "_")

        # 1. Fill Text & Email Inputs
        inputs = await page.locator("input:visible, textarea:visible").all()
        for field in inputs:
            try:
                f_type = (await field.get_attribute("type") or "text").lower()
                if f_type in ("hidden", "submit", "button", "checkbox", "radio", "file"):
                    continue

                # Check if already filled
                val = await field.input_value()
                if val and val.strip():
                    continue

                # Determine label / field identity
                name_attr = await field.get_attribute("name") or ""
                id_attr = await field.get_attribute("id") or ""
                placeholder = await field.get_attribute("placeholder") or ""
                aria_label = await field.get_attribute("aria-label") or ""

                hint = f"{name_attr} {id_attr} {placeholder} {aria_label}".lower()
                fill_val = None
                matched_label = ""

                # Direct profile matching
                if any(k in hint for k in ["first_name", "firstname", "first name"]):
                    name_parts = profile.get("name", " ").split()
                    fill_val = name_parts[0] if name_parts else ""
                    matched_label = "first_name"
                elif any(k in hint for k in ["last_name", "lastname", "last name", "surname"]):
                    name_parts = profile.get("name", " ").split()
                    fill_val = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
                    matched_label = "last_name"
                elif any(k in hint for k in ["full_name", "fullname", "your name", "candidate name", "applicant name", "name"]):
                    fill_val = profile.get("name", "")
                    matched_label = "name"
                elif any(k in hint for k in ["email", "e-mail"]):
                    fill_val = profile.get("email", "")
                    matched_label = "email"
                elif any(k in hint for k in ["phone", "mobile", "cell", "contact"]):
                    fill_val = profile.get("phone", "")
                    matched_label = "phone"
                elif any(k in hint for k in ["linkedin"]):
                    fill_val = profile.get("linkedin", "")
                    matched_label = "linkedin"
                elif any(k in hint for k in ["github"]):
                    fill_val = profile.get("github", "")
                    matched_label = "github"
                elif any(k in hint for k in ["portfolio", "website"]):
                    fill_val = profile.get("portfolio", "")
                    matched_label = "portfolio"
                else:
                    vault_val = _match_vault(hint)
                    if vault_val:
                        fill_val = str(vault_val)
                        matched_label = hint[:30]

                if fill_val:
                    await _react_safe_fill(page, field, fill_val)
                    filled_count += 1
                    selector = f"input[name='{name_attr}']" if name_attr else (f"#{id_attr}" if id_attr else f"input[placeholder='{placeholder}']")
                    action_trace.append({
                        "action": "fill",
                        "selector": selector,
                        "field": matched_label,
                        "value": fill_val
                    })
            except Exception:
                continue

        # 2. Upload Resume
        resume_path = profile.get("resume_path", "")
        if resume_path and os.path.exists(resume_path):
            file_inputs = await page.locator("input[type='file']").all()
            for fi in file_inputs:
                try:
                    await fi.set_input_files(resume_path)
                    log_message(f"Generalist: Uploaded resume ({os.path.basename(resume_path)})")
                    filled_count += 1
                    action_trace.append({
                        "action": "upload",
                        "selector": "input[type='file']",
                        "field": "resume"
                    })
                    break
                except Exception:
                    continue

        # 3. If successfully filled and action trace recorded, trigger Self-Compiling Generator (P4.3)
        if filled_count >= 2 and action_trace and ats_name:
            # Don't overwrite the core built-in specialists
            if ats_name not in ("greenhouse", "lever", "ashby", "generalist"):
                try:
                    from automation.specialists.generator import compile_specialist
                    compile_specialist(ats_name, action_trace)
                except Exception as ge:
                    log_message(f"Generalist: Self-compilation attempt failed: {ge}")

        return filled_count > 0

    except Exception as e:
        log_message(f"Generalist handler error: {e}")
        return False
