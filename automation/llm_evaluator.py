import re
import json
import urllib.request
import base64
import hashlib
from core.config_manager import CONFIG, get_model_name, get_ai_provider, get_cloud_ai_config
from core.db_manager import log_message

MAX_RETRIES = 2

# Curated 300+ tech vocabulary for denominator calculation in JD skill coverage
TECH_VOCABULARY = [
    # Languages
    "python", "javascript", "typescript", "java", "c++", "c#", "golang", "go", "rust", "ruby",
    "php", "swift", "kotlin", "scala", "r", "julia", "perl", "bash", "shell", "sql",
    "html", "css", "sass", "scss", "graphql", "dart", "elixir", "clojure", "haskell", "lua",
    "matlab", "assembly", "solidity", "powershell", "groovy", "erlang", "fortran", "cobol",
    # Frontend frameworks & libs
    "react", "react.js", "reactjs", "next.js", "nextjs", "angular", "angularjs", "vue",
    "vue.js", "vuejs", "nuxt", "nuxtjs", "svelte", "sveltekit", "remix", "gatsby", "redux",
    "mobx", "zustand", "tailwind", "tailwindcss", "bootstrap", "material-ui", "mui",
    "chakra", "storybook", "webpack", "vite", "babel", "rollup", "parcel", "jquery",
    # Backend frameworks & runtimes
    "node", "node.js", "nodejs", "express", "express.js", "nestjs", "fastify", "django",
    "flask", "fastapi", "tornado", "celery", "spring", "spring boot", "ruby on rails", "rails",
    "laravel", "symfony", "asp.net", ".net", "dotnet", "gin", "echo", "fiber", "actix", "rocket",
    # Databases & Caches
    "postgresql", "postgres", "mysql", "mariadb", "mongodb", "redis", "memcached", "sqlite",
    "cassandra", "scylladb", "elasticsearch", "opensearch", "dynamodb", "couchbase", "neo4j",
    "snowflake", "bigquery", "redshift", "clickhouse", "duckdb", "cockroachdb", "supabase",
    "firebase", "planetscale", "prisma", "sqlalchemy", "hibernate", "dbt", "kafka", "rabbitmq",
    # Cloud & Infrastructure
    "aws", "amazon web services", "azure", "gcp", "google cloud", "docker", "kubernetes", "k8s",
    "helm", "terraform", "terragrunt", "ansible", "pulumi", "cloudformation", "jenkins",
    "gitlab", "github actions", "circleci", "argo", "argocd", "linux", "ubuntu", "debian",
    "centos", "nginx", "apache", "caddy", "envoy", "istio", "cloudflare", "datadog", "new relic",
    "prometheus", "grafana", "sentry", "splunk", "pagerduty", "vault", "consul",
    # Architecture & Protocols
    "rest", "restful", "grpc", "soap", "websocket", "webrtc", "microservices", "event-driven",
    "serverless", "lambda", "cloud functions", "system design", "distributed systems",
    "ci/cd", "devops", "mlops", "devsecops", "load balancing", "api gateway",
    # AI / ML / Data
    "machine learning", "deep learning", "nlp", "natural language processing", "llm",
    "computer vision", "pytorch", "tensorflow", "keras", "scikit-learn", "sklearn", "pandas",
    "numpy", "scipy", "xgboost", "lightgbm", "catboost", "hugging face", "transformers",
    "langchain", "llama-index", "ollama", "vllm", "onnx", "spark", "pyspark", "hadoop",
    "flink", "airflow", "prefect", "dagster", "vector database", "pinecone", "chromadb",
    "weaviate", "qdrant", "milvus", "faiss", "rag", "embeddings",
    # Methodologies & Tools
    "git", "github", "gitlab", "bitbucket", "jira", "confluence", "agile", "scrum", "kanban",
    "tdd", "bdd", "unit testing", "integration testing", "playwright", "selenium", "cypress",
    "jest", "pytest", "mocha", "chai", "postman", "swagger", "openapi", "linux/unix",
    # Security & Networking
    "oauth", "jwt", "saml", "sso", "iam", "tls", "ssl", "tcp/ip", "dns", "vpn",
    "penetration testing", "owasp", "zero trust", "soc2", "gdpr", "hipaa"
]

