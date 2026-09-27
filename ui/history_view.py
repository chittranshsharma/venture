import os
from datetime import datetime
import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox
from core.db_manager import (
    APPLIED_DB_PATH, 
    log_message, 
    AppStatus, 
    get_applications_history, 
    export_applications_to_csv, 
    update_job_status_in_csv
)
from automation.status_tracker import start_tracker_thread
from ui.components import C, F, create_action_btn

class HistoryView(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent, fg_color="transparent")
        self.controller = controller
        
        # ── Header Row ──
        title_row = ctk.CTkFrame(self, fg_color="transparent")
        title_row.pack(fill='x', pady=(0, 14))
        lbl_title = ctk.CTkLabel(title_row, text="Application History", font=F["h1"], text_color=C["text"])
        lbl_title.pack(side='left')
        
        btn_frame = ctk.CTkFrame(title_row, fg_color="transparent")
        btn_frame.pack(side='right')
        
        btn_export = create_action_btn(btn_frame, "Export CSV", self.export_csv, "success", "small")
        btn_export.pack(side='right', padx=(8, 0))
        
        btn_scan = create_action_btn(btn_frame, "Scan Statuses", start_tracker_thread, "primary", "small")
        btn_scan.pack(side='right', padx=(8, 0))

        btn_refresh = create_action_btn(btn_frame, "Refresh", self.load_history_table, "ghost", "small")
        btn_refresh.pack(side='right')
        
        # ── Table Card ──
        card = ctk.CTkFrame(self, fg_color=C["card"], corner_radius=12)
        card.pack(fill='both', expand=True)
        
        columns = ('company', 'role', 'platform', 'status', 'detail', 'date')
        self.tree = ttk.Treeview(card, columns=columns, show='headings', style="Dark.Treeview")
        self.tree.heading('company', text='Company')
        self.tree.heading('role', text='Role')
        self.tree.heading('platform', text='Platform')
        self.tree.heading('status', text='Status')
        self.tree.heading('detail', text='Detail')
        self.tree.heading('date', text='Applied Date')
        
        self.tree.column('company', width=130)
        self.tree.column('role', width=180)
        self.tree.column('platform', width=80)
        self.tree.column('status', width=80)
        self.tree.column('detail', width=220)
        self.tree.column('date', width=120)

        # ── Status Row Color Tags (P2.2) ──
        # Blue for Interview, Green for Offer, Dimmed Gray for Withdrawn, Red for Rejected
        self.tree.tag_configure('interview', foreground='#38BDF8')
        self.tree.tag_configure('offer', foreground='#34D399')
        self.tree.tag_configure('withdrawn', foreground='#64748B')
        self.tree.tag_configure('rejected', foreground='#F87171')
        self.tree.tag_configure('applied', foreground='#F1F5F9')
        
        scrollbar = ttk.Scrollbar(card, orient="vertical", command=self.tree.yview, style="Dark.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side='left', fill='both', expand=True, padx=12, pady=12)
        scrollbar.pack(side='right', fill='y', pady=12, padx=(0, 6))

        # ── Right-Click Context Menu (P2.2) ──
        self.context_menu = tk.Menu(
            self.tree, 
            tearoff=0, 
            bg="#1E293B", 
            fg="#F8FAFC",
            activebackground="#3B82F6", 
            activeforeground="#FFFFFF",
            font=("Segoe UI", 9)
        )
        self.context_menu.add_command(label="🎯 Mark as Interview", command=lambda: self.update_status_action(AppStatus.INTERVIEW))
        self.context_menu.add_command(label="🎉 Mark as Offer", command=lambda: self.update_status_action(AppStatus.OFFER))
        self.context_menu.add_command(label="⏸ Mark as Withdrawn", command=lambda: self.update_status_action(AppStatus.WITHDRAWN))
        self.context_menu.add_separator()
        self.context_menu.add_command(label="✕ Mark as Rejected", command=lambda: self.update_status_action(AppStatus.REJECTED))
        self.context_menu.add_command(label="✓ Mark as Applied", command=lambda: self.update_status_action(AppStatus.APPLIED))
        
        self.tree.bind("<Button-3>", self.show_context_menu)
        
        self.load_history_table()

    def show_context_menu(self, event):
        """Display right-click context menu on row selection."""
        row_id = self.tree.identify_row(event.y)
        if row_id:
            self.tree.selection_set(row_id)
            self.context_menu.post(event.x_root, event.y_root)

    def update_status_action(self, new_status: str):
        """Update status of the selected job application in SQLite."""
        selected = self.tree.selection()
        if not selected:
            return
        url = selected[0]
        success = update_job_status_in_csv(url, None, new_status, f"Manually marked as {new_status}")
        if success:
            self.load_history_table()
            if hasattr(self.controller, "refresh_nav_buttons"):
                self.controller.refresh_nav_buttons()
            log_message(f"History: Updated status of {url[:40]} to '{new_status}'")

    def export_csv(self):
        """Export SQLite applications table to CSV in user's Downloads folder."""
        downloads_folder = os.path.join(os.path.expanduser('~'), 'Downloads')
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_path = os.path.join(downloads_folder, f"applied_jobs_{timestamp}.csv")
        
        success = export_applications_to_csv(export_path)
        if success:
            messagebox.showinfo("Export Successful", f"History exported to:\n{export_path}")
        else:
            messagebox.showinfo("Export CSV", "No history data available to export.")

    def load_history_table(self):
        """Load applications directly from SQLite database and apply status colors."""
        for item in self.tree.get_children():
            self.tree.delete(item)
        try:
            records = get_applications_history()
            for rec in records:
                url = rec.get("url", "")
                status = rec.get("status", "Applied")
                applied_at = rec.get("applied_at", "")
                formatted_date = applied_at
                if applied_at:
                    try:
                        dt = datetime.fromisoformat(applied_at)
                        formatted_date = dt.strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        formatted_date = applied_at[:16]
                
                # P2.2 Color coding: Blue for Interview, Green for Offer, Dimmed Gray for Withdrawn, Red for Rejected
                tag = "applied"
                status_lower = status.lower()
                if "interview" in status_lower:
                    tag = "interview"
                elif "offer" in status_lower:
                    tag = "offer"
                elif "withdrawn" in status_lower:
                    tag = "withdrawn"
                elif "reject" in status_lower or "failed" in status_lower or "not selected" in status_lower:
                    tag = "rejected"

                row_vals = (rec["company"], rec["role"], rec["platform"], status, rec["detail"], formatted_date)
                self.tree.insert('', 'end', iid=url, values=row_vals, tags=(tag,))
        except Exception as e:
            log_message(f"History load error: {e}")
