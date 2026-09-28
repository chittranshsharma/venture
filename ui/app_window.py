import os
import csv
import json
import threading
from datetime import datetime
import customtkinter as ctk
import tkinter as tk
from tkinter import ttk
import core.state as state
from core.config_manager import CONFIG, CONFIG_PATH, get_model_name, get_active_model_display
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
        self.title("VENTURE — Autonomous Career Operations")
        self.geometry("1300x840")
        self.minsize(1100, 720)
        self.configure(fg_color=C["canvas"])

        self.current_view = "dashboard"
        configure_treeview_style()        # ── Sidebar Container (Clean Dark Rail with 1px Hairline Right Border) ──
        self.sidebar = ctk.CTkFrame(self, fg_color=C["sidebar"], corner_radius=0, width=224)
        self.sidebar.pack(side='left', fill='y')
        self.sidebar.pack_propagate(False)

        self.sidebar_divider = ctk.CTkFrame(self, fg_color=C["border"], width=1, corner_radius=0)
        self.sidebar_divider.pack(side='left', fill='y')

        # ── Brand Header ──
        logo_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        logo_frame.pack(pady=(22, 10), padx=16, anchor='w', fill='x')

        brand_row = ctk.CTkFrame(logo_frame, fg_color="transparent")
        brand_row.pack(anchor='w')

        logo_icon = ctk.CTkLabel(brand_row, text="◆", font=("Segoe UI", 12, "bold"), text_color=C["accent"])
        logo_icon.pack(side='left', padx=(0, 6))
        logo_text = ctk.CTkLabel(brand_row, text="VENTURE", font=F["logo"], text_color=C["text"])
        logo_text.pack(side='left')

        brand_sub = ctk.CTkLabel(logo_frame, text="Autonomous Career Engine", font=F["xs"], text_color=C["tertiary"], anchor="w")
        brand_sub.pack(anchor='w', padx=(18, 0), pady=(1, 0))

        # Hairline separator
        sep = ctk.CTkFrame(self.sidebar, fg_color=C["border"], height=1, corner_radius=0)
        sep.pack(fill='x', padx=16, pady=(12, 10))

        # ── Navigation Items ──
        self.nav_btns = {}

        nav_sections = [
            ("WORKSPACE", [
                ('dashboard',   '⊞', 'Dashboard'),
                ('suggestions', '◎', 'Opportunities'),
                ('approvals',   '⚑', 'Approvals'),
                ('history',     '☰', 'Applied History'),
            ]),
            ("INTELLIGENCE", [
                ('contacts',    '📇', 'Recruiters'),
                ('profile',     '◉', 'Profile & QA'),
            ]),
            ("SYSTEM", [
                ('accounts',    '🔒', 'Credentials'),
                ('settings',    '⚙', 'Settings'),
            ])
        ]

        for group_title, items in nav_sections:
            lbl_group = ctk.CTkLabel(
                self.sidebar, text=group_title,
                font=F["xs_b"], text_color=C["tertiary"], anchor="w"
            )
            lbl_group.pack(fill='x', padx=16, pady=(8, 2))

            for name, icon, label in items:
                btn = ctk.CTkButton(
                    self.sidebar,
                    text=f"  {icon}   {label}",
                    anchor="w",
                    font=F["nav"],
                    fg_color="transparent",
                    hover_color=C["card_hover"],
                    text_color=C["secondary"],
                    corner_radius=6,
                    height=34,
                    border_width=0,
                    cursor="hand2",
                    command=lambda n=name: self.show_view(n)
                )
                btn.pack(fill='x', padx=10, pady=2)
                self.nav_btns[name] = btn

        # ── Sidebar Bottom Status Pill ──
        status_card = ctk.CTkFrame(
            self.sidebar, fg_color=C["elevated"], corner_radius=6,
            border_width=1, border_color=C["border"], height=36
        )
        status_card.pack(side='bottom', fill='x', padx=12, pady=12)

        self.status_dot = ctk.CTkLabel(status_card, text="●", font=("Arial", 9), text_color=C["green"], width=14)
        self.status_dot.pack(side='left', padx=(10, 2), pady=8)

        self.status_var = tk.StringVar(value="Agent Idle")
        self.status_lbl = ctk.CTkLabel(
            status_card, textvariable=self.status_var,
            font=F["xs"], text_color=C["secondary"], anchor="w"
        )
        self.status_lbl.pack(side='left', padx=(2, 10), pady=8)

        # ── Main Content Container ──
        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.pack(side='right', fill='both', expand=True, padx=(18, 20), pady=16)

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
            clean_name = status_text.replace("Local (", "").replace(")", "").replace("Cloud (", "").replace(")", "")
            clean_name = clean_name.replace("🤖", "").replace("☁️", "").replace(": Ready", "").strip()
            self.ind_core_val.configure(text=clean_name or "Ready")
            self.ind_core_dot.configure(text_color=color)

    def create_top_navbar(self):
        # ── Top Bar Card: Prestigious System Status Bar ──
        self.top_bar = ctk.CTkFrame(
            self.container, fg_color=C["card"], corner_radius=8,
            border_width=1, border_color=C["border"], height=52
        )
        self.top_bar.pack(fill='x', pady=(0, 14))
        self.top_bar.pack_propagate(False)

        bar_inner = ctk.CTkFrame(self.top_bar, fg_color="transparent")
        bar_inner.pack(fill='both', expand=True, padx=16)

        # Left: Brand indicator & Live Operational state
        left_hud = ctk.CTkFrame(bar_inner, fg_color="transparent")
        left_hud.pack(side='left', fill='y')

        self.telemetry_dot = ctk.CTkLabel(left_hud, text="●", font=("Arial", 10), text_color=C["dim"], width=14)
        self.telemetry_dot.pack(side='left', pady=15)

        self.telemetry_status_lbl = ctk.CTkLabel(
            left_hud, text="VENTURE STANDBY",
            font=F["mono_sm"], text_color=C["text"], anchor="w"
        )
        self.telemetry_status_lbl.pack(side='left', padx=(4, 12), pady=15)

        # Hairline separator
        ctk.CTkFrame(left_hud, fg_color=C["border"], width=1).pack(side='left', fill='y', pady=12)

        self.telemetry_desc_lbl = ctk.CTkLabel(
            left_hud, text="Autonomous Career Engine · Multi-Source Pipeline",
            font=F["xs"], text_color=C["tertiary"]
        ).pack(side='left', padx=(12, 0), pady=15)

        # Right: Technical Telemetry Triad (CORE, RADAR, DATABASE)
        right_hud = ctk.CTkFrame(bar_inner, fg_color="transparent")
        right_hud.pack(side='right', fill='y')

        # Version Pill
        badge = ctk.CTkLabel(
            right_hud, text="  v3.5  ",
            fg_color=C["elevated"], text_color=C["secondary"],
            font=F["xs"], corner_radius=4, height=22
        )
        badge.pack(side='right', pady=14, padx=(12, 0))

        # DATABASE segment
        db_f = ctk.CTkFrame(right_hud, fg_color="transparent")
        db_f.pack(side='right', fill='y', padx=(10, 0))
        ctk.CTkLabel(db_f, text="●", font=("Arial", 8), text_color=C["green"]).pack(side='left', pady=16)
        ctk.CTkLabel(db_f, text=" DB:", font=F["xs_b"], text_color=C["tertiary"]).pack(side='left', pady=16)
        self.ind_db = ctk.CTkLabel(db_f, text=" Synced", font=F["xs"], text_color=C["secondary"])
        self.ind_db.pack(side='left', pady=16)

        ctk.CTkFrame(right_hud, fg_color=C["border"], width=1).pack(side='right', fill='y', pady=14, padx=8)

        # RADAR segment
        radar_f = ctk.CTkFrame(right_hud, fg_color="transparent")
        radar_f.pack(side='right', fill='y', padx=(10, 0))
        self.ind_radar_dot = ctk.CTkLabel(radar_f, text="●", font=("Arial", 8), text_color=C["dim"])
        self.ind_radar_dot.pack(side='left', pady=16)
        ctk.CTkLabel(radar_f, text=" RADAR:", font=F["xs_b"], text_color=C["tertiary"]).pack(side='left', pady=16)
        self.ind_radar_val = ctk.CTkLabel(radar_f, text=" Idle", font=F["xs"], text_color=C["secondary"])
        self.ind_radar_val.pack(side='left', pady=16)

        ctk.CTkFrame(right_hud, fg_color=C["border"], width=1).pack(side='right', fill='y', pady=14, padx=8)

        # CORE segment
        core_f = ctk.CTkFrame(right_hud, fg_color="transparent")
        core_f.pack(side='right', fill='y', padx=(10, 0))
        self.ind_core_dot = ctk.CTkLabel(core_f, text="●", font=("Arial", 8), text_color=C["green"])
        self.ind_core_dot.pack(side='left', pady=16)
        ctk.CTkLabel(core_f, text=" CORE:", font=F["xs_b"], text_color=C["tertiary"]).pack(side='left', pady=16)
        self.ind_core_val = ctk.CTkLabel(core_f, text=" Checking...", font=F["xs"], text_color=C["secondary"], cursor="hand2")
        self.ind_core_val.pack(side='left', pady=16)
        self.ind_core_val.bind("<Button-1>", lambda e: self.show_view('settings'))

        self._update_ai_status_async()

    def show_view(self, name):
        if name not in self.views:
            return
        self.current_view = name

        def _switch():
            for v in self.views.values():
                v.pack_forget()
            self.views[name].pack(fill='both', expand=True)
            self.refresh_nav_buttons()

            if name == 'history':
                self.views['history'].load_history_table()
            elif name == 'suggestions':
                self.views['suggestions'].load_suggestions_table()
            elif name == 'approvals':
                self.views['approvals'].load_approvals_table()
            elif name == 'contacts':
                self.views['contacts'].load_contacts_table()

        animate_view_transition(self.container, _switch)

    def refresh_nav_buttons(self):
        doubt_count = len(state.DOUBT_QUEUE)
        sug_count = getattr(state, 'SUGGESTION_COUNT', 0)

        nav_labels = {
            'dashboard':   ('⊞', 'Dashboard'),
            'suggestions': ('◎', 'Opportunities'),
            'approvals':   ('⚑', 'Approvals'),
            'history':     ('☰', 'Applied History'),
            'contacts':    ('📇', 'Recruiters'),
            'profile':     ('◉', 'Profile & QA'),
            'accounts':    ('🔒', 'Credentials'),
            'settings':    ('⚙', 'Settings'),
        }

        for name, btn in self.nav_btns.items():
            is_active = self.current_view == name
            icon, base_label = nav_labels.get(name, ('•', name.capitalize()))

            if name == 'approvals' and doubt_count > 0:
                text = f"  {icon}   Approvals ({doubt_count})"
                text_color = C["red"] if not is_active else C["text"]
            elif name == 'suggestions' and sug_count > 0:
                text = f"  {icon}   Opportunities ({sug_count})"
                text_color = C["amber"] if not is_active else C["text"]
            else:
                text = f"  {icon}   {base_label}"
                text_color = C["text"] if is_active else C["secondary"]

            if is_active:
                btn.configure(
                    text=text,
                    fg_color=C["elevated"],
                    text_color=C["text"],
                    font=F["nav_a"],
                    border_width=1,
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

            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(CONFIG, f, indent=4)

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
            self.ind_radar_val.configure(text=" Active")
        else:
            self.ind_radar_dot.configure(text_color=C["dim"])
            self.ind_radar_val.configure(text=" Idle")

        if state.BOT_PAUSED:
            self.status_var.set("Agent Paused")
            self.status_dot.configure(text_color=C["amber"])
            self.telemetry_dot.configure(text_color=C["amber"])
            self.telemetry_status_lbl.configure(text="VENTURE PAUSED")
        elif state.BOT_RUNNING:
            self.status_var.set("Agent Active")
            self.status_dot.configure(text_color=C["green"])
            self.telemetry_dot.configure(text_color=C["green"])
            self.telemetry_status_lbl.configure(text="VENTURE ACTIVE")
        else:
            self.status_var.set("Agent Idle")
            self.status_dot.configure(text_color=C["dim"])
            self.telemetry_dot.configure(text_color=C["dim"])
            self.telemetry_status_lbl.configure(text="VENTURE STANDBY")

        self.refresh_nav_buttons()
        self.after(1000, self.update_gui_loop)
