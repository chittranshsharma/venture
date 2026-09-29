"""
automation/skill_normalizer.py — Fast, deterministic skill normalization, vocabulary matching,
coverage computation, and zero-LLM gap extraction.
"""

import re
from typing import Any, Dict, List, Set, Tuple

# Curated alias map to normalize variants to canonical forms
SKILL_ALIASES: Dict[str, str] = {
    # Frontend
    "react": "react",
    "react.js": "react",
    "reactjs": "react",
    "vue": "vue",
    "vue.js": "vue",
    "vuejs": "vue",
    "angular": "angular",
    "angularjs": "angular",
    "next.js": "next.js",
    "nextjs": "next.js",
    "tailwind": "tailwind",
    "tailwindcss": "tailwind",
    "js": "javascript",
    "javascript": "javascript",
    "ts": "typescript",
    "typescript": "typescript",
    
    # Backend & Runtimes
    "node": "node.js",
    "node.js": "node.js",
    "nodejs": "node.js",
    "node js": "node.js",
    "express": "express",
    "express.js": "express",
    "expressjs": "express",
    "django": "django",
    "fastapi": "fastapi",
    "flask": "flask",
    "spring": "spring",
    "spring boot": "spring boot",
    "springboot": "spring boot",
    "dotnet": ".net",
    ".net": ".net",
    "asp.net": ".net",
    "golang": "go",
    "go": "go",
    
    # Databases
    "postgres": "postgres",
    "postgresql": "postgres",
    "mongo": "mongodb",
    "mongodb": "mongodb",
    "redis": "redis",
    "mysql": "mysql",
    "sqlite": "sqlite",
    
    # Cloud & DevOps
    "k8s": "kubernetes",
    "kubernetes": "kubernetes",
    "docker": "docker",
    "aws": "aws",
    "amazon web services": "aws",
    "gcp": "gcp",
    "google cloud": "gcp",
    "azure": "azure",
    "git": "git",
    "github": "github",
    "gitlab": "gitlab",
    "ci/cd": "ci/cd",
}


def normalize_skill(skill: str) -> str:
    """Normalize a skill string via lowercasing, whitespace stripping, and alias mapping."""
    if not skill:
        return ""
    clean = skill.strip().lower()
    return SKILL_ALIASES.get(clean, clean)


def build_skill_pattern(term: str) -> re.Pattern:
    """
    Construct safe word-boundary regex pattern that handles C++, C#, .NET, Node.js.
    """
    term_l = term.lower()
    if term_l in ("c++", "cpp"):
        return re.compile(r"(?<![\w])c\+\+(?![\w])", re.IGNORECASE)
    if term_l == "c#":
        return re.compile(r"(?<![\w])c#(?![\w])", re.IGNORECASE)
    if term_l in (".net", "dotnet"):
        return re.compile(r"(?<![\w])(?:\.net|dotnet)(?![\w])", re.IGNORECASE)
    if term_l in ("go", "golang"):
        return re.compile(r"(?<![\w])(?:go\s+lang|golang|go\s+developer|golang\s+developer|\bgo\b)(?![\w])", re.IGNORECASE)
    
    escaped = re.escape(term_l)
    return re.compile(rf"(?<![\w+#.]){escaped}(?![\w+#])", re.IGNORECASE)


def extract_jd_skills(jd_text: str, vocab: List[str]) -> Set[str]:
    """
    Extract recognized technical skills present in the JD using the vocabulary.
    Returns normalized canonical skill terms.
    """
    if not jd_text:
        return set()
    
    found: Set[str] = set()
    text_l = jd_text.lower()
    
    for term in vocab:
        pat = build_skill_pattern(term)
        if pat.search(text_l):
            found.add(normalize_skill(term))
            
    return found


def compute_skill_metrics(
    candidate_skills: List[str],
    jd_text: str,
    vocab: List[str]
) -> Dict[str, Any]:
    """
    Deterministic skill coverage and zero-LLM gap extraction.
    Returns:
        - jd_skills: set of recognized technical skills in the JD
        - cand_skills: normalized set of candidate skills
        - matched_skills: intersection (strengths)
        - missing_skills: JD skills candidate lacks (gaps)
        - jd_coverage: fraction of JD requirements possessed by candidate
        - cand_coverage: fraction of candidate skills utilized by the JD
    """
    cand_norm = {normalize_skill(s) for s in candidate_skills if s and s.strip()}
    jd_norm = extract_jd_skills(jd_text, vocab)
    
    matched = cand_norm & jd_norm
    missing = jd_norm - cand_norm
    
    jd_cov = len(matched) / max(len(jd_norm), 1)
    cand_cov = len(matched) / max(len(cand_norm), 1)
    
    return {
        "jd_skills": sorted(list(jd_norm)),
        "cand_skills": sorted(list(cand_norm)),
        "matched_skills": sorted(list(matched)),
        "missing_skills": sorted(list(missing)),
        "jd_coverage": round(jd_cov, 4),
        "cand_coverage": round(cand_cov, 4)
    }
