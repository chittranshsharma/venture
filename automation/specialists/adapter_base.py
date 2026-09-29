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
from typing import Any, Dict, List, Optional
import core.db_manager as db


class ATSAdapter(ABC):
    platform_name: str = "Generic"

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
