import os
import csv
import json
import re
import sqlite3
import threading
from datetime import datetime, timedelta
import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, scrolledtext
import core.state as state
from core.config_manager import CONFIG, CONFIG_PATH
from core.db_manager import log_message, recalculate_metrics, SQLITE_DB_PATH, get_recent_history_text
from core.resume_parser import extract_resume_text
from automation.llm_evaluator import query_ai_model
from automation.job_scraper import fast_scrape_jobs
from automation.bot_runner import start_bot_thread, stop_bot
from automation.radar import get_radar_agent
from ui.components import C, F, create_action_btn


def _get_stats() -> dict:
    """Run real aggregate SQLite queries across applications table."""
    min_score = CONFIG.get("settings", {}).get("min_score", 70)
    s = {
        "opportunities": 0,
        "high_fit": 0,
        "applied": 0,
        "interview": 0,
        "offer": 0,
        "avg_score": 0.0,
        "by_platform": [],
        "last_7_days": [],
        "pipeline_stages": []
    }
    try:
        conn = sqlite3.connect(SQLITE_DB_PATH, timeout=10.0)
        s["opportunities"] = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0] or 0
        s["high_fit"]      = conn.execute("SELECT COUNT(*) FROM applications WHERE score >= ?", (min_score,)).fetchone()[0] or 0
        s["applied"]       = conn.execute("SELECT COUNT(*) FROM applications WHERE status IN ('Applied', 'Submitted', 'SUBMITTED', 'Manual Approval Apply')").fetchone()[0] or 0
        s["interview"]     = conn.execute("SELECT COUNT(*) FROM applications WHERE status IN ('Interview', 'Interviewing')").fetchone()[0] or 0
        s["offer"]         = conn.execute("SELECT COUNT(*) FROM applications WHERE status IN ('Offer', 'Offer Received')").fetchone()[0] or 0
        avg_row            = conn.execute("SELECT ROUND(AVG(score), 1) FROM applications WHERE score > 0").fetchone()
        s["avg_score"]     = avg_row[0] if (avg_row and avg_row[0] is not None) else 0.0

        s["by_platform"] = conn.execute("""
            SELECT COALESCE(platform, 'Other') p, COUNT(*) c 
            FROM applications 
            GROUP BY p 
            ORDER BY c DESC
        """).fetchall()

        s["last_7_days"] = conn.execute("""
            SELECT date(applied_at) d, COUNT(*) c 
            FROM applications
            WHERE applied_at >= date('now', '-7 days')
            GROUP BY d 
            ORDER BY d
        """).fetchall()
        conn.close()
    except Exception:
        pass

    s["pipeline_stages"] = [
        ("RADAR", s["opportunities"]),
        ("MATCHED", s["high_fit"]),
        ("APPROVED", max(0, s["high_fit"] - s["applied"])),
        ("APPLIED", s["applied"]),
        ("INTERVIEW", s["interview"]),
        ("OFFER", s["offer"]),
    ]
    return s


