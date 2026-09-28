import json
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
from core.config_manager import CONFIG, CONFIG_PATH, LOCATION_DATA, get_installed_ollama_models
from core.db_manager import log_message, recalculate_metrics
from core.credential_store import get_credential, store_credential
from ui.components import C, F, TagChipContainer, add_form_input, create_action_btn, add_section_divider

class SettingsView(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent, fg_color="transparent")
        self.controller = controller
        
        # ── Header ──
        title_row = ctk.CTkFrame(self, fg_color="transparent")
        title_row.pack(fill='x', pady=(0, 14))
        
        title_box = ctk.CTkFrame(title_row, fg_color="transparent")
        title_box.pack(side='left', anchor='w')
        
        lbl_title = ctk.CTkLabel(title_box, text="AI & Search Settings", font=F["h1"], text_color=C["ink"], anchor="w")
        lbl_title.pack(anchor='w')
        lbl_sub = ctk.CTkLabel(title_box, text="Model provider configuration, telemetry thresholds, and execution filters.", font=F["xs"], text_color=C["ash"], anchor="w")
        lbl_sub.pack(anchor='w', pady=(2, 0))
        
        # ── Scrollable Card ──
        card = ctk.CTkScrollableFrame(
            self, fg_color=C["card"], corner_radius=12,
            border_width=1, border_color=C["border"]
        )
        card.pack(fill='both', expand=True)
        
        # ═══════════════════════════════════════════════════
        # AI Provider & Model Selector Block
        # ═══════════════════════════════════════════════════
        add_section_divider(card, "AI Engine Provider")
        
        f_ai = ctk.CTkFrame(card, fg_color="transparent")
        f_ai.pack(fill='x', padx=16, pady=6)
        
        provider_val = CONFIG["settings"].get("ai_provider", "local")
        if provider_val == "gemini": provider_val = "cloud"
        
        self.seg_provider = ctk.CTkSegmentedButton(
            f_ai,
            values=["Local Ollama (Offline)", "Cloud AI / REST API"],
            command=self.on_provider_changed,
            selected_color=C["primary"],
            selected_hover_color=C["accent_h"],
            unselected_color=C["input"],
            unselected_hover_color=C["card_hover"],
            text_color=C["primary_on"],
            font=F["xs_b"],
            corner_radius=8,
            height=36
        )
        self.seg_provider.pack(fill='x', pady=(0, 10))
        self.seg_provider.set("Cloud AI / REST API" if provider_val == "cloud" else "Local Ollama (Offline)")

        # Frame for Local Ollama Settings
        self.f_ollama_sub = ctk.CTkFrame(f_ai, fg_color="transparent")
        self.f_ollama_sub.pack(fill='x', pady=5)
        
        lbl_ollama = ctk.CTkLabel(self.f_ollama_sub, text="Local Ollama Model", font=F["sm_b"], text_color=C["muted"], anchor="w")
        lbl_ollama.pack(anchor='w', pady=(0, 4))
        
        model_row = ctk.CTkFrame(self.f_ollama_sub, fg_color="transparent")
        model_row.pack(fill='x')
        
        self.sel_model = ctk.CTkOptionMenu(model_row, fg_color=C["input"], button_color=C["card_hover"],
                                          button_hover_color=C["border"], text_color=C["ink"],
                                          dropdown_fg_color=C["card"], dropdown_text_color=C["ink"], dropdown_hover_color=C["elevated"], font=F["sm"], corner_radius=8, height=36)
        self.sel_model.pack(side='left', fill='x', expand=True, padx=(0, 10))
        
        btn_refresh_models = create_action_btn(model_row, "Refresh Models", self.refresh_models, "outline", "small")
        btn_refresh_models.pack(side='left')

        # Frame for Universal Cloud AI Settings
        self.f_cloud_sub = ctk.CTkFrame(f_ai, fg_color="transparent")
        self.f_cloud_sub.pack(fill='x', pady=5)
        
        # Preset Selector
        f_preset = ctk.CTkFrame(self.f_cloud_sub, fg_color="transparent")
        f_preset.pack(fill='x', pady=(0, 8))
        
        lbl_preset = ctk.CTkLabel(f_preset, text="Cloud Provider Preset", font=F["sm_b"], text_color=C["muted"], anchor="w")
        lbl_preset.pack(anchor='w', pady=(0, 4))
        
        self.sel_preset = ctk.CTkOptionMenu(f_preset, values=["OpenAI / ChatGPT", "DeepSeek", "Groq", "Google AI", "Custom Endpoint"],
                                           command=self.on_cloud_preset_selected,
                                           fg_color=C["input"], button_color=C["card_hover"],
                                           button_hover_color=C["border"], text_color=C["ink"],
                                           dropdown_fg_color=C["card"], dropdown_text_color=C["ink"], dropdown_hover_color=C["elevated"], font=F["sm"], corner_radius=8, height=36)
        self.sel_preset.pack(fill='x')
        self.sel_preset.set(CONFIG["settings"].get("cloud_ai_preset", "OpenAI / ChatGPT"))
        
        # Endpoint & Model Row
        cloud_grid = ctk.CTkFrame(self.f_cloud_sub, fg_color="transparent")
        cloud_grid.pack(fill='x', pady=4)
        cloud_grid.columnconfigure((0, 1), weight=1, uniform="equal")
        
        f_url = ctk.CTkFrame(cloud_grid, fg_color="transparent")
        f_url.grid(row=0, column=0, sticky='ew', padx=(0, 6))
        ctk.CTkLabel(f_url, text="Base API Endpoint URL", font=F["sm_b"], text_color=C["muted"], anchor="w").pack(anchor='w', pady=(0, 4))
        
        self.entry_cloud_url = ctk.CTkEntry(f_url, fg_color=C["input"], border_color=C["border"],
                                           text_color=C["ink"], font=F["xs"], corner_radius=8, height=36)
        self.entry_cloud_url.pack(fill='x')
        self.entry_cloud_url.insert(0, CONFIG["settings"].get("cloud_ai_base_url", "https://api.openai.com/v1"))
        
        f_cmod = ctk.CTkFrame(cloud_grid, fg_color="transparent")
        f_cmod.grid(row=0, column=1, sticky='ew', padx=(6, 0))
        ctk.CTkLabel(f_cmod, text="Model Name / ID", font=F["sm_b"], text_color=C["muted"], anchor="w").pack(anchor='w', pady=(0, 4))
        
        self.entry_cloud_model = ctk.CTkEntry(f_cmod, fg_color=C["input"], border_color=C["border"],
                                             text_color=C["ink"], font=F["xs"], corner_radius=8, height=36)
        self.entry_cloud_model.pack(fill='x')
        self.entry_cloud_model.insert(0, CONFIG["settings"].get("cloud_ai_model", "gpt-4o-mini"))
        
        # Authentication Segmented Control
        f_auth_type = ctk.CTkFrame(self.f_cloud_sub, fg_color="transparent")
        f_auth_type.pack(fill='x', pady=(10, 4))
        ctk.CTkLabel(f_auth_type, text="Authentication Method", font=F["sm_b"], text_color=C["muted"], anchor="w").pack(anchor='w', pady=(0, 4))
        
        current_auth = CONFIG["settings"].get("cloud_ai_auth_type", "api_key")
        self.seg_auth = ctk.CTkSegmentedButton(
            f_auth_type,
            values=["API Key / Bearer Token", "Username & Password (Basic Auth)"],
            command=self.on_auth_type_changed,
            selected_color=C["accent"],
            selected_hover_color=C["accent_d"],
            unselected_color=C["input"],
            unselected_hover_color=C["card_hover"],
            text_color=C["ink"],
            font=F["xs_b"],
            corner_radius=8,
            height=34
        )
        self.seg_auth.pack(fill='x')
        self.seg_auth.set("Username & Password (Basic Auth)" if current_auth == "user_pass" else "API Key / Bearer Token")

        # API Key Frame
        self.f_key_sub = ctk.CTkFrame(self.f_cloud_sub, fg_color="transparent")
        self.f_key_sub.pack(fill='x', pady=4)
        ctk.CTkLabel(self.f_key_sub, text="API Key / Token", font=F["sm_b"], text_color=C["muted"], anchor="w").pack(anchor='w', pady=(0, 4))
        self.entry_cloud_key = ctk.CTkEntry(self.f_key_sub, fg_color=C["input"], border_color=C["border"],
                                           text_color=C["ink"], font=F["sm"], corner_radius=8, height=36, show="*")
        self.entry_cloud_key.pack(fill='x')
        self.entry_cloud_key.insert(0, get_credential("settings.cloud_ai_api_key", CONFIG["settings"].get("cloud_ai_api_key", CONFIG["settings"].get("gemini_api_key", ""))))

        # Username & Password Frame
        self.f_userpass_sub = ctk.CTkFrame(self.f_cloud_sub, fg_color="transparent")
        self.f_userpass_sub.pack(fill='x', pady=4)
        up_grid = ctk.CTkFrame(self.f_userpass_sub, fg_color="transparent")
        up_grid.pack(fill='x')
        up_grid.columnconfigure((0, 1), weight=1, uniform="equal")
        
        f_u = ctk.CTkFrame(up_grid, fg_color="transparent")
        f_u.grid(row=0, column=0, sticky='ew', padx=(0, 6))
        ctk.CTkLabel(f_u, text="API Username", font=F["sm_b"], text_color=C["muted"], anchor="w").pack(anchor='w', pady=(0, 4))
        self.entry_cloud_user = ctk.CTkEntry(f_u, fg_color=C["input"], border_color=C["border"],
                                            text_color=C["ink"], font=F["xs"], corner_radius=8, height=36)
        self.entry_cloud_user.pack(fill='x')
        self.entry_cloud_user.insert(0, get_credential("settings.cloud_ai_username", CONFIG["settings"].get("cloud_ai_username", "")))
        
        f_p = ctk.CTkFrame(up_grid, fg_color="transparent")
        f_p.grid(row=0, column=1, sticky='ew', padx=(6, 0))
        ctk.CTkLabel(f_p, text="API Password", font=F["sm_b"], text_color=C["muted"], anchor="w").pack(anchor='w', pady=(0, 4))
        self.entry_cloud_pass = ctk.CTkEntry(f_p, fg_color=C["input"], border_color=C["border"],
                                            text_color=C["ink"], font=F["xs"], corner_radius=8, height=36, show="*")
        self.entry_cloud_pass.pack(fill='x')
        self.entry_cloud_pass.insert(0, get_credential("settings.cloud_ai_password", CONFIG["settings"].get("cloud_ai_password", "")))
        
        btn_test_cloud = create_action_btn(self.f_cloud_sub, "⚡ Test Connection", self.test_cloud_connection, "success", "small")
        btn_test_cloud.pack(anchor='w', pady=(10, 0))

        self.on_provider_changed(self.seg_provider.get())
        self.on_auth_type_changed(self.seg_auth.get())
        self.refresh_models()

        # ═══════════════════════════════════════════════════
        # Job Search Configuration
        # ═══════════════════════════════════════════════════
        add_section_divider(card, "Job Search Queries")

        self.settings_queries = TagChipContainer(card, CONFIG["settings"]["queries"], "Target Job Queries (Press Enter or Comma to add)", lambda val: self.update_config_list("queries", val))
        self.settings_queries.pack(fill='x', pady=5)
        
        self.settings_skip = TagChipContainer(card, CONFIG["settings"]["skip_keywords"], "Skip Keywords (Press Enter or Comma to add)", lambda val: self.update_config_list("skip_keywords", val))
        self.settings_skip.pack(fill='x', pady=5)

        # ═══════════════════════════════════════════════════
        # Geographic Settings
        # ═══════════════════════════════════════════════════
        add_section_divider(card, "Geographic Location")

        f_scope = ctk.CTkFrame(card, fg_color="transparent")
        f_scope.pack(fill='x', padx=16, pady=6)
        ctk.CTkLabel(f_scope, text="Location Scope", font=F["sm_b"], text_color=C["muted"], anchor="w").pack(anchor='w', pady=(0, 4))
        
        self.sel_scope = ctk.CTkOptionMenu(f_scope, values=["Entire Country", "Custom Cities & States"],
                                          command=self.on_scope_changed,
                                          fg_color=C["input"], button_color=C["card_hover"],
                                          button_hover_color=C["border"], text_color=C["ink"],
                                          dropdown_fg_color=C["card"], dropdown_text_color=C["ink"], dropdown_hover_color=C["elevated"], font=F["sm"], corner_radius=8, height=36)
        self.sel_scope.pack(fill='x')
        self.sel_scope.set(CONFIG["settings"].get("location_scope", "Entire Country"))

        # Hierarchical Location Selection
        self.f_hierarchical = ctk.CTkFrame(card, fg_color="transparent")
        self.f_hierarchical.pack(fill='x', padx=16, pady=10)
        
        ctk.CTkLabel(self.f_hierarchical, text="Location Hierarchy Selector", font=F["h3"], text_color=C["ink"]).pack(anchor='w', pady=(0, 6))
        
        drop_grid = ctk.CTkFrame(self.f_hierarchical, fg_color="transparent")
        drop_grid.pack(fill='x')
        drop_grid.columnconfigure((0, 1, 2), weight=1, uniform="equal")
        
        fc = ctk.CTkFrame(drop_grid, fg_color="transparent")
        fc.grid(row=0, column=0, padx=4, sticky='ew')
        ctk.CTkLabel(fc, text="Country", font=F["sm_b"], text_color=C["muted"], anchor="w").pack(anchor='w', pady=(0, 2))
        self.sel_country = ctk.CTkOptionMenu(fc, values=list(LOCATION_DATA.keys()), command=self.on_country_selected,
                                             fg_color=C["input"], button_color=C["elevated"], text_color=C["ink"], dropdown_fg_color=C["card"], dropdown_text_color=C["ink"], dropdown_hover_color=C["elevated"], font=F["xs"], corner_radius=8, height=34)
        self.sel_country.pack(fill='x')
        
        fs = ctk.CTkFrame(drop_grid, fg_color="transparent")
        fs.grid(row=0, column=1, padx=4, sticky='ew')
        ctk.CTkLabel(fs, text="State", font=F["sm_b"], text_color=C["muted"], anchor="w").pack(anchor='w', pady=(0, 2))
        self.sel_state = ctk.CTkOptionMenu(fs, values=["Select State"], command=self.on_state_selected,
                                           fg_color=C["input"], button_color=C["elevated"], text_color=C["ink"], dropdown_fg_color=C["card"], dropdown_text_color=C["ink"], dropdown_hover_color=C["elevated"], font=F["xs"], corner_radius=8, height=34)
        self.sel_state.pack(fill='x')
        
        fcy = ctk.CTkFrame(drop_grid, fg_color="transparent")
        fcy.grid(row=0, column=2, padx=4, sticky='ew')
        ctk.CTkLabel(fcy, text="City", font=F["sm_b"], text_color=C["muted"], anchor="w").pack(anchor='w', pady=(0, 2))
        self.sel_city = ctk.CTkOptionMenu(fcy, values=["Select City"],
                                          fg_color=C["input"], button_color=C["elevated"], text_color=C["ink"], dropdown_fg_color=C["card"], dropdown_text_color=C["ink"], dropdown_hover_color=C["elevated"], font=F["xs"], corner_radius=8, height=34)
        self.sel_city.pack(fill='x')
        
        self.sel_country.set("India")
        self.on_country_selected("India")
        
        btn_add_loc = create_action_btn(self.f_hierarchical, "Add Location", self.add_hierarchical_location, "success", "small")
        btn_add_loc.pack(anchor='w', pady=(10, 0))

        self.settings_locations = TagChipContainer(card, CONFIG["settings"].get("preferred_locations", []), "Selected Search Locations", lambda val: self.update_config_list("preferred_locations", val))
        self.settings_locations.pack(fill='x', pady=5)
        
        self.on_scope_changed(self.sel_scope.get())

        # ═══════════════════════════════════════════════════
        # Account Safety & Anti-Bot Rate Limiter
        # ═══════════════════════════════════════════════════
        add_section_divider(card, "Account Safety & Anti-Bot Protection")
        
        safe_frame = ctk.CTkFrame(card, fg_color="transparent")
        safe_frame.pack(fill='x', padx=16, pady=5)
        
        self.sw_safe_mode = ctk.CTkSwitch(safe_frame, text="  Enable Account Safety Mode (Daily Cap & Human Emulation Delays)",
                                         progress_color=C["accent"], button_color=C["text"],
                                         button_hover_color=C["accent_h"], text_color=C["ink"], font=F["sm_b"])
        self.sw_safe_mode.pack(anchor='w', pady=4)
        if CONFIG["settings"].get("safe_mode", True):
            self.sw_safe_mode.select()
        else:
            self.sw_safe_mode.deselect()

        self.settings_daily_cap = add_form_input(card, "Daily Application Safety Cap (Max per day)")
        self.settings_min_delay = add_form_input(card, "Minimum Delay Between Applications (Seconds)")
        self.settings_max_delay = add_form_input(card, "Maximum Delay Between Applications (Seconds)")
        
        self.settings_daily_cap.insert(0, str(CONFIG["settings"].get("daily_apply_cap", 25)))
        self.settings_min_delay.insert(0, str(CONFIG["settings"].get("min_delay_seconds", 15)))
        self.settings_max_delay.insert(0, str(CONFIG["settings"].get("max_delay_seconds", 45)))

        # ═══════════════════════════════════════════════════
        # Search Thresholds & Filters
        # ═══════════════════════════════════════════════════
        add_section_divider(card, "Search Thresholds")

        self.settings_min_score = add_form_input(card, "Minimum Match Score (%)")
        self.settings_max_jobs = add_form_input(card, "Max Jobs to Check Per Query")
        self.settings_radar_interval = add_form_input(card, "Background Radar Scan Interval (Seconds, min 10)")
        
        self.settings_min_score.insert(0, str(CONFIG["settings"]["min_score"]))
        self.settings_max_jobs.insert(0, str(CONFIG["settings"].get("max_jobs_per_query", 10)))
        self.settings_radar_interval.insert(0, str(CONFIG["settings"].get("radar_interval_seconds", 60)))
        
        # Filters
        add_section_divider(card, "Job Search Filters")
        
        drop_frame = ctk.CTkFrame(card, fg_color="transparent")
        drop_frame.pack(fill='x', padx=16, pady=5)
        drop_frame.columnconfigure((0, 1, 2), weight=1, uniform="equal")
        
        f_exp = ctk.CTkFrame(drop_frame, fg_color="transparent")
        f_exp.grid(row=0, column=0, padx=5, sticky='ew')
        ctk.CTkLabel(f_exp, text="Experience Level", font=F["sm_b"], text_color=C["muted"], anchor="w").pack(anchor='w', pady=(0, 4))
        self.sel_exp = ctk.CTkOptionMenu(f_exp, values=["All", "Fresher", "Mid", "Senior"],
                                        fg_color=C["input"], button_color=C["elevated"], text_color=C["ink"], dropdown_fg_color=C["card"], dropdown_text_color=C["ink"], dropdown_hover_color=C["elevated"], font=F["xs"], corner_radius=8, height=34)
        self.sel_exp.pack(fill='x')
        self.sel_exp.set(CONFIG["settings"].get("experience_level", "All"))
        
        f_jt = ctk.CTkFrame(drop_frame, fg_color="transparent")
        f_jt.grid(row=0, column=1, padx=5, sticky='ew')
        ctk.CTkLabel(f_jt, text="Job Type", font=F["sm_b"], text_color=C["muted"], anchor="w").pack(anchor='w', pady=(0, 4))
        self.sel_jt = ctk.CTkOptionMenu(f_jt, values=["All", "Full-time", "Internship", "Contract"],
                                       fg_color=C["input"], button_color=C["elevated"], text_color=C["ink"], dropdown_fg_color=C["card"], dropdown_text_color=C["ink"], dropdown_hover_color=C["elevated"], font=F["xs"], corner_radius=8, height=34)
        self.sel_jt.pack(fill='x')
        self.sel_jt.set(CONFIG["settings"].get("job_type", "All"))
        
        f_loc = ctk.CTkFrame(drop_frame, fg_color="transparent")
        f_loc.grid(row=0, column=2, padx=5, sticky='ew')
        ctk.CTkLabel(f_loc, text="Location Mode", font=F["sm_b"], text_color=C["muted"], anchor="w").pack(anchor='w', pady=(0, 4))
        self.sel_loc = ctk.CTkOptionMenu(f_loc, values=["All", "Remote", "On-site", "Hybrid"],
                                        fg_color=C["input"], button_color=C["elevated"], text_color=C["ink"], dropdown_fg_color=C["card"], dropdown_text_color=C["ink"], dropdown_hover_color=C["elevated"], font=F["xs"], corner_radius=8, height=34)
        self.sel_loc.pack(fill='x')
        self.sel_loc.set(CONFIG["settings"].get("location_type", "All"))
        
        # ═══════════════════════════════════════════════════
        # Target Platforms (with Switches!)
        # ═══════════════════════════════════════════════════
        add_section_divider(card, "Target Platforms")
        
        plat_frame = ctk.CTkFrame(card, fg_color="transparent")
        plat_frame.pack(fill='x', padx=16, pady=5)
        
        self.plat_switches = {}
        for plat in ["Indeed", "Naukri", "LinkedIn"]:
            is_on = plat in CONFIG["settings"].get("target_platforms", [])
            sw = ctk.CTkSwitch(plat_frame, text=f"  {plat}",
                               progress_color=C["accent"], button_color=C["text"],
                               button_hover_color=C["accent_h"], text_color=C["ink"],
                               font=F["sm"])
            sw.pack(anchor='w', pady=4)
            if is_on: sw.select()
            else: sw.deselect()
            self.plat_switches[plat] = sw
            
        ctk.CTkLabel(card, text="Coming Soon: Hirist, Foundit, Wellfound", font=F["xs"],
                     text_color=C["dim"], anchor="w").pack(anchor='w', padx=16, pady=(8, 0))

        # ═══════════════════════════════════════════════════
        # Company Career Pages (Direct Crawl)
        # ═══════════════════════════════════════════════════
        add_section_divider(card, "Company Career Pages")

        career_info = ctk.CTkLabel(
            card,
            text="Add direct company careers page URLs (e.g. jobs.lever.co/stripe, boards.greenhouse.io/notion).\nRadar will crawl these on every poll cycle alongside job boards.",
            font=F["xs"], text_color=C["ash"], anchor="w", justify="left"
        )
        career_info.pack(anchor='w', padx=16, pady=(0, 8))

        # Input row: URL + Company Name + Add button
        career_input_row = ctk.CTkFrame(card, fg_color="transparent")
        career_input_row.pack(fill='x', padx=16, pady=(0, 6))
        career_input_row.columnconfigure(0, weight=3)
        career_input_row.columnconfigure(1, weight=1)
        career_input_row.columnconfigure(2, weight=0)

        self.entry_career_url = ctk.CTkEntry(
            career_input_row,
            placeholder_text="https://jobs.lever.co/stripe",
            fg_color=C["input"], border_color=C["border"],
            text_color=C["ink"], font=F["xs"], corner_radius=8, height=36
        )
        self.entry_career_url.grid(row=0, column=0, sticky='ew', padx=(0, 6))

        self.entry_career_company = ctk.CTkEntry(
            career_input_row,
            placeholder_text="Company Name",
            fg_color=C["input"], border_color=C["border"],
            text_color=C["ink"], font=F["xs"], corner_radius=8, height=36
        )
        self.entry_career_company.grid(row=0, column=1, sticky='ew', padx=(0, 6))

        btn_add_career = create_action_btn(career_input_row, "+ Add", self._add_career_page, "success", "small")
        btn_add_career.grid(row=0, column=2)

        # Scrollable list of added pages
        self._career_list_frame = ctk.CTkScrollableFrame(
            card, fg_color=C["elevated"], corner_radius=8, height=130
        )
        self._career_list_frame.pack(fill='x', padx=16, pady=(0, 8))
        self._career_list_frame.columnconfigure(0, weight=1)
        self._career_pages_widgets = []  # track rows for removal

        self._render_career_pages()

        # ═══════════════════════════════════════════════════
        # Save Button
        # ═══════════════════════════════════════════════════
        btn_frame = ctk.CTkFrame(card, fg_color="transparent")
        btn_frame.pack(anchor='w', padx=16, pady=(24, 16))
        btn_save = create_action_btn(btn_frame, "Save All Settings", self.save_settings_action, "primary", "large")
        btn_save.pack(side='left')


    # ── Career Pages Handlers ──
    def _render_career_pages(self):
        """Rebuild the career pages list display from config."""
        for w in self._career_list_frame.winfo_children():
            w.destroy()
        pages = CONFIG.get("settings", {}).get("company_career_pages", [])
        if not pages:
            ctk.CTkLabel(
                self._career_list_frame,
                text="No company career pages added yet.",
                font=F["xs"], text_color=C["dim"], anchor="w"
            ).pack(anchor='w', padx=8, pady=8)
            return
        for i, entry in enumerate(pages):
            url = entry.get("url", "") if isinstance(entry, dict) else entry
            company = entry.get("company", "") if isinstance(entry, dict) else ""
            row = ctk.CTkFrame(self._career_list_frame, fg_color="transparent")
            row.pack(fill='x', pady=2)
            # Colored dot
            ctk.CTkLabel(row, text="🏢", font=("Segoe UI", 10), width=20).pack(side='left', padx=(4, 4))
            # Company + URL label
            display = f"{company}  —  {url}" if company else url
            ctk.CTkLabel(
                row, text=display[:80] + ("..." if len(display) > 80 else ""),
                font=F["xs"], text_color=C["body"], anchor="w"
            ).pack(side='left', fill='x', expand=True)
            # Remove button
            btn_rm = ctk.CTkButton(
                row, text="✕", width=24, height=22,
                fg_color="transparent", hover_color=C["red_glow"],
                text_color=C["muted"], font=F["xs_b"], corner_radius=4, cursor="hand2",
                command=lambda idx=i: self._remove_career_page(idx)
            )
            btn_rm.pack(side='right', padx=(0, 4))

    def _add_career_page(self):
        url = self.entry_career_url.get().strip()
        company = self.entry_career_company.get().strip()
        if not url:
            return
        if not url.startswith("http"):
            url = "https://" + url
        pages = list(CONFIG.get("settings", {}).get("company_career_pages", []))
        # Dedup by URL
        existing_urls = [e.get("url", "") if isinstance(e, dict) else e for e in pages]
        if url in existing_urls:
            return
        pages.append({"url": url, "company": company})
        CONFIG.setdefault("settings", {})["company_career_pages"] = pages
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(CONFIG, f, indent=4)
        self.entry_career_url.delete(0, 'end')
        self.entry_career_company.delete(0, 'end')
        self._render_career_pages()
        log_message(f"🏢 Career page added: {company or url}")

    def _remove_career_page(self, idx: int):
        pages = list(CONFIG.get("settings", {}).get("company_career_pages", []))
        if 0 <= idx < len(pages):
            removed = pages.pop(idx)
            CONFIG["settings"]["company_career_pages"] = pages
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(CONFIG, f, indent=4)
            self._render_career_pages()
            name = removed.get("company") or removed.get("url", "") if isinstance(removed, dict) else removed
            log_message(f"🏢 Career page removed: {name}")

    # ── Handler Methods ──
    def on_provider_changed(self, value):
        if "Cloud" in value:
            self.f_ollama_sub.pack_forget()
            self.f_cloud_sub.pack(fill='x', pady=5)
        else:
            self.f_cloud_sub.pack_forget()
            self.f_ollama_sub.pack(fill='x', pady=5)

    def on_auth_type_changed(self, value):
        if "Username" in value:
            self.f_key_sub.pack_forget()
            self.f_userpass_sub.pack(fill='x', pady=4)
        else:
            self.f_userpass_sub.pack_forget()
            self.f_key_sub.pack(fill='x', pady=4)

    def on_cloud_preset_selected(self, preset):
        if "OpenAI" in preset:
            self.entry_cloud_url.delete(0, 'end'); self.entry_cloud_url.insert(0, "https://api.openai.com/v1")
            self.entry_cloud_model.delete(0, 'end'); self.entry_cloud_model.insert(0, "gpt-4o-mini")
        elif "DeepSeek" in preset:
            self.entry_cloud_url.delete(0, 'end'); self.entry_cloud_url.insert(0, "https://api.deepseek.com/v1")
            self.entry_cloud_model.delete(0, 'end'); self.entry_cloud_model.insert(0, "deepseek-chat")
        elif "Groq" in preset:
            self.entry_cloud_url.delete(0, 'end'); self.entry_cloud_url.insert(0, "https://api.groq.com/openai/v1")
            self.entry_cloud_model.delete(0, 'end'); self.entry_cloud_model.insert(0, "openai/gpt-oss-120b")
        elif "Google" in preset:
            self.entry_cloud_url.delete(0, 'end'); self.entry_cloud_url.insert(0, "https://generativelanguage.googleapis.com/v1beta")
            self.entry_cloud_model.delete(0, 'end'); self.entry_cloud_model.insert(0, "gemini-2.5-flash")

    def test_cloud_connection(self):
        url = self.entry_cloud_url.get().strip()
        model = self.entry_cloud_model.get().strip()
        atype = "user_pass" if "Username" in self.seg_auth.get() else "api_key"
        key = self.entry_cloud_key.get().strip()
        uname = self.entry_cloud_user.get().strip()
        passwd = self.entry_cloud_pass.get().strip()
        
        if atype == "user_pass" and (not uname or not passwd):
            messagebox.showerror("Error", "Please enter both API Username and Password.")
            return
        elif atype == "api_key" and not key:
            messagebox.showerror("Error", "Please enter an API Key / Token.")
            return
            
        def _do_test():
            import urllib.request
            import base64
            headers = {
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            if atype == "user_pass" or (uname and passwd and not key):
                up = f"{uname}:{passwd}".encode('utf-8')
                headers['Authorization'] = f"Basic {base64.b64encode(up).decode('utf-8')}"
            elif key:
                if "generativelanguage.googleapis.com" in url:
                    headers['x-goog-api-key'] = key
                else:
                    headers['Authorization'] = f"Bearer {key}"
                    
            endpoint = f"{url.rstrip('/')}/models/{model}:generateContent" if "generativelanguage.googleapis.com" in url else (f"{url.rstrip('/')}/chat/completions" if not url.endswith("/chat/completions") else url)
            payload = {"contents": [{"parts": [{"text": "Hello"}]}]} if "generativelanguage.googleapis.com" in url else {"model": model, "messages": [{"role": "user", "content": "Hello"}]}
            
            try:
                req = urllib.request.Request(endpoint, data=json.dumps(payload).encode('utf-8'), headers=headers)
                with urllib.request.urlopen(req, timeout=12) as resp:
                    res = json.loads(resp.read().decode('utf-8'))
                    self.after(0, lambda: messagebox.showinfo("Success", f"Cloud AI ({model}) connected successfully!"))
            except Exception as e:
                err_msg = str(e)
                if hasattr(e, 'read'):
                    try:
                        err_body = json.loads(e.read().decode('utf-8'))
                        if isinstance(err_body, dict) and "error" in err_body:
                            err_msg = err_body["error"].get("message", str(err_body["error"]))
                    except Exception:
                        pass
                self.after(0, lambda msg=err_msg: messagebox.showerror("Connection Error", f"Cloud AI test failed: {msg}"))
                
        import threading
        threading.Thread(target=_do_test, daemon=True).start()

    def refresh_models(self):
        models = get_installed_ollama_models()
        if models:
            self.sel_model.configure(values=models)
            current_model = CONFIG["settings"].get("ollama_model", "qwen2.5:latest")
            if current_model in models:
                self.sel_model.set(current_model)
            else:
                self.sel_model.set(models[0])
        else:
            self.sel_model.configure(values=["qwen2.5:latest"])
            self.sel_model.set("qwen2.5:latest")

    def on_country_selected(self, country):
        states = list(LOCATION_DATA.get(country, {}).keys())
        if states:
            self.sel_state.configure(values=states)
            self.sel_state.set(states[0])
            self.on_state_selected(states[0])
            
    def on_state_selected(self, state):
        country = self.sel_country.get()
        cities = LOCATION_DATA.get(country, {}).get(state, ["All Cities"])
        if cities:
            self.sel_city.configure(values=cities)
            self.sel_city.set(cities[0])

    def add_hierarchical_location(self):
        country = self.sel_country.get()
        state = self.sel_state.get()
        city = self.sel_city.get()
        loc_str = f"{city}, {state}, {country}"
        
        current_items = self.settings_locations.items
        if loc_str not in current_items:
            current_items.append(loc_str)
            self.settings_locations.update_items(current_items)
            self.update_config_list("preferred_locations", current_items)
            self.controller.refresh_nav_buttons()

    def on_scope_changed(self, scope):
        if scope == "Entire Country":
            self.f_hierarchical.pack_forget()
            self.settings_locations.pack_forget()
        else:
            self.f_hierarchical.pack(fill='x', padx=16, pady=10, after=self.sel_scope.master)
            self.settings_locations.pack(fill='x', pady=5, after=self.f_hierarchical)

    def update_config_list(self, key, val):
        CONFIG["settings"][key] = val
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(CONFIG, f, indent=4)
        recalculate_metrics()
        self.controller.refresh_nav_buttons()

    def save_settings_action(self):
        try:
            # ── Validation checks (Upgrade 3.3) ──
            try:
                min_sc = int(self.settings_min_score.get().strip())
                if not (0 <= min_sc <= 100):
                    messagebox.showerror("Validation Error", "Minimum Match Score must be between 0 and 100%.")
                    return
            except ValueError:
                messagebox.showerror("Validation Error", "Minimum Match Score must be a valid integer.")
                return

            try:
                max_jb = int(self.settings_max_jobs.get().strip())
                if not (1 <= max_jb <= 100):
                    messagebox.showerror("Validation Error", "Max Jobs to Check must be between 1 and 100.")
                    return
            except ValueError:
                messagebox.showerror("Validation Error", "Max Jobs to Check must be a valid integer.")
                return

            try:
                radar_int = int(self.settings_radar_interval.get().strip())
                if radar_int < 10:
                    messagebox.showerror("Validation Error", "Radar Scan Interval must be at least 10 seconds.")
                    return
            except ValueError:
                messagebox.showerror("Validation Error", "Radar Scan Interval must be a valid integer.")
                return

            try:
                daily_cap = int(self.settings_daily_cap.get().strip())
                if not (1 <= daily_cap <= 200):
                    messagebox.showerror("Validation Error", "Daily Application Safety Cap must be between 1 and 200.")
                    return
            except ValueError:
                messagebox.showerror("Validation Error", "Daily Application Safety Cap must be a valid integer.")
                return

            try:
                min_d = int(self.settings_min_delay.get().strip())
                max_d = int(self.settings_max_delay.get().strip())
                if min_d < 1 or max_d < 1:
                    messagebox.showerror("Validation Error", "Delays must be at least 1 second.")
                    return
                if max_d < min_d:
                    messagebox.showerror("Validation Error", "Maximum delay cannot be less than minimum delay.")
                    return
            except ValueError:
                messagebox.showerror("Validation Error", "Delay values must be valid integers.")
                return
            
            plat_list = []
            for plat, sw in self.plat_switches.items():
                if sw.get(): plat_list.append(plat)
                
            CONFIG["settings"]["min_score"] = min_sc
            CONFIG["settings"]["max_jobs_per_query"] = max_jb
            CONFIG["settings"]["radar_interval_seconds"] = radar_int
            CONFIG["settings"]["safe_mode"] = True if self.sw_safe_mode.get() else False
            CONFIG["settings"]["daily_apply_cap"] = daily_cap
            CONFIG["settings"]["min_delay_seconds"] = min_d
            CONFIG["settings"]["max_delay_seconds"] = max_d
            CONFIG["settings"]["experience_level"] = self.sel_exp.get()
            CONFIG["settings"]["job_type"] = self.sel_jt.get()
            CONFIG["settings"]["location_type"] = self.sel_loc.get()
            CONFIG["settings"]["location_scope"] = self.sel_scope.get()
            CONFIG["settings"]["target_platforms"] = plat_list
            CONFIG["settings"]["ollama_model"] = self.sel_model.get()
            
            CONFIG["settings"]["ai_provider"] = "cloud" if "Cloud" in self.seg_provider.get() else "local"
            CONFIG["settings"]["cloud_ai_preset"] = self.sel_preset.get()
            CONFIG["settings"]["cloud_ai_base_url"] = self.entry_cloud_url.get().strip()
            CONFIG["settings"]["cloud_ai_model"] = self.entry_cloud_model.get().strip()
            CONFIG["settings"]["cloud_ai_auth_type"] = "user_pass" if "Username" in self.seg_auth.get() else "api_key"
            store_credential("settings.cloud_ai_api_key", self.entry_cloud_key.get().strip())
            store_credential("settings.cloud_ai_username", self.entry_cloud_user.get().strip())
            store_credential("settings.cloud_ai_password", self.entry_cloud_pass.get().strip())
            CONFIG["settings"]["cloud_ai_api_key"] = ""
            CONFIG["settings"]["cloud_ai_username"] = ""
            CONFIG["settings"]["cloud_ai_password"] = ""
            
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(CONFIG, f, indent=4)
            messagebox.showinfo("Success", "All settings validated & saved successfully!")
            log_message("Settings validated & saved via Desktop GUI.")
            recalculate_metrics()
            self.controller.refresh_nav_buttons()
        except Exception as e:
            messagebox.showerror("Error", f"Could not save settings: {e}")
            
    def reload_view_data(self):
        self.settings_queries.update_items(CONFIG["settings"]["queries"])
        self.settings_min_score.delete(0, 'end')
        self.settings_min_score.insert(0, str(CONFIG["settings"]["min_score"]))
        self.settings_max_jobs.delete(0, 'end')
        self.settings_max_jobs.insert(0, str(CONFIG["settings"].get("max_jobs_per_query", 10)))
        if hasattr(self, 'settings_radar_interval'):
            self.settings_radar_interval.delete(0, 'end')
            self.settings_radar_interval.insert(0, str(CONFIG["settings"].get("radar_interval_seconds", 60)))
        
        prov_val = CONFIG["settings"].get("ai_provider", "local")
        if prov_val == "gemini": prov_val = "cloud"
        self.seg_provider.set("Cloud AI / REST API" if prov_val == "cloud" else "Local Ollama (Offline)")
        
        self.sel_preset.set(CONFIG["settings"].get("cloud_ai_preset", "OpenAI / ChatGPT"))
        self.entry_cloud_url.delete(0, 'end'); self.entry_cloud_url.insert(0, CONFIG["settings"].get("cloud_ai_base_url", "https://api.openai.com/v1"))
        self.entry_cloud_model.delete(0, 'end'); self.entry_cloud_model.insert(0, CONFIG["settings"].get("cloud_ai_model", "gpt-4o-mini"))
        
        auth_val = CONFIG["settings"].get("cloud_ai_auth_type", "api_key")
        self.seg_auth.set("Username & Password (Basic Auth)" if auth_val == "user_pass" else "API Key / Bearer Token")
        
        self.entry_cloud_key.delete(0, 'end'); self.entry_cloud_key.insert(0, get_credential("settings.cloud_ai_api_key", CONFIG["settings"].get("cloud_ai_api_key", CONFIG["settings"].get("gemini_api_key", ""))))
        self.entry_cloud_user.delete(0, 'end'); self.entry_cloud_user.insert(0, get_credential("settings.cloud_ai_username", CONFIG["settings"].get("cloud_ai_username", "")))
        self.entry_cloud_pass.delete(0, 'end'); self.entry_cloud_pass.insert(0, get_credential("settings.cloud_ai_password", CONFIG["settings"].get("cloud_ai_password", "")))
        
        self.on_provider_changed(self.seg_provider.get())
        self.on_auth_type_changed(self.seg_auth.get())
        
        self.sel_exp.set(CONFIG["settings"].get("experience_level", "All"))
        self.sel_jt.set(CONFIG["settings"].get("job_type", "All"))
        self.sel_loc.set(CONFIG["settings"].get("location_type", "All"))
        self.sel_scope.set(CONFIG["settings"].get("location_scope", "Entire Country"))
        self.on_scope_changed(self.sel_scope.get())
        
        self.settings_skip.update_items(CONFIG["settings"]["skip_keywords"])
        self.settings_locations.update_items(CONFIG["settings"].get("preferred_locations", []))
        self.refresh_models()
        
        # Reload safety settings
        if CONFIG["settings"].get("safe_mode", True):
            self.sw_safe_mode.select()
        else:
            self.sw_safe_mode.deselect()
        self.settings_daily_cap.delete(0, 'end'); self.settings_daily_cap.insert(0, str(CONFIG["settings"].get("daily_apply_cap", 25)))
        self.settings_min_delay.delete(0, 'end'); self.settings_min_delay.insert(0, str(CONFIG["settings"].get("min_delay_seconds", 15)))
        self.settings_max_delay.delete(0, 'end'); self.settings_max_delay.insert(0, str(CONFIG["settings"].get("max_delay_seconds", 45)))
