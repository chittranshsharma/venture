# VENTURE / JobPilot-AI — Complete System Architecture & Context Specification

> **Purpose of this Document:** This document serves as the single source of truth for **JobPilot-AI (VENTURE)**. Any AI model, engineer, or agent reading this document will possess 100% full context of the project architecture, tech stack, data schemas, state machines, machine learning models, scraping mechanics, UI design system, configuration parameters, and edge cases.

---

## 1. Project Overview & Mission

- **Project Name:** JobPilot-AI (Internal System Codename: **VENTURE**)
- **Repository Root:** `d:\JobPilot-AI`
- **Application Type:** Desktop Autonomous Career Operations Agent & Automated Application Pipeline
- **Core Mission:** An end-to-end autonomous agent that continuously scans job boards and direct company career pages, semantically evaluates job descriptions against candidate profiles using local/cloud AI, tailors ATS resumes, auto-fills application forms via headless browser automation, and tracks application lifecycles with crash-resilient state machines.
- **Operating Environment:** Windows 10/11 (Python 3.11+ virtual environment at `.\venv\Scripts\python.exe`)
- **Primary Entrypoint:** `gui_app.py` (Desktop GUI) or CLI scripts

---

## 2. Technology Stack & Dependencies

| Layer | Technology | Version | Purpose & Rationale |
|---|---|---|---|
| **Language & Runtime** | Python | `>= 3.11.0` | Core language runtime with native Windows support |
| **Desktop GUI** | CustomTkinter | `>= 5.2.0` | Modern dark-mode Tkinter wrapper for desktop interface |
| **GUI Styling Fallback** | Tkinter / ttk (`clam`) | Standard Lib | Low-level Canvas graphs, ScrolledText, and Treeviews |
| **Browser Automation** | Playwright | `== 1.45.0` | Headless/Headed Chromium automation for ATS form filling |
| **Multi-Board Scraping**| `python-jobspy` | `>= 1.1.0` | Multi-board scraper for Indeed, Naukri, and LinkedIn |
| **ATS Career Scraping** | Python Standard Lib (`urllib`) | Standard Lib | Native REST API & HTML crawler for company career sites |
| **Local Vector Embeddings** | `sentence-transformers` | `>= 2.7.0` | `all-MiniLM-L6-v2` (384-dimensional cosine similarity ranking) |
| **Vector Math** | `numpy` | `>= 1.26.0, < 2.0.0` | Cosine similarity dot-product calculations |
| **Local LLM Engine** | Ollama API | HTTP REST | `http://127.0.0.1:11434` (default model: `qwen2.5:7b`) |
| **Cloud LLM Engine** | REST Client | Standard Lib | OpenAI (`gpt-4o-mini`), Anthropic, Google Gemini |
| **Database** | SQLite3 | Standard Lib | WAL mode, thread-locked, local relational database (`venture.db`) |
| **Document Parsing** | `pypdf` | `== 4.2.0` | PDF resume parsing, section extraction, text mining |
| **Document Generation**| `reportlab` | `>= 4.0.0` | Dynamic programmatic generation of ATS-optimized PDF resumes |
| **Credential Security** | `keyring` | `>= 24.0.0` | Windows DPAPI encrypted vault for portal credentials |
| **Configuration** | `json` & `pyyaml` | Standard Lib / `>= 6.0` | `config.json` settings and `selectors.yaml` DOM maps |
| **Notifications** | Windows PowerShell Toast | Native OS | Desktop notifications for discoveries and milestones |

---

## 3. Directory & File Structure

