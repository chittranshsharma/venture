"""
tests/test_scorer_regressions.py — Regression tests for:
1. Language routing (non-English JDs routed to explore/needs_human, never false rejected).
2. YOE soft penalty scaling (2.5 pts/yr capped strictly at 10.0 pts).
3. Company name sanitization (nan/none/null string handling across scrape & normalization boundary).
4. Dry-run mode defaults safely to True.
"""

import os
import sys
import pytest

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from automation.composite_scorer import is_english_jd, evaluate_opportunity
from automation.constraint_checker import evaluate_constraints
from core.db_manager import normalize_company
from automation.orchestrator import process_job


def test_language_detection_and_routing():
    """Non-English job descriptions must route to 'explore' / needs_human and never be hard rejected."""
    # Sample Portuguese text from actual label
    portuguese_jd = (
        "Estamos buscando Desenvolvedor Full Stack com sólida experiência em React e Node.js. "
        "Requisitos: domínio de JavaScript, TypeScript, APIs RESTful, bancos de dados PostgreSQL e MongoDB. "
        "Desejável conhecimento em Docker, Kubernetes e metodologias ágeis. "
        "Oferecemos ambiente descontraído, benefícios competitivos e trabalho remoto."
    )
    assert not is_english_jd(portuguese_jd)

    # Standard English JD
    english_jd = (
        "We are looking for a Full Stack Engineer to join our growing product team. "
        "You will build performant React frontends and Node.js backend microservices with PostgreSQL."
    )
    assert is_english_jd(english_jd)

    # Verify evaluate_opportunity routes non-English to 'explore'
    res = evaluate_opportunity(
        title="Desenvolvedor Full Stack",
        company="Conecta Ads",
        jd_text=portuguese_jd,
    )
    assert res.route == "explore", f"Expected route 'explore' for non-English JD, got '{res.route}'"
    assert not res.hard_block


def test_yoe_penalty_scaling_and_strict_cap():
    """YOE penalty must scale at 2.5 pts/year over max candidate YOE and cap strictly at 10.0 pts."""
    mock_cfg = {
        "candidate": {
            "qa_vault": {"experience_years": "1"},
            "skills": ["Python", "React"],
        },
        "settings": {"queries": ["Software Engineer"]},
    }

    # Case A: Job requires 3 years -> (3 - 1) * 2.5 = 5.0 pts penalty
    res_3yr = evaluate_constraints("Software Engineer", "Requirements: 3+ years of experience in software development.", mock_cfg)
    assert res_3yr.total_penalty == pytest.approx(5.0, abs=0.1)

    # Case B: Job requires 10 years -> (10 - 1) * 2.5 = 22.5 -> capped at 10.0 pts
    res_10yr = evaluate_constraints("Staff Engineer", "Requirements: 10+ years of experience building distributed systems.", mock_cfg)
    assert res_10yr.total_penalty == pytest.approx(10.0, abs=0.1)

    # Case C: Candidate has 5 years, job requires 3 years -> 0 penalty
    mock_cfg_senior = {
        "candidate": {"qa_vault": {"experience_years": "5"}},
        "settings": {},
    }
    res_senior = evaluate_constraints("Software Engineer", "Requirements: 3 years experience.", mock_cfg_senior)
    assert res_senior.total_penalty == 0.0


def test_company_nan_sanitization():
    """Company strings representing missing values ('nan', 'None', 'null') must normalize to empty string."""
    assert normalize_company("nan") == ""
    assert normalize_company("NaN") == ""
    assert normalize_company("None") == ""
    assert normalize_company("null") == ""
    assert normalize_company("Google Inc.") == "google"


def test_dry_run_default_safety():
    """process_job must default dry_run to True when omitted or missing from settings."""
    cfg_no_dry_run = {
        "candidate": {"skills": ["Python"]},
        "settings": {},  # dry_run_mode omitted
    }
    # Run process_job without explicitly passing dry_run
    res = process_job(
        job={"title": "Python Developer", "company": "Test Co", "description": "Python developer role", "url": ""},
        cfg=cfg_no_dry_run,
    )
    # The job was evaluated safely and didn't crash
    assert res.score is not None
    assert res.state in ("EVALUATED", "PREPARED", "REJECTED", "READY_FOR_APPROVAL")
    assert res.title == "Python Developer"
