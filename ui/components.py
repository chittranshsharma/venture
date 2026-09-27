import customtkinter as ctk
from tkinter import ttk
import tkinter as tk

# ═══════════════════════════════════════════════════════════════
#  DESIGN SYSTEM — Inspired by Resend Editorial Developer Aesthetic
#  Pure Black Canvas • Translucent Hairlines • Editorial Typography
#  Reference: DESIGN.md
# ═══════════════════════════════════════════════════════════════

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ── Color Palette (DESIGN.md Tokens) ──
C = {
    # Surface & Canvas
    "bg":               "#000000",       # Canvas: Pure black, never near-black
    "canvas":           "#000000",       # True black
    "sidebar":          "#050507",       # Surface Deep subtle contrast
    "card":             "#0a0a0c",       # Surface Card: Standard inset card surface
    "card_hover":       "#121215",       # Subtle elevation hover
    "elevated":         "#101012",       # Surface Elevated: Ghost button & featured tiers
    "input":            "#0a0a0c",       # Surface Card for inputs
    "deep":             "#06060a",       # Surface Deep: Code window well
    
    # Borders & Dividers (Translucent White Approximations on #000000)
    "hairline":         "#17171a",       # Hairline (6% white)
    "hairline_strong":  "#26262b",       # Hairline Strong (14% white structural border)
    "border":           "#26262b",       # Structural 1px border
    "divider_soft":     "#101012",       # Low-contrast 4% divider
    "focus":            "#fcfdff",       # Focus ring thickens to ink white

    # Brand Signature & Text
    "primary":          "#fcfdff",       # Primary White: Brand signature accent
    "primary_on":       "#000000",       # Label on primary white button
    "primary_p":        "#f1f7fe",       # Surface Light: Active/pressed state
    "accent":           "#fcfdff",       # White CTA anchor
    "accent_h":         "#e2e8f0",       # White CTA hover
    "accent_d":         "#cbd5e1",       # White CTA pressed

    # Text Hierarchy
    "text":             "#fcfdff",       # Ink: Primary text colour (faintly blue-cool)
    "ink":              "#fcfdff",       # Ink
    "body":             "#dfe1e6",       # Body copy (86% white)
    "charcoal":         "#b3b5b8",       # Captions & secondary labels (70% white)
    "muted":            "#a1a4a5",       # Supporting text & inactive labels
    "dim":              "#64748b",       # Dim text
    "ash":              "#888e90",       # Tertiary text / footer
    "stone":            "#464a4d",       # Disabled foreground

    # Semantic & Atmospheric Accents
    "orange":           "#ff801f",       # Accent Orange
    "orange_glow":      "#261205",       # Low-opacity warm wash
    "yellow":           "#ffc53d",       # Accent Yellow / key callouts
    "amber":            "#ffc53d",       # Warning amber
    "amber_h":          "#e6b032",
    "blue":             "#3b9eff",       # Accent Blue / inline link
    "link":             "#3b9eff",       # Link color
    "green":            "#11ff99",       # Accent Green / success status dot
    "green_h":          "#0fe085",
    "red":              "#ff2047",       # Accent Red / error wash
    "red_h":            "#e01a3c",
    "purple":           "#c084fc",       # Context accent
    "cyan":             "#38bdf8",       # Cool accent

    # Pills & Badges
    "chip":             "#101012",       # Surface Elevated
    "chip_border":      "#26262b",       # Hairline Strong
    "chip_text":        "#fcfdff",       # Ink
}

# ── Typography Hierarchy (Domaine Editorial + Modern Sans + Geist Mono) ──
F = {
    "display": ("Georgia", 24, "bold"),       # Display headline (Domaine Display substitute)
    "h1":      ("Georgia", 18, "bold"),       # Section opener editorial headline
    "h2":      ("Segoe UI", 14, "bold"),      # Card title
    "h3":      ("Segoe UI", 12, "bold"),      # Sub-section header
    "body":    ("Segoe UI", 11),              # Standard UI body
    "body_b":  ("Segoe UI", 11, "bold"),      # Bold UI body
    "sm":      ("Segoe UI", 10),              # Card body / metadata
    "sm_b":    ("Segoe UI", 10, "bold"),      # Button labels
    "xs":      ("Segoe UI", 9),               # Captions / disclosures
    "xs_b":    ("Segoe UI", 9, "bold"),       # Badges / pill labels
    "mono":    ("Consolas", 10),              # Code well (Geist Mono / Consolas)
    "logo":    ("Georgia", 16, "bold"),       # Wordmark brand
    "metric":  ("Georgia", 24, "bold"),       # Big metric numbers
    "nav":     ("Segoe UI", 11),              # Sidebar nav link
    "nav_a":   ("Segoe UI", 11, "bold"),      # Active nav link
}