```
d:\JobPilot-AI\
├── automation\                  # Autonomous bots, crawlers, and form-fillers
│   ├── specialists\             # Platform-specific ATS autofill engines
│   │   ├── greenhouse.py        # Greenhouse form automation
│   │   ├── lever.py             # Lever form automation
│   │   ├── ashby.py             # Ashby form automation
│   │   ├── generalist.py        # Generic heuristics-based form filler
│   │   └── generator.py         # Dynamic selector & question answering
│   ├── ats_detector.py          # URL & DOM heuristics for ATS identification
│   ├── bot_runner.py            # Primary pipeline coordinator & runner
│   ├── career_crawler.py        # Direct company career site scraper (Greenhouse, Lever, Ashby, etc.)
│   ├── form_autofiller.py       # Playwright browser interaction & DOM filler
│   ├── job_scraper.py           # Multi-platform job board scraper (JobSpy wrapper)
│   ├── llm_evaluator.py         # Local/Cloud LLM qualification engine & caching
│   ├── radar.py                 # Background autonomous polling daemon (RadarAgent)
│   └── status_tracker.py        # Application status tracker & sync engine
├── core\                        # Core utilities, data models, and business logic
│   ├── config_manager.py        # Central configuration loading and validation
│   ├── contact_extractor.py     # Regex recruiter contact miner (email/phone)
│   ├── credential_store.py      # Windows Keyring secure credential manager
│   ├── db_manager.py            # SQLite database manager (WAL mode, transactions)
│   ├── email_smtp.py            # SMTP dispatcher for notifications & cold emails
│   ├── notifier.py              # Windows toast/balloon notification dispatcher
│   ├── rag_scorer.py            # Local SentenceTransformer semantic RAG scorer
│   ├── resume_exporter.py       # ReportLab PDF resume generator
│   ├── resume_parser.py         # PyPDF resume text & section extractor
│   ├── state.py                 # Global in-memory volatile execution state
│   └── state_machine.py         # Crash-recovery finite state machine (FSM)
├── ui\                          # Desktop Graphical User Interface (CustomTkinter)
│   ├── accounts_view.py         # Portal accounts and Keyring credentials view
│   ├── app_window.py            # Main application window, navbar, and sidebar
│   ├── approvals_view.py        # Human-in-the-loop manual approval queue
│   ├── components.py            # Warm Ink Design System (tokens, buttons, widgets)
│   ├── contacts_view.py         # Recruiter directory and cold email actions
│   ├── dashboard_view.py        # Live metrics, radar banner, logs, analytics, AI chat
│   ├── history_view.py          # Applications table, status tags, CSV/JSON export
│   ├── profile_view.py          # Candidate QA vault, resume upload, skills editor
│   ├── settings_view.py         # System settings, validation, career page editor
│   └── suggestions_view.py      # High-match job suggestions review queue
├── backups\                     # Automated CSV migration backups
├── tailored_resumes\            # Dynamically generated job-tailored PDF resumes
├── config.json                  # Main user configuration, candidate info, and settings
├── DESIGN.md                    # Official Design System specification (Warm Ink)
├── gui_app.py                   # GUI startup script
├── requirements.txt             # Pip dependency declarations
├── selectors.yaml               # DOM selectors for job boards and form inputs
└── venture.db                   # SQLite database (WAL mode)
```

---

## 4. End-to-End System Architecture & Data Flow

