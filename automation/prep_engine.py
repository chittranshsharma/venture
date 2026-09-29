"""
automation/prep_engine.py — Application Preparation Engine (Package Reproducibility).

Transforms an approved or high-fit job opportunity into a versioned, reproducible application package:
  application_packages/{dedup_key}/
  ├── manifest.json
  ├── tailored_resume_{v}.pdf
  ├── tailored_resume_{v}.txt
  ├── cover_letter_{v}.txt
  └── form_answers_{v}.json
"""

from dataclasses import dataclass, asdict
from datetime import datetime
import json
import os
import re
from typing import Any, Dict, List, Optional

from core.config_manager import CONFIG, BASE_DIR, load_config
from core.resume_parser import extract_resume_text
from core.rag_scorer import get_top_k_bullets_and_score
import core.db_manager as db

PACKAGES_DIR = os.path.join(BASE_DIR, "application_packages")


@dataclass
class ApplicationPackage:
    dedup_key: str
    package_dir: str
    resume_path: str
    resume_version: str
    cover_letter_path: str
    cover_letter_version: str
    form_answers_path: str
    answers_version: str
    manifest_path: str
    created_at: str
    evaluation_snapshot: Dict[str, Any]
    job_snapshot: Dict[str, Any]
    form_answers: Dict[str, Any]
    cover_letter_text: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _generate_cover_letter(
    candidate: Dict[str, Any],
    title: str,
    company: str,
    matched_skills: List[str],
    top_bullets: List[str]
) -> str:
    """Generate a clean, targeted 3-paragraph cover letter using real candidate credentials."""
    name = candidate.get("name", "Applicant")
    skills_phrase = ", ".join(matched_skills[:4]) if matched_skills else "software engineering and system design"
    bullet_snippet = top_bullets[0] if top_bullets else "built scalable systems and robust full-stack applications"

    p1 = (
        f"Dear Hiring Team at {company},\n\n"
        f"I am writing to express my strong interest in the {title} position. With hands-on experience in "
        f"{skills_phrase}, I have developed high-performance applications and reliable backend architectures "
        f"that closely match the challenges outlined for this role."
    )

    p2 = (
        f"In my previous work, I have focused on delivering practical engineering impact: {bullet_snippet}. "
        f"I specialize in writing clean, well-tested code, streamlining deployment workflows, and collaborating "
        f"cross-functionally to take complex features from technical design through production."
    )

    p3 = (
        f"I welcome the opportunity to discuss how my technical skills in {skills_phrase} can contribute to "
        f"{company}'s engineering objectives. Thank you for your time and consideration.\n\n"
        f"Sincerely,\n{name}\n"
        f"Email: {candidate.get('email', '')} | Phone: {candidate.get('phone', '')}\n"
        f"GitHub: {candidate.get('github', '')} | LinkedIn: {candidate.get('linkedin', '')}"
    )

    return f"{p1}\n\n{p2}\n\n{p3}"


def _build_form_answers(candidate: Dict[str, Any], qa_vault: Dict[str, Any]) -> Dict[str, Any]:
    """Map candidate profile and QA vault to canonical ATS application questions."""
    name_parts = candidate.get("name", "").split()
    first_name = name_parts[0] if name_parts else ""
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

    return {
        "full_name": candidate.get("name", ""),
        "first_name": first_name,
        "last_name": last_name,
        "email": candidate.get("email", ""),
        "phone": candidate.get("phone", ""),
        "location": candidate.get("location", ""),
        "linkedin": candidate.get("linkedin", ""),
        "github": candidate.get("github", ""),
        "portfolio": candidate.get("portfolio", "") or candidate.get("website", ""),
        "years_of_experience": str(qa_vault.get("experience_years", candidate.get("experience_years", 1))),
        "work_authorization": qa_vault.get("work_authorization", "Authorized to work in country of residence"),
        "sponsorship_required": qa_vault.get("sponsorship_required", "No"),
        "notice_period": qa_vault.get("notice_period", "Immediate / 15 days"),
        "current_salary": qa_vault.get("current_salary", ""),
        "expected_salary": qa_vault.get("expected_salary", ""),
        "gender": qa_vault.get("gender", "Decline to Self-Identify"),
        "veteran_status": qa_vault.get("veteran_status", "Decline to Self-Identify"),
        "disability_status": qa_vault.get("disability_status", "Decline to Self-Identify"),
    }


