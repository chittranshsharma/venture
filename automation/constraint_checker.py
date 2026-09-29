"""
automation/constraint_checker.py — 3-Tier Constraint & Evaluation Engine.

Tier 1: Hard Invariants (Zero-LLM deterministic rejection for legal/security/location blockers)
Tier 2: Soft Constraints (Graduated penalties for YOE gaps or secondary skill deficits)
Tier 3: Stretch Signals (Positive boosts for high project/domain alignment offsetting seniority)
"""

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class Penalty:
    type: str
    value: float
    evidence: str


@dataclass
class StretchSignal:
    type: str
    value: float
    evidence: str


@dataclass
class ConstraintResult:
    hard_block: bool
    hard_reason: str = ""
    penalties: List[Penalty] = field(default_factory=list)
    stretch_signals: List[StretchSignal] = field(default_factory=list)

    @property
    def total_penalty(self) -> float:
        return sum(p.value for p in self.penalties)

    @property
    def total_stretch_boost(self) -> float:
        return sum(s.value for s in self.stretch_signals)

    @property
    def net_adjustment(self) -> float:
        """Net score modifier (positive boosts minus penalties)."""
        return self.total_stretch_boost - self.total_penalty

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hard_block": self.hard_block,
            "hard_reason": self.hard_reason,
            "penalties": [{"type": p.type, "value": p.value, "evidence": p.evidence} for p in self.penalties],
            "stretch_signals": [{"type": s.type, "value": s.value, "evidence": s.evidence} for s in self.stretch_signals],
            "net_adjustment": self.net_adjustment,
        }


def evaluate_constraints(title: str, text: str, cfg: Dict[str, Any]) -> ConstraintResult:
    """
    Evaluates a job against the 3-tier constraint model.
    """
    qa_vault = cfg.get("candidate", {}).get("qa_vault", {})
    settings = cfg.get("settings", {})
    try:
        cand_yoe = float(qa_vault.get("experience_years", 1))
    except (ValueError, TypeError):
        cand_yoe = 1.0

    t = (text or "").lower()
    tit = (title or "").lower()

    # =========================================================================
    # TIER 1: HARD INVARIANTS (Instant Skip)
    # =========================================================================

    # 1. Citizenship / Government Security Clearance
    if re.search(r"\b(us citizen only|u\.s\. citizen only|active ts/sci|security clearance required|green card required)\b", t):
        return ConstraintResult(hard_block=True, hard_reason="citizenship_or_clearance_required")

    # 2. Hard PhD Requirement (excluding BS/MS equivalence)
    if re.search(r"\b(phd|doctorate)\b[^.]{0,30}\b(required|must)\b", t):
        phd_pos = t.find("phd")
        context = t[max(0, phd_pos - 100):min(len(t), phd_pos + 200)]
        if "bachelor" not in context and "master" not in context:
            return ConstraintResult(hard_block=True, hard_reason="phd_required")

    # 3. Location Invariant (Strict Onsite when user preference is Remote)
    user_pref = qa_vault.get("work_preference") or settings.get("location_type")
    if user_pref == "Remote":
        if re.search(r"\bon[- ]?site\b", t) and not re.search(r"\b(remote|hybrid)\b", t):
            return ConstraintResult(hard_block=True, hard_reason="onsite_only_when_remote_required")

    # 4. Blacklisted / Skip Keywords in Title Only
    skip_kw = [k.strip().lower() for k in settings.get("skip_keywords", []) if k.strip()]
    for kw in skip_kw:
        if kw in tit:
            return ConstraintResult(hard_block=True, hard_reason=f"skip_keyword_in_title={kw}")

    # =========================================================================
    # TIER 2: SOFT CONSTRAINTS (Graduated Score Penalties)
    # =========================================================================
    penalties: List[Penalty] = []

    # YOE Extraction: filter out unrealistic numbers (>15 is usually company history e.g. "60 years in business")
    # and restrict regex to candidate requirements context
    yoe_matches = re.findall(
        r"(\d{1,2})\s*(?:\+|-\s*\d{1,2})?\s*years?\s*(?:of\s+)?(?:relevant\s+|professional\s+|software\s+|hands-on\s+)?experience",
        t
    )
    # Exclude typical company history numbers (> 15)
    valid_yoes = [int(x) for x in yoe_matches if 1 <= int(x) <= 15]

    if valid_yoes:
        min_yoe = min(valid_yoes)
        if min_yoe > cand_yoe:
            yoe_diff = min_yoe - cand_yoe
            # Scale penalty: 5 pts per missing year, capped at 25 pts
            pen_val = min(25.0, round(yoe_diff * 5.0, 1))
            penalties.append(Penalty(
                type="YOE_GAP",
                value=pen_val,
                evidence=f"Requested {min_yoe}+ YOE vs candidate {cand_yoe} YOE"
            ))

    # =========================================================================
    # TIER 3: STRETCH SIGNALS (Compensating Boosts)
    # =========================================================================
    stretch_signals: List[StretchSignal] = []

    # Dense project / core language alignment (Python, C++, IoT, Embedded, Computer Vision)
    core_anchors = ["python", "c++", "iot", "mqtt", "esp32", "computer vision", "opencv", "flask"]
    hits = [a for a in core_anchors if a in t]
    if len(hits) >= 2:
        boost_val = min(15.0, len(hits) * 3.0)
        stretch_signals.append(StretchSignal(
            type="PROJECT_ALIGNMENT",
            value=boost_val,
            evidence=f"Strong overlap with core project competencies: {', '.join(hits)}"
        ))

    return ConstraintResult(
        hard_block=False,
        penalties=penalties,
        stretch_signals=stretch_signals,
    )


# Backwards compatibility helper
def check_constraints(title: str, text: str, cfg: Dict[str, Any]) -> Tuple[bool, str]:
    res = evaluate_constraints(title, text, cfg)
    return (not res.hard_block, res.hard_reason)