```
                           ┌──────────────────────────┐
                           │   Autonomous Triggers    │
                           │ (Radar Daemon / Manual)  │
                           └─────────────┬────────────┘
                                         │
                                         ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                             DISCOVERY LAYER                                      │
│                                                                                  │
│  ┌─────────────────────────────┐           ┌──────────────────────────────────┐  │
│  │    JobSpy Scraper Engine    │           │    Direct ATS Career Crawler     │  │
│  │ (LinkedIn, Indeed, Naukri)  │           │ (Greenhouse, Lever, Ashby, etc.) │  │
│  └──────────────┬──────────────┘           └────────────────┬─────────────────┘  │
└─────────────────┼───────────────────────────────────────────┼────────────────────┘
                  └─────────────────────┬─────────────────────┘
                                        ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                            QUALIFICATION LAYER                                   │
│                                                                                  │
│  1. Fast Pre-Filter Gate: Title & keyword heuristic check (< 5ms)                │
│  2. Local Semantic RAG Scorer: 384-dim all-MiniLM-L6-v2 cosine ranking           │
│     - Section-weighted: Experience/Projects = 2.0x, Education/Other = 0.5x       │
│     - 3,000-character JD extraction window                                       │
│  3. SQLite Evaluation Cache: Skip re-evaluating unchanged URLs                   │
│  4. LLM Evaluator (Ollama Qwen2.5:7b / Cloud AI):                                │
│     - Deterministic extraction (temp=0.1, max_tokens=1024)                       │
│     - Output: Score (0-100), Match Category, Strengths, Gaps, Reason             │
└───────────────────────────────────────┬──────────────────────────────────────────┘
                                        │
           ┌────────────────────────────┴────────────────────────────┐
           ▼                                                         ▼
   Score < min_score                                         Score >= min_score
  [Marked REJECTED]                                                  │
                                                                     ▼
                                                     ┌───────────────────────────────┐
                                                     │ Safe Mode / Manual Approval?  │
                                                     └───────┬───────────────┬───────┘
                                                             │ Yes           │ No
                                                             ▼               ▼
                                                   ┌──────────────┐   ┌──────────────┐
                                                   │ Approvals Q  │   │ Direct Apply │
                                                   └──────────────┘   └──────┬───────┘
                                                                             │
                                                                             ▼
┌────────────────────────────────────────────────────────────────────────────────────┐
│                             EXECUTION LAYER                                        │
│                                                                                    │
│  1. Recruiter Extraction: Regex scan JD for contact emails and phones              │
│  2. Dynamic Resume Tailoring: Generate keyword-aligned PDF via ReportLab           │
│  3. FSM State Updates: DISCOVERED -> QUALIFIED -> FORM_OPENED -> SUBMITTED         │
│  4. Playwright Browser Engine:                                                     │
│     - Headless/Headed Chromium with human-like delays (min_delay to max_delay)     │
│     - Specialist ATS modules (Greenhouse, Lever, Ashby, Generalist)                │
│     - QA Vault Autofill (experience, CTC, sponsorship, notice period, questions)   │
│     - Resume file upload & form submission                                         │
│  5. SQLite Persistence: Updated record status = 'Applied'                          │
│  6. Native Desktop Notification: Toast alert triggered                             │
└────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Database Schema & Persistence

SQLite database location: `venture.db` (configured with `PRAGMA journal_mode=WAL;` and thread-safe mutex `DB_LOCK`).

### 5.1 Tables and Indexes

#### 1. `applications` (Core Application Lifecycle)
| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | Unique application ID |
| `url` | `TEXT` | `NOT NULL UNIQUE` | Canonical job posting URL |
| `title` | `TEXT` | | Job title |
| `company` | `TEXT` | | Hiring company name |
| `platform` | `TEXT` | | Source platform (Indeed, Naukri, LinkedIn, CareerPage) |
| `status` | `TEXT` | `DEFAULT 'Applied'` | Lifecycle status (`Applied`, `Rejected`, `Interview`, `Offer`, `Withdrawn`) |
| `score` | `INTEGER` | `DEFAULT 0` | Semantic match score (0–100%) |
| `reason` | `TEXT` | | Explanation of score and qualifications |
| `strengths` | `TEXT` | | JSON array string: matching candidate skills |
| `gaps` | `TEXT` | | JSON array string: missing requirements/technologies |
| `applied_at` | `TEXT` | | ISO-8601 timestamp of application |
| `updated_at` | `TEXT` | | ISO-8601 timestamp of last status change |

*Indices:*
- `idx_url` ON `applications(url)`
- `idx_status` ON `applications(status)`
- `idx_company` ON `applications(company)`

#### 2. `recruiter_contacts` (Mined Recruiter Directory)
| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | Unique contact ID |
| `company` | `TEXT` | | Company name |
| `role` | `TEXT` | | Targeted role |
| `recruiter_name`| `TEXT` | | Extracted or inferred recruiter name |
| `email` | `TEXT` | | Recruiter email address |
| `phone` | `TEXT` | | Contact telephone number |
| `platform` | `TEXT` | | Platform where contact was discovered |
| `job_url` | `TEXT` | | Associated job posting URL |
| `found_at` | `TEXT` | | Timestamp of discovery |

*Indices:*
- `idx_recruiter_url` ON `recruiter_contacts(job_url)`
- `idx_recruiter_email` ON `recruiter_contacts(email)`

#### 3. `evaluation_cache` (LLM Result Caching)
| Column | Type | Constraints | Description |
|---|---|---|---|
| `url` | `TEXT` | `PRIMARY KEY` | Job posting URL |
| `score` | `INTEGER` | | Cached match score (0–100) |
| `reason` | `TEXT` | | Cached LLM justification |
| `strengths` | `TEXT` | | JSON array string of candidate strengths |
| `gaps` | `TEXT` | | JSON array string of candidate gaps |
| `cached_at` | `TEXT` | `DEFAULT (datetime('now'))`| Timestamp of evaluation cache |

#### 4. `logs` (Persistent Audit Log)
| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | Unique log ID |
| `message` | `TEXT` | | Log line content |
| `logged_at` | `TEXT` | `DEFAULT (datetime('now'))`| Timestamp of event |

---

## 6. Finite State Machine (Crash Recovery Lifecycle)

Implemented in `core/state_machine.py`. Every application undergoes strictly validated state transitions to ensure that browser crashes, power cuts, or network failures can resume at the exact last known checkpoint without duplicate submissions.

### 6.1 State Flow Diagram

```
[DISCOVERED] ──► [QUALIFIED] ──► [APPROVED] ──► [FORM_OPENED] ──► [RESUME_UPLOADED] ──► [FIELDS_FILLED] ──► [SUBMITTED]
      │               │              │                │                   │                  │
      ▼               ▼              │                │                   │                  ▼
  [REJECTED]      [REJECTED]         ▼                ▼                   ▼            [NEEDS_RETRY]
                                  [FAILED]         [FAILED]            [FAILED]              │
                                     │                                                       │
                                     └───────────────────► [FORM_OPENED] ◄───────────────────┘
