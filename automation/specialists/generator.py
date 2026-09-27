"""
automation/specialists/generator.py — Self-Compiling ATS Specialist Generator (P4.3)
Converts a successful generalist action trace into a typed, validated, and security-scanned
Playwright Python specialist module.
"""

import ast
import json
from pathlib import Path
from automation.llm_evaluator import query_ai_model
from core.db_manager import log_message

FORBIDDEN_PATTERNS = ["os.system", "subprocess", "eval(", "exec(", "__import__", "open(", "socket", "shutil"]


def compile_specialist(ats_name: str, action_trace: list[dict]) -> bool:
    """
    Convert a successful generalist action trace into a typed Python specialist.
    Returns True if saved, False if validation failed.
    """
    if not ats_name or not action_trace:
        return False

    log_message(f"Self-Learning: Compiling new specialist for ATS '{ats_name}' from {len(action_trace)} action trace(s)...")

    prompt = f"""Convert this action trace into a Playwright Python module for '{ats_name}'.
Trace: {json.dumps(action_trace, indent=2)}

Requirements:
- Signature: async def fill(page, profile: dict) -> bool
- Imports: only from playwright.async_api and automation.form_autofiller (for _react_safe_fill)
- Return True on success, False on failure
- Use profile fields (e.g. profile.get("name"), profile.get("email"), profile.get("phone"), profile.get("resume_path"))
- Never use: os, subprocess, eval, exec, __import__, socket, shutil
Output ONLY valid Python. No explanation."""

    code = query_ai_model(prompt)
    if not code:
        log_message(f"Specialist compilation failed: Empty AI response for '{ats_name}'.")
        return False

    # Clean markdown fences if any
    clean_code = code.strip()
    if clean_code.startswith("```"):
        lines = clean_code.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        clean_code = "\n".join(lines).strip()

    # Validate syntax
    try:
        ast.parse(clean_code)
    except SyntaxError as e:
        log_message(f"Specialist compilation failed for '{ats_name}': SyntaxError: {e}")
        return False

    # Security scan
    if any(pat in clean_code for pat in FORBIDDEN_PATTERNS):
        log_message(f"Specialist compilation rejected for '{ats_name}': Forbidden security pattern detected.")
        return False

    # Save (not executed until next run)
    try:
        out = Path(__file__).resolve().parent / f"{ats_name}.py"
        out.write_text(clean_code, encoding="utf-8")
        log_message(f"✨ Self-Compiled Specialist saved: {out.name} (Future encounters with '{ats_name}' are zero-cost!)")
        return True
    except Exception as e:
        log_message(f"Could not save compiled specialist for '{ats_name}': {e}")
        return False