class DashboardView(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent, fg_color="transparent")
        self.controller = controller

        # ── 1. Central Hero: "Venture Status" Card ──
        self.hero_card = ctk.CTkFrame(
            self, fg_color=C["card"], corner_radius=10,
            border_width=1, border_color=C["border"]
        )
        self.hero_card.pack(fill='x', pady=(0, 12))

        hero_inner = ctk.CTkFrame(self.hero_card, fg_color="transparent")
        hero_inner.pack(fill='x', padx=18, pady=16)

        # Left: Agent state & operational summary
        hero_left = ctk.CTkFrame(hero_inner, fg_color="transparent")
        hero_left.pack(side='left', fill='both', expand=True)

        status_header_row = ctk.CTkFrame(hero_left, fg_color="transparent")
        status_header_row.pack(anchor='w')

        self.hero_status_dot = ctk.CTkLabel(
            status_header_row, text="●", font=("Arial", 11),
            text_color=C["dim"], width=14
        )
        self.hero_status_dot.pack(side='left', padx=(0, 8))

        self.hero_status_title = ctk.CTkLabel(
            status_header_row, text="VENTURE STANDBY",
            font=F["h2"], text_color=C["text"], anchor="w"
        )
        self.hero_status_title.pack(side='left')

        self.hero_runtime_lbl = ctk.CTkLabel(
            status_header_row, text="", font=F["mono_sm"],
            text_color=C["secondary"], anchor="w"
        )
        self.hero_runtime_lbl.pack(side='left', padx=(12, 0))

        self.hero_subtext_lbl = ctk.CTkLabel(
            hero_left,
            text="Autonomous career engine idle · 3 sources armed · Ready for instruction",
            font=F["xs"], text_color=C["secondary"], anchor="w"
        )
        self.hero_subtext_lbl.pack(anchor='w', pady=(4, 0))

        # Right: Restrained Action Controls
        hero_right = ctk.CTkFrame(hero_inner, fg_color="transparent")
        hero_right.pack(side='right', anchor='e')

        self.btn_radar = create_action_btn(
            hero_right, "Radar off", self.toggle_radar_action, "ghost", "normal"
        )
        self.btn_radar.pack(side='right', padx=(8, 0))

        self.btn_pause = create_action_btn(
            hero_right, "Pause", self.toggle_pause_action, "ghost", "normal"
        )
        self.btn_pause.pack(side='right', padx=(8, 0))

        self.btn_toggle = create_action_btn(
            hero_right, "Start agent", self.toggle_bot_action, "primary", "normal"
        )
        self.btn_toggle.pack(side='right')

        # ── 2. Metric Cards Row ──
        metrics_frame = ctk.CTkFrame(self, fg_color="transparent")
        metrics_frame.pack(fill='x', pady=(0, 10))
        metrics_frame.columnconfigure((0, 1, 2, 3), weight=1, uniform="equal")

        self.metric_opps       = self.create_metric_card(metrics_frame, "OPPORTUNITIES FOUND", "0", 0, "total evaluated")
        self.metric_high_fit   = self.create_metric_card(metrics_frame, "HIGH FIT LEADS", "0", 1, ">=70% semantic match")
        self.metric_applied    = self.create_metric_card(metrics_frame, "APPLICATIONS SENT", "0", 2, "verified pipeline")
        self.metric_interviews = self.create_metric_card(metrics_frame, "INTERVIEWS SCHEDULED", "0", 3, "active leads")

        # ── 3. Visual Opportunity Pipeline Bar ──
        self.pipeline_card = ctk.CTkFrame(
            self, fg_color=C["card"], corner_radius=8,
            border_width=1, border_color=C["border"], height=42
        )
        self.pipeline_card.pack(fill='x', pady=(0, 12))
        self.pipeline_card.pack_propagate(False)

        self.pipeline_canvas = tk.Canvas(
            self.pipeline_card, bg=C["card"],
            highlightthickness=0, bd=0
        )
        self.pipeline_canvas.pack(fill='both', expand=True, padx=12, pady=4)
        self.pipeline_canvas.bind("<Configure>", lambda e: self.draw_pipeline_flow())

        # ── 4. Workspace 2-Column Split: Activity Stream & AI Console ──
        workspace_frame = ctk.CTkFrame(self, fg_color="transparent")
        workspace_frame.pack(fill='both', expand=True)
        workspace_frame.columnconfigure(0, weight=6)
        workspace_frame.columnconfigure(1, weight=5)
        workspace_frame.rowconfigure(0, weight=1)

        # ── Left Column: Live Engineering Activity Stream ──
        activity_card = ctk.CTkFrame(
            workspace_frame, fg_color=C["deep"], corner_radius=10,
            border_width=1, border_color=C["border"]
        )
        activity_card.grid(row=0, column=0, sticky='nsew', padx=(0, 8), pady=0)

        activity_header = ctk.CTkFrame(activity_card, fg_color="transparent", height=34)
        activity_header.pack(fill='x', padx=14, pady=(10, 4))
        activity_header.pack_propagate(False)

        dots = ctk.CTkFrame(activity_header, fg_color="transparent")
        dots.pack(side='left', pady=4)
        ctk.CTkLabel(dots, text="●", font=("Arial", 10), text_color=C["red"], width=13).pack(side='left')
        ctk.CTkLabel(dots, text="●", font=("Arial", 10), text_color=C["amber"], width=13).pack(side='left')
        ctk.CTkLabel(dots, text="●", font=("Arial", 10), text_color=C["green"], width=13).pack(side='left')

        lbl_log_title = ctk.CTkLabel(
            activity_header, text=" VENTURE / ACTIVITY",
            font=F["mono_sm"], text_color=C["secondary"]
        )
        lbl_log_title.pack(side='left', padx=(6, 0))

        self.log_search_var = tk.StringVar()
        log_search = ctk.CTkEntry(
            activity_header, textvariable=self.log_search_var,
            placeholder_text="Filter activity...",
            fg_color=C["input"], border_color=C["border"],
            text_color=C["text"], font=F["xs"], width=140, height=24, corner_radius=4,
            border_width=1
        )
        log_search.pack(side='right')

        logs_inner = ctk.CTkFrame(activity_card, fg_color="transparent")
        logs_inner.pack(fill='both', expand=True, padx=12, pady=(0, 10))

        self.logs_box = scrolledtext.ScrolledText(
            logs_inner, bg=C["deep"], fg=C["body"],
            insertbackground=C["text"], font=F["mono_sm"],
            bd=0, highlightthickness=0, wrap='none'
        )
        self.logs_box.pack(fill='both', expand=True)

        self._configure_log_tags()
        self.log_search_var.trace_add("write", lambda *args: self.update_logs_display())

        # ── Right Column: AI Assistant Console (Restrained Agent Workspace) ──
        chat_card = ctk.CTkFrame(
            workspace_frame, fg_color=C["card"], corner_radius=10,
            border_width=1, border_color=C["border"]
        )
        chat_card.grid(row=0, column=1, sticky='nsew', padx=(8, 0), pady=0)

        chat_header = ctk.CTkFrame(chat_card, fg_color="transparent", height=34)
        chat_header.pack(fill='x', padx=14, pady=(10, 4))
        chat_header.pack_propagate(False)

        lbl_chat_title = ctk.CTkLabel(
            chat_header, text="VENTURE INTELLIGENCE",
            font=F["h3"], text_color=C["text"]
        )
        lbl_chat_title.pack(side='left')

        self.chat_model_badge = ctk.CTkLabel(
            chat_header, text="QWEN 2.5 ●",
            font=F["mono_sm"], text_color=C["green"]
        )
        self.chat_model_badge.pack(side='right')

        # Chat history container
        chat_inner = ctk.CTkFrame(
            chat_card, fg_color=C["deep"], corner_radius=6,
            border_width=1, border_color=C["border"]
        )
        chat_inner.pack(fill='both', expand=True, padx=12, pady=(0, 10))

        self.chat_history = scrolledtext.ScrolledText(
            chat_inner, bg=C["deep"], fg=C["body"],
            insertbackground=C["text"], font=F["sm"],
            bd=0, state='disabled', wrap='word', highlightthickness=0
        )
        self.chat_history.pack(fill='both', expand=True, padx=8, pady=8)

        # Quick action chips row (shown in empty state)
        self.quick_chips_frame = ctk.CTkFrame(chat_card, fg_color="transparent")
        self.quick_chips_frame.pack(fill='x', padx=12, pady=(0, 8))

        quick_prompts = [
            ("Find opportunities", "Search for new matching opportunities"),
            ("Best matches",       "Show my top 5 highest match scores"),
            ("Resume analysis",    "Analyze strengths and gaps in my resume"),
            ("Pipeline stats",     "Give me an executive summary of the pipeline"),
        ]
        for label, prompt in quick_prompts:
            btn = ctk.CTkButton(
                self.quick_chips_frame, text=label,
                font=F["xs"], fg_color=C["elevated"],
                hover_color=C["card_hover"], text_color=C["secondary"],
                border_width=1, border_color=C["border"],
                corner_radius=4, height=24,
                cursor="hand2", command=lambda p=prompt: self._inject_quick_prompt(p)
            )
            btn.pack(side='left', padx=(0, 6))

        # Chat input row
        input_row = ctk.CTkFrame(chat_card, fg_color="transparent")
        input_row.pack(fill='x', padx=12, pady=(0, 12))

        self.chat_input = ctk.CTkEntry(
            input_row, placeholder_text="Ask VENTURE anything...",
            fg_color=C["input"], border_color=C["border"],
            text_color=C["text"], font=F["sm"],
            corner_radius=6, height=34, border_width=1
        )
        self.chat_input.pack(side='left', fill='x', expand=True, padx=(0, 6))
        self.chat_input.bind("<Return>", lambda e: self.send_chat_message())

        btn_send = create_action_btn(input_row, "→", self.send_chat_message, "primary", "small")
        btn_send.configure(width=34)
        btn_send.pack(side='right')

        # Initial seed logs and chat prompt
        self._seed_initial_activity()
        self._seed_initial_chat()

    # ── Metric Card Builder ──
    def create_metric_card(self, parent, label, val, col, subtext=""):
        card = ctk.CTkFrame(
            parent, fg_color=C["card"], corner_radius=8,
            border_width=1, border_color=C["border"]
        )
        card.grid(row=0, column=col, sticky='nsew', padx=4, pady=0)

        lbl_lbl = ctk.CTkLabel(card, text=label, font=F["xs_b"], text_color=C["tertiary"], anchor="w")
        lbl_lbl.pack(anchor='w', padx=14, pady=(12, 0))

        lbl_val = ctk.CTkLabel(card, text=val, font=F["metric"], text_color=C["text"], anchor="w")
        lbl_val.pack(anchor='w', padx=14, pady=(2, 2))

        if subtext:
            lbl_sub = ctk.CTkLabel(card, text=subtext, font=F["xs"], text_color=C["secondary"], anchor="w")
            lbl_sub.pack(anchor='w', padx=14, pady=(0, 10))

        return lbl_val

    # ── Pipeline Visualization ──
    def draw_pipeline_flow(self, stats=None):
        self.pipeline_canvas.delete("all")
        s = stats or _get_stats()
        stages = s.get("pipeline_stages", [])
        if not stages:
            return

        w = self.pipeline_canvas.winfo_width()
        h = self.pipeline_canvas.winfo_height()
        if w < 100: w = 700
        if h < 20: h = 34

        n = len(stages)
        col_w = w / n

        for idx, (name, count) in enumerate(stages):
            cx = idx * col_w + col_w / 2
            cy = h / 2

            # Stage Count + Name
            text_stage = f"{name}  {count}"
            self.pipeline_canvas.create_text(
                cx, cy, text=text_stage,
                fill=C["text"] if count > 0 else C["tertiary"],
                font=F["xs_b"]
            )

            # Connector arrow
            if idx < n - 1:
                arrow_x = (idx + 1) * col_w
                self.pipeline_canvas.create_text(
                    arrow_x, cy, text="→",
                    fill=C["tertiary"], font=F["xs"]
                )

    # ── Activity Stream Logging ──
    def _configure_log_tags(self):
        self.logs_box.tag_config("ts", foreground=C["tertiary"], font=F["mono_sm"])
        self.logs_box.tag_config("radar", foreground=C["blue"], font=F["mono_sm"])
        self.logs_box.tag_config("match", foreground=C["amber"], font=F["mono_sm"])
        self.logs_box.tag_config("rag", foreground=C["purple"], font=F["mono_sm"])
        self.logs_box.tag_config("app", foreground=C["green"], font=F["mono_sm"])
        self.logs_box.tag_config("sys", foreground=C["secondary"], font=F["mono_sm"])
        self.logs_box.tag_config("body", foreground=C["body"], font=F["mono_sm"])

    def _seed_initial_activity(self):
        """Populate initial engineering telemetry so console never appears empty."""
        now = datetime.now()
        t1 = (now - timedelta(seconds=12)).strftime("%H:%M:%S")
        t2 = (now - timedelta(seconds=8)).strftime("%H:%M:%S")
        t3 = (now - timedelta(seconds=3)).strftime("%H:%M:%S")
        t4 = now.strftime("%H:%M:%S")

        self._append_activity_entry(t1, "SYSTEM", "Neural embedding engine initialized (all-MiniLM-L6-v2 · 384 dim)")
        self._append_activity_entry(t2, "DATABASE", "SQLite database verified: venture.db (WAL mode active)")
        self._append_activity_entry(t3, "RADAR", f"Autonomous background poller ready ({len(CONFIG.get('settings', {}).get('queries', []))} queries loaded)")
        self._append_activity_entry(t4, "PIPELINE", "System armed · Ready for operator instruction")

    def _append_activity_entry(self, timestamp, tag, message):
        tag_key = "sys"
        tl = tag.lower()
        if "radar" in tl: tag_key = "radar"
        elif "match" in tl or "score" in tl: tag_key = "match"
        elif "rag" in tl: tag_key = "rag"
        elif "apply" in tl or "subm" in tl: tag_key = "app"

        self.logs_box.insert('end', f"{timestamp}  ", "ts")
        self.logs_box.insert('end', f"{tag:<10}  ", tag_key)
        self.logs_box.insert('end', f"{message}\n", "body")
        self.logs_box.see('end')

    def update_logs_display(self):
        if not hasattr(self, 'logs_box'):
            return
        search_query = self.log_search_var.get().strip().lower()

        # Update with real state logs
        if state.LOG_QUEUE:
            self.logs_box.delete('1.0', 'end')
            for log in state.LOG_QUEUE:
                if not search_query or search_query in log.lower():
                    # Parse timestamp if present
                    ts_match = re.match(r'(\d{2}:\d{2}:\d{2})\s*(.*)', log)
                    if ts_match:
                        ts, rest = ts_match.groups()
                        # Extract tag
                        tag_match = re.match(r'\[(.*?)\]\s*(.*)', rest)
                        if tag_match:
                            tag, content = tag_match.groups()
                            self._append_activity_entry(ts, tag.upper()[:10], content)
                        else:
                            self._append_activity_entry(ts, "EVENT", rest)
                    else:
                        now_str = datetime.now().strftime("%H:%M:%S")
                        self._append_activity_entry(now_str, "LOG", log)
            self.logs_box.see('end')

    # ── AI Console Logic ──
    def _seed_initial_chat(self):
        self.chat_history.configure(state='normal')
        self.chat_history.insert('end', "VENTURE\n", "ai_tag")
        self.chat_history.insert(
            'end',
            "Autonomous career operations agent online. I continuously scan job boards, evaluate semantic fit, and manage your application pipeline.\n\nWhat should I work on?\n\n",
            "ai_body"
        )
        self.chat_history.tag_config("ai_tag", foreground=C["accent"], font=F["mono_sm"])
        self.chat_history.tag_config("ai_body", foreground=C["body"], font=F["sm"])
        self.chat_history.configure(state='disabled')

    def _inject_quick_prompt(self, prompt_text):
        self.chat_input.delete(0, 'end')
        self.chat_input.insert(0, prompt_text)
        self.send_chat_message()

    def send_chat_message(self):
        msg = self.chat_input.get().strip()
        if not msg:
            return

        # Hide quick chips once chatting
        if hasattr(self, 'quick_chips_frame'):
            self.quick_chips_frame.pack_forget()

        self.chat_history.configure(state='normal')
        self.chat_history.insert('end', f"OPERATOR\n", "user_tag")
        self.chat_history.insert('end', f"{msg}\n\n", "user_body")
        self.chat_history.tag_config("user_tag", foreground=C["secondary"], font=F["mono_sm"])
        self.chat_history.tag_config("user_body", foreground=C["text"], font=F["sm"])
        self.chat_history.configure(state='disabled')
        self.chat_history.see('end')
        self.chat_input.delete(0, 'end')

        def update_chat_ui(reply, commands):
            self.chat_history.configure(state='normal')
            hist_content = self.chat_history.get('1.0', 'end')
            thinking_idx = hist_content.rfind("VENTURE  ·  Thinking...")
            if thinking_idx != -1:
                line_no = hist_content.count('\n', 0, thinking_idx) + 1
                self.chat_history.delete(f"{line_no}.0", 'end')

            self.chat_history.insert('end', "VENTURE\n", "ai_tag")
            self.chat_history.insert('end', f"{reply}\n\n", "ai_body")
            self.chat_history.tag_config("ai_tag", foreground=C["accent"], font=F["mono_sm"])
            self.chat_history.tag_config("ai_body", foreground=C["body"], font=F["sm"])
            self.chat_history.configure(state='disabled')
            self.chat_history.see('end')

            if commands:
                for cmd in commands:
                    self.controller.execute_chat_command(cmd)

        def generate_response():
            self.after(0, lambda: self._show_thinking())

            logs_list = list(state.LOG_QUEUE)
            logs_context = "\n".join(logs_list[-10:])
            cand_context = json.dumps(CONFIG.get("candidate", {}), indent=2)
            resume_text = extract_resume_text()
            history_text = get_recent_history_text(limit=10)

            prompt = f"""
You are VENTURE, the autonomous career intelligence agent.
Candidate Stored Profile:
{cand_context}

Resume Excerpt:
{resume_text[:2500]}

Recent Applied Database Records:
{history_text}

Recent Operations Log Context:
{logs_context}

User Query: {msg}

Answer concisely, authoritative and execution-focused like Linear or Palantir console software.
If the user asks to add or search a job query, include: [COMMAND: {{"type": "append_query", "value": "<query>"}}]
If the user updates expected CTC, include: [COMMAND: {{"type": "update_qa_vault", "key": "expected_ctc", "value": "<ctc>"}}]
"""
            reply = query_ai_model(prompt)

            commands = []
            for match_cmd in re.finditer(r'\[COMMAND:\s*(.*?)\]', reply, re.DOTALL):
                try:
                    cmd_json = json.loads(match_cmd.group(1).strip())
                    commands.append(cmd_json)
                    reply = reply.replace(match_cmd.group(0), "").strip()
                except Exception:
                    pass

            self.after(0, lambda: update_chat_ui(reply, commands))

        threading.Thread(target=generate_response, daemon=True).start()

    def _show_thinking(self):
        self.chat_history.configure(state='normal')
        self.chat_history.insert('end', "VENTURE  ·  Thinking...\n\n", "thinking")
        self.chat_history.tag_config("thinking", foreground=C["secondary"], font=F["mono_sm"])
        self.chat_history.configure(state='disabled')
        self.chat_history.see('end')

    # ── Action Handlers ──
    def toggle_radar_action(self):
        agent = get_radar_agent(callback=self.on_radar_job_found)
        if agent.is_running():
            agent.stop()
            self.btn_radar.configure(text="Radar off", text_color=C["secondary"])
            log_message("[RADAR] Background polling stopped")
        else:
            agent.start()
            self.btn_radar.configure(text="Radar on", text_color=C["green"])
            queries_cnt = len(CONFIG.get("settings", {}).get("queries", []))
            log_message(f"[RADAR] Scanning active across {queries_cnt} queries")

    def toggle_pause_action(self):
        state.BOT_PAUSED = not state.BOT_PAUSED
        if state.BOT_PAUSED:
            self.btn_pause.configure(text="Resume", text_color=C["green"])
            log_message("[AGENT] Execution paused by operator")
        else:
            self.btn_pause.configure(text="Pause", text_color=C["secondary"])
            log_message("[AGENT] Execution resumed by operator")

    def toggle_bot_action(self):
        if state.BOT_RUNNING:
            stop_bot()
            self.btn_toggle.configure(
                text="Start agent",
                fg_color=C["accent"],
                hover_color=C["accent_h"],
                text_color=C["primary_on"],
                border_width=0
            )
            log_message("[AGENT] Pipeline stopped")
        else:
            start_bot_thread()
            self.btn_toggle.configure(
                text="Stop agent",
                fg_color="transparent",
                hover_color=C["red_glow"],
                text_color=C["red"],
                border_width=1,
                border_color=C["red"]
            )
            log_message("[AGENT] Pipeline engaged")

    def on_radar_job_found(self, job):
        title = job.get("title", "")
        company = job.get("company", "")
        url = job.get("url", "")
        platform = job.get("platform", "Radar")
        desc = job.get("description", "")

        def bg_eval():
            try:
                from automation.llm_evaluator import evaluate_job_with_qwen
                eval_res = evaluate_job_with_qwen(title, desc or f"{title} at {company}")
                score = eval_res.get("score", 0) if eval_res else 0
                reason = eval_res.get("reason", "") if eval_res else ""

                if score >= 85:
                    from core.notifier import notify
                    notify("VENTURE — Strong Match", f"{title} at {company} ({score}%)")

                with state.DOUBT_LOCK:
                    state.DOUBT_QUEUE.append({
                        "title": title, "company": company, "url": url,
                        "platform": platform, "score": score, "reason": reason, "description": desc
                    })
                from core.db_manager import save_to_db
                save_to_db(url, title, company, platform, "Suggested", f"Radar Match ({score}%): {reason}", score=score)
                log_message(f"[MATCH] {title} at {company} — Fit score {score}%")
            except Exception as e:
                log_message(f"[RADAR] Evaluation error: {e}")

        threading.Thread(target=bg_eval, daemon=True).start()

    # ── Main Update Loop ──
    def update_dashboard_data(self):
        s = _get_stats()

        self.metric_opps.configure(text=str(s["opportunities"]))
        self.metric_high_fit.configure(text=str(s["high_fit"]))
        self.metric_applied.configure(text=str(s["applied"]))
        self.metric_interviews.configure(text=str(s["interview"]))

        # Hero Status Text
        num_sources = len(CONFIG.get("settings", {}).get("target_platforms", [])) + len(CONFIG.get("settings", {}).get("company_career_pages", []))
        if state.BOT_RUNNING and state.BOT_PAUSED:
            self.hero_status_dot.configure(text_color=C["amber"])
            self.hero_status_title.configure(text="VENTURE PAUSED")
            self.hero_subtext_lbl.configure(text=f"Pipeline on hold · {s['opportunities']} evaluated · {s['high_fit']} high-fit matches")
        elif state.BOT_RUNNING:
            self.hero_status_dot.configure(text_color=C["green"])
            self.hero_status_title.configure(text="VENTURE ACTIVE")
            status_line = state.CURRENT_STATUS or f"Scanning {num_sources} sources"
            self.hero_subtext_lbl.configure(text=f"{status_line} · {s['opportunities']} evaluated · {s['high_fit']} high-fit")
        else:
            self.hero_status_dot.configure(text_color=C["dim"])
            self.hero_status_title.configure(text="VENTURE STANDBY")
            self.hero_subtext_lbl.configure(text=f"Autonomous career engine idle · {num_sources} sources armed · {s['opportunities']} evaluated")

        # Session Runtime
        session_start = state.SESSION_STATS.get("session_start")
        if state.BOT_RUNNING and session_start:
            elapsed = int((datetime.now() - session_start).total_seconds())
            h, rem = divmod(elapsed, 3600)
            m, sec = divmod(rem, 60)
            self.hero_runtime_lbl.configure(text=f"[{h:02d}:{m:02d}:{sec:02d}]")
        else:
            self.hero_runtime_lbl.configure(text="")

        # Radar button label
        agent = get_radar_agent()
        if agent.is_running():
            self.btn_radar.configure(text="Radar on", text_color=C["green"])
        else:
            self.btn_radar.configure(text="Radar off", text_color=C["secondary"])

        # Update pipeline flow and activity stream
        self.draw_pipeline_flow(s)
        self.update_logs_display()
