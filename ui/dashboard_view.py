import os
import csv
import json
import re
import sqlite3
import threading
from datetime import datetime, timedelta
import customtkinter as ctk
import tkinter as tk
from tkinter import ttk
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
        "approved": 0,
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
        s["approved"]      = conn.execute("SELECT COUNT(*) FROM applications WHERE status IN ('APPROVED', 'EXECUTING')").fetchone()[0] or 0
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
        ("APPROVED", s["approved"]),
        ("APPLIED", s["applied"]),
        ("INTERVIEW", s["interview"]),
        ("OFFER", s["offer"]),
    ]
    return s


class DashboardView(ctk.CTkScrollableFrame):
    def __init__(self, parent, controller):
        super().__init__(parent, fg_color="transparent",
                         scrollbar_fg_color=C["canvas"],
                         scrollbar_button_color=C["elevated"],
                         scrollbar_button_hover_color=C["hairline_strong"])
        self.controller = controller

        heading = ctk.CTkFrame(self, fg_color="transparent")
        heading.pack(fill='x', pady=(0, 12))
        ctk.CTkLabel(heading, text="Move forward.", font=F["display_xl"],
                     text_color=C["text"], anchor="w").pack(anchor='w')
        ctk.CTkLabel(heading, text="Find roles worth your time. Keep every next step moving.",
                     font=F["subtitle"], text_color=C["secondary"], anchor="w").pack(anchor='w', pady=(2, 0))

        # ── 1. Central Hero: "Venture Status" Card (Compressed Layout) ──
        self.hero_card = ctk.CTkFrame(
            self, fg_color="#252C57", corner_radius=16,
            border_width=1, border_color="#4D5C91"
        )
        self.hero_card.pack(fill='x', pady=(0, 12))

        hero_inner = ctk.CTkFrame(self.hero_card, fg_color="transparent")
        hero_inner.pack(fill='x', padx=28, pady=16)

        pulse = tk.Canvas(hero_inner, width=126, height=126, bg="#252C57",
                          bd=0, highlightthickness=0)
        pulse.pack(side='right', padx=(12, 18))
        for radius, color in ((58, "#394677"), (43, "#52639B"), (28, "#8292CF")):
            pulse.create_oval(63-radius, 63-radius, 63+radius, 63+radius,
                              outline=color, width=1)
        pulse.create_arc(20, 20, 106, 106, start=45, extent=105,
                         style='arc', outline=C["accent"], width=4)
        pulse.create_oval(57, 57, 69, 69, fill=C["accent"], outline="")
        pulse.create_oval(103, 59, 109, 65, fill=C["blue"], outline="")
        pulse.create_oval(29, 34, 35, 40, fill=C["purple"], outline="")

        # Left: Clean 2-row compact layout
        hero_left = ctk.CTkFrame(hero_inner, fg_color="transparent")
        hero_left.pack(side='left', fill='both', expand=True)

        ctk.CTkLabel(hero_left, text="YOUR SEARCH ENGINE", font=F["xs_b"],
                     text_color=C["accent"], anchor="w").pack(anchor='w', pady=(0, 4))

        status_header_row = ctk.CTkFrame(hero_left, fg_color="transparent")
        status_header_row.pack(anchor='w')

        self.hero_status_dot = ctk.CTkLabel(
            status_header_row, text="●", font=("Arial", 10),
            text_color=C["dim"], width=12
        )
        self.hero_status_dot.pack(side='left', padx=(0, 6))

        self.hero_status_title = ctk.CTkLabel(
            status_header_row, text="Ready when you are",
            font=F["display_lg"], text_color=C["text"], anchor="w"
        )
        self.hero_status_title.pack(side='left')

        self.hero_runtime_lbl = ctk.CTkLabel(
            status_header_row, text="", font=F["mono_sm"],
            text_color=C["secondary"], anchor="w"
        )
        self.hero_runtime_lbl.pack(side='left', padx=(10, 0))

        # Compact telemetry subline
        sub_row = ctk.CTkFrame(hero_left, fg_color="transparent")
        sub_row.pack(anchor='w', pady=(2, 0))

        self.hero_sub_primary = ctk.CTkLabel(
            sub_row, text="Agent idle",
            font=F["xs"], text_color=C["body"], anchor="w"
        )
        self.hero_sub_primary.pack(side='left')

        self.hero_sub_sep = ctk.CTkLabel(sub_row, text=" · ", font=F["xs"], text_color=C["tertiary"])
        self.hero_sub_sep.pack(side='left')

        num_sources = len(CONFIG.get("settings", {}).get("target_platforms", [])) + len(CONFIG.get("settings", {}).get("company_career_pages", []))
        self.hero_sub_secondary = ctk.CTkLabel(
            sub_row, text=f"{num_sources} sources armed · 0 evaluated",
            font=F["xs"], text_color=C["tertiary"], anchor="w"
        )
        self.hero_sub_secondary.pack(side='left')

        # Right: Restrained Action Controls
        hero_right = ctk.CTkFrame(hero_left, fg_color="transparent")
        hero_right.pack(anchor='w', pady=(14, 0))

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

        # ── 2. Metric Cards Row with Differentiated Hierarchy ──
        metrics_frame = ctk.CTkFrame(self, fg_color="transparent")
        metrics_frame.pack(fill='x', pady=(0, 12))
        metrics_frame.columnconfigure(0, weight=2)
        for col in (1, 2, 3):
            metrics_frame.columnconfigure(col, weight=1)

        min_score = CONFIG.get("settings", {}).get("min_score", 70)
        # Prominent intelligence metrics
        self.metric_opps       = self.create_metric_card(metrics_frame, "Opportunities", "0", 0, "in your workspace", prominent=True)
        self.metric_high_fit   = self.create_metric_card(metrics_frame, "High-fit leads", "0", 1, f"fit score ≥ {min_score}", prominent=True)
        # Secondary outcome metrics
        self.metric_applied    = self.create_metric_card(metrics_frame, "Applications", "0", 2, "marked as submitted", prominent=False)
        self.metric_interviews = self.create_metric_card(metrics_frame, "Interviews", "0", 3, "active conversations", prominent=False)

        # ── 3. Visual Opportunity Pipeline Bar with Breathing Room ──
        self.pipeline_card = ctk.CTkFrame(
            self, fg_color=C["card"], corner_radius=12,
            border_width=1, border_color=C["border"], height=72
        )
        self.pipeline_card.pack(fill='x', pady=(0, 12))
        self.pipeline_card.pack_propagate(False)

        ctk.CTkLabel(self.pipeline_card, text="THE JOURNEY", font=F["xs_b"],
                     text_color=C["tertiary"], anchor="w").pack(fill='x', padx=20, pady=(10, 0))

        self.pipeline_canvas = tk.Canvas(
            self.pipeline_card, bg=C["card"],
            highlightthickness=0, bd=0
        )
        self.pipeline_canvas.pack(fill='both', expand=True, padx=16, pady=(0, 8))
        self.pipeline_canvas.bind("<Configure>", lambda e: self.draw_pipeline_flow())

        # ── 4. Workspace 2-Column Split: Activity Stream & AI Console ──
        workspace_frame = ctk.CTkFrame(self, fg_color="transparent", height=350)
        workspace_frame.pack(fill='x')
        workspace_frame.pack_propagate(False)
        workspace_frame.columnconfigure(0, weight=6)
        workspace_frame.columnconfigure(1, weight=5)
        workspace_frame.rowconfigure(0, weight=1)

        # ── Left Column: Live Engineering Activity Stream ──
        activity_card = ctk.CTkFrame(
            workspace_frame, fg_color=C["card"], corner_radius=12,
            border_width=1, border_color=C["border"]
        )
        activity_card.grid(row=0, column=0, sticky='nsew', padx=(0, 8), pady=0)

        activity_header = ctk.CTkFrame(activity_card, fg_color="transparent", height=38)
        activity_header.pack(fill='x', padx=18, pady=(12, 8))
        activity_header.pack_propagate(False)

        dots = ctk.CTkFrame(activity_header, fg_color="transparent")

        lbl_log_title = ctk.CTkLabel(
            activity_header, text="Activity feed",
            font=F["h2"], text_color=C["text"]
        )
        lbl_log_title.pack(side='left', padx=(6, 0))

        self.log_search_var = tk.StringVar()
        log_search = ctk.CTkEntry(
            activity_header,
            placeholder_text="Filter activity...",
            fg_color=C["input"], border_color=C["border"],
            text_color=C["text"], placeholder_text_color=C["tertiary"],
            font=F["xs"], width=156, height=30, corner_radius=7,
            border_width=1
        )
        log_search.pack(side='right')
        log_search.bind("<KeyRelease>", lambda event: self.log_search_var.set(log_search.get()))

        logs_inner = ctk.CTkFrame(activity_card, fg_color="transparent")
        logs_inner.pack(fill='both', expand=True, padx=18, pady=(0, 14))

        self.logs_box = tk.Text(
            logs_inner, bg=C["input"], fg=C["body"],
            insertbackground=C["text"], font=F["mono_sm"],
            bd=0, highlightthickness=0, wrap='word', width=1, height=1,
            padx=18, pady=18
        )
        log_scroll = ctk.CTkScrollbar(logs_inner, command=self.logs_box.yview,
                                      fg_color=C["input"], button_color=C["elevated"],
                                      button_hover_color=C["hairline_strong"])
        log_scroll.pack(side='right', fill='y')
        self.logs_box.configure(yscrollcommand=log_scroll.set)
        self.logs_box.pack(side='left', fill='both', expand=True)

        self._configure_log_tags()
        self.log_search_var.trace_add("write", lambda *args: self.update_logs_display())

        # ── Right Column: AI Assistant Console (Restrained Agent Workspace) ──
        chat_card = ctk.CTkFrame(
            workspace_frame, fg_color=C["card"], corner_radius=12,
            border_width=1, border_color=C["border"]
        )
        chat_card.grid(row=0, column=1, sticky='nsew', padx=(8, 0), pady=0)

        chat_header = ctk.CTkFrame(chat_card, fg_color="transparent", height=38)
        chat_header.pack(fill='x', padx=18, pady=(12, 8))
        chat_header.pack_propagate(False)

        lbl_chat_title = ctk.CTkLabel(
            chat_header, text="Career assistant",
            font=F["h2"], text_color=C["text"]
        )
        lbl_chat_title.pack(side='left')

        self.chat_model_badge = ctk.CTkLabel(
            chat_header, text="AI",
            font=F["xs"], text_color=C["secondary"]
        )
        self.chat_model_badge.pack(side='right')

        # Chat history container
        chat_inner = ctk.CTkFrame(
            chat_card, fg_color=C["deep"], corner_radius=6,
            border_width=1, border_color=C["border"]
        )

        self.chat_history = tk.Text(
            chat_inner, bg=C["deep"], fg=C["body"],
            insertbackground=C["text"], font=F["sm"],
            bd=0, state='disabled', wrap='word', highlightthickness=0,
            width=1, height=1, padx=12, pady=12
        )
        chat_scroll = ctk.CTkScrollbar(chat_inner, command=self.chat_history.yview,
                                       fg_color=C["deep"], button_color=C["elevated"],
                                       button_hover_color=C["hairline_strong"])
        chat_scroll.pack(side='right', fill='y')
        self.chat_history.configure(yscrollcommand=chat_scroll.set)
        self.chat_history.pack(side='left', fill='both', expand=True)

        # Quick action chips 2x2 grid
        self.quick_chips_frame = ctk.CTkFrame(chat_card, fg_color="transparent")
        self.quick_chips_frame.columnconfigure((0, 1), weight=1, uniform="chip")

        quick_prompts = [
            ("Find opportunities", "Search for new matching opportunities"),
            ("Best matches",       "Show my top 5 highest match scores"),
            ("Resume analysis",    "Analyze strengths and gaps in my resume"),
            ("Pipeline stats",     "Give me an executive summary of the pipeline"),
        ]
        row, col = 0, 0
        for label, prompt in quick_prompts:
            btn = ctk.CTkButton(
                self.quick_chips_frame, text=label,
                font=F["xs"], fg_color=C["elevated"],
                hover_color=C["card_hover"], text_color=C["secondary"],
                border_width=1, border_color=C["border"],
                corner_radius=8, height=30,
                cursor="hand2", command=lambda p=prompt: self._inject_quick_prompt(p)
            )
            btn.grid(row=row, column=col, padx=3, pady=2, sticky='ew')
            col += 1
            if col > 1:
                col = 0
                row += 1

        # Chat input row
        input_row = ctk.CTkFrame(chat_card, fg_color="transparent")
        input_row.pack(side='bottom', fill='x', padx=18, pady=(0, 16))

        self.chat_input = ctk.CTkEntry(
            input_row, placeholder_text="Ask about your next move...",
            fg_color=C["input"], border_color=C["border"],
            text_color=C["text"], font=F["sm"],
            corner_radius=8, height=40, border_width=1
        )
        self.chat_input.pack(side='left', fill='x', expand=True, padx=(0, 6))
        self.chat_input.bind("<Return>", lambda e: self.send_chat_message())

        btn_send = create_action_btn(input_row, "→", self.send_chat_message, "primary", "small")
        btn_send.configure(width=34)
        btn_send.pack(side='right')

        self.quick_chips_frame.pack(side='bottom', fill='x', padx=18, pady=(0, 8))
        chat_inner.pack(side='top', fill='both', expand=True, padx=18, pady=(0, 8))

        # Initial seed logs and chat prompt
        self._seed_initial_activity()
        self._seed_initial_chat()

    # ── Differentiated Metric Card Builder (Compact Engineering Design) ──
    def create_metric_card(self, parent, label, val, col, subtext="", prominent=False):
        border_col = C["border"] if prominent else C["hairline"]
        card = ctk.CTkFrame(
            parent, fg_color="#202A4B" if col == 0 else C["card"], corner_radius=12,
            border_width=1, border_color=border_col
        )
        card.grid(row=0, column=col, sticky='nsew', padx=6, pady=0)

        ctk.CTkFrame(card, fg_color=(C["accent"] if col == 0 else C["purple"] if col == 1 else C["blue"]),
                     width=28, height=3, corner_radius=2).pack(anchor='w', padx=20, pady=(14, 0))

        val_font = F["metric"]
        val_color = C["accent"] if col == 0 else C["text"]
        lbl_color = C["secondary"] if prominent else C["tertiary"]

        lbl_val = ctk.CTkLabel(card, text=val, font=val_font, text_color=val_color, anchor="w")
        lbl_val.pack(anchor='w', padx=20, pady=(4, 0))

        lbl_lbl = ctk.CTkLabel(card, text=label, font=F["xs_b"], text_color=lbl_color, anchor="w")
        lbl_lbl.pack(anchor='w', padx=20, pady=(2, 0))

        if subtext:
            lbl_sub = ctk.CTkLabel(card, text=subtext, font=F["xs"], text_color=C["tertiary"], anchor="w")
            lbl_sub.pack(anchor='w', padx=20, pady=(2, 14))
        else:
            ctk.CTkFrame(card, fg_color="transparent", height=6).pack()

        return lbl_val

    # ── Pipeline Visualization (Breathing Room + Subtle Active Brightness) ──
    def draw_pipeline_flow(self, stats=None):
        self.pipeline_canvas.delete("all")
        s = stats or _get_stats()
        stages = s.get("pipeline_stages", [])
        if not stages:
            return

        w = self.pipeline_canvas.winfo_width()
        h = self.pipeline_canvas.winfo_height()
        if w < 100: w = 700
        if h < 20: h = 48

        n = len(stages)
        col_w = w / n

        # Determine current active stage
        active_idx = 0
        if state.BOT_RUNNING:
            st = (state.CURRENT_STATUS or "").lower()
            if "apply" in st or "submit" in st: active_idx = 3
            elif "match" in st or "eval" in st: active_idx = 1
            else: active_idx = 0
        else:
            # Highlight latest non-zero stage
            for i in range(len(stages) - 1, -1, -1):
                if stages[i][1] > 0:
                    active_idx = i
                    break

        for idx, (name, count) in enumerate(stages):
            cx = idx * col_w + col_w / 2
            cy = h / 2

            is_current = idx == active_idx
            dot_x = cx - min(col_w * .27, 44)
            dot_color = C["accent"] if is_current else C["blue"] if count else C["hairline_strong"]
            self.pipeline_canvas.create_oval(dot_x-5, cy-5, dot_x+5, cy+5,
                                             fill=dot_color, outline="")
            self.pipeline_canvas.create_text(
                dot_x + 13, cy, text=f"{name.title()}  {count}", anchor="w",
                fill=C["text"] if is_current else C["secondary"],
                font=F["xs_b"] if is_current else F["xs"]
            )
            if idx < n - 1:
                next_dot = (idx + 1) * col_w + col_w / 2 - min(col_w * .27, 44)
                self.pipeline_canvas.create_line(cx + col_w * .25, cy, next_dot - 12, cy,
                                                 fill=C["hairline_strong"], width=1)

    # ── Activity Stream (Denser Vertically + Intentional SYSTEM IDLE) ──
    def _configure_log_tags(self):
        self.logs_box.tag_config("ts", foreground=C["tertiary"], font=F["mono_sm"])
        self.logs_box.tag_config("radar", foreground=C["blue"], font=F["mono_sm"])
        self.logs_box.tag_config("match", foreground=C["amber"], font=F["mono_sm"])
        self.logs_box.tag_config("rag", foreground=C["purple"], font=F["mono_sm"])
        self.logs_box.tag_config("app", foreground=C["green"], font=F["mono_sm"])
        self.logs_box.tag_config("sys", foreground=C["secondary"], font=F["mono_sm"])
        self.logs_box.tag_config("body", foreground=C["body"], font=F["mono_sm"])

    def _seed_initial_activity(self):
        self.logs_box.tag_config("empty_title", foreground=C["text"], font=F["h2"])
        self.logs_box.tag_config("empty_hint", foreground=C["secondary"], font=F["sm"])
        self.logs_box.insert('end', "✦\n\n", "radar")
        self.logs_box.insert('end', "Your story starts here\n", "empty_title")
        self.logs_box.insert('end', "Start the agent or turn on Radar to see discoveries and decisions as they happen.\n", "empty_hint")

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

        if state.LOG_QUEUE:
            self.logs_box.delete('1.0', 'end')
            recent_logs = list(state.LOG_QUEUE)[-120:]
            for log in recent_logs:
                if search_query and search_query not in log.lower():
                    continue

                raw = log.strip()
                ts = datetime.now().strftime("%H:%M:%S")

                # Match [YYYY-MM-DD HH:MM:SS] or [HH:MM:SS] or bare HH:MM:SS
                ts_m = re.match(r'\[(?:\d{4}-\d{2}-\d{2}\s+)?(\d{2}:\d{2}:\d{2})\]\s*(.*)', raw)
                if ts_m:
                    ts = ts_m.group(1)
                    raw = ts_m.group(2)
                else:
                    bare_m = re.match(r'^(\d{2}:\d{2}:\d{2})\s+(.*)', raw)
                    if bare_m:
                        ts = bare_m.group(1)
                        raw = bare_m.group(2)

                # Match explicit tag [TAG]
                tag = "SYSTEM"
                tag_m = re.match(r'\[([A-Za-z0-9_\-\.\s]+)\]\s*(.*)', raw)
                if tag_m:
                    tag = tag_m.group(1).upper()
                    raw = tag_m.group(2)
                else:
                    raw_lower = raw.lower()
                    if "radar" in raw_lower or "scanning" in raw_lower or "jobspy" in raw_lower:
                        tag = "RADAR"
                    elif "match" in raw_lower or "fit score" in raw_lower:
                        tag = "MATCH"
                    elif "rag" in raw_lower or "embedding" in raw_lower:
                        tag = "RAG"
                    elif "pipeline" in raw_lower or "applied" in raw_lower or "queued" in raw_lower:
                        tag = "PIPELINE"
                    elif "database" in raw_lower or "sqlite" in raw_lower:
                        tag = "DATABASE"

                # Strip internal log prefixes
                clean_msg = raw.replace("INFO - JobSpy:", "").replace("INFO - ", "").replace("WARNING - ", "").strip()
                self._append_activity_entry(ts, tag[:10], clean_msg)

            if state.BOT_RUNNING and state.BOT_PAUSED:
                self.logs_box.insert('end', "\nAgent paused\n", "ts")
            elif state.BOT_RUNNING:
                self.logs_box.insert('end', "\nAgent running\n", "ts")
            else:
                self.logs_box.insert('end', "\nAgent idle\n", "ts")
            self.logs_box.see('end')

    # ── AI Console Logic (Agentic & Calm Personality) ──
    def _seed_initial_chat(self):
        self.chat_history.configure(state='normal')
        self.chat_history.insert('end', "✦  VENTURE\n\n", "ai_tag")
        self.chat_history.insert(
            'end',
            "Let's find what comes next.\n\nAsk me to find opportunities, explore your strengths, or review your pipeline.\n\n",
            "ai_body"
        )
        self.chat_history.tag_config("ai_tag", foreground=C["accent"], font=F["sm_b"])
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

        def bg_eval():
            try:
                from automation.orchestrator import process_job
                result = process_job(job, CONFIG, dry_run=False)
                if result.score >= 85 and result.state == "READY_FOR_APPROVAL":
                    from core.notifier import notify
                    notify("VENTURE — Strong Match", f"{title} at {company} ({result.score}%)")
            except Exception as e:
                log_message(f"[RADAR] Processing error: {e}")

        threading.Thread(target=bg_eval, daemon=True).start()

    # ── Main Update Loop ──
    def update_dashboard_data(self):
        s = _get_stats()

        self.metric_opps.configure(text=str(s["opportunities"]))
        self.metric_high_fit.configure(text=str(s["high_fit"]))
        self.metric_applied.configure(text=str(s["applied"]))
        self.metric_interviews.configure(text=str(s["interview"]))

        # Hero Status Text with Refined Hierarchy
        num_sources = len(CONFIG.get("settings", {}).get("target_platforms", [])) + len(CONFIG.get("settings", {}).get("company_career_pages", []))
        if state.BOT_RUNNING and state.BOT_PAUSED:
            self.hero_status_dot.configure(text_color=C["amber"])
            self.hero_status_title.configure(text="Taking a pause")
            self.hero_sub_primary.configure(text="Pipeline suspended by operator")
            self.hero_sub_secondary.configure(text=f"{num_sources} sources on hold · {s['opportunities']} evaluated · {s['high_fit']} high-fit")
        elif state.BOT_RUNNING:
            self.hero_status_dot.configure(text_color=C["green"])
            self.hero_status_title.configure(text="Finding your next role")
            status_line = state.CURRENT_STATUS or f"Scanning {num_sources} sources"
            self.hero_sub_primary.configure(text=status_line)
            self.hero_sub_secondary.configure(text=f"{num_sources} sources active · {s['opportunities']} evaluated · {s['high_fit']} high-fit")
        else:
            self.hero_status_dot.configure(text_color=C["dim"])
            self.hero_status_title.configure(text="Ready when you are")
            self.hero_sub_primary.configure(text="Agent idle")
            self.hero_sub_secondary.configure(text=f"{num_sources} sources armed · {s['opportunities']} evaluated")

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