# ═══════════════════════════════════════════════════════════════
#  Treeview Styling (ttk widgets inside pure black canvas)
# ═══════════════════════════════════════════════════════════════
def configure_treeview_style():
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("Dark.Treeview",
        background=C["input"], foreground=C["text"],
        fieldbackground=C["input"], rowheight=36,
        borderwidth=0, font=F["sm"])
    style.configure("Dark.Treeview.Heading",
        background=C["card"], foreground=C["muted"],
        font=F["sm_b"], relief="flat", borderwidth=0)
    style.map("Dark.Treeview",
        background=[("selected", C["elevated"])],
        foreground=[("selected", C["primary"])])
    style.layout("Dark.Treeview", [
        ("Treeview.treearea", {"sticky": "nswe"})
    ])
    # Scrollbar
    style.configure("Dark.Vertical.TScrollbar",
        troughcolor=C["bg"], background=C["card_hover"],
        bordercolor=C["bg"], arrowcolor=C["muted"], width=8)

# ═══════════════════════════════════════════════════════════════
#  Button Component (button-primary, button-ghost, button-outline)
# ═══════════════════════════════════════════════════════════════
def make_btn_interactive(btn, bg_normal, bg_hover, fg_normal, fg_hover):
    """Interactive hover binder for standard widgets"""
    try:
        btn.configure(fg_color=bg_normal, hover_color=bg_hover, text_color=fg_normal)
    except Exception:
        btn.config(bg=bg_normal, fg=fg_normal,
                   activebackground=bg_hover, activeforeground=fg_hover,
                   relief='flat', bd=0, cursor='hand2')
        btn.bind("<Enter>", lambda e: btn.config(bg=bg_hover, fg=fg_hover))
        btn.bind("<Leave>", lambda e: btn.config(bg=bg_normal, fg=fg_normal))

def create_action_btn(parent, text, command, color="primary", size="normal"):
    """
    Component: Button (from DESIGN.md)
    - 'primary': White button (#fcfdff) with black text (#000000). The loudest visual element.
    - 'ghost' / 'secondary': Surface Elevated (#101012) with ink text and 1px hairline border.
    - 'outline': Transparent surface with ink text and 1px hairline border.
    - 'success' / 'danger' / 'warning': Subtle dark surface with semantic text/border.
    """
    color_map = {
        "primary":   (C["primary"],   C["primary_p"],  C["primary_on"], None),
        "secondary": (C["elevated"],  C["card_hover"], C["text"],       C["border"]),
        "ghost":     (C["elevated"],  C["card_hover"], C["text"],       C["border"]),
        "outline":   ("transparent",  C["card_hover"], C["text"],       C["border"]),
        "success":   (C["elevated"],  C["card_hover"], C["green"],      C["border"]),
        "danger":    (C["elevated"],  C["card_hover"], C["red"],        C["border"]),
        "warning":   (C["elevated"],  C["card_hover"], C["amber"],      C["border"]),
    }
    fg, hover, tc, bc = color_map.get(color, color_map["primary"])
    dim = {"small": (28, 6), "normal": (36, 8), "large": (40, 8)}
    h, cr = dim.get(size, dim["normal"])
    font = F["xs_b"] if size == "small" else F["sm_b"]
    border_w = 1 if bc else 0
    return ctk.CTkButton(
        parent, text=text, command=command,
        fg_color=fg, hover_color=hover, text_color=tc,
        font=font, corner_radius=cr, height=h,
        border_width=border_w, border_color=bc
    )

