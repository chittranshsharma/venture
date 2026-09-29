"""
automation/specialists/registry.py — ATS Adapter Registry & Dispatcher.
Detects platform and returns the appropriate specialist adapter (Greenhouse, Lever, Ashby, or Generalist).
"""

from typing import List, Optional
from automation.specialists.adapter_base import ATSAdapter
from automation.specialists.greenhouse_adapter import GreenhouseAdapter
from automation.specialists.lever_adapter import LeverAdapter
from automation.specialists.ashby_adapter import AshbyAdapter
from automation.specialists.generalist_adapter import GeneralistAdapter
from automation.ats_detector import detect_from_url

_ADAPTERS: List[ATSAdapter] = [
    GreenhouseAdapter(),
    LeverAdapter(),
    AshbyAdapter(),
    GeneralistAdapter(),  # Fallback must be last
]


def get_ats_adapter(url: str, dom_text: str = "") -> ATSAdapter:
    """
    Returns the matching specialist ATS adapter for the target URL/DOM.
    Defaults to GeneralistAdapter if no specialized match is found.
    """
    for adapter in _ADAPTERS:
        if adapter.can_handle(url, dom_text):
            return adapter
    return _ADAPTERS[-1]