```

### 6.2 Valid Transitions Table
| Current State | Permitted Next States |
|---|---|
| `DISCOVERED` | `QUALIFIED`, `REJECTED`, `FAILED` |
| `QUALIFIED` | `APPROVED`, `REJECTED`, `FAILED` |
| `APPROVED` | `FORM_OPENED`, `FAILED` |
| `FORM_OPENED` | `RESUME_UPLOADED`, `FIELDS_FILLED`, `FAILED` |
| `RESUME_UPLOADED` | `FIELDS_FILLED`, `FAILED` |
| `FIELDS_FILLED` | `SUBMITTED`, `NEEDS_RETRY`, `FAILED` |
| `NEEDS_RETRY` | `FORM_OPENED`, `RESUME_UPLOADED`, `FIELDS_FILLED`, `FAILED` |
| `FAILED` | `NEEDS_RETRY`, `FORM_OPENED` |

### 6.3 Terminal States (`_TERMINAL_STATES`)
A job in any of the following states is considered complete and will never be re-evaluated or re-applied to:
- `SUBMITTED`, `REJECTED`, `Applied`, `Withdrawn`, `Offer`, `Offer Received`, `Interview`, `Interviewing`, `Manual Approval Apply`

---

## 7. AI & Semantic Intelligence Pipeline

### 7.1 Local RAG Scoring Engine (`core/rag_scorer.py`)
1. **Model:** `sentence-transformers/all-MiniLM-L6-v2` (running locally via PyTorch / CPU / GPU).
2. **Dimension:** 384-dimensional dense semantic vectors.
3. **Session Resume Cache:** Resume text is MD5-hashed; line embeddings are cached in memory (`_resume_cache`) to prevent redundant encodings across multiple jobs.
4. **Section-Aware Weighting:**
   - Lines under `experience`, `work experience`, `projects`, `responsibilities` receive **2.0x weight**.
   - Lines under `education`, `certifications`, `academics` receive **0.5x weight**.
   - General summary or skills bullets receive **1.0x weight**.
5. **JD Window:** Extracts up to **3,000 characters** of the job description (ensuring mid-document technical requirements are captured).
6. **Output:** Top-5 candidate bullet matches ranked by weighted cosine similarity, yielding a baseline semantic score.

### 7.2 LLM Evaluation Engine (`automation/llm_evaluator.py`)
1. **Fast Pre-Filter Gate (< 5ms):**
   - Heuristically checks `skip_keywords` (e.g., "Senior Staff", "Director", "Clearance Required", "US Citizen Only").
   - Rejects obvious non-matches before calling the LLM.
2. **SQLite Evaluation Cache:**
   - Checks `evaluation_cache` table by URL before generating LLM prompts.
3. **Model Providers:**
   - **Local (Ollama):** Queries `http://127.0.0.1:11434/api/generate` with `qwen2.5:7b`.
     - `temperature`: `0.1` (strict determinism).
     - `num_predict`: `1024` (avoids runaway generations).
     - `max_retries`: `2` with exponential backoff.
   - **Cloud (REST):** Universal adapter for OpenAI (`/chat/completions`), Anthropic (`/v1/messages`), and Google Gemini (`/models/...:generateContent`) with support for Bearer tokens, Google API keys, and Basic HTTP Auth.
