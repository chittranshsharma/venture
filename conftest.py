import os
import pytest
from unittest.mock import patch
from core.config_manager import CONFIG

DUMMY_RESUME_TEXT = (
    "Full Stack Software Engineer with expertise in Python, FastAPI, React, TypeScript, "
    "PostgreSQL, Docker, and AWS. Over 3 years of experience developing scalable microservices, "
    "RESTful APIs, and responsive frontend applications. Proficient in database design, automated testing, "
    "CI/CD pipelines, and cloud deployment. Strong problem solving, debugging, and cross-functional collaboration skills."
)

@pytest.fixture(autouse=True)
def mock_resume_if_missing():
    """Autouse fixture ensuring fresh clones without private resume PDF pass all tests."""
    resume_path = CONFIG.get("candidate", {}).get("resume_path", "")
    if not resume_path or not os.path.exists(resume_path):
        with patch("core.resume_parser.extract_resume_text", return_value=DUMMY_RESUME_TEXT):
            yield
    else:
        yield

@pytest.fixture(autouse=True)
def default_input_submit(monkeypatch):
    """Default input() to SUBMIT in tests unless explicitly mocked or overridden."""
    monkeypatch.setattr("builtins.input", lambda prompt="": "SUBMIT")
