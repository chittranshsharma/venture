import re
import json
import urllib.request
import base64
from core.config_manager import CONFIG, get_model_name, get_ai_provider, get_cloud_ai_config
from core.db_manager import log_message

MAX_RETRIES = 2

def check_live_ai_status():
    """
    Empirically pings the active AI model (Ollama local endpoint or Cloud REST API)
    and returns a tuple: (status_text, is_online_bool)
    """
    provider = get_ai_provider()
    if provider == "cloud":
        cfg = get_cloud_ai_config()
        m_name = cfg.get("model") or cfg.get("preset", "Cloud")
        key = cfg.get("api_key") or cfg.get("password")
        if not key and cfg.get("auth_type") == "api_key":
            return (f"☁️ Cloud ({m_name}): Key Missing", False)
        return (f"☁️ Cloud ({m_name}): Ready", True)
    else:
        l_model = get_model_name()
        try:
            url = "http://127.0.0.1:11434/api/tags"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode('utf-8'))
                    models = [m.get("name") for m in data.get("models", [])]
                    base_m = l_model.split(":")[0]
                    found = any(base_m in m for m in models)
                    if found:
                        return (f"🤖 Local ({l_model}): Ready", True)
                    else:
                        return (f"🤖 Local ({l_model}): Model Not Pulled", False)
        except Exception:
            return (f"🤖 Local ({l_model}): Ollama Offline", False)
        return (f"🤖 Local ({l_model}): Ready", True)

def query_local_ollama(prompt):
    """Query the local Ollama LLM with automatic retry on transient failures."""
    url = "http://127.0.0.1:11434/api/generate"
    model = get_model_name()
    data = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "temperature": 0.1,    # Fix 1.5: deterministic, consistent JSON output
        "num_predict": 1024,   # Fix 1.5: cap response length, avoids hanging on large models
    }
    req_data = json.dumps(data).encode('utf-8')

    for attempt in range(MAX_RETRIES + 1):
        req = urllib.request.Request(
            url,
            data=req_data,
            headers={'Content-Type': 'application/json'}
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                res = json.loads(response.read().decode('utf-8'))
                return res.get("response", "").strip()
        except Exception as e:
            if attempt < MAX_RETRIES:
                import time
                time.sleep(2 * (attempt + 1))
                continue
            log_message(f"Local Ollama API error after {MAX_RETRIES + 1} attempts: {e}")
            return f"Ollama model '{model}' is unavailable or took too long to respond."

# Backwards-compat alias (old name kept so bot_runner.py still works if referenced)
query_local_qwen = query_local_ollama

def query_cloud_ai(prompt):
    """Universal Cloud AI query supporting API Key, Bearer Token, Username/Password Auth, and Custom REST endpoints."""
    cfg = get_cloud_ai_config()
    base_url = (cfg.get("base_url") or "https://api.openai.com/v1").strip().rstrip('/')
    model = (cfg.get("model") or "gpt-4o-mini").strip()
    auth_type = cfg.get("auth_type", "api_key")
    api_key = (cfg.get("api_key") or "").strip()
    username = (cfg.get("username") or "").strip()
    password = (cfg.get("password") or "").strip()
    
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    # 1. Setup Auth Headers (Bearer Token vs Username/Password Basic Auth)
    if auth_type == "user_pass" or (username and password and not api_key):
        userpass = f"{username}:{password}".encode('utf-8')
        b64_userpass = base64.b64encode(userpass).decode('utf-8')
        headers['Authorization'] = f"Basic {b64_userpass}"
    elif api_key:
        if "generativelanguage.googleapis.com" in base_url:
            headers['x-goog-api-key'] = api_key
        elif "anthropic.com" in base_url:
            headers['x-api-key'] = api_key
        else:
            headers['Authorization'] = f"Bearer {api_key}"

    # 2. Build Endpoint URL & Request Payload
    if "generativelanguage.googleapis.com" in base_url:
        endpoint = f"{base_url}/models/{model}:generateContent"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
    elif "anthropic.com" in base_url:
        endpoint = f"{base_url}/v1/messages"
        payload = {
            "model": model,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}]
        }
    else:
        # Standard OpenAI / v1 format
        if not base_url.endswith("/chat/completions") and not base_url.endswith("/generate"):
            endpoint = f"{base_url}/chat/completions"
        else:
            endpoint = base_url
            
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3
        }

    req_data = json.dumps(payload).encode('utf-8')

    for attempt in range(MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(endpoint, data=req_data, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                res = json.loads(response.read().decode('utf-8'))
                
                # Parse response according to provider schema
                if "choices" in res and len(res["choices"]) > 0:
                    msg = res["choices"][0].get("message", {})
                    return msg.get("content", "").strip()
                elif "candidates" in res and len(res["candidates"]) > 0:
                    parts = res["candidates"][0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "").strip()
                elif "content" in res and isinstance(res["content"], list):
                    return res["content"][0].get("text", "").strip()
                else:
                    return str(res)
        except Exception as e:
            err_detail = str(e)
            if hasattr(e, 'read'):
                try:
                    body = json.loads(e.read().decode('utf-8'))
                    if isinstance(body, dict) and "error" in body:
                        err_detail = body["error"].get("message", str(body["error"]))
                except Exception:
                    pass
            if attempt < MAX_RETRIES:
                import time
                time.sleep(2 * (attempt + 1))
                continue
            log_message(f"Cloud AI Error ({endpoint}): {err_detail}")
            return f"Cloud AI Service Error: {err_detail}"

def query_ai_model(prompt):
    """Unified entry point for AI evaluations."""
    provider = get_ai_provider()
    if provider == "cloud":
        return query_cloud_ai(prompt)
    else:
        return query_local_ollama(prompt)

def _extract_json_from_text(text):
    """Extract the first valid JSON object from text using brace-depth counting."""
    start = text.find('{')
    if start == -1:
        return None
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i+1])
                except json.JSONDecodeError:
                    return None
    return None

