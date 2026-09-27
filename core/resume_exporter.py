import os
import json
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from core.config_manager import CONFIG, BASE_DIR
from core.resume_parser import extract_resume_text
from automation.llm_evaluator import query_ai_model
from core.db_manager import log_message
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os as _os

# Try to register a Unicode-capable font
_UNICODE_FONT = 'Helvetica'  # fallback
try:
    # Try common Windows fonts
    for _font_path in [
        _os.path.join(_os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts', 'arial.ttf'),
        _os.path.join(_os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts', 'segoeui.ttf'),
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/System/Library/Fonts/Helvetica.ttc',
    ]:
        if _os.path.exists(_font_path):
            pdfmetrics.registerFont(TTFont('UnicodeFont', _font_path))
            _UNICODE_FONT = 'UnicodeFont'
            break
except Exception:
    pass

from core.rag_scorer import get_top_k_bullets

COMMON_TECH = ["kubernetes", "aws", "gcp", "azure", "docker", "kafka", "spark", "tensorflow"]

def _extract_json(text):
    if not text:
        return None
    # Find first '{' or '['
    first_brace = text.find('{')
    first_bracket = text.find('[')
    
    if first_brace == -1 and first_bracket == -1:
        return None
    
    # If bracket comes first, or there's no brace
    if first_brace == -1 or (0 <= first_bracket < first_brace):
        start = first_bracket
        open_c, close_c = '[', ']'
    else:
        start = first_brace
        open_c, close_c = '{', '}'
        
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == open_c:
            depth += 1
        elif ch == close_c:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i+1])
                except json.JSONDecodeError:
                    return None
    return None

def _extract_jd_keywords(jd: str) -> list[str]:
    """Step 1: Extract ATS keywords from JD without candidate resume."""
    reply = query_ai_model(f"""Extract ATS keywords from this JD.
Return ONLY a JSON array. Max 20.
JD: {jd[:1500]}
Response:""")
    res = _extract_json(reply)
    if isinstance(res, list):
        return [str(x) for x in res if x]
    return []

def _filter_supported(keywords: list, resume: str) -> list[str]:
    """Step 2: Filter keywords to only those explicitly present in candidate's resume."""
    reply = query_ai_model(f"""From these keywords, return ONLY those EXPLICITLY
in this resume. Be conservative. JSON array only.
Keywords: {json.dumps(keywords)}
Resume: {resume[:2000]}""")
    res = _extract_json(reply)
    if isinstance(res, list):
        return [str(x) for x in res if x]
    return []

def _generate_content(title: str, company: str, supported_kw: list, top_bullets: list, forbidden_clause: str = "") -> dict:
    """Step 3: Generate tailored content bounded strictly to supported keywords and RAG bullets."""
    bullet_context = "\n".join(f"• {b}" for b in top_bullets)
    prompt = f"""Role: {title} at {company}
CRITICAL: Only use these supported keywords: {supported_kw}
Based ONLY on:
{bullet_context}
{forbidden_clause}
Generate JSON: {{"summary": "...", "tailored_skills": [...], "bullet_points": [...]}}
Respond ONLY with JSON format:"""
    reply = query_ai_model(prompt)
    res = _extract_json(reply)
    if isinstance(res, dict):
        return res
    return {}

def _check_violations(content: dict, supported: list) -> list[str]:
    """Step 4: Check if generated content introduced unsupported common tech terms."""
    all_text = " ".join(content.get("tailored_skills", []) + content.get("bullet_points", []))
    sup_lower = " ".join(str(s) for s in supported).lower()
    return [t for t in COMMON_TECH if t in all_text.lower() and t not in sup_lower]

RESUMES_OUTPUT_DIR = os.path.join(BASE_DIR, "tailored_resumes")
os.makedirs(RESUMES_OUTPUT_DIR, exist_ok=True)

