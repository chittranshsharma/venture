"""
automation/specialists/adapter_base.py — Abstract ATS Specialist Adapter Interface.

Every ATS adapter must implement:
- can_handle(url, dom_text)
- inspect(page)
- fill(page, package, profile)
- validate(page)
- submit(page, dry_run)
"""

from abc import ABC, abstractmethod
import re
from typing import Any, Dict, List, Optional
import core.db_manager as db


class ATSAdapter(ABC):
    platform_name: str = "Generic"

    async def verify_success(self, page) -> bool:
        """Require a visible receipt message, not merely a missing submit button or redirect."""
        try:
            receipt = page.get_by_text(re.compile(
                r"thank you for applying|application (?:has been|was) (?:received|submitted)|"
                r"application submitted|we have received your application", re.I)).first
            await receipt.wait_for(state="visible", timeout=10000)
            return True
        except Exception:
            return False

    async def validate_required_fields(self, page) -> Dict[str, Any]:
        """Use browser constraint validation for required inputs, files, groups, and selects."""
        return await page.evaluate("""() => {
            const missing = Array.from(document.querySelectorAll('input, textarea, select'))
                .filter(el => !el.disabled && el.willValidate && !el.checkValidity())
                .map(el => el.labels?.[0]?.innerText?.trim() || el.name || el.id || 'Required field');
            const custom = Array.from(document.querySelectorAll('[aria-required="true"]'))
                .filter(el => el.getAttribute('aria-disabled') !== 'true' && el.offsetParent !== null
                    && !String(el.value || el.getAttribute('aria-valuetext') || '').trim())
                .map(el => el.getAttribute('aria-label') || el.name || el.id || 'Required custom field');
            return {valid: missing.length === 0 && custom.length === 0,
                    missing_required: [...new Set([...missing, ...custom])]};
        }""")

    async def fill_work_authorization(self, page, answers: Dict[str, Any]) -> bool:
        """Fill legal yes/no fields only from explicit answers; ambiguous visa questions require review."""
        fields = page.locator("select[name*='authorized' i], select[name*='authorization' i], "
                              "select[name*='sponsorship' i], select[name*='visa' i], "
                              "select[id*='authorized' i], select[id*='sponsorship' i]")
        valid = True
        for index in range(await fields.count()):
            field = fields.nth(index)
            hint = ((await field.get_attribute("name") or "") + " " + (await field.get_attribute("id") or "")).lower()
            key = "sponsorship_required" if "sponsorship" in hint else (
                "work_authorization" if "authorized" in hint or "authorization" in hint else None)
            answer = answers.get(key) if key else None
            if isinstance(answer, bool):
                answer = "Yes" if answer else "No"
            if str(answer).strip().lower() not in ("yes", "no"):
                valid = False
                continue
            label = str(answer).strip().capitalize()
            try:
                await field.select_option(label=label)
            except Exception:
                try:
                    await field.select_option(value=label.lower())
                except Exception:
                    valid = False
        return valid

    @abstractmethod
    def can_handle(self, url: str, dom_text: str = "") -> bool:
        """Return True if this adapter can process the given target URL or DOM."""
        pass

    @abstractmethod
    async def inspect(self, page) -> Dict[str, Any]:
        """
        Inspect the page to discover standard fields, required inputs,
        file upload widgets, and submission controls.
        """
        pass

    @abstractmethod
    async def fill(self, page, package: Any, profile: Dict[str, Any]) -> bool:
        """
        Fill all standard and custom application fields using the prepared package
        and candidate profile. Records checkpoints as fields are completed.
        """
        pass

    @abstractmethod
    async def validate(self, page) -> Dict[str, Any]:
        """
        Validate filled inputs before submission.
        Returns a dict: {"valid": bool, "missing_required": list, "errors": list}
        """
        pass

    @abstractmethod
    async def submit(self, page, dry_run: bool = False) -> bool:
        """
        Submit the completed application form.
        If dry_run is True, simulates submission without clicking the final submit action.
        """
        pass