4. **Structured JSON Output Schema:**
```json
{
  "score": 85,
  "match_category": "Strong Match",
  "strengths": ["Python", "FastAPI", "PostgreSQL", "Docker"],
  "gaps": ["Kubernetes", "AWS Lambda"],
  "reason": "Candidate has solid backend experience matching 85% of tech stack."
}
```

---

## 8. Web Scraping & Career Crawler Architecture

### 8.1 Multi-Board Scraper (`automation/job_scraper.py`)
- Powered by `python-jobspy`.
- Supports **Indeed**, **Naukri**, and **LinkedIn**.
- Features LinkedIn fallback detail fetching with an in-memory URL detail cache to resolve truncated descriptions.
- Bounded by `max_jobs_per_query` (default: 10).

### 8.2 Direct Company Career Crawler (`automation/career_crawler.py`)
Directly extracts roles from raw company career URLs (`careers.company.com`) without relying on aggregators. Supports:
1. **Greenhouse:** Detects board slug; queries `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true`.
2. **Lever:** Detects site slug; queries `https://api.lever.co/v0/postings/{slug}?mode=json`.
3. **Ashby:** Queries Ashby HQ API endpoints `https://api.ashbyhq.com/posting-api/job-board/{slug}`.
4. **Workday:** Identifies `myworkdayjobs.com` tenants and parses job search pagination APIs.
5. **SmartRecruiters:** Hits `https://api.smartrecruiters.com/v1/companies/{company}/postings`.
6. **BambooHR:** Extracts postings from `{company}.bamboohr.com/careers/list`.
7. **Generic HTML Fallback:** Uses regex heuristic parsers for unstructured HTML career tables.

### 8.3 Autonomous Radar Poller (`automation/radar.py`)
- Background polling daemon (`RadarAgent`) running on a dedicated thread.
- Dynamically reads `radar_interval_seconds` (default: 60s, configurable down to 10s) on every loop.
- Emits real-time progress callbacks: `queries_checked`, `jobs_found`, `new_jobs`, `cycle_time`, `next_scan_seconds`.
- Triggers desktop toast notifications via `core/notifier.py` on new discoveries.

---

## 9. Browser Automation & Form Autofilling

Located in `automation/form_autofiller.py` and `automation/specialists/`.
- **Browser:** Playwright Chromium with persistent context, stealth flags, and spoofed user-agent.
- **ATS Detection (`ats_detector.py`):** Automatically classifies pages into Greenhouse, Lever, Ashby, Workday, Taleo, iCIMS, or BambooHR via DOM selectors and URL patterns.
- **QA Vault Integration:** Answers complex questions automatically from `config.json` -> `candidate.qa_vault`:
  - Years of experience, notice period, current & expected CTC/salary, work authorization, sponsorship requirements, relocation preferences, gender disclosures, and education histories.
