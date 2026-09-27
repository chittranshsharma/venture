import re
import json
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
from core.config_manager import CONFIG, CONFIG_PATH
from core.db_manager import log_message, recalculate_metrics
from ui.components import C, F, TagChipContainer, add_grid_input, create_action_btn, add_section_divider

class ProfileView(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent, fg_color="transparent")
        self.controller = controller
        
        # ── Header ──
        title_row = ctk.CTkFrame(self, fg_color="transparent")
        title_row.pack(fill='x', pady=(0, 14))
        
        title_box = ctk.CTkFrame(title_row, fg_color="transparent")
        title_box.pack(side='left', anchor='w')
        
        lbl_title = ctk.CTkLabel(title_box, text="Candidate Profile", font=F["h1"], text_color=C["ink"], anchor="w")
        lbl_title.pack(anchor='w')
        lbl_sub = ctk.CTkLabel(title_box, text="Master curriculum data, candidate vault, and verification parameters.", font=F["xs"], text_color=C["ash"], anchor="w")
        lbl_sub.pack(anchor='w', pady=(2, 0))
        
        # ── Scrollable Card ──
        card = ctk.CTkScrollableFrame(
            self, fg_color=C["card"], corner_radius=12,
            border_width=1, border_color=C["border"]
        )
        card.pack(fill='both', expand=True)
        
        # ── Personal Information ──
        add_section_divider(card, "Personal Information")
        
        grid_frame = ctk.CTkFrame(card, fg_color="transparent")
        grid_frame.pack(fill='x', padx=16, pady=4)
        grid_frame.columnconfigure((0, 1), weight=1, uniform="equal")
        
        self.prof_name = add_grid_input(grid_frame, "Full Name", 0, 0)
        self.prof_email = add_grid_input(grid_frame, "Email Address", 0, 1)
        self.prof_phone = add_grid_input(grid_frame, "Phone Number", 1, 0)
        self.prof_country = add_grid_input(grid_frame, "Country Code", 1, 1)
        
        # ── Online Presence ──
        add_section_divider(card, "Online Presence")
        
        grid_frame2 = ctk.CTkFrame(card, fg_color="transparent")
        grid_frame2.pack(fill='x', padx=16, pady=4)
        grid_frame2.columnconfigure((0, 1), weight=1, uniform="equal")
        
        self.prof_linkedin = add_grid_input(grid_frame2, "LinkedIn URL", 0, 0)
        self.prof_github = add_grid_input(grid_frame2, "GitHub URL", 0, 1)
        self.prof_portfolio = add_grid_input(grid_frame2, "Portfolio Website", 1, 0)
        self.prof_resume = add_grid_input(grid_frame2, "Resume Local Path (PDF)", 1, 1)
        
        # ── Candidate QA Vault (ATS Form Memory) ──
        add_section_divider(card, "Candidate QA Vault (Smart Form Memory)")
        
        grid_qa = ctk.CTkFrame(card, fg_color="transparent")
        grid_qa.pack(fill='x', padx=16, pady=4)
        grid_qa.columnconfigure((0, 1), weight=1, uniform="equal")
        
        # Experience (Years) - Entry
        self.qa_exp = add_grid_input(grid_qa, "Experience (Years) e.g. 1 or 3.5", 0, 0)
        
        # Notice Period - Dropdown System
        f_notice = ctk.CTkFrame(grid_qa, fg_color="transparent")
        f_notice.grid(row=0, column=1, padx=8, pady=6, sticky='ew')
        ctk.CTkLabel(f_notice, text="Notice Period", font=F["sm_b"], text_color=C["muted"], anchor="w").pack(anchor='w', pady=(0, 2))
        self.qa_notice = ctk.CTkOptionMenu(f_notice, values=["Immediate", "15 Days", "30 Days", "45 Days", "60 Days", "90 Days"],
                                           fg_color=C["input"], button_color=C["card_hover"], text_color=C["text"],
                                           dropdown_fg_color=C["card"], font=F["sm"], corner_radius=8, height=36)
        self.qa_notice.pack(fill='x')
        
        # Current CTC & Expected CTC - Numeric Entry
        self.qa_cctc = add_grid_input(grid_qa, "Current Salary / CTC (LPA e.g. 0, 6, 12)", 1, 0)
        self.qa_ectc = add_grid_input(grid_qa, "Expected Salary / CTC (LPA e.g. 3, 8, 15)", 1, 1)

        # Expected Stipend & Work Preference
        self.qa_stipend = add_grid_input(grid_qa, "Expected Stipend / Month (e.g. 15000)", 2, 0)
        
        f_pref = ctk.CTkFrame(grid_qa, fg_color="transparent")
        f_pref.grid(row=2, column=1, padx=8, pady=6, sticky='ew')
        ctk.CTkLabel(f_pref, text="Work Preference / Mode", font=F["sm_b"], text_color=C["muted"], anchor="w").pack(anchor='w', pady=(0, 2))
        self.qa_pref = ctk.CTkOptionMenu(f_pref, values=["Remote", "Hybrid", "On-site", "Flexible"],
                                         fg_color=C["input"], button_color=C["card_hover"], text_color=C["text"],
                                         dropdown_fg_color=C["card"], font=F["sm"], corner_radius=8, height=36)
        self.qa_pref.pack(fill='x')
        
        # Work Authorization & Require Sponsorship
        f_auth = ctk.CTkFrame(grid_qa, fg_color="transparent")
        f_auth.grid(row=3, column=0, padx=8, pady=6, sticky='ew')
        ctk.CTkLabel(f_auth, text="Authorized to Work?", font=F["sm_b"], text_color=C["muted"], anchor="w").pack(anchor='w', pady=(0, 2))
        self.qa_auth = ctk.CTkOptionMenu(f_auth, values=["Yes", "No"],
                                         fg_color=C["input"], button_color=C["card_hover"], text_color=C["text"],
                                         dropdown_fg_color=C["card"], font=F["sm"], corner_radius=8, height=36)
        self.qa_auth.pack(fill='x')

        f_spons = ctk.CTkFrame(grid_qa, fg_color="transparent")
        f_spons.grid(row=3, column=1, padx=8, pady=6, sticky='ew')
        ctk.CTkLabel(f_spons, text="Require Visa Sponsorship?", font=F["sm_b"], text_color=C["muted"], anchor="w").pack(anchor='w', pady=(0, 2))
        self.qa_spons = ctk.CTkOptionMenu(f_spons, values=["No", "Yes"],
                                          fg_color=C["input"], button_color=C["card_hover"], text_color=C["text"],
                                          dropdown_fg_color=C["card"], font=F["sm"], corner_radius=8, height=36)
        self.qa_spons.pack(fill='x')
        
        # Relocation & Gender
        f_reloc = ctk.CTkFrame(grid_qa, fg_color="transparent")
        f_reloc.grid(row=4, column=0, padx=8, pady=6, sticky='ew')
        ctk.CTkLabel(f_reloc, text="Willing to Relocate?", font=F["sm_b"], text_color=C["muted"], anchor="w").pack(anchor='w', pady=(0, 2))
        self.qa_reloc = ctk.CTkOptionMenu(f_reloc, values=["Yes", "No"],
                                          fg_color=C["input"], button_color=C["card_hover"], text_color=C["text"],
                                          dropdown_fg_color=C["card"], font=F["sm"], corner_radius=8, height=36)
        self.qa_reloc.pack(fill='x')

        f_gender = ctk.CTkFrame(grid_qa, fg_color="transparent")
        f_gender.grid(row=4, column=1, padx=8, pady=6, sticky='ew')
        ctk.CTkLabel(f_gender, text="Gender", font=F["sm_b"], text_color=C["muted"], anchor="w").pack(anchor='w', pady=(0, 2))
        self.qa_gender = ctk.CTkOptionMenu(f_gender, values=["Decline to state", "Male", "Female", "Non-binary", "Other"],
                                           fg_color=C["input"], button_color=C["card_hover"], text_color=C["text"],
                                           dropdown_fg_color=C["card"], font=F["sm"], corner_radius=8, height=36)
        self.qa_gender.pack(fill='x')
        
        # ── Education & Academic Scores ──
        add_section_divider(card, "Education & Academic Scores")
        
        grid_edu = ctk.CTkFrame(card, fg_color="transparent")
        grid_edu.pack(fill='x', padx=16, pady=4)
        grid_edu.columnconfigure((0, 1), weight=1, uniform="equal")
        
        self.edu_degree = add_grid_input(grid_edu, "Degree / Branch (e.g. B.Tech Computer Science)", 0, 0)
        self.edu_uni = add_grid_input(grid_edu, "University / College Name", 0, 1)
        self.edu_grad = add_grid_input(grid_edu, "Graduation Year (e.g. 2025)", 1, 0)
        self.edu_cgpa = add_grid_input(grid_edu, "College CGPA / Percentage (e.g. 8.5)", 1, 1)
        self.edu_10th = add_grid_input(grid_edu, "10th / SSC Percentage (e.g. 92)", 2, 0)
        self.edu_12th = add_grid_input(grid_edu, "12th / HSC Percentage (e.g. 88)", 2, 1)

        # ── Technical Skills (Categorized) ──
        add_section_divider(card, "Technical Skills by Category")
        
        self.skills_primary = TagChipContainer(card, [], "Primary Skills (Press Enter to add)", lambda val: self.update_category_skill("primary", val))
        self.skills_primary.pack(fill='x', pady=4)
        
        self.skills_tools = TagChipContainer(card, [], "Tools & Frameworks (e.g. Git, Docker, Postman)", lambda val: self.update_category_skill("tools", val))
        self.skills_tools.pack(fill='x', pady=4)
        
        self.skills_db = TagChipContainer(card, [], "Databases (e.g. PostgreSQL, MongoDB, Redis)", lambda val: self.update_category_skill("databases", val))
        self.skills_db.pack(fill='x', pady=4)
        
        self.skills_cloud = TagChipContainer(card, [], "Cloud & Infrastructure (e.g. AWS, GCP, Azure)", lambda val: self.update_category_skill("cloud", val))
        self.skills_cloud.pack(fill='x', pady=4)

        self.reload_profile_fields()
        
        # ── Save Button ──
        btn_frame = ctk.CTkFrame(card, fg_color="transparent")
        btn_frame.pack(anchor='w', padx=16, pady=(20, 16))
        btn_save = create_action_btn(btn_frame, "Save Profile", self.save_profile_action, "primary", "large")
        btn_save.pack(side='left')

    def update_category_skill(self, cat_key, items):
        cand = CONFIG.setdefault("candidate", {})
        qa = cand.setdefault("qa_vault", {})
        sbc = qa.setdefault("skills_by_category", {})
        sbc[cat_key] = items
        
        # Sync flat skills array for backwards compatibility
        all_skills = []
        for cat in ["primary", "tools", "databases", "cloud"]:
            for s in sbc.get(cat, []):
                if s and s not in all_skills:
                    all_skills.append(s)
        if all_skills:
            cand["skills"] = all_skills
            
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(CONFIG, f, indent=4)
        recalculate_metrics()
        self.controller.refresh_nav_buttons()

    def reload_profile_fields(self):
        cand = CONFIG.get("candidate", {})
        self.prof_name.delete(0, 'end'); self.prof_name.insert(0, cand.get("name", ""))
        self.prof_email.delete(0, 'end'); self.prof_email.insert(0, cand.get("email", ""))
        self.prof_phone.delete(0, 'end'); self.prof_phone.insert(0, cand.get("phone", ""))
        self.prof_country.delete(0, 'end'); self.prof_country.insert(0, cand.get("country_code", "+91"))
        self.prof_linkedin.delete(0, 'end'); self.prof_linkedin.insert(0, cand.get("linkedin", ""))
        self.prof_github.delete(0, 'end'); self.prof_github.insert(0, cand.get("github", ""))
        self.prof_portfolio.delete(0, 'end'); self.prof_portfolio.insert(0, cand.get("portfolio", ""))
        self.prof_resume.delete(0, 'end'); self.prof_resume.insert(0, cand.get("resume_path", ""))
        
        qa = cand.get("qa_vault", {})
        self.qa_exp.delete(0, 'end'); self.qa_exp.insert(0, str(qa.get("experience_years", "1")))
        self.qa_notice.set(qa.get("notice_period", "Immediate"))
        self.qa_cctc.delete(0, 'end'); self.qa_cctc.insert(0, str(qa.get("current_ctc", "0")))
        self.qa_ectc.delete(0, 'end'); self.qa_ectc.insert(0, str(qa.get("expected_ctc", "3")))
        self.qa_stipend.delete(0, 'end'); self.qa_stipend.insert(0, str(qa.get("expected_stipend", "15000")))
        self.qa_pref.set(qa.get("work_preference", "Remote"))
        self.qa_auth.set(qa.get("work_authorization", "Yes"))
        self.qa_spons.set(qa.get("require_sponsorship", "No"))
        self.qa_reloc.set(qa.get("willing_to_relocate", "Yes"))
        self.qa_gender.set(qa.get("gender", "Decline to state"))
        
        edu = qa.get("education", {})
        self.edu_degree.delete(0, 'end'); self.edu_degree.insert(0, edu.get("degree", "B.Tech Computer Science"))
        self.edu_uni.delete(0, 'end'); self.edu_uni.insert(0, edu.get("university", "XYZ University"))
        self.edu_grad.delete(0, 'end'); self.edu_grad.insert(0, str(edu.get("graduation_year", "2025")))
        self.edu_cgpa.delete(0, 'end'); self.edu_cgpa.insert(0, str(edu.get("cgpa", "8.5")))
        self.edu_10th.delete(0, 'end'); self.edu_10th.insert(0, str(edu.get("tenth_percentage", "92")))
        self.edu_12th.delete(0, 'end'); self.edu_12th.insert(0, str(edu.get("twelfth_percentage", "88")))
        
        sbc = qa.get("skills_by_category", {})
        self.skills_primary.update_items(sbc.get("primary", ["Python", "React"]))
        self.skills_tools.update_items(sbc.get("tools", ["Git", "Docker", "Postman"]))
        self.skills_db.update_items(sbc.get("databases", ["PostgreSQL", "MongoDB"]))
        self.skills_cloud.update_items(sbc.get("cloud", ["AWS", "GCP"]))

    def save_profile_action(self):
        try:
            exp_val = self.qa_exp.get().strip()
            cctc_val = self.qa_cctc.get().strip()
            ectc_val = self.qa_ectc.get().strip()
            stipend_val = self.qa_stipend.get().strip()
            
            # Numeric/Decimal Validation for Experience and CTC
            num_pattern = re.compile(r'^\d*(\.\d+)?$')
            if exp_val and not num_pattern.match(exp_val):
                messagebox.showerror("Invalid Input", "Experience (Years) must be a valid number or decimal (e.g. 1 or 3.5).")
                return
            if cctc_val and not num_pattern.match(cctc_val):
                messagebox.showerror("Invalid Input", "Current Salary / CTC must be a valid number or decimal (e.g. 0, 6, or 12.5).")
                return
            if ectc_val and not num_pattern.match(ectc_val):
                messagebox.showerror("Invalid Input", "Expected Salary / CTC must be a valid number or decimal (e.g. 0, 3, or 15.5).")
                return

            cand = CONFIG.setdefault("candidate", {})
            cand["name"] = self.prof_name.get().strip()
            cand["email"] = self.prof_email.get().strip()
            cand["phone"] = self.prof_phone.get().strip()
            cand["country_code"] = self.prof_country.get().strip()
            cand["linkedin"] = self.prof_linkedin.get().strip()
            cand["github"] = self.prof_github.get().strip()
            cand["portfolio"] = self.prof_portfolio.get().strip()
            cand["resume_path"] = self.prof_resume.get().strip()
            
            qa = cand.setdefault("qa_vault", {})
            qa["experience_years"] = exp_val if exp_val else "1"
            qa["notice_period"] = self.qa_notice.get()
            qa["current_ctc"] = cctc_val if cctc_val else "0"
            qa["expected_ctc"] = ectc_val if ectc_val else "3"
            qa["expected_stipend"] = stipend_val if stipend_val else "15000"
            qa["work_preference"] = self.qa_pref.get()
            qa["work_authorization"] = self.qa_auth.get()
            qa["require_sponsorship"] = self.qa_spons.get()
            qa["willing_to_relocate"] = self.qa_reloc.get()
            qa["gender"] = self.qa_gender.get()
            
            edu = qa.setdefault("education", {})
            edu["degree"] = self.edu_degree.get().strip()
            edu["university"] = self.edu_uni.get().strip()
            edu["graduation_year"] = self.edu_grad.get().strip()
            edu["cgpa"] = self.edu_cgpa.get().strip()
            edu["tenth_percentage"] = self.edu_10th.get().strip()
            edu["twelfth_percentage"] = self.edu_12th.get().strip()
            
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(CONFIG, f, indent=4)
            messagebox.showinfo("Success", "Candidate profile, Education & ATS QA Vault updated successfully!")
            log_message("Candidate Profile, Education & QA Vault saved via Desktop GUI.")
            recalculate_metrics()
            self.controller.refresh_nav_buttons()
        except Exception as e:
            messagebox.showerror("Error", f"Could not save profile: {e}")
