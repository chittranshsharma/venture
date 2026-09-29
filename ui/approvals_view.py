import json
import webbrowser
import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import core.state as state
from core.db_manager import (
    save_to_db, recalculate_metrics, update_job_status_in_csv,
    log_approval_decision, get_pending_approvals
)
from automation.bot_runner import apply_single_job_async
from ui.components import C, F, create_action_btn


class ApprovalsView(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent, fg_color="transparent")
        self.controller = controller
        self._active_jobs = {}

        # ── Header ──
        title_row = ctk.CTkFrame(self, fg_color="transparent")
        title_row.pack(fill='x', pady=(0, 14))
        
        title_box = ctk.CTkFrame(title_row, fg_color="transparent")
        title_box.pack(side='left', anchor='w')
        
        lbl_title = ctk.CTkLabel(title_box, text="Doubt Queue Approvals", font=F["h1"], text_color=C["ink"], anchor="w")
        lbl_title.pack(anchor='w')
        lbl_sub = ctk.CTkLabel(
            title_box,
            text="Human-in-the-loop decision center: review, approve, or skip calibrated opportunities.",
            font=F["xs"], text_color=C["ash"], anchor="w"
        )
        lbl_sub.pack(anchor='w', pady=(2, 0))

        # ── Split Layout ──
        card_split = ctk.CTkFrame(self, fg_color="transparent")
        card_split.pack(fill='both', expand=True)
        card_split.columnconfigure(0, weight=1)
        card_split.columnconfigure(1, weight=2)
        card_split.rowconfigure(0, weight=1)

        # ── Left: Job List Card ──
        left_card = ctk.CTkFrame(
            card_split, fg_color=C["card"], corner_radius=12,
            border_width=1, border_color=C["border"]
        )
        left_card.grid(row=0, column=0, sticky='nsew', padx=(0, 8))

        columns = ('company', 'role', 'score')
        self.appr_tree = ttk.Treeview(left_card, columns=columns, show='headings', style="Dark.Treeview")
        self.appr_tree.heading('company', text='Company')
        self.appr_tree.heading('role', text='Role / Opportunity')
        self.appr_tree.heading('score', text='Fit')
        self.appr_tree.column('company', width=110)
        self.appr_tree.column('role', width=160)
        self.appr_tree.column('score', width=60)
        self.appr_tree.bind("<<TreeviewSelect>>", self.on_approval_select)
        self.appr_tree.pack(fill='both', expand=True, padx=12, pady=12)

        # ── Right: Structured Detail Panel ──
        right_card = ctk.CTkFrame(
            card_split, fg_color=C["card"], corner_radius=12,
            border_width=1, border_color=C["border"]
        )
        right_card.grid(row=0, column=1, sticky='nsew', padx=(8, 0))
        right_card.columnconfigure(0, weight=1)
        right_card.rowconfigure(4, weight=1)

        # Row 0: Score Badge Strip (Surface Deep)
        score_strip = ctk.CTkFrame(
            right_card, fg_color=C["deep"], corner_radius=8,
            border_width=1, border_color=C["hairline_strong"]
        )
        score_strip.grid(row=0, column=0, sticky='ew', padx=14, pady=(12, 6))
        score_strip.columnconfigure(1, weight=1)

        self._lbl_score_val = ctk.CTkLabel(
            score_strip, text="—",
            font=F["metric"], text_color=C["charcoal"]
        )
        self._lbl_score_val.grid(row=0, column=0, rowspan=2, padx=(14, 12), pady=8)

        self._lbl_badge = ctk.CTkLabel(
            score_strip, text="NO JOB SELECTED",
            font=F["xs_b"], text_color=C["muted"]
        )
        self._lbl_badge.grid(row=0, column=1, sticky='w', padx=(0, 10), pady=(8, 2))

        self._lbl_meta = ctk.CTkLabel(
            score_strip, text="",
            font=F["xs"], text_color=C["ash"]
        )
        self._lbl_meta.grid(row=1, column=1, sticky='w', padx=(0, 10), pady=(0, 8))

        # Row 1: Evidence & Telemetry Bar
        ev_box = ctk.CTkFrame(right_card, fg_color="transparent")
        ev_box.grid(row=1, column=0, sticky='ew', padx=14, pady=(2, 4))
        self._lbl_evidence = ctk.CTkLabel(
            ev_box, text="EVIDENCE: RAG Cosine — · Skill Coverage —",
            font=F["xs"], text_color=C["ash"], anchor='w'
        )
        self._lbl_evidence.pack(anchor='w')

        # Row 2: Strengths (Competencies)
        s_outer = ctk.CTkFrame(right_card, fg_color="transparent")
        s_outer.grid(row=2, column=0, sticky='ew', padx=14, pady=(2, 2))
        ctk.CTkLabel(
            s_outer, text="✓  STRENGTHS & MATCHES",
            font=F["xs_b"], text_color=C["green"]
        ).pack(anchor='w')
        s_box = ctk.CTkFrame(
            s_outer, fg_color=C["deep"], corner_radius=6,
            border_width=1, border_color=C["hairline_strong"]
        )
        s_box.pack(fill='x', pady=(3, 0))
        self._lbl_strengths = ctk.CTkLabel(
            s_box, text="Select a job to inspect match criteria.",
            font=F["sm"], text_color=C["charcoal"],
            anchor='w', justify='left', wraplength=420
        )
        self._lbl_strengths.pack(anchor='w', padx=12, pady=8)

        # Row 3: Gaps & Soft Penalties
        g_outer = ctk.CTkFrame(right_card, fg_color="transparent")
        g_outer.grid(row=3, column=0, sticky='ew', padx=14, pady=(2, 4))
        ctk.CTkLabel(
            g_outer, text="⚠  GAPS & SOFT CONSTRAINTS",
            font=F["xs_b"], text_color=C["amber"]
        ).pack(anchor='w')
        g_box = ctk.CTkFrame(
            g_outer, fg_color=C["deep"], corner_radius=6,
            border_width=1, border_color=C["hairline_strong"]
        )
        g_box.pack(fill='x', pady=(3, 0))
        self._lbl_gaps = ctk.CTkLabel(
            g_box, text="—",
            font=F["sm"], text_color=C["charcoal"],
            anchor='w', justify='left', wraplength=420
        )
        self._lbl_gaps.pack(anchor='w', padx=12, pady=8)

        # Row 4: Reason & JD (Scrollable well in Surface Deep)
        d_outer = ctk.CTkFrame(right_card, fg_color="transparent")
        d_outer.grid(row=4, column=0, sticky='nsew', padx=14, pady=(0, 6))
        d_outer.rowconfigure(1, weight=1)
        d_outer.columnconfigure(0, weight=1)
        ctk.CTkLabel(
            d_outer, text="DECISION BREAKDOWN & JD",
            font=F["xs_b"], text_color=C["muted"]
        ).grid(row=0, column=0, sticky='w')
        d_box = ctk.CTkFrame(
            d_outer, fg_color=C["deep"], corner_radius=6,
            border_width=1, border_color=C["hairline_strong"]
        )
        d_box.grid(row=1, column=0, sticky='nsew', pady=(3, 0))
        self.appr_desc = scrolledtext.ScrolledText(
            d_box, bg=C["deep"], fg=C["text"],
            font=F["sm"], wrap='word', bd=0, highlightthickness=0
        )
        self.appr_desc.pack(fill='both', expand=True, padx=8, pady=8)

        # Row 5: Action Buttons (Review / Approve / Skip)
        btn_row = ctk.CTkFrame(right_card, fg_color="transparent")
        btn_row.grid(row=5, column=0, sticky='ew', padx=14, pady=(0, 14))
        
        btn_rev = create_action_btn(btn_row, "🔍  Review", self.review_job_in_browser, "secondary", "normal")
        btn_rev.pack(side='left', padx=(0, 8))

        btn_appr = create_action_btn(btn_row, "✓  Approve & Apply", self.approve_and_apply_job, "primary", "normal")
        btn_appr.pack(side='left', padx=(0, 8))

        btn_rej = create_action_btn(btn_row, "✕  Reject & Skip", self.reject_and_skip_job, "danger", "normal")
        btn_rej.pack(side='left', padx=(0, 8))

        ctk.CTkLabel(btn_row, text="Reason:", font=F["xs_b"], text_color=C["muted"]).pack(side='left', padx=(4, 4))
        self.reject_reason_var = ctk.StringVar(value="unsure")
        self.reject_reason_menu = ctk.CTkOptionMenu(
            btn_row,
            values=["unsure", "not_fit", "location", "seniority", "duplicate", "company", "other"],
            variable=self.reject_reason_var,
            width=110,
            height=32,
            fg_color=C["surface"],
            button_color=C["deep"],
            text_color=C["text"],
            font=F["xs"]
        )
        self.reject_reason_menu.pack(side='left')

        self.load_approvals_table()

    # ── helpers ──────────────────────────────────────────────────

    def _render_detail(self, job: dict):
        """Populate right panel with persisted evaluation evidence without recomputing."""
        score = int(job.get("score", 0))
        features = job.get("features")
        if not features and job.get("features_json"):
            try:
                features = json.loads(job["features_json"])
            except Exception:
                features = {}
        if not features:
            features = {}

        is_stretch = job.get("is_stretch", False) or features.get("is_stretch", False)
        penalties = job.get("penalties") or features.get("penalties", [])
        stretch_signals = job.get("stretch_signals") or features.get("stretch_signals", [])

        if is_stretch:
            color = "#38bdf8"  # vibrant cyan
            badge = "⚡ STRETCH OPPORTUNITY"
        elif job.get("source") == "explore":
            color = C["amber"]
            badge = "EXPLORATION SAMPLE"
        elif score >= 80:
            color = C["green"]
            badge = "STRONG MATCH"
        elif score >= 60:
            color = C["amber"]
            badge = "BORDERLINE FIT"
        else:
            color = C["red"]
            badge = "WEAK MATCH"

        self._lbl_score_val.configure(text=f"{score}%", text_color=color)
        self._lbl_badge.configure(text=badge, text_color=color)

        meta_parts = [job.get('company', ''), job.get('title', ''), job.get('platform', '')]
        self._lbl_meta.configure(text="  ·  ".join(p for p in meta_parts if p))

        # Evidence Bar
        rag_val = job.get("rag_score") if job.get("rag_score") is not None else features.get("rag_score")
        rag_str = f"RAG: {rag_val:.2f}" if rag_val is not None else "RAG: —"
        cov_val = features.get("jd_coverage")
        cov_str = f"JD Coverage: {cov_val * 100:.0f}%" if cov_val is not None else "JD Coverage: —"
        net_val = features.get("net_adjustment")
        net_str = f"Net Modifier: {net_val:+.1f} pts" if net_val is not None else ""
        ev_text = f"EVIDENCE:  {rag_str}   |   {cov_str}" + (f"   |   {net_str}" if net_str else "")
        self._lbl_evidence.configure(text=ev_text)

        # Strengths
        strengths = job.get("strengths") or features.get("matched_skills") or []
        if isinstance(strengths, list) and strengths:
            self._lbl_strengths.configure(
                text="\n".join(f"✓  {s}" for s in strengths[:5]),
                text_color=C["green"]
            )
        else:
            self._lbl_strengths.configure(text="No specific strengths recorded.", text_color=C["muted"])

        # Gaps & Soft Penalties
        gaps_items = []
        if penalties:
            for p in penalties:
                gaps_items.append(f"Soft Penalty: -{p.get('value', 0):.0f} pts ({p.get('evidence', p.get('type', ''))})")
        raw_gaps = job.get("gaps") or features.get("missing_skills") or []
        if isinstance(raw_gaps, list):
            for g in raw_gaps:
                gaps_items.append(str(g))

        if gaps_items:
            self._lbl_gaps.configure(
                text="\n".join(f"⚠  {g}" for g in gaps_items[:5]),
                text_color=C["amber"]
            )
        else:
            self._lbl_gaps.configure(text="No gaps identified.", text_color=C["muted"])

        # Breakdown and JD
        decision_reason = job.get("decision_reason") or job.get("reason", "")
        self.appr_desc.delete('1.0', 'end')
        self.appr_desc.insert('end',
            f"DECISION BREAKDOWN:\n{decision_reason}\n\n"
            f"URL: {job.get('url', '')}\n\n"
            f"JOB DESCRIPTION:\n{job.get('description', '')}"
        )

    def _clear_detail(self):
        self._lbl_score_val.configure(text="—", text_color=C["muted"])
        self._lbl_badge.configure(text="NO JOB SELECTED", text_color=C["muted"])
        self._lbl_meta.configure(text="")
        self._lbl_evidence.configure(text="EVIDENCE: RAG Cosine — · Skill Coverage —")
        self._lbl_strengths.configure(text="Select a job to see match details.", text_color=C["muted"])
        self._lbl_gaps.configure(text="—", text_color=C["muted"])
        self.appr_desc.delete('1.0', 'end')

    # ── data ─────────────────────────────────────────────────────

    def load_approvals_table(self):
        for item in self.appr_tree.get_children():
            self.appr_tree.delete(item)

        # Merge in-memory doubt queue with persisted pending approvals from DB
        seen_urls = set()
        jobs_to_show = []

        with state.DOUBT_LOCK:
            for job in state.DOUBT_QUEUE:
                u = job.get("url")
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    jobs_to_show.append(job)

        db_pending = get_pending_approvals()
        for job in db_pending:
            u = job.get("url")
            if u and u not in seen_urls:
                seen_urls.add(u)
                jobs_to_show.append(job)

        self._active_jobs = {j["url"]: j for j in jobs_to_show if j.get("url")}

        for job in jobs_to_show:
            tag = ""
            if job.get("is_stretch"):
                tag = " [⚡ STRETCH]"
            elif job.get("source") == "explore":
                tag = " [EXPLORE]"
            self.appr_tree.insert('', 'end', iid=job.get('url', ''), values=(
                job.get("company", ""), f"{job.get('title', '')}{tag}", f"{job.get('score', 0)}%"
            ))
        self._clear_detail()

    def on_approval_select(self, event):
        selected = self.appr_tree.selection()
        if not selected:
            return
        url_iid = selected[0]
        job = self._active_jobs.get(url_iid)
        if not job:
            with state.DOUBT_LOCK:
                for j in state.DOUBT_QUEUE:
                    if j.get("url") == url_iid:
                        job = j
                        break
        if job:
            self._render_detail(job)

    def review_job_in_browser(self):
        """Open the job's URL in the system browser for detailed review."""
        selected = self.appr_tree.selection()
        if not selected:
            return
        url_iid = selected[0]
        job = self._active_jobs.get(url_iid)
        url = (job.get("url") if job else url_iid) or ""
        if url:
            webbrowser.open(url)

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
            job = self._active_jobs.get(url_iid)
        if not job:
            return

        # Log human approve decision as training label before dispatching
        log_approval_decision(
            url=job.get("url", ""),
            label="approve",
            score=job.get("score"),
            eval_model=job.get("eval_model"),
            prompt_version=job.get("prompt_version"),
            rag_score=job.get("rag_score"),
            seniority=job.get("seniority"),
            skill_overlap=job.get("skill_overlap"),
            content_hash=job.get("content_hash"),
            source=job.get("source", "queue"),
            propensity=job.get("propensity", 1.0),
        )
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
            job = self._active_jobs.get(url_iid)
        if not job:
            return

        # Log human reject decision as training label with reject reason
        reason = self.reject_reason_var.get() or "unsure"
        log_approval_decision(
            url=job.get("url", ""),
            label="reject",
            reject_reason=reason,
            score=job.get("score"),
            eval_model=job.get("eval_model"),
            prompt_version=job.get("prompt_version"),
            rag_score=job.get("rag_score"),
            seniority=job.get("seniority"),
            skill_overlap=job.get("skill_overlap"),
            content_hash=job.get("content_hash"),
            source=job.get("source", "queue"),
            propensity=job.get("propensity", 1.0),
        )
        updated = update_job_status_in_csv(
            job.get("url", ""), "Approval Needed",
            f"Manual User Disapproval ({reason})", f"Manual User Disapproval ({reason})")
        if not updated:
            save_to_db(job.get("url", ""), job.get("title", ""), job.get("company", ""),
                       job.get("platform", ""), "Manual User Disapproval", f"Manual User Disapproval ({reason})")
        self.load_approvals_table()
        self.appr_desc.delete('1.0', 'end')
        messagebox.showinfo("Skipped", f"Job rejected ({reason}) and logged for model training.")
        recalculate_metrics()
        self.controller.refresh_nav_buttons()