- **Resume Uploading:** Attaches either the base resume or a dynamically tailored PDF generated by `core/resume_exporter.py`.
- **Rate-Limiting & Anti-Ban Protections:**
  - Jitter delay: Random sleep between `min_delay_seconds` (15s) and `max_delay_seconds` (45s).
  - Safety cap: `daily_apply_cap` (default: 25) prevents exceeding human thresholds.

---

## 10. User Interface & Design System

The application follows a **quiet, dark, restrained, technical, and premium** aesthetic inspired by **Linear, Raycast, Palantir, and Vercel** ("Luxury through Restraint").

### 10.1 Color Palette Tokens (`ui/components.py` -> `C`)
| Token | Hex Code | Visual Role |
|---|---|---|
| `C["bg"]` / `C["canvas"]` | `#0F0F0D` | Quiet technical dark canvas background |
| `C["sidebar"]` | `#11110F` | Deep dark left navigation rail |
| `C["card"]` / `C["surface"]` | `#171614` | Primary card and panel surface |
| `C["card_hover"]` / `C["elevated"]` | `#1C1B18` | Interactive hover and elevated containers |
| `C["deep"]` | `#0D0D0B` | Deep console background for activity stream & chat |
| `C["hairline"]` | `#1F1E1B` | Subtle 1px structural separator |
| `C["border"]` / `C["hairline_strong"]`| `#282621` | Structural 1px boundary for cards, inputs, and tables |
| `C["primary"]` / `C["text"]` | `#E8E5DE` | Off-white primary readable text |
| `C["secondary"]` / `C["charcoal"]` | `#9A968D` | Secondary labels, subtexts, and metadata |
| `C["tertiary"]` / `C["muted"]` | `#66635C` | Group headers, timestamps, and subtle indicators |
| `C["accent"]` | `#D6D0C4` | Neutral warm accent for primary buttons & highlights |
| `C["green"]` (Success) | `#8FAF9A` | Muted sage green for active states & offers |
| `C["amber"]` / `C["yellow"]` (Warning)| `#B5A06A` | Muted amber for warnings and pauses |
| `C["red"]` (Error/Danger) | `#A87575` | Muted rose red for rejections and stops |
| `C["blue"]` | `#7E9DB5` | Muted slate blue for links and telemetry tags |
| `C["purple"]` | `#9E8FA8` | Muted slate purple for RAG retrieval tags |

### 10.2 Typography (`ui/components.py` -> `F`)
- **Display & UI Headers:** `Segoe UI` (e.g., `metric` 24pt bold, `h1` 15pt bold, `h2` 12pt bold, `h3` 11pt bold).
- **Body & Labels:** `Segoe UI` (e.g., `sm` 10pt regular, `sm_b` 10pt bold, `xs` 9pt regular, `xs_b` 9pt bold).
- **Technical & Telemetry:** `Consolas` (e.g., `mono` 10pt regular, `mono_sm` 9pt regular for timestamps, tags, and logs).

### 10.3 Primary Views & Architectural Layout
1. **Top Status Bar (`ui/app_window.py`):**
   - Brand identifier (`◆ VENTURE v3.5`) and operational descriptor (`Autonomous Career Engine`).
   - Technical Telemetry Triad: `● CORE: Qwen 2.5 7B`, `● RADAR: Active/Idle`, `● DB: Synced`.
2. **Categorized Sidebar (`ui/app_window.py`):**
   - `WORKSPACE`: Dashboard, Opportunities, Approvals, Applications.
   - `INTELLIGENCE`: VENTURE AI, Radar, Recruiters.
   - `PROFILE`: Profile, Resume, Credentials.
   - `SYSTEM`: Settings.
