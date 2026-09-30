import os
from core.config_manager import CONFIG

def extract_resume_text() -> str:
    """
    Extract text from the candidate's resume PDF.
    Raises RuntimeError if resume path is missing, file doesn't exist, pypdf
    fails, or extracted text length is < 500 characters (preventing silent empty-resume bugs).
    """
    path = CONFIG.get("candidate", {}).get("resume_path", "")
    if not path:
        raise RuntimeError("Candidate 'resume_path' is not configured in config.json.")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Candidate resume file not found at: {path}")

    try:
        import pypdf
    except ImportError as exc:
        raise ImportError(
            "pypdf is required to parse the resume. Run using the project venv: .\\venv\\Scripts\\python.exe"
        ) from exc

    try:
        reader = pypdf.PdfReader(path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        text = text.strip()
    except Exception as exc:
        raise RuntimeError(f"Failed to read resume PDF at {path}: {exc}") from exc

    if len(text) < 500:
        raise ValueError(
            f"Extracted resume text is too short ({len(text)} chars < 500). "
            f"Check PDF content at '{path}'."
        )

    return text

