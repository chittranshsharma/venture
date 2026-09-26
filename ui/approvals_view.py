import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import core.state as state
from core.db_manager import save_to_db, recalculate_metrics, update_job_status_in_csv
from automation.bot_runner import apply_single_job_async
from ui.components import C, F, create_action_btn


class ApprovalsView(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent, fg_color="transparent")
        self.controller = controller

        # ── Header ──
        title_row = ctk.CTkFrame(self, fg_color="transparent")
        title_row.pack(fill='x', pady=(0, 14))
        lbl_title = ctk.CTkLabel(title_row, text="Doubt Queue Approvals", font=F["h1"], text_color=C["text"])
        lbl_title.pack(side='left')

        # ── Split Layout ──
        card_split = ctk.CTkFrame(self, fg_color="transparent")
        card_split.pack(fill='both', expand=True)
        card_split.columnconfigure(0, weight=1)
        card_split.columnconfigure(1, weight=2)
        card_split.rowconfigure(0, weight=1)

        # ── Left: job list ──
        left_card = ctk.CTkFrame(card_split, fg_color=C["card"], corner_radius=12)
        left_card.grid(row=0, column=0, sticky='nsew', padx=(0, 8))

        columns = ('company', 'role', 'score')
        self.appr_tree = ttk.Treeview(left_card, columns=columns, show='headings', style="Dark.Treeview")
        self.appr_tree.heading('company', text='Company')
        self.appr_tree.heading('role', text='Role')
        self.appr_tree.heading('score', text='Score')
        self.appr_tree.column('company', width=120)
        self.appr_tree.column('role', width=150)
        self.appr_tree.column('score', width=70)
        self.appr_tree.bind("<<TreeviewSelect>>", self.on_approval_select)
        self.appr_tree.pack(fill='both', expand=True, padx=10, pady=10)

        # ── Right: structured detail panel ──
        right_card = ctk.CTkFrame(card_split, fg_color=C["card"], corner_radius=12)
        right_card.grid(row=0, column=1, sticky='nsew', padx=(8, 0))
        right_card.columnconfigure(0, weight=1)
        right_card.rowconfigure(3, weight=1)  # description row expands

        # Row 0: Score badge strip
        score_strip = ctk.CTkFrame(right_card, fg_color=C["input"], corner_radius=8)
        score_strip.grid(row=0, column=0, sticky='ew', padx=14, pady=(12, 6))
        score_strip.columnconfigure(1, weight=1)

        self._lbl_score_val = ctk.CTkLabel(
            score_strip, text="—",
            font=("Segoe UI", 30, "bold"), text_color=C["muted"])
        self._lbl_score_val.grid(row=0, column=0, rowspan=2, padx=(14, 12), pady=8)

        self._lbl_badge = ctk.CTkLabel(
            score_strip, text="NO JOB SELECTED",
            font=("Segoe UI", 11, "bold"), text_color=C["muted"])
        self._lbl_badge.grid(row=0, column=1, sticky='w', padx=(0, 10), pady=(8, 2))

        self._lbl_meta = ctk.CTkLabel(
            score_strip, text="",
            font=("Segoe UI", 10), text_color=C["dim"])
        self._lbl_meta.grid(row=1, column=1, sticky='w', padx=(0, 10), pady=(0, 8))

        # Row 1: Strengths
        s_outer = ctk.CTkFrame(right_card, fg_color="transparent")
        s_outer.grid(row=1, column=0, sticky='ew', padx=14, pady=(4, 2))
        ctk.CTkLabel(
            s_outer, text="✓  STRENGTHS",
            font=("Segoe UI", 10, "bold"), text_color=C["green"]
        ).pack(anchor='w')
        s_box = ctk.CTkFrame(s_outer, fg_color=C["input"], corner_radius=6)
        s_box.pack(fill='x', pady=(3, 0))
        self._lbl_strengths = ctk.CTkLabel(
            s_box, text="Select a job to see match details.",
            font=("Segoe UI", 10), text_color=C["muted"],
            anchor='w', justify='left', wraplength=400)
        self._lbl_strengths.pack(anchor='w', padx=10, pady=7)

        # Row 2: Gaps
        g_outer = ctk.CTkFrame(right_card, fg_color="transparent")
        g_outer.grid(row=2, column=0, sticky='ew', padx=14, pady=(2, 4))
        ctk.CTkLabel(
            g_outer, text="⚠  GAPS",
            font=("Segoe UI", 10, "bold"), text_color=C["amber"]
        ).pack(anchor='w')
        g_box = ctk.CTkFrame(g_outer, fg_color=C["input"], corner_radius=6)
        g_box.pack(fill='x', pady=(3, 0))
        self._lbl_gaps = ctk.CTkLabel(
            g_box, text="—",
            font=("Segoe UI", 10), text_color=C["muted"],
            anchor='w', justify='left', wraplength=400)
        self._lbl_gaps.pack(anchor='w', padx=10, pady=7)

        # Row 3: Reason + JD (scrollable)
        d_outer = ctk.CTkFrame(right_card, fg_color="transparent")
        d_outer.grid(row=3, column=0, sticky='nsew', padx=14, pady=(0, 4))
        d_outer.rowconfigure(1, weight=1)
        d_outer.columnconfigure(0, weight=1)
        ctk.CTkLabel(
            d_outer, text="REASON & JD",
            font=("Segoe UI", 10, "bold"), text_color=C["muted"]
        ).grid(row=0, column=0, sticky='w')
        d_box = ctk.CTkFrame(d_outer, fg_color=C["input"], corner_radius=6)
        d_box.grid(row=1, column=0, sticky='nsew', pady=(3, 0))
        self.appr_desc = scrolledtext.ScrolledText(
            d_box, bg=C["input"], fg=C["text"],
            font=("Segoe UI", 10), wrap='word', bd=0, highlightthickness=0)
        self.appr_desc.pack(fill='both', expand=True, padx=6, pady=6)

        # Row 4: Action buttons
        btn_row = ctk.CTkFrame(right_card, fg_color="transparent")
        btn_row.grid(row=4, column=0, sticky='ew', padx=14, pady=(0, 14))
        btn_appr = create_action_btn(btn_row, "✓  Approve & Apply", self.approve_and_apply_job, "success", "normal")
        btn_appr.pack(side='left', padx=(0, 8))
        btn_rej = create_action_btn(btn_row, "✕  Reject & Skip", self.reject_and_skip_job, "danger", "normal")
        btn_rej.pack(side='left')

        self.load_approvals_table()

    # ── helpers ──────────────────────────────────────────────────

    def _score_color(self, score: int) -> tuple:
        """Return (color_hex, badge_text) based on score range."""
        if score >= 80:
            return C["green"], "STRONG MATCH"
        elif score >= 60:
            return C["amber"], "BORDERLINE"
        return C["red"], "WEAK MATCH"

    def _render_detail(self, job: dict):
        """Populate right panel with structured match info from state.DOUBT_QUEUE entry."""
        score = int(job.get("score", 0))
        color, badge = self._score_color(score)

        self._lbl_score_val.configure(text=f"{score}%", text_color=color)
        self._lbl_badge.configure(text=badge, text_color=color)
        self._lbl_meta.configure(
            text=f"{job.get('company', '')}  ·  {job.get('title', '')}  ·  {job.get('platform', '')}"
        )

        strengths = job.get("strengths", [])
        if isinstance(strengths, list) and strengths:
            self._lbl_strengths.configure(
                text="\n".join(f"✓  {s}" for s in strengths),
                text_color=C["green"])
        else:
            self._lbl_strengths.configure(text="No specific strengths recorded.", text_color=C["muted"])

        gaps = job.get("gaps", [])
        if isinstance(gaps, list) and gaps:
            self._lbl_gaps.configure(
                text="\n".join(f"⚠  {g}" for g in gaps),
                text_color=C["amber"])
        else:
            self._lbl_gaps.configure(text="No gaps identified.", text_color=C["muted"])

        self.appr_desc.delete('1.0', 'end')
        self.appr_desc.insert('end',
            f"REASON:\n{job.get('reason', '')}\n\n"
            f"URL: {job.get('url', '')}\n\n"
            f"JOB DESCRIPTION:\n{job.get('description', '')}")

    def _clear_detail(self):
        self._lbl_score_val.configure(text="—", text_color=C["muted"])
        self._lbl_badge.configure(text="NO JOB SELECTED", text_color=C["muted"])
        self._lbl_meta.configure(text="")
        self._lbl_strengths.configure(text="Select a job to see match details.", text_color=C["muted"])
        self._lbl_gaps.configure(text="—", text_color=C["muted"])
        self.appr_desc.delete('1.0', 'end')

    # ── data ─────────────────────────────────────────────────────

    def load_approvals_table(self):
        for item in self.appr_tree.get_children():
            self.appr_tree.delete(item)
        with state.DOUBT_LOCK:
            for job in state.DOUBT_QUEUE:
                self.appr_tree.insert('', 'end', iid=job.get('url', ''), values=(
                    job.get("company", ""), job.get("title", ""), f"{job.get('score', 0)}%"
                ))
        self._clear_detail()

    def on_approval_select(self, event):
        selected = self.appr_tree.selection()
        if not selected:
            return
        url_iid = selected[0]
        job = None
        with state.DOUBT_LOCK:
            for j in state.DOUBT_QUEUE:
                if j.get("url") == url_iid:
                    job = j
                    break
        if job:
            self._render_detail(job)

    def approve_and_apply_job(self):
        selected = self.appr_tree.selection()
        if not selected:
            return
        url_iid = selected[0]
        job = None
        with state.DOUBT_LOCK:
            for idx, j in enumerate(state.DOUBT_QUEUE):
                if j.get("url") == url_iid:
                    job = state.DOUBT_QUEUE.pop(idx)
                    break
        if not job:
            return
        apply_single_job_async(job)
        self.load_approvals_table()
        self.appr_desc.delete('1.0', 'end')
        messagebox.showinfo("Success", "Applying to approved job in background...")
        recalculate_metrics()
        self.controller.refresh_nav_buttons()

    def reject_and_skip_job(self):
        selected = self.appr_tree.selection()
        if not selected:
            return
        url_iid = selected[0]
        job = None
        with state.DOUBT_LOCK:
            for idx, j in enumerate(state.DOUBT_QUEUE):
                if j.get("url") == url_iid:
                    job = state.DOUBT_QUEUE.pop(idx)
                    break
        if not job:
            return
        updated = update_job_status_in_csv(
            job.get("url", ""), "Approval Needed",
            "Manual User Disapproval", "Manual User Disapproval")
        if not updated:
            save_to_db(job.get("url", ""), job.get("title", ""), job.get("company", ""),
                       job.get("platform", ""), "Manual User Disapproval", "Manual User Disapproval")
        self.load_approvals_table()
        self.appr_desc.delete('1.0', 'end')
        messagebox.showinfo("Skipped", "Job rejected and marked as Manual User Disapproval.")
        recalculate_metrics()
        self.controller.refresh_nav_buttons()