3. **Control Dashboard (`ui/dashboard_view.py`):**
   - **Central Hero Status Card:** Agent state (`VENTURE ACTIVE` or `VENTURE STANDBY`), evaluated metrics summary, and restrained controls (`[Start agent]` filled, `Pause` ghost, `Radar` ghost).
   - **Four Metric Cards:** Opportunities Found, High Fit Leads, Applications Sent, Interviews Scheduled.
   - **Opportunity Pipeline Flow:** Horizontal visual stage bar (`RADAR ➔ MATCHED ➔ APPROVED ➔ APPLIED ➔ INTERVIEW ➔ OFFER`).
   - **Live Engineering Activity Stream:** Formatted console with timestamp (`Consolas`), category tags (`RADAR`, `MATCH`, `RAG`, `APPLICATION`), and seed events preventing empty states.
   - **AI Console (`VENTURE INTELLIGENCE`):** Model indicator (`QWEN 2.5 ●`), empty-state quick-action prompt chips, and clean operator conversation stream.
2. **Applied History (`ui/history_view.py`):**
   - Interactive SQLite Treeview table with status color badges (`Applied`, `Interview`, `Offer`, `Rejected`, `Withdrawn`).
   - One-click full export to CSV and JSON (including AI score, strengths, gaps, and justifications).
3. **Suggestions (`ui/suggestions_view.py`):**
   - AI-qualified job leads awaiting review before application.
4. **Approvals (`ui/approvals_view.py`):**
   - Human-in-the-loop review queue for jobs flagged for manual inspection.
5. **Recruiter Contacts (`ui/contacts_view.py`):**
   - Directory of mined recruiter names, emails, and phone numbers with mailto triggers.
6. **AI & Search Settings (`ui/settings_view.py`):**
   - AI Model selector (Local Ollama vs. Cloud OpenAI/Anthropic/Gemini).
   - Validated input fields: minimum match score (0-100), max jobs per query (1-100), radar scan interval (>=10s), daily application cap (1-200), minimum and maximum delay seconds.
   - Direct ATS Company Career Page manager (add, remove, and list career URLs).
7. **My Profile (`ui/profile_view.py`):**
   - Candidate personal info, dynamic tag chip manager for skills, and full QA vault editor.
8. **Credentials (`ui/accounts_view.py`):**
   - Platform account manager backed by encrypted OS Keyring.

---

## 11. Configuration Schema (`config.json`)

```json
{
    "candidate": {
        "name": "Full Name",
        "email": "user@example.com",
        "phone": "9999999999",
        "country_code": "+91",
        "linkedin": "https://linkedin.com/in/...",
        "github": "https://github.com/...",
        "portfolio": "https://...",
        "resume_path": "path/to/resume.pdf",
        "skills": ["Python", "FastAPI", "React", "Docker", "PostgreSQL"],
        "qa_vault": {
            "experience_years": "3",
            "notice_period": "30 days",
            "current_ctc": "1200000",
            "expected_ctc": "1800000",
            "expected_stipend": "0",
            "work_authorization": "Yes",
            "require_sponsorship": "No",
            "willing_to_relocate": "Yes",
            "work_preference": "Remote",
            "gender": "Decline to state",
            "education": {
                "degree": "B.Tech Computer Science",
                "university": "University Name",
                "graduation_year": "2022",
                "cgpa": "8.8"
            }
        }
    },
    "settings": {
        "queries": ["Full Stack Developer", "Backend Engineer", "Python Developer"],
        "min_score": 70,
        "skip_keywords": ["Senior Staff", "Principal", "Director"],
        "blacklist_companies": ["Revature", "Infosys"],
        "max_jobs_per_query": 10,
        "experience_level": "Mid-Level",
        "job_type": "Full-time",
        "location_type": "Remote",
        "preferred_locations": ["Bangalore, India", "Remote"],
        "target_platforms": ["Indeed", "Naukri", "LinkedIn"],
        "company_career_pages": [
            {"company": "Stripe", "url": "https://boards.greenhouse.io/stripe"},
            {"company": "Figma", "url": "https://jobs.lever.co/figma"}
        ],
        "ollama_model": "qwen2.5:7b",
        "ai_provider": "local",
        "cloud_ai_preset": "OpenAI",
        "cloud_ai_base_url": "https://api.openai.com/v1",
        "cloud_ai_model": "gpt-4o-mini",
        "cloud_ai_auth_type": "api_key",
        "cloud_ai_api_key": "",
        "safe_mode": true,
        "daily_apply_cap": 25,
        "min_delay_seconds": 15,
        "max_delay_seconds": 45,
        "radar_interval_seconds": 60
    }
}
```