# ── Upgrade 2.3: Pre-filter gate ─────────────────────────────────────────────

def _pre_filter_passes(job_title: str, job_description: str) -> bool:
    """
    Fast keyword-level pre-filter (< 5ms) that rejects obvious mismatches
    before touching the LLM. Returns False if the job should be discarded.
    """
    set_obj = CONFIG.get("settings", {}) if isinstance(CONFIG.get("settings"), dict) else {}
    cand_obj = CONFIG.get("candidate", {}) if isinstance(CONFIG.get("candidate"), dict) else {}

    title_lower = job_title.lower()
    desc_lower = (job_description or "")[:500].lower()
    combined = f"{title_lower} {desc_lower}"

    # Skip keywords check
    skip_kw = [k.lower() for k in set_obj.get("skip_keywords", [])]
    if any(kw in combined for kw in skip_kw):
        return False

    # At least one candidate skill must appear in title or first 500 chars of description
    skills = [s.lower() for s in (cand_obj.get("skills") or []) if isinstance(s, str)]
    if skills and not any(sk in combined for sk in skills):
        return False

    return True


def evaluate_job_with_qwen(job_title, job_description):
    """
    Evaluates job relevance using the active AI provider (Local Ollama or Cloud REST API).
    Returns JSON dictionary with match score (0-100), reasoning, and approval flag.

    Upgrades applied:
    - Upgrade 2.2: Cached eval lookup — skip LLM if URL already scored in DB
    - Upgrade 2.3: Pre-filter gate — discard obvious mismatches before LLM call
    - Upgrade 2.1: Few-shot examples + chain-of-thought in prompt
    - Fix 1.1: Handles None from extract_resume_text gracefully
    """
    import sqlite3
    from core.db_manager import SQLITE_DB_PATH

    cand_obj = CONFIG.get('candidate', {}) if isinstance(CONFIG.get('candidate'), dict) else {}
    set_obj = CONFIG.get('settings', {}) if isinstance(CONFIG.get('settings'), dict) else {}

    cand_skills = cand_obj.get('skills', []) if isinstance(cand_obj.get('skills'), list) else []
    target_queries = set_obj.get('queries', []) if isinstance(set_obj.get('queries'), list) else []
    skip_kw = set_obj.get('skip_keywords', []) if isinstance(set_obj.get('skip_keywords'), list) else []
    min_score_val = set_obj.get('min_score', 70)

    skills_str = ", ".join([str(s) for s in cand_skills])
    queries_str = ", ".join([str(q) for q in target_queries])
    skip_str = ", ".join([str(k) for k in skip_kw])

    # Upgrade 2.3 — Pre-filter gate: skip LLM for obvious mismatches
    if not _pre_filter_passes(job_title, job_description):
        log_message(f"⚡ Pre-filter: Skipped '{job_title}' (no skill/keyword match)")
        return {
            "score": 10,
            "is_match": False,
            "reason": "Pre-filter: No candidate skills found in job title or description.",
            "strengths": [],
            "gaps": ["Job description does not mention candidate's core skills."],
            "should_approve": False
        }

    # P3.1 — Local RAG Scoring Engine: Cosine-ranked top-5 relevant resume bullets
    from core.rag_scorer import get_top_k_bullets
    from core.resume_parser import extract_resume_text
    base_resume = extract_resume_text()  # Fix 1.1: now returns None on failure
    if base_resume:
        top_bullets = get_top_k_bullets(base_resume, job_description, k=5)
        resume_snippet = "\n".join(f"• {b}" for b in top_bullets)
    else:
        resume_snippet = "Candidate resume not available — evaluate based on skills list only."

    # Upgrade 2.1 — Few-shot + Chain-of-Thought prompt
    prompt = f"""You are an expert senior technical recruiter evaluating job-candidate fit.

IMPORTANT: Ignore all legal boilerplate ("Equal Opportunity Employer", GDPR notices, benefit
descriptions, office perks, etc.). Focus ONLY on required skills, experience level, and role title.

--- FEW-SHOT EXAMPLES ---
Example 1:
Job: "Senior Go Developer, 7+ years, fintech background required"
Candidate skills: Python, React, 1 year Go
Result: {{"thinking": "Go is listed as secondary skill, 7yr seniority unmet, fintech domain missing.", "score": 32, "is_match": false, "reason": "Go experience insufficient and seniority requirement not met.", "strengths": ["Has Go exposure"], "gaps": ["7+ years Go required", "No fintech experience"], "should_approve": false}}

Example 2:
Job: "Full Stack Engineer (React/Node.js), 2-4 years, startup environment"
Candidate skills: React, Node.js, TypeScript, Python, 3 years experience
Result: {{"thinking": "Strong React+Node match, experience range fits, startup culture is neutral.", "score": 88, "is_match": true, "reason": "Strong technical alignment with required stack and seniority.", "strengths": ["React expertise", "Node.js experience", "TypeScript proficiency"], "gaps": ["No specific startup domain mentioned"], "should_approve": false}}
--- END EXAMPLES ---

Now evaluate this job:
Job Title: {job_title}
Job Description (key parts only):
{job_description[:2500]}

Candidate Target Roles: {queries_str}
Candidate Core Skills: {skills_str}
Relevant Candidate Experience (Top RAG-ranked resume highlights):
{resume_snippet}

Skip Keywords (auto-reject if present in title/desc): {skip_str}

Return a JSON object with these EXACT keys:
- "thinking": 1-2 sentence internal reasoning (ignored by scoring, helps accuracy)
- "score": Integer 0-100 representing job match fit
- "is_match": true if score >= {min_score_val}, else false
- "reason": 1-2 sentence explanation of the overall match
- "strengths": List of 2-4 specific candidate skills/experiences that match this JD
- "gaps": List of 2-4 specific JD requirements the candidate is missing
- "should_approve": true if job is borderline or unusual and requires human review

Respond ONLY with valid JSON. No markdown, no explanation outside the JSON.
"""
    reply = query_ai_model(prompt)

    try:
        match_obj = _extract_json_from_text(reply)
        if match_obj:
            match_obj.setdefault("strengths", [])
            match_obj.setdefault("gaps", [])
            match_obj.pop("thinking", None)  # strip internal reasoning before storing
            return match_obj
    except Exception as e:
        log_message(f"Error parsing AI response JSON: {e}")

    return {
        "score": 50,
        "is_match": False,
        "reason": "Could not parse structured evaluation from AI model.",
        "strengths": [],
        "gaps": [],
        "should_approve": True
    }
