import os
import csv
import json
import threading
from datetime import datetime
import customtkinter as ctk
import tkinter as tk
from tkinter import ttk
import core.state as state
from core.config_manager import CONFIG, save_config, get_model_name, get_active_model_display
from core.db_manager import APPLIED_DB_PATH, recalculate_metrics
from automation.llm_evaluator import check_live_ai_status
from automation.radar import get_radar_agent
from ui.components import C, F, configure_treeview_style, animate_view_transition
from ui.dashboard_view import DashboardView
from ui.history_view import HistoryView
from ui.suggestions_view import SuggestionsView
from ui.approvals_view import ApprovalsView
from ui.settings_view import SettingsView
from ui.profile_view import ProfileView
from ui.accounts_view import AccountsView
from ui.contacts_view import ContactsView


class AppWindow(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Venture — Career workspace")
        self.geometry("1440x900")
        self.minsize(1200, 800)
        self.configure(fg_color=C["canvas"])

        self.current_view = "dashboard"
        configure_treeview_style()

        # Navigation rail shared by every screen.
        self.sidebar = ctk.CTkFrame(self, fg_color=C["sidebar"], corner_radius=0, width=238)
        self.sidebar.pack(side='left', fill='y')
        self.sidebar.pack_propagate(False)

        self.sidebar_divider = ctk.CTkFrame(self, fg_color=C["border"], width=1, corner_radius=0)
        self.sidebar_divider.pack(side='left', fill='y')

        # ── Brand Header ──
        logo_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        logo_frame.pack(pady=(28, 18), padx=22, anchor='w', fill='x')

        brand_row = ctk.CTkFrame(logo_frame, fg_color="transparent")
        brand_row.pack(anchor='w')

        logo_icon = ctk.CTkLabel(brand_row, text="↗", font=("Segoe UI", 26, "bold"), text_color=C["primary_on"], fg_color=C["accent"], corner_radius=11, width=40, height=40)
        logo_icon.pack(side='left', padx=(0, 10))
        logo_text = ctk.CTkLabel(brand_row, text="venture.", font=F["logo"], text_color=C["text"])
        logo_text.pack(side='left')

        brand_sub = ctk.CTkLabel(logo_frame, text="Your career, in motion", font=F["xs"], text_color=C["tertiary"], anchor="w")
        brand_sub.pack(anchor='w', pady=(10, 0))

        # Hairline separator
        sep = ctk.CTkFrame(self.sidebar, fg_color=C["border"], height=1, corner_radius=0)
        sep.pack(fill='x', padx=18, pady=(8, 14))

        # ── Navigation Items ──
        self.nav_btns = {}

        nav_sections = [
            ("WORKSPACE", [
                ('dashboard',   '⊞', 'Dashboard'),
                ('suggestions', '◎', 'Opportunities'),
                ('approvals',   '⚑', 'Approvals'),
                ('history',     '☰', 'Applications'),
            ]),
            ("INTELLIGENCE", [
                ('venture_ai',  '✦', 'Assistant'),
                ('contacts',    '○', 'Recruiters'),
            ]),
            ("PROFILE", [
                ('profile',     '◉', 'Profile'),
                ('accounts',    '□', 'Credentials'),
            ]),
            ("SYSTEM", [
                ('settings',    '⚙', 'Settings'),
            ])
        ]

        for group_title, items in nav_sections:
            lbl_group = ctk.CTkLabel(
                self.sidebar, text=group_title,
                font=F["xs_b"], text_color=C["tertiary"], anchor="w"
            )
            lbl_group.pack(fill='x', padx=22, pady=(12, 4))

            for name, icon, label in items:
                btn = ctk.CTkButton(
                    self.sidebar,
                    text=f"   {label}",
                    anchor="w",
                    font=F["nav"],
                    fg_color="transparent",
                    hover_color=C["card_hover"],
                    text_color=C["secondary"],
                    corner_radius=9,
                    height=42,
                    border_width=0,
                    cursor="hand2",
                    command=lambda n=name: self.show_view(n)
                )
                btn.pack(fill='x', padx=14, pady=2)
                self.nav_btns[name] = btn

        # A small status and shortcut stay available on every screen.
        status_card = ctk.CTkFrame(
            self.sidebar, fg_color="#202A4B", corner_radius=12,
            border_width=1, border_color=C["hairline_strong"]
        )
        status_card.pack(side='bottom', fill='x', padx=14, pady=16)

        status_row = ctk.CTkFrame(status_card, fg_color="transparent")
        status_row.pack(fill='x', padx=14, pady=(13, 2))
        self.status_dot = ctk.CTkLabel(status_row, text="●", font=("Arial", 9), text_color=C["green"], width=14)
        self.status_dot.pack(side='left', padx=(0, 4))

        self.status_var = tk.StringVar(value="Agent Idle")
        self.status_lbl = ctk.CTkLabel(
            status_row, textvariable=self.status_var,
            font=F["xs_b"], text_color=C["secondary"], anchor="w"
        )
        self.status_lbl.pack(side='left')
        ctk.CTkLabel(status_card, text="Keep your search in motion.", font=F["xs"],
                     text_color=C["secondary"], anchor='w').pack(fill='x', padx=14, pady=(0, 8))
        ctk.CTkButton(status_card, text="Open dashboard  →", command=lambda: self.show_view('dashboard'),
                      fg_color=C["elevated"], hover_color=C["card_hover"],
                      text_color=C["text"], font=F["xs_b"], corner_radius=8,
                      height=32, cursor="hand2").pack(fill='x', padx=12, pady=(0, 12))

        # ── Main Content Container ──
        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.pack(side='right', fill='both', expand=True, padx=28, pady=20)

        self.create_top_navbar()

        # Views Dictionary
        self.views = {}
        self.views['dashboard']   = DashboardView(self.container, self)
        self.views['history']     = HistoryView(self.container, self)
        self.views['suggestions'] = SuggestionsView(self.container, self)
        self.views['approvals']   = ApprovalsView(self.container, self)
        self.views['contacts']    = ContactsView(self.container, self)
        self.views['settings']    = SettingsView(self.container, self)
        self.views['profile']     = ProfileView(self.container, self)
        self.views['accounts']    = AccountsView(self.container, self)

        self.show_view('dashboard')
        self.update_gui_loop()
        self.lift()
        self.attributes('-topmost', True)
        self.after_idle(self.attributes, '-topmost', False)
        self.focus_force()

    def _update_ai_status_async(self):
        def _check():
            try:
                status_text, is_online = check_live_ai_status()
                self._pending_ai_status = (status_text, is_online)
            except Exception:
                self._pending_ai_status = ("Offline", False)
        threading.Thread(target=_check, daemon=True).start()

    def _apply_ai_status(self, status_text, is_online):
        if hasattr(self, 'ind_core_val'):
            color = C["green"] if is_online else C["red"]
            self.ind_core_val.configure(text="AI online" if is_online else "AI offline")
            self.ind_core_dot.configure(text_color=color)

    def create_top_navbar(self):
        self.top_bar = ctk.CTkFrame(
            self.container, fg_color=C["card"], corner_radius=12,
            border_width=1, border_color=C["border"], height=54
        )
        self.top_bar.pack(fill='x', pady=(0, 20))
        self.top_bar.pack_propagate(False)

        self.telemetry_desc_lbl = ctk.CTkLabel(
            self.top_bar, text="Overview",
            font=F["sm_b"], text_color=C["text"], anchor="w"
        )
        self.telemetry_desc_lbl.pack(side='left', padx=20, pady=12)

        right_hud = ctk.CTkFrame(self.top_bar, fg_color="transparent")
        right_hud.pack(side='right', padx=12, pady=9)

        agent_pill = ctk.CTkFrame(right_hud, fg_color=C["elevated"], corner_radius=8)
        agent_pill.pack(side='left', padx=4)
        self.telemetry_dot = ctk.CTkLabel(agent_pill, text="●", font=("Arial", 9), text_color=C["dim"], width=18)
        self.telemetry_dot.pack(side='left', padx=(8, 0))
        self.telemetry_status_lbl = ctk.CTkLabel(agent_pill, text="Standby", font=F["xs_b"], text_color=C["secondary"])
        self.telemetry_status_lbl.pack(side='left', padx=(0, 12), pady=5)

        radar_pill = ctk.CTkFrame(right_hud, fg_color=C["elevated"], corner_radius=8)
        radar_pill.pack(side='left', padx=4)
        self.ind_radar_dot = ctk.CTkLabel(radar_pill, text="●", font=("Arial", 9), text_color=C["dim"], width=18)
        self.ind_radar_dot.pack(side='left', padx=(8, 0))
        self.ind_radar_val = ctk.CTkLabel(radar_pill, text="Radar idle", font=F["xs_b"], text_color=C["secondary"])
        self.ind_radar_val.pack(side='left', padx=(0, 12), pady=5)

        core_pill = ctk.CTkFrame(right_hud, fg_color=C["elevated"], corner_radius=8, cursor="hand2")
        core_pill.pack(side='left', padx=4)
        self.ind_core_dot = ctk.CTkLabel(core_pill, text="●", font=("Arial", 9), text_color=C["dim"], width=18)
        self.ind_core_dot.pack(side='left', padx=(8, 0))
        self.ind_core_val = ctk.CTkLabel(core_pill, text="Checking AI", font=F["xs_b"], text_color=C["secondary"], cursor="hand2")
        self.ind_core_val.pack(side='left', padx=(0, 12), pady=5)
        core_pill.bind("<Button-1>", lambda e: self.show_view('settings'))
        self.ind_core_dot.bind("<Button-1>", lambda e: self.show_view('settings'))
        self.ind_core_val.bind("<Button-1>", lambda e: self.show_view('settings'))

        self._update_ai_status_async()

    def show_view(self, name):
        target_view = name
        if name in ('venture_ai', 'radar'):
            target_view = 'dashboard'
        elif name == 'resume':
            target_view = 'profile'

        if target_view not in self.views:
            return
        self.current_view = name

        def _switch():
            for v in self.views.values():
                v.pack_forget()
            self.views[target_view].pack(fill='both', expand=True)
            self.telemetry_desc_lbl.configure(text={
                'dashboard': 'Overview', 'suggestions': 'Opportunities',
                'approvals': 'Approvals', 'history': 'Applications',
                'contacts': 'Recruiters', 'settings': 'Settings',
                'profile': 'Candidate profile', 'accounts': 'Credentials',
            }.get(target_view, 'Workspace'))
            self.refresh_nav_buttons()

            if name == 'venture_ai' and hasattr(self.views['dashboard'], 'chat_input'):
                dashboard = self.views['dashboard']
                dashboard._parent_canvas.yview_moveto(1.0)
                dashboard.chat_input.focus_set()
            elif name == 'radar' and hasattr(self.views['dashboard'], 'toggle_radar_action'):
                self.views['dashboard'].toggle_radar_action()
            elif name == 'resume' and hasattr(self.views['profile'], 'prof_resume'):
                self.views['profile'].prof_resume.focus_set()

            if target_view == 'history':
                self.views['history'].load_history_table()
            elif target_view == 'suggestions':
                self.views['suggestions'].load_suggestions_table()
            elif target_view == 'approvals':
                self.views['approvals'].load_approvals_table()
            elif target_view == 'contacts':
                self.views['contacts'].load_contacts_table()

        animate_view_transition(self.container, _switch)

    def refresh_nav_buttons(self):
        doubt_count = len(state.DOUBT_QUEUE)
        sug_count = getattr(state, 'SUGGESTION_COUNT', 0)

        nav_labels = {
            'dashboard':   ('⊞', 'Dashboard'),
            'suggestions': ('◎', 'Opportunities'),
            'approvals':   ('⚑', 'Approvals'),
            'history':     ('☰', 'Applications'),
            'venture_ai':  ('✦', 'Assistant'),
            'radar':       ('◬', 'Radar'),
            'contacts':    ('📇', 'Recruiters'),
            'profile':     ('◉', 'Profile'),
            'resume':      ('📄', 'Resume'),
            'accounts':    ('🔒', 'Credentials'),
            'settings':    ('⚙', 'Settings'),
        }

        for name, btn in self.nav_btns.items():
            is_active = (self.current_view == name)
            icon, base_label = nav_labels.get(name, ('•', name.capitalize()))

            if name == 'approvals' and doubt_count > 0:
                text = f"   Approvals  ·  {doubt_count}"
                text_color = C["text"] if is_active else C["secondary"]
            elif name == 'suggestions' and sug_count > 0:
                text = f"   Opportunities  ·  {sug_count}"
                text_color = C["text"] if is_active else C["secondary"]
            else:
                text = f"   {base_label}"
                text_color = C["text"] if is_active else C["secondary"]

            if is_active:
                btn.configure(
                    text=text,
                    fg_color=C["elevated"],
                    text_color=C["text"],
                    font=F["nav_a"],
                    border_width=0,
                    border_color=C["border"]
                )
            else:
                btn.configure(
                    text=text,
                    fg_color="transparent",
                    text_color=text_color,
                    font=F["nav"],
                    border_width=0
                )

    def execute_chat_command(self, cmd):
        c_type = cmd.get("type")
        key = cmd.get("key")
        val = cmd.get("value")

        try:
            if c_type == "append_query":
                existing = CONFIG["settings"].get("queries", [])
                if isinstance(val, list):
                    for v in val:
                        if v and v not in existing: existing.append(v)
                elif isinstance(val, str) and val not in existing:
                    existing.append(val)
                CONFIG["settings"]["queries"] = existing
            elif c_type == "update_setting":
                CONFIG["settings"][key] = val
            elif c_type == "update_candidate":
                CONFIG["candidate"][key] = val
            elif c_type == "update_qa_vault":
                if "qa_vault" not in CONFIG["candidate"]: CONFIG["candidate"]["qa_vault"] = {}
                CONFIG["candidate"]["qa_vault"][key] = str(val)

            save_config()

            self.after(10, self.reload_all_views)
        except Exception as e:
            from core.db_manager import log_message
            log_message(f"Error executing chat command: {e}")

    def reload_all_views(self):
        self.views['settings'].reload_view_data()
        self.views['profile'].reload_profile_fields()
        self._update_ai_status_async()
        recalculate_metrics()
        self.refresh_nav_buttons()

    def update_gui_loop(self):
        if hasattr(self, '_pending_ai_status') and self._pending_ai_status is not None:
            status_text, is_online = self._pending_ai_status
            self._pending_ai_status = None
            self._apply_ai_status(status_text, is_online)

        recalculate_metrics()
        self.views['dashboard'].update_dashboard_data()

        # Update Top Status Bar & Sidebar Status Pill
        agent = get_radar_agent()
        radar_running = agent.is_running()
        if radar_running:
            self.ind_radar_dot.configure(text_color=C["green"])
            self.ind_radar_val.configure(text="Radar active")
        else:
            self.ind_radar_dot.configure(text_color=C["dim"])
            self.ind_radar_val.configure(text="Radar idle")

        if state.BOT_PAUSED:
            self.status_var.set("Agent Paused")
            self.status_dot.configure(text_color=C["amber"])
            self.telemetry_dot.configure(text_color=C["amber"])
            self.telemetry_status_lbl.configure(text="Paused")
        elif state.BOT_RUNNING:
            self.status_var.set("Agent Active")
            self.status_dot.configure(text_color=C["green"])
            self.telemetry_dot.configure(text_color=C["green"])
            self.telemetry_status_lbl.configure(text="Agent running")
        else:
            self.status_var.set("Agent Idle")
            self.status_dot.configure(text_color=C["dim"])
            self.telemetry_dot.configure(text_color=C["dim"])
            self.telemetry_status_lbl.configure(text="Standby")

        self.refresh_nav_buttons()
        self.after(1000, self.update_gui_loop)