---

## 12. Complete Metric, Threshold & Parameter Reference

| Metric / Parameter | Location | Default Value | Valid Range | Operational Meaning |
|---|---|---|---|---|
| `min_score` | `config.json` | `70` | `0 – 100` (%) | Minimum LLM evaluation score required to auto-apply |
| `daily_apply_cap` | `config.json` | `25` | `1 – 200` | Safety rate limit for submissions per 24 hours |
| `radar_interval_seconds` | `config.json` | `60` | `>= 10` (sec) | Autonomous background polling frequency |
| `max_jobs_per_query` | `config.json` | `10` | `1 – 100` | Number of jobs to scrape per search keyword per platform |
| `min_delay_seconds` | `config.json` | `15` | `>= 1` (sec) | Minimum human-mimicking delay before form action |
| `max_delay_seconds` | `config.json` | `45` | `>= min_delay` | Maximum human-mimicking delay before form action |
| `temperature` | `llm_evaluator.py` | `0.1` | `0.0 – 1.0` | Ollama model temperature for deterministic JSON output |
| `num_predict` | `llm_evaluator.py` | `1024` | Tokens | Max tokens for local LLM generation (prevents hang) |
| `JD extraction window` | `rag_scorer.py` | `3000` | Characters | Length of job description extracted for semantic scoring |
| `Experience multiplier` | `rag_scorer.py` | `2.0x` | Float | Embedding score multiplier for experience & project lines |
| `Education multiplier` | `rag_scorer.py` | `0.5x` | Float | Embedding score multiplier for education & hobbies lines |
| `SQLite lock timeout` | `db_manager.py` | `30.0` | Seconds | Mutex lock wait timeout before raising SQLite busy error |
| `LLM HTTP timeout` | `llm_evaluator.py` | `120` | Seconds | Network timeout for local Ollama query |
| `Cloud AI HTTP timeout` | `llm_evaluator.py` | `30` | Seconds | Network timeout for Cloud REST API queries |

---

## 13. Critical Developer & AI Extension Guidelines

When reading, updating, or debugging this codebase, adhere strictly to the following architectural invariants:

1. **Linear / Raycast Dark Aesthetic Invariant:** Under NO circumstances introduce electric cyan, neon blue, or bright saturation into the UI. All components must strictly reference tokens from `C` in `ui/components.py` matching the quiet, restrained, technical dark palette (`#0F0F0D`, `#11110F`, `#171614`, `#1C1B18`, `#282621`, `#E8E5DE`, `#9A968D`, `#66635C`).
2. **Atomic SQLite Transactions:** Never execute raw SQLite commands without acquiring `with DB_LOCK:` or `_get_connection()`. The app runs multiple background threads (Radar, Playwright, StatusTracker, Tkinter event loop).
3. **FSM Enforcement:** Always route application status changes through `core.state_machine.transition(url, new_state)` to ensure crash-recovery validity.
4. **Deterministic LLM Output:** When querying Ollama or Cloud LLMs, use temperature `0.1` and extract JSON using brace-depth matching (`_extract_json_from_text`) rather than assuming raw markdown formatting.
5. **Session Cache Invalidation:** If the candidate updates their resume in `profile_view.py`, clear `_resume_cache` in `core/rag_scorer.py` so new vectors are recomputed.
6. **No Plaintext Passwords:** Always route portal passwords through `core/credential_store.py` (`keyring`) instead of saving raw passwords in `config.json`.
7. **Thread Safety in UI:** Tkinter is not thread-safe. Background threads must never modify widgets directly; always dispatch updates through `widget.after(0, callback)`.