# Standard prompt template
PROMPT_TEMPLATE = """You are an expert senior technical recruiter evaluating job-candidate fit.

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
{job_description}

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


def prompt_version(template: str = PROMPT_TEMPLATE) -> str:
    """Derive deterministic 8-char version tag from SHA256 of prompt template."""
    return hashlib.sha256(template.encode("utf-8")).hexdigest()[:8]


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


def query_local_ollama(prompt, model=None, options=None):
    """Query the local Ollama LLM with automatic retry on transient failures."""
    url = "http://127.0.0.1:11434/api/generate"
    target_model = model or get_model_name()
    data = {
        "model": target_model,
        "prompt": prompt,
        "stream": False,
        "temperature": 0.1,    # deterministic, consistent JSON output
        "num_predict": 1024,   # cap response length, avoids hanging on large models
    }
    if options and isinstance(options, dict):
        data.update(options)

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
            return f"Ollama model '{target_model}' is unavailable or took too long to respond."


# Backwards-compat alias (old name kept so existing references still resolve)
query_local_qwen = query_local_ollama


def query_cloud_ai(prompt, model=None, options=None):
    """Universal Cloud AI query supporting API Key, Bearer Token, Username/Password Auth, and Custom REST endpoints."""
    cfg = get_cloud_ai_config()
    base_url = (cfg.get("base_url") or "https://api.openai.com/v1").strip().rstrip('/')
    target_model = model or (cfg.get("model") or "gpt-4o-mini").strip()
    auth_type = cfg.get("auth_type", "api_key")
    api_key = (cfg.get("api_key") or "").strip()
    username = (cfg.get("username") or "").strip()
    password = (cfg.get("password") or "").strip()

    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

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

    if "generativelanguage.googleapis.com" in base_url:
        endpoint = f"{base_url}/models/{target_model}:generateContent"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
    elif "anthropic.com" in base_url:
        endpoint = f"{base_url}/v1/messages"
        payload = {
            "model": target_model,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}]
        }
    else:
        if not base_url.endswith("/chat/completions") and not base_url.endswith("/generate"):
            endpoint = f"{base_url}/chat/completions"
        else:
            endpoint = base_url

        payload = {
            "model": target_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3
        }

    if options and isinstance(options, dict):
        payload.update(options)

    req_data = json.dumps(payload).encode('utf-8')

    for attempt in range(MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(endpoint, data=req_data, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                res = json.loads(response.read().decode('utf-8'))
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


def query_ai_model(prompt, model=None, options=None):
    """Unified entry point for AI evaluations."""
    provider = get_ai_provider()
    if provider == "cloud":
        return query_cloud_ai(prompt, model=model, options=options)
    else:
        return query_local_ollama(prompt, model=model, options=options)


def _extract_json_from_text(text):
    """Extract the first valid JSON object from text using brace-depth counting."""
    if not text:
        return None
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


def _pre_filter_passes(job_title: str, job_description: str) -> bool:
    """
    Fast keyword-level pre-filter (< 5ms) that rejects obvious mismatches
    before touching the LLM. Returns False if the job should be discarded.
    """
    set_obj = CONFIG.get("settings", {}) if isinstance(CONFIG.get("settings"), dict) else {}
    cand_obj = CONFIG.get("candidate", {}) if isinstance(CONFIG.get("candidate"), dict) else {}

    title_lower = (job_title or "").lower()
    desc_lower = (job_description or "")[:500].lower()
    combined = f"{title_lower} {desc_lower}"

    # Skip keywords check
    skip_kw = [k.lower() for k in set_obj.get("skip_keywords", []) if k]
    if any(kw in combined for kw in skip_kw):
        return False

    # At least one candidate skill must appear in title or first 500 chars of description
    skills = [s.lower() for s in (cand_obj.get("skills") or []) if isinstance(s, str) and s.strip()]
    if skills and not any(sk in combined for sk in skills):
        return False

    return True


def extract_seniority(title: str, text: str = "") -> str:
    """
    Extract standard seniority tier from job title first, falling back to body YOE.
    Prevents false positives like 'You will collaborate with senior staff engineers'.
    """
    t = (title or "").lower()
    if re.search(r"\b(intern|trainee|fresher|graduate|junior|jr\.?|associate)\b", t):
        return "entry"
    if re.search(r"\b(staff|principal|distinguished|director|head of|vp|vice president)\b", t):
        return "staff+"
    if re.search(r"\b(senior|sr\.?|lead)\b", t):
        return "senior"
    m = re.findall(r"(\d+)\s*\+?\s*(?:-\s*\d+\s*)?years?", (text or "").lower()[:3000])
    if m:
        y = min(int(x) for x in m)
        return "entry" if y <= 1 else "mid" if y <= 4 else "senior"
    return "mid"


def compute_skill_overlap(candidate_skills: list, text: str) -> float:
    """Word-boundary normalized fraction of candidate skills found in JD text."""
    if not candidate_skills or not text:
        return 0.0
    text_l = text.lower()
    hits = 0
    clean_skills = {str(x).strip().lower() for x in candidate_skills if str(x).strip()}
    for s in clean_skills:
        pat = r"(?<![\w+#.])" + re.escape(s) + r"(?:\d+)?(?![\w+#])"
        if re.search(pat, text_l):
            hits += 1
    return round(hits / max(len(clean_skills), 1), 4)


def compute_skill_overlaps(candidate_skills: list, text: str) -> tuple[float, float]:
    """
    Returns (candidate_skill_coverage, jd_skill_coverage).
    - candidate_skill_coverage: hits / max(len(candidate_skills), 1)
    - jd_skill_coverage: hits / max(jd_tech_mentions, 1)
    """
    if not text:
        return (0.0, 0.0)
    text_l = text.lower()
    clean_skills = {str(x).strip().lower() for x in (candidate_skills or []) if str(x).strip()}

    cand_hits = 0
    matched_skills = set()
    for s in clean_skills:
        pat = r"(?<![\w+#.])" + re.escape(s) + r"(?:\d+)?(?![\w+#])"
        if re.search(pat, text_l):
            cand_hits += 1
            matched_skills.add(s)

    cand_coverage = cand_hits / max(len(clean_skills), 1)

    jd_tech_mentions = 0
    for term in TECH_VOCABULARY:
        pat = r"(?<![\w+#.])" + re.escape(term) + r"(?![\w+#])"
        if re.search(pat, text_l):
            jd_tech_mentions += 1

    jd_coverage = len(matched_skills) / max(jd_tech_mentions, 1)
    return round(cand_coverage, 4), round(jd_coverage, 4)


def evaluate_job_with_qwen(
    job_title: str = None,
    job_description: str = None,
    title: str = None,
    company: str = None,
    description: str = None,
    url: str = None,
    model: str = None,
    use_cache: bool = False,
    skip_prefilter: bool = False,
    options: dict = None,
):
    """
    Evaluates job relevance using the active AI provider (Local Ollama or Cloud REST API).
    Accepts flexible keyword arguments to accommodate bot_runner and eval_harness.
    Returns JSON dictionary with match score (0-100), reasoning, approval flag, and ML features.
    """
    actual_title = (title or job_title or "").strip()
    actual_desc = (description or job_description or "").strip()
    actual_company = (company or "").strip()
    actual_url = (url or "").strip()

    cand_obj = CONFIG.get('candidate', {}) if isinstance(CONFIG.get('candidate'), dict) else {}
    set_obj = CONFIG.get('settings', {}) if isinstance(CONFIG.get('settings'), dict) else {}

    cand_skills = cand_obj.get('skills', []) if isinstance(cand_obj.get('skills'), list) else []
    target_queries = set_obj.get('queries', []) if isinstance(set_obj.get('queries'), list) else []
    skip_kw = set_obj.get('skip_keywords', []) if isinstance(set_obj.get('skip_keywords'), list) else []
    min_score_val = set_obj.get('min_score', 70)

    skills_str = ", ".join([str(s) for s in cand_skills])
    queries_str = ", ".join([str(q) for q in target_queries])
    skip_str = ", ".join([str(k) for k in skip_kw])

    seniority_val = extract_seniority(actual_title, actual_desc)
    cand_overlap, jd_overlap = compute_skill_overlaps(cand_skills, actual_desc)

    provider = get_ai_provider()
    eval_model_val = model or (get_cloud_ai_config().get("model", "cloud") if provider == "cloud" else get_model_name()) or "local"
    prompt_version_val = prompt_version(PROMPT_TEMPLATE)
    embedding_model_val = "all-MiniLM-L6-v2"

    # Pre-filter gate: skip LLM for obvious mismatches (unless skip_prefilter=True)
    if not skip_prefilter and not _pre_filter_passes(actual_title, actual_desc):
        log_message(f"⚡ Pre-filter: Skipped '{actual_title}' (no skill/keyword match)")
        return {
            "score": 10,
            "is_match": False,
            "reason": "Pre-filter: No candidate skills found in job title or description.",
            "strengths": [],
            "gaps": ["Job description does not mention candidate's core skills."],
            "should_approve": False,
            "rag_score": 0.0,
            "seniority": seniority_val,
            "skill_overlap": cand_overlap,
            "jd_skill_overlap": jd_overlap,
            "eval_model": eval_model_val,
            "prompt_version": prompt_version_val,
            "embedding_model": embedding_model_val,
            "jd_text": actual_desc,
            "rejection_source": "pre_filter"
        }

    # RAG Scoring Engine: Cosine-ranked top-5 relevant resume bullets
    from core.rag_scorer import get_top_k_bullets_and_score
    from core.resume_parser import extract_resume_text
    base_resume = extract_resume_text()
    if base_resume:
        top_bullets, rag_score_val = get_top_k_bullets_and_score(base_resume, actual_desc, k=5)
        resume_snippet = "\n".join(f"• {b}" for b in top_bullets)
    else:
        rag_score_val = 0.5
        resume_snippet = "Candidate resume not available — evaluate based on skills list only."

    prompt = PROMPT_TEMPLATE.format(
        job_title=actual_title,
        job_description=(actual_desc or '')[:2500],
        queries_str=queries_str,
        skills_str=skills_str,
        resume_snippet=resume_snippet,
        skip_str=skip_str,
        min_score_val=min_score_val,
    )

    reply = query_ai_model(prompt, model=model, options=options)

    try:
        match_obj = _extract_json_from_text(reply)
        if match_obj:
            match_obj.setdefault("strengths", [])
            match_obj.setdefault("gaps", [])
            match_obj.pop("thinking", None)  # strip internal reasoning before storing
            match_obj["rag_score"] = rag_score_val
            match_obj["seniority"] = seniority_val
            match_obj["skill_overlap"] = cand_overlap
            match_obj["jd_skill_overlap"] = jd_overlap
            match_obj["eval_model"] = eval_model_val
            match_obj["prompt_version"] = prompt_version_val
            match_obj["embedding_model"] = embedding_model_val
            match_obj["jd_text"] = actual_desc
            return match_obj
    except Exception as e:
        log_message(f"Error parsing AI response JSON: {e}")

    return {
        "score": 50,
        "is_match": False,
        "reason": "Could not parse structured evaluation from AI model.",
        "strengths": [],
        "gaps": [],
        "should_approve": True,
        "rag_score": rag_score_val,
        "seniority": seniority_val,
        "skill_overlap": cand_overlap,
        "jd_skill_overlap": jd_overlap,
        "eval_model": eval_model_val,
        "prompt_version": prompt_version_val,
        "embedding_model": embedding_model_val,
        "jd_text": actual_desc
    }