def prepare_application_package(
    job: Dict[str, Any],
    signals: Any = None,
    llm_evidence: Optional[Dict[str, Any]] = None,
    cfg: Optional[Dict[str, Any]] = None,
    version: int = 1
) -> ApplicationPackage:
    """
    Assembles, versions, and saves a reproducible application package for an opportunity.
    """
    if cfg is None:
        cfg = CONFIG or load_config()

    title = job.get("title", "Software Engineer")
    company = job.get("company", "Company")
    url = job.get("url", "")
    desc = job.get("description") or job.get("jd_text", "")

    dk = job.get("dedup_key") or db.compute_dedup_key(company, title)
    package_dir = os.path.join(PACKAGES_DIR, dk)
    os.makedirs(package_dir, exist_ok=True)

    cand = cfg.get("candidate", {})
    qa_vault = cand.get("qa_vault", {})

    # 1. Base Resume and Highlights
    base_resume = extract_resume_text() or ""
    top_bullets, rag_sc = get_top_k_bullets_and_score(base_resume, desc, k=5)

    matched_skills = []
    if signals and hasattr(signals, "matched_skills"):
        matched_skills = signals.matched_skills
    elif llm_evidence and llm_evidence.get("strengths"):
        matched_skills = llm_evidence["strengths"]
    else:
        matched_skills = cand.get("skills", [])[:5]

    # 2. Versioned Plaintext & PDF Resume
    resume_ver = f"v{version}"
    resume_txt_file = os.path.join(package_dir, f"tailored_resume_{resume_ver}.txt")
    with open(resume_txt_file, "w", encoding="utf-8") as f:
        f.write(f"=== TAILORED RESUME ({title} at {company}) ===\n")
        f.write(f"Candidate: {cand.get('name', '')} | {cand.get('email', '')} | {cand.get('phone', '')}\n\n")
        f.write(f"KEY TECHNICAL ALIGNMENT:\n")
        for s in matched_skills:
            f.write(f"• {s}\n")
        f.write(f"\nRELEVANT EXPERIENCE HIGHLIGHTS:\n")
        for b in top_bullets:
            f.write(f"• {b}\n")
        f.write(f"\nFULL BACKGROUND:\n{base_resume}\n")

    # Use candidate base resume PDF as default primary submission file if exists
    resume_pdf_file = cand.get("resume_path") or resume_txt_file

    # 3. Versioned Cover Letter
    cl_ver = f"v{version}"
    cover_letter_text = _generate_cover_letter(cand, title, company, matched_skills, top_bullets)
    cl_file = os.path.join(package_dir, f"cover_letter_{cl_ver}.txt")
    with open(cl_file, "w", encoding="utf-8") as f:
        f.write(cover_letter_text)

    # 4. Versioned Form Answers
    ans_ver = f"v{version}"
    form_answers = _build_form_answers(cand, qa_vault)
    ans_file = os.path.join(package_dir, f"form_answers_{ans_ver}.json")
    with open(ans_file, "w", encoding="utf-8") as f:
        json.dump(form_answers, f, indent=2)

    # 5. Manifest
    now_iso = datetime.now().isoformat()
    manifest_data = {
        "dedup_key": dk,
        "job_title": title,
        "company": company,
        "url": url,
        "package_version": version,
        "created_at": now_iso,
        "resume_path": resume_pdf_file,
        "resume_text_path": resume_txt_file,
        "cover_letter_path": cl_file,
        "form_answers_path": ans_file,
        "evaluation_snapshot": signals.to_features_dict() if hasattr(signals, "to_features_dict") else {},
        "job_snapshot": {
            "title": title,
            "company": company,
            "url": url,
            "platform": job.get("platform", "Unknown"),
            "description_length": len(desc),
        }
    }
    manifest_file = os.path.join(package_dir, "manifest.json")
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)

    # Link to SQLite DB
    if url:
        db.update_application_package(
            url=url,
            package_path=package_dir,
            resume_v=resume_ver,
            cl_v=cl_ver,
            answers_v=ans_ver
        )
        db.set_checkpoint(url, "package_prepared")

    return ApplicationPackage(
        dedup_key=dk,
        package_dir=package_dir,
        resume_path=resume_pdf_file,
        resume_version=resume_ver,
        cover_letter_path=cl_file,
        cover_letter_version=cl_ver,
        form_answers_path=ans_file,
        answers_version=ans_ver,
        manifest_path=manifest_file,
        created_at=now_iso,
        evaluation_snapshot=manifest_data["evaluation_snapshot"],
        job_snapshot=manifest_data["job_snapshot"],
        form_answers=form_answers,
        cover_letter_text=cover_letter_text,
    )