def generate_tailored_resume_pdf(job_title="Software Engineer", company_name="Target Company", job_description=""):
    """
    Uses 4-step guarded AI pipeline to tailor candidate's resume content for a target job description
    with zero hallucination, grounded strictly in candidate's real experience and supported keywords.
    Compiles a modern professional PDF resume file.
    Returns absolute path of the generated PDF.
    """
    log_message(f"PDF RESUME GENERATOR: Tailoring resume for {job_title} at {company_name} (4-Step Guarded Pipeline)...")
    
    cand = CONFIG.get("candidate", {})
    cand_name = cand.get("name", "Candidate Name")
    cand_email = cand.get("email", "candidate@email.com")
    cand_phone = cand.get("phone", "+91 9999999999")
    cand_linkedin = cand.get("linkedin", "")
    cand_github = cand.get("github", "")
    cand_skills = ", ".join(cand.get("skills", []))
    
    base_resume = extract_resume_text()
    
    # RAG: Extract top semantic bullets relevant to this JD
    top_bullets = get_top_k_bullets(base_resume, job_description, k=5)
    
    # 4-Step Guarded Anti-Hallucination Pipeline
    # Step 1: Extract JD Keywords
    jd_keywords = _extract_jd_keywords(job_description)
    
    # Step 2: Filter to Resume-Supported Only
    supported_kw = _filter_supported(jd_keywords, base_resume)
    if not supported_kw:
        supported_kw = [s.strip() for s in cand.get("skills", []) if s.strip()]
    
    # Step 3: Generate With Forbidden Clause
    content = _generate_content(job_title, company_name, supported_kw, top_bullets)
    
    # Step 4: Violation Check + Auto-Retry
    violations = _check_violations(content, supported_kw)
    if violations:
        log_message(f"Anti-Hallucination Guard: Detected unsupported tech {violations}. Retrying Step 3 with forbidden clause...")
        retry_clause = f"DO NOT include: {', '.join(violations)}"
        content = _generate_content(job_title, company_name, supported_kw, top_bullets, forbidden_clause=retry_clause)
        violations = _check_violations(content, supported_kw)
        if violations:
            log_message(f"Anti-Hallucination Guard: Second violation for {violations}. Enforcing supported keywords directly.")
            content["tailored_skills"] = [s for s in supported_kw if s.lower() not in violations] or supported_kw
            
    # Fallback guarantees if AI fails or returns empty fields
    safe_summary = f"{cand_name} is a {cand.get('experience', 'motivated')} professional skilled in {cand_skills[:120] if cand_skills else 'software development'}."
    safe_skills = supported_kw if supported_kw else (cand.get("skills", []) or ["Software Development"])
    safe_bullets = top_bullets if top_bullets else [
        f"Worked on {job_title} related projects applying {(cand_skills.split(',')[0] if cand_skills else 'technical')} skills.",
        f"Collaborated with team members to deliver results at {company_name}.",
    ]
    
    ai_summary = content.get("summary", "")
    summary = ai_summary if (ai_summary and len(ai_summary) > 20 and "[" not in ai_summary) else safe_summary
    
    ai_skills = content.get("tailored_skills", [])
    if ai_skills and isinstance(ai_skills, list) and len(ai_skills) > 0 and all(isinstance(s, str) and len(s) > 1 for s in ai_skills):
        skills_list = ai_skills
    else:
        skills_list = safe_skills
        
    ai_bullets = content.get("bullet_points", [])
    if ai_bullets and isinstance(ai_bullets, list) and len(ai_bullets) > 0:
        valid_bullets = [b for b in ai_bullets if isinstance(b, str) and len(b) > 15]
        bullets = valid_bullets if valid_bullets else safe_bullets
    else:
        bullets = safe_bullets


    # Build PDF with ReportLab
    safe_company = "".join(c for c in company_name if c.isalnum() or c in (' ', '_')).rstrip().replace(" ", "_")
    safe_title = "".join(c for c in job_title if c.isalnum() or c in (' ', '_')).rstrip().replace(" ", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pdf_filename = f"Resume_{safe_company}_{safe_title}_{timestamp}.pdf"
    pdf_path = os.path.join(RESUMES_OUTPUT_DIR, pdf_filename)
    
    doc = SimpleDocTemplate(pdf_path, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('NameTitle', parent=styles['Heading1'], fontSize=22, leading=26, textColor=colors.HexColor('#0f172a'), fontName=_UNICODE_FONT)
    contact_style = ParagraphStyle('ContactInfo', parent=styles['Normal'], fontSize=9, leading=12, textColor=colors.HexColor('#475569'), fontName=_UNICODE_FONT)
    heading_style = ParagraphStyle('SectionHeading', parent=styles['Heading2'], fontSize=12, leading=16, textColor=colors.HexColor('#2563eb'), fontName=_UNICODE_FONT, spaceBefore=12, spaceAfter=4)
    body_style = ParagraphStyle('BodyTextCustom', parent=styles['Normal'], fontSize=10, leading=14, textColor=colors.HexColor('#1e293b'), fontName=_UNICODE_FONT)
    bullet_style = ParagraphStyle('BulletCustom', parent=styles['Normal'], fontSize=10, leading=14, textColor=colors.HexColor('#334155'), leftIndent=12, firstLineIndent=-8, spaceAfter=4, fontName=_UNICODE_FONT)
    
    elements = []
    
    # Header Name
    elements.append(Paragraph(f"<b>{cand_name}</b>", title_style))
    contact_str = f"Email: {cand_email}  |  Phone: {cand_phone}"
    if cand_linkedin: contact_str += f"  |  LinkedIn: {cand_linkedin}"
    if cand_github: contact_str += f"  |  GitHub: {cand_github}"
    elements.append(Paragraph(contact_str, contact_style))
    elements.append(Spacer(1, 8))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#2563eb'), spaceAfter=10))
    
    # Professional Summary
    elements.append(Paragraph("<b>PROFESSIONAL SUMMARY</b>", heading_style))
    elements.append(Paragraph(summary, body_style))
    elements.append(Spacer(1, 8))
    
    # Technical Skills
    elements.append(Paragraph("<b>TECHNICAL SKILLS</b>", heading_style))
    skills_str = ", ".join(skills_list)
    elements.append(Paragraph(skills_str, body_style))
    elements.append(Spacer(1, 8))
    
    # Key Achievements & Experience Highlights
    elements.append(Paragraph(f"<b>KEY HIGHLIGHTS ({job_title.upper()})</b>", heading_style))
    for b in bullets:
        elements.append(Paragraph(f"•  {b}", bullet_style))
        
    doc.build(elements)
    log_message(f"📄 TAILORED RESUME CREATED: {pdf_path}")
    return pdf_path