# ═══════════════════════════════════════════════════════════════
#  Form Input Helpers (text-input: 8px radius, hairline border)
# ═══════════════════════════════════════════════════════════════
def add_form_input(parent, label):
    lbl = ctk.CTkLabel(parent, text=label, font=F["sm_b"], text_color=C["muted"], anchor="w")
    lbl.pack(anchor='w', padx=16, pady=(12, 4))
    entry = ctk.CTkEntry(parent, fg_color=C["input"], border_color=C["border"],
        text_color=C["text"], font=F["sm"], corner_radius=8, height=38, border_width=1)
    entry.pack(fill='x', padx=16)
    return entry

def add_grid_input(parent, label, row, col):
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.grid(row=row, column=col, sticky='nsew', padx=6, pady=6)
    lbl = ctk.CTkLabel(frame, text=label, font=F["sm_b"], text_color=C["muted"], anchor="w")
    lbl.pack(anchor='w', pady=(0, 4))
    entry = ctk.CTkEntry(frame, fg_color=C["input"], border_color=C["border"],
        text_color=C["text"], font=F["sm"], corner_radius=8, height=38, border_width=1)
    entry.pack(fill='x')
    return entry

def add_section_divider(parent, text):
    f = ctk.CTkFrame(parent, fg_color="transparent")
    f.pack(fill='x', padx=16, pady=(20, 10))
    lbl = ctk.CTkLabel(f, text=text, font=F["h3"], text_color=C["text"])
    lbl.pack(side='left')
    sep = ctk.CTkFrame(f, fg_color=C["border"], height=1, corner_radius=0)
    sep.pack(side='left', fill='x', expand=True, padx=(12, 0))

def enable_canvas_mousewheel(canvas):
    pass

# ═══════════════════════════════════════════════════════════════
#  TagChipContainer — Badge-Pill Shapes ({rounded.full})
# ═══════════════════════════════════════════════════════════════
class TagChipContainer(ctk.CTkFrame):
    def __init__(self, parent, initial_items, label_text, on_change_callback):
        super().__init__(parent, fg_color="transparent")
        self.items = list(initial_items)
        self.on_change = on_change_callback

        lbl = ctk.CTkLabel(self, text=label_text, font=F["sm_b"], text_color=C["muted"], anchor="w")
        lbl.pack(anchor='w', padx=16, pady=(10, 5))

        self.chips_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.chips_frame.pack(fill='x', padx=16, pady=3)

        self.entry = ctk.CTkEntry(self, placeholder_text="Type and press Enter...",
            fg_color=C["input"], border_color=C["border"], text_color=C["text"],
            font=F["sm"], corner_radius=8, height=36, border_width=1)
        self.entry.pack(fill='x', padx=16, pady=(4, 6))

        self.entry.bind("<Return>", self.add_item_event)
        self.entry.bind("<KeyPress-comma>", self.add_item_comma)
        self.redraw_chips()

    def redraw_chips(self):
        for widget in self.chips_frame.winfo_children():
            widget.destroy()
        row, col = 0, 0
        for item in self.items:
            chip = ctk.CTkButton(self.chips_frame,
                text=f" {item}  ✕", fg_color=C["chip"], hover_color=C["card_hover"],
                border_width=1, border_color=C["chip_border"],
                text_color=C["chip_text"], font=F["xs_b"],
                corner_radius=14, height=26, width=0,
                command=lambda val=item: self.remove_item(val))
            chip.grid(row=row, column=col, padx=4, pady=4, sticky='w')
            col += 1
            if col >= 5:
                col = 0
                row += 1

    def add_item_event(self, event):
        self.add_item()
        return "break"

    def add_item_comma(self, event):
        self.after(10, self.add_item)
        return "break"

    def add_item(self):
        val = self.entry.get().replace(",", "").strip()
        if val and val not in self.items:
            self.items.append(val)
            self.redraw_chips()
            self.on_change(self.items)
        self.entry.delete(0, 'end')

    def remove_item(self, val):
        if val in self.items:
            self.items.remove(val)
            self.redraw_chips()
            self.on_change(self.items)

    def update_items(self, new_items):
        self.items = list(new_items)
        self.redraw_chips()
