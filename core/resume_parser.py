import os
from core.config_manager import CONFIG

def extract_resume_text() -> str | None:
    """
    Extract text from the candidate's resume PDF.
    Returns the text string on success, or None on any failure (missing path,
    missing file, import error, or parse error).  Callers must handle None.
    """
    path = CONFIG["candidate"].get("resume_path", "")
    if not path or not os.path.exists(path):
        return None
    try:
        import pypdf
        reader = pypdf.PdfReader(path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text.strip() or None
    except ImportError:
        return None
    except Exception:
        return None
