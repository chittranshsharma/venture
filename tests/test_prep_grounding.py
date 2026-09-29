"""
tests/test_prep_grounding.py — Fabrication and Grounding Verification:
1. Anti-hallucination guard: Prepared packages NEVER invent skills not possessed by the candidate (e.g. Rust, Kubernetes).
2. Grounding: Cover letter and tailored packages only reference verified projects and experiences from base resume.
3. Form questions: Unknown or sensitive questions deterministically return (None, 'NEEDS_HUMAN') rather than guessing with LLM.
"""

import os
import sys
import pytest

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from automation.prep_engine import prepare_application_package, resolve_form_question
from automation.composite_scorer import evaluate_opportunity


# Candidate verified skills: Python, React, Node.js, JavaScript, Git, C++
SAMPLE_CFG = {
    "candidate": {
        "name": "Chittransh Sharma",
        "email": "chittransh@example.com",
        "phone": "+91 9876543210",
        "skills": ["Python", "React", "Node.js", "JavaScript", "Git", "C++"],
        "qa_vault": {
            "experience_years": "1.5",
            "work_authorization": "Authorized to work in India",
            "require_sponsorship": "No",
            "sponsorship_required": "No",
            "notice_period": "Immediate",
            "current_ctc": "0",
            "expected_ctc": "6 LPA",
            "gender": "Decline to Self-Identify",
            "willing_to_relocate": "Yes",
            "education": {
                "degree": "B.Tech Computer Science",
                "university": "ABC Tech University"
            }
        }
    },
    "settings": {
        "min_score": 70,
    }
}


def test_no_unsupported_skills_hallucinated():
    """Application preparation must NEVER fabricate banned skills the candidate does not have."""
    job_requiring_rust_and_k8s = {
        "title": "Principal Systems Engineer",
        "company": "NovaCloud Systems",
        "url": "https://example.com/job/novacloud-systems",
        "jd_text": (
            "We are seeking an engineer with deep expertise in Rust, Kubernetes cluster orchestration, "
            "Scala, Solidity, Haskell, and Erlang actor models."
        )
    }

    signals = evaluate_opportunity(
        job_requiring_rust_and_k8s["title"],
        job_requiring_rust_and_k8s["company"],
        job_requiring_rust_and_k8s["jd_text"],
        cfg=SAMPLE_CFG
    )

    pkg = prepare_application_package(
        job_requiring_rust_and_k8s,
        signals=signals,
        cfg=SAMPLE_CFG
    )

    full_package_text = (pkg.cover_letter_text).lower()

    # Banned skills candidate does NOT have:
    banned_skills = ["rust", "kubernetes", "scala", "solidity", "haskell", "erlang"]
    for banned in banned_skills:
        assert banned not in full_package_text, f"Fabrication violation: '{banned}' found in prepared cover letter!"


def test_form_answers_qa_vault_grounding_20_questions():
    """
    Feeds 20 diverse real-world form question strings.
    Asserts known fields map strictly to QA vault, and unknown/sensitive fields return NEEDS_HUMAN.
    NEVER invokes LLM guessing.
    """
    qa_vault = SAMPLE_CFG["candidate"]["qa_vault"]
    cand = SAMPLE_CFG["candidate"]

    # 10 Known / Vault Mapped questions
    known_questions = [
        ("Are you legally authorized to work in India?", "Authorized to work in India", "VAULT_MATCH"),
        ("Will you now or in the future require visa sponsorship?", "No", "VAULT_MATCH"),
        ("What is your expected salary / CTC?", "6 LPA", "VAULT_MATCH"),
        ("What is your current notice period?", "Immediate", "VAULT_MATCH"),
        ("How many years of professional experience do you have?", "1.5", "VAULT_MATCH"),
        ("Are you open to relocation?", "Yes", "VAULT_MATCH"),
        ("What is your gender?", "Decline to Self-Identify", "VAULT_MATCH"),
        ("Please provide your full legal name:", "Chittransh Sharma", "VAULT_MATCH"),
        ("What is your primary email address?", "chittransh@example.com", "VAULT_MATCH"),
        ("What is your phone number?", "+91 9876543210", "VAULT_MATCH"),
    ]

    for q_text, expected_val, expected_status in known_questions:
        val, status = resolve_form_question(q_text, qa_vault, cand)
        assert status == expected_status, f"Failed on question: '{q_text}'"
        assert val == expected_val, f"Wrong answer for '{q_text}': got {val}, expected {expected_val}"

    # 10 Unknown / Sensitive / Unmapped questions that MUST return NEEDS_HUMAN
    unknown_questions = [
        "Do you possess a commercial driver's license (CDL)?",
        "Have you ever been convicted of a felony or misdemeanor?",
        "Are you willing to submit to a mandatory 10-panel drug test?",
        "What is your active security clearance level (Secret / Top Secret)?",
        "Describe your PhD dissertation topic in 500 words or less:",
        "Please provide the names and contact info of 3 past managers:",
        "What is your high school GPA and graduation year?",
        "Do you hold an active professional engineer (PE) stamp in California?",
        "How many patents do you hold in the semiconductor domain?",
        "Are you bound by a non-compete agreement with your former employer?",
    ]

    for q_text in unknown_questions:
        val, status = resolve_form_question(q_text, qa_vault, cand)
        assert status == "NEEDS_HUMAN", f"Safety violation: Unrecognized question '{q_text}' did not flag NEEDS_HUMAN! (got status={status}, val={val})"
        assert val is None, f"Safety violation: Answer hallucinated for unmapped question '{q_text}': {val}"
