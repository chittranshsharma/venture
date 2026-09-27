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
    """Run real aggregate SQLite queries across applications table (P5.3)."""
    s = {
        "total": 0,
        "applied": 0,
        "interview": 0,
        "offer": 0,
        "avg_score": 0.0,
        "by_platform": [],
        "last_7_days": []
    }
    try:
        conn = sqlite3.connect(SQLITE_DB_PATH, timeout=10.0)
        s["total"]     = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0] or 0
        s["applied"]   = conn.execute("SELECT COUNT(*) FROM applications WHERE status IN ('Applied', 'Submitted', 'SUBMITTED', 'Manual Approval Apply')").fetchone()[0] or 0
        s["interview"] = conn.execute("SELECT COUNT(*) FROM applications WHERE status IN ('Interview', 'Interviewing')").fetchone()[0] or 0
        s["offer"]     = conn.execute("SELECT COUNT(*) FROM applications WHERE status IN ('Offer', 'Offer Received')").fetchone()[0] or 0
        avg_row        = conn.execute("SELECT ROUND(AVG(score), 1) FROM applications WHERE score > 0").fetchone()
        s["avg_score"] = avg_row[0] if (avg_row and avg_row[0] is not None) else 0.0
        
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
    return s


class DashboardView(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent, fg_color="transparent")
        self.controller = controller
        
        # ── Header Row ──
        title_row = ctk.CTkFrame(self, fg_color="transparent")
        title_row.pack(fill='x', pady=(0, 10))
        lbl_title = ctk.CTkLabel(title_row, text="Control Dashboard", font=F["h1"], text_color=C["text"])
        lbl_title.pack(side='left')
        
        btn_frame = ctk.CTkFrame(title_row, fg_color="transparent")
        btn_frame.pack(side='right')
        
        self.btn_radar = create_action_btn(btn_frame, "📡  Radar: Off", self.toggle_radar_action, "secondary", "normal")
        self.btn_radar.pack(side='right', padx=(8, 0))
        
        self.btn_pause = create_action_btn(btn_frame, "⏸  Pause", self.toggle_pause_action, "warning", "normal")
        self.btn_pause.pack(side='right', padx=(8, 0))
        
        self.btn_toggle = create_action_btn(btn_frame, "▶  Start Bot", self.toggle_bot_action, "primary", "normal")
        self.btn_toggle.pack(side='right')

        # ── Radar Status Banner (P5.1) ──
        self.radar_banner = ctk.CTkFrame(self, fg_color=C["card"], corner_radius=8, height=36)
        self.radar_banner.pack(fill='x', pady=(0, 10))

        self.radar_status_dot = ctk.CTkLabel(self.radar_banner, text="●", text_color=C["dim"], font=("Arial", 16))
        self.radar_status_dot.pack(side='left', padx=(12, 4))

        self.radar_status_lbl = ctk.CTkLabel(self.radar_banner, text="Radar: Inactive — Background polling idle",
                                            font=F["xs_b"], text_color=C["muted"])
        self.radar_status_lbl.pack(side='left', padx=4)

        self.radar_count_lbl = ctk.CTkLabel(self.radar_banner, text="0 new jobs found this session",
                                           font=F["xs_b"], text_color=C["cyan"])
        self.radar_count_lbl.pack(side='right', padx=14)
        
        # ── Metric Cards Row (P5.3 SQLite-Powered) ──
        metrics_frame = ctk.CTkFrame(self, fg_color="transparent")
        metrics_frame.pack(fill='x', pady=(0, 6))
        metrics_frame.columnconfigure((0, 1, 2, 3), weight=1, uniform="equal")
        
        self.applied_metric = self.create_metric_card(metrics_frame, "Applications Sent", "0", 0, C["green"])
        self.interview_metric = self.create_metric_card(metrics_frame, "Interviews", "0", 1, C["amber"])
        self.offer_metric = self.create_metric_card(metrics_frame, "Offers Received", "0", 2, C["purple"])
        self.avg_score_metric = self.create_metric_card(metrics_frame, "Avg Match Score", "0%", 3, C["cyan"])
        
        # Funnel & Session Conversion Label
        self.session_stats_lbl = ctk.CTkLabel(self, text="Funnel: 0 Applied ➔ 0 Interviews (0%) ➔ 0 Offers (0%)",
                                              text_color=C["muted"], font=F["xs_b"], anchor="w")
        self.session_stats_lbl.pack(anchor='w', pady=(0, 10))
        
        # ── Workspace 2x2 Grid ──
        workspace_frame = ctk.CTkFrame(self, fg_color="transparent")
        workspace_frame.pack(fill='both', expand=True)
        workspace_frame.columnconfigure(0, weight=1)
        workspace_frame.columnconfigure(1, weight=1)
        workspace_frame.rowconfigure(0, weight=1)
        workspace_frame.rowconfigure(1, weight=1)
        
        # ── Logs Card ──
        logs_card = ctk.CTkFrame(workspace_frame, fg_color=C["card"], corner_radius=12)
        logs_card.grid(row=0, column=0, sticky='nsew', padx=(0, 8), pady=(0, 8))
        
        log_top = ctk.CTkFrame(logs_card, fg_color="transparent")
        log_top.pack(fill='x', padx=14, pady=(12, 6))
        lbl_log_title = ctk.CTkLabel(log_top, text="Operation Logs", font=F["h3"], text_color=C["text"])
        lbl_log_title.pack(side='left')
        
        self.log_search_var = tk.StringVar()
        log_search = ctk.CTkEntry(log_top, textvariable=self.log_search_var,
                                 placeholder_text="Search logs...",
                                 fg_color=C["input"], border_color=C["border"],
                                 text_color=C["text"], font=F["xs"], width=180, height=30, corner_radius=8)
        log_search.pack(side='right')
        
        logs_inner = ctk.CTkFrame(logs_card, fg_color=C["input"], corner_radius=8)
        logs_inner.pack(fill='both', expand=True, padx=14, pady=(0, 14))
        
        self.logs_box = scrolledtext.ScrolledText(logs_inner,
            bg=C["input"], fg=C["cyan"],
            insertbackground="white",
            font=F["mono"], bd=0, highlightthickness=0)
        self.logs_box.pack(fill='both', expand=True, padx=6, pady=6)
        
        self.log_search_var.trace_add("write", lambda *args: self.update_logs_display())
        
        # ── Analytics Card (P5.3 Funnel, Sparkline & Platform Breakdown) ──
        charts_card = ctk.CTkFrame(workspace_frame, fg_color=C["card"], corner_radius=12)
        charts_card.grid(row=1, column=0, sticky='nsew', padx=(0, 8), pady=(8, 0))
        
        lbl_charts_title = ctk.CTkLabel(charts_card, text="Pipeline Analytics (SQLite Live Data)", font=F["h3"], text_color=C["text"])
        lbl_charts_title.pack(anchor='w', padx=14, pady=(12, 6))
        
        self.chart_canvas = tk.Canvas(charts_card, bg=C["card"], highlightthickness=0, bd=0)
        self.chart_canvas.pack(fill='both', expand=True, padx=14, pady=(0, 14))
        
        # ── Chat Card ──
        chat_card = ctk.CTkFrame(workspace_frame, fg_color=C["card"], corner_radius=12)
        chat_card.grid(row=0, column=1, rowspan=2, sticky='nsew', padx=(8, 0))
        
        chat_header = ctk.CTkFrame(chat_card, fg_color="transparent")
        chat_header.pack(fill='x', padx=14, pady=(12, 8))
        lbl_chat_title = ctk.CTkLabel(chat_header, text="AI Assistant Chat", font=F["h3"], text_color=C["text"])
        lbl_chat_title.pack(side='left')
        
        chat_badge = ctk.CTkLabel(chat_header, text="RAG", fg_color=C["accent"], text_color="white",
                                 font=F["xs_b"], corner_radius=6, width=42, height=20)
        chat_badge.pack(side='left', padx=(8, 0))
        
        chat_inner = ctk.CTkFrame(chat_card, fg_color=C["input"], corner_radius=8)
        chat_inner.pack(fill='both', expand=True, padx=14, pady=(0, 10))
        
        self.chat_history = scrolledtext.ScrolledText(chat_inner,
            bg=C["input"], fg=C["text"],
            insertbackground="white", font=F["sm"],
            bd=0, state='disabled', wrap='word', highlightthickness=0)
        self.chat_history.pack(fill='both', expand=True, padx=6, pady=6)
        
        input_row = ctk.CTkFrame(chat_card, fg_color="transparent")
        input_row.pack(fill='x', padx=14, pady=(0, 14))
        
        self.chat_input = ctk.CTkEntry(input_row,
            placeholder_text="Ask about resume, jobs, or settings...",
            fg_color=C["input"], border_color=C["border"], text_color=C["text"],
            font=F["sm"], corner_radius=8, height=38)
        self.chat_input.pack(side='left', fill='x', expand=True, padx=(0, 8))
        self.chat_input.bind("<Return>", lambda e: self.send_chat_message())
        
        btn_send = create_action_btn(input_row, "Send", self.send_chat_message, "primary", "small")
        btn_send.pack(side='right')

    def create_metric_card(self, parent, label, val, col, accent_color):
        card = ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=12)
        card.grid(row=0, column=col, sticky='nsew', padx=5, pady=2)
        
        accent_bar = ctk.CTkFrame(card, fg_color=accent_color, height=3, corner_radius=0)
        accent_bar.pack(fill='x', pady=(0, 10))
        
        lbl_lbl = ctk.CTkLabel(card, text=label, font=F["xs_b"], text_color=C["muted"], anchor="w")
        lbl_lbl.pack(anchor='w', padx=14)
        
        lbl_val = ctk.CTkLabel(card, text=val, font=F["metric"], text_color=accent_color, anchor="w")
        lbl_val.pack(anchor='w', padx=14, pady=(2, 10))
        return lbl_val

    def toggle_radar_action(self):
        """Toggle background radar poller (P5.1)."""
        agent = get_radar_agent(callback=self.on_radar_job_found)
        if agent.is_running():
            agent.stop()
            self.btn_radar.configure(text="📡  Radar: Off", fg_color=C["card_hover"])
            self.radar_status_dot.configure(text_color=C["dim"])
            self.radar_status_lbl.configure(text="Radar: Inactive — Background polling idle", text_color=C["muted"])
        else:
            agent.start()
            self.btn_radar.configure(text="📡  Radar: On", fg_color=C["green"])
            queries_cnt = len(CONFIG.get("settings", {}).get("queries", []))
            self.radar_status_dot.configure(text_color=C["green"])
            self.radar_status_lbl.configure(
                text=f"Radar: Active — {queries_cnt} queries polling every {agent._interval}s",
                text_color=C["green"]
            )

    def on_radar_job_found(self, job):
        """Callback invoked when Radar discovers a fresh job opening."""
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
                    notify("JobPilot — Strong Match", f"{title} at {company} ({score}%)")

                with state.DOUBT_LOCK:
                    state.DOUBT_QUEUE.append({
                        "title": title, "company": company, "url": url,
                        "platform": platform, "score": score, "reason": reason, "description": desc
                    })
                from core.db_manager import save_to_db
                save_to_db(url, title, company, platform, "Suggested", f"Radar Match ({score}%): {reason}", score=score)
            except Exception as e:
                log_message(f"Radar evaluation error: {e}")

        threading.Thread(target=bg_eval, daemon=True).start()

    def toggle_bot_action(self):
        if state.BOT_RUNNING:
            stop_bot()
            self.btn_toggle.configure(text="▶  Start Bot", fg_color=C["accent"], hover_color=C["accent_d"])
        else:
            start_bot_thread()
            self.btn_toggle.configure(text="■  Stop Bot", fg_color=C["red"], hover_color=C["red_h"])

    def toggle_pause_action(self):
        state.BOT_PAUSED = not state.BOT_PAUSED
        if state.BOT_PAUSED:
            self.btn_pause.configure(text="▶  Resume", fg_color=C["green"], hover_color=C["green_h"])
        else:
            self.btn_pause.configure(text="⏸  Pause", fg_color=C["amber"], hover_color=C["amber_h"])

    def update_logs_display(self):
        if not hasattr(self, 'logs_box'):
            return
        search_query = self.log_search_var.get().strip().lower()
        if search_query == "search logs...":
            search_query = ""
            
        self.logs_box.delete('1.0', 'end')
        for log in state.LOG_QUEUE:
            if not search_query or search_query in log.lower():
                self.logs_box.insert('end', log + "\n")
        self.logs_box.see('end')

    def update_dashboard_data(self):
        recalculate_metrics()
        s = _get_stats()
        
        self.applied_metric.configure(text=str(s["applied"]))
        self.interview_metric.configure(text=str(s["interview"]))
        self.offer_metric.configure(text=str(s["offer"]))
        self.avg_score_metric.configure(text=f"{s['avg_score']}%")
        
        # Calculate funnel conversion percentages
        int_rate = f"{(s['interview'] / s['applied'] * 100):.1f}%" if s['applied'] > 0 else "0%"
        offer_rate = f"{(s['offer'] / s['interview'] * 100):.1f}%" if s['interview'] > 0 else "0%"
        today_eval = state.SESSION_STATS.get("evaluated_today", 0)
        today_match = state.SESSION_STATS.get("matches_today", 0)
        
        self.session_stats_lbl.configure(
            text=f"Funnel: {s['applied']} Applied ➔ {s['interview']} Interviews ({int_rate}) ➔ {s['offer']} Offers ({offer_rate})  |  Today: {today_eval} evaluated, {today_match} matches"
        )
        
        # Update Radar stats
        agent = get_radar_agent()
        self.radar_count_lbl.configure(text=f"{agent.new_jobs_found} new jobs found this session")
        if agent.is_running():
            self.radar_status_dot.configure(text_color=C["green"])
            self.radar_status_lbl.configure(text=f"Radar: Active — {len(CONFIG.get('settings', {}).get('queries', []))} queries polling", text_color=C["green"])
        else:
            self.radar_status_dot.configure(text_color=C["dim"])
            self.radar_status_lbl.configure(text="Radar: Inactive — Click 'Radar' to start background polling", text_color=C["muted"])
            
        if state.BOT_RUNNING:
            self.btn_toggle.configure(text="■  Stop Bot", fg_color=C["red"], hover_color=C["red_h"])
        else:
            self.btn_toggle.configure(text="▶  Start Bot", fg_color=C["accent"], hover_color=C["accent_d"])
            
        self.update_logs_display()
        self.draw_vector_charts(s)

    def draw_vector_charts(self, stats=None):
        self.chart_canvas.delete("all")
        s = stats or _get_stats()
        
        w = self.chart_canvas.winfo_width()
        h = self.chart_canvas.winfo_height()
        if w < 100: w = 450
        if h < 100: h = 180

        mid_x = int(w * 0.52)

        # ── 1. Left Half: 7-Day Activity Sparkline ──
        self.chart_canvas.create_text(20, 14, text="7-Day Applications Activity", fill=C["text"], font=F["xs_b"], anchor="w")
        
        # Generate last 7 days list
        today = datetime.now().date()
        date_map = {row[0]: row[1] for row in s["last_7_days"]}
        days_data = []
        for i in range(6, -1, -1):
            d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            label = (today - timedelta(days=i)).strftime("%a")
            days_data.append((label, date_map.get(d, 0)))

        max_activity = max([cnt for _, cnt in days_data] + [1])
        plot_x0, plot_x1 = 25, mid_x - 30
        plot_y0, plot_y1 = 35, h - 30
        step_x = (plot_x1 - plot_x0) / max(len(days_data) - 1, 1)

        # Draw baseline
        self.chart_canvas.create_line(plot_x0, plot_y1, plot_x1, plot_y1, fill=C["border"], width=1)

        points = []
        for idx, (label, count) in enumerate(days_data):
            px = plot_x0 + idx * step_x
            py = plot_y1 - (count / max_activity) * (plot_y1 - plot_y0)
            points.append((px, py, count, label))

        # Connect sparkline dots
        for idx in range(len(points) - 1):
            x1, y1 = points[idx][0], points[idx][1]
            x2, y2 = points[idx + 1][0], points[idx + 1][1]
            self.chart_canvas.create_line(x1, y1, x2, y2, fill=C["cyan"], width=2)

        # Draw points, values, and day labels
        for px, py, count, label in points:
            r = 3
            self.chart_canvas.create_oval(px - r, py - r, px + r, py + r, fill=C["cyan"], outline=C["card"])
            if count > 0:
                self.chart_canvas.create_text(px, py - 10, text=str(count), fill=C["text"], font=F["xs_b"])
            self.chart_canvas.create_text(px, plot_y1 + 12, text=label, fill=C["muted"], font=("Segoe UI", 8))

        # Divider between sparkline and platform breakdown
        self.chart_canvas.create_line(mid_x - 10, 15, mid_x - 10, h - 15, fill=C["border"], width=1)

        # ── 2. Right Half: Platform Breakdown Bar Chart ──
        self.chart_canvas.create_text(mid_x + 10, 14, text="Applications by Platform", fill=C["text"], font=F["xs_b"], anchor="w")
        
        plats = s["by_platform"]
        if not plats:
            # Fallback default display
            plats = [("Indeed", 0), ("Naukri", 0), ("LinkedIn", 0)]

        max_plat_c = max([c for _, c in plats] + [1])
        start_y = 40
        bar_max_w = w - mid_x - 90
        colors_plat = {"indeed": C["blue"], "naukri": C["amber"], "linkedin": "#0077b5", "radar": C["cyan"]}

        for idx, (p_name, count) in enumerate(plats[:4]):
            y = start_y + idx * 28
            if y + 20 > h:
                break
            p_display = (p_name or "Other").capitalize()
            self.chart_canvas.create_text(mid_x + 10, y + 8, text=p_display[:10], fill=C["muted"], font=F["xs_b"], anchor="w")

            bar_w = int((count / max_plat_c) * bar_max_w) if max_plat_c > 0 else 0
            bar_w = max(bar_w, 4) if count > 0 else 2
            color = colors_plat.get(p_name.lower(), C["accent"])

            # Background groove
            self.chart_canvas.create_rectangle(mid_x + 85, y + 2, mid_x + 85 + bar_max_w, y + 14, fill=C["card_hover"], outline="")
            # Filled bar
            self.chart_canvas.create_rectangle(mid_x + 85, y + 2, mid_x + 85 + bar_w, y + 14, fill=color, outline="")
            # Count label
            self.chart_canvas.create_text(mid_x + 95 + bar_max_w, y + 8, text=str(count), fill=C["text"], font=F["xs_b"], anchor="w")

    def send_chat_message(self):
        msg = self.chat_input.get().strip()
        if not msg: return
        
        self.chat_history.configure(state='normal')
        self.chat_history.insert('end', f"You: {msg}\n\n", "user")
        self.chat_history.tag_config("user", foreground=C["accent_h"], font=('Segoe UI', 9, 'bold'))
        self.chat_history.configure(state='disabled')
        self.chat_history.see('end')
        self.chat_input.delete(0, 'end')
        
        def update_chat_ui(reply, commands):
            self.chat_history.configure(state='normal')
            hist_content = self.chat_history.get('1.0', 'end')
            thinking_idx = hist_content.rfind("AI: Thinking...")
            if thinking_idx != -1:
                line_no = hist_content.count('\n', 0, thinking_idx) + 1
                self.chat_history.delete(f"{line_no}.0", 'end')
                
            self.chat_history.insert('end', f"AI: {reply}\n\n", "ai")
            self.chat_history.tag_config("ai", foreground=C["text"])
            self.chat_history.configure(state='disabled')
            self.chat_history.see('end')
            
            if commands:
                for cmd in commands:
                    self.controller.execute_chat_command(cmd)

        def generate_response():
            self.after(0, lambda: self._show_thinking())
            
            logs_list = list(state.LOG_QUEUE)
            logs_context = "\n".join(logs_list[-10:])
            cand_context = json.dumps(CONFIG["candidate"], indent=2)
            resume_text = extract_resume_text()
            
            history_text = get_recent_history_text(limit=10)
            
            # Web Search Integration: Check if user question requests live internet/job market data
            web_context = ""
            msg_lower = msg.lower()
            if any(k in msg_lower for k in ["search", "find", "job", "opening", "salary", "market", "latest", "company", "recruit"]):
                try:
                    q_term = CONFIG["settings"]["queries"][0] if CONFIG["settings"]["queries"] else "Software Engineer"
                    web_results = fast_scrape_jobs(query=q_term, limit=5)
                    if web_results:
                        formatted_jobs = [f"- {j['title']} at {j['company']} ({j['platform']}): {j['url']}" for j in web_results[:5]]
                        web_context = "5. Live Internet Job Market Data (Real-time Web Search):\n" + "\n".join(formatted_jobs) + "\n"
                except Exception as e:
                    web_context = f"5. Live Internet Search Notice: {e}\n"

            prompt = f"""
You are the Job Assistant AI agent. You have access to:
1. Candidate's PDF Resume content:
{resume_text[:3000]}

2. Stored Profile Configuration:
{cand_context}

3. Recent Applied Job History (from database):
{history_text}

4. Recent Operations Logs:
{logs_context}

{web_context}
User Question: {msg}

Instructions:
1. Answer the user's question accurately and politely using the resume content, applied database history, profile configs, or live internet job market data.
2. If they ask about their resume details or past job applications, retrieve it from the context fields.
3. If they ask to search or add a new job role (e.g. "look for Python Developer jobs" or "add React Native"), append a command tag:
[COMMAND: {{"type": "append_query", "value": "Python Developer"}}]
4. If they state a salary preference or expected CTC (e.g. "my expected CTC is 12 LPA"), append a command tag:
[COMMAND: {{"type": "update_qa_vault", "key": "expected_ctc", "value": "12"}}]
"""
            reply = query_ai_model(prompt)
            
            commands = []
            for match_cmd in re.finditer(r'\[COMMAND:\s*(.*?)\]', reply, re.DOTALL):
                try:
                    cmd_json = json.loads(match_cmd.group(1).strip())
                    commands.append(cmd_json)
                    reply = reply.replace(match_cmd.group(0), "").strip()
                except Exception: pass
            
            self.after(0, lambda: update_chat_ui(reply, commands))
                
        threading.Thread(target=generate_response, daemon=True).start()

    def _show_thinking(self):
        self.chat_history.configure(state='normal')
        self.chat_history.insert('end', "AI: Thinking...\n", "thinking")
        self.chat_history.tag_config("thinking", foreground=C["dim"], font=('Segoe UI', 9, 'italic'))
        self.chat_history.configure(state='disabled')
        self.chat_history.see('end')
