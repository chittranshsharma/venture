import customtkinter as ctk
from tkinter import ttk
import tkinter as tk

# ═══════════════════════════════════════════════════════════════
#  DESIGN SYSTEM — Resend Editorial Developer Aesthetic
#  Pure Black Canvas (#000000) • Translucent Hairlines • Domaine Typography
#  Reference: DESIGN.md
# ═══════════════════════════════════════════════════════════════

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ── Color Palette (DESIGN.md Tokens) ──
C = {
    # Surface & Canvas
    "bg":               "#000000",       # Canvas: Pure black, never near-black
    "canvas":           "#000000",       # True black
    "sidebar":          "#000000",       # True black sidebar framed by hairline border
    "card":             "#0a0a0c",       # Surface Card: Standard inset card surface
    "card_hover":       "#131317",       # Subtle elevation hover
    "elevated":         "#101012",       # Surface Elevated: Ghost button & featured tiers
    "input":            "#0a0a0c",       # Surface Card for inputs
    "deep":             "#06060a",       # Surface Deep: Code window well & terminals
    
    # Borders & Dividers (Translucent White Approximations on #000000)
    "hairline":         "#161619",       # Hairline (6% white)
    "hairline_strong":  "#26262b",       # Hairline Strong (14% white structural border)
    "border":           "#26262b",       # Structural 1px border on cards and inputs
    "divider_soft":     "#111114",       # Low-contrast 4% divider between columns
    "focus":            "#fcfdff",       # Focus ring thickens to ink white

    # Brand Signature & Contrast Anchor
    "primary":          "#fcfdff",       # Primary White: Brand de facto accent (brightest pixel)
    "primary_on":       "#000000",       # Label on primary white button
    "primary_p":        "#f1f7fe",       # Surface Light: Active/pressed state
    "accent":           "#fcfdff",       # White CTA anchor
    "accent_h":         "#e8ecf2",       # White CTA hover
    "accent_d":         "#cbd5e1",       # White CTA pressed

    # Text Hierarchy
    "text":             "#fcfdff",       # Ink: Primary text colour (faintly blue-cool)
    "ink":              "#fcfdff",       # Ink: Primary text
    "body":             "#dfe1e6",       # Body copy (86% white)
    "charcoal":         "#b3b5b8",       # Captions & secondary nav labels (70% white)
    "muted":            "#a1a4a5",       # Supporting text & inactive labels
    "dim":              "#5a5e62",       # Dimmed metadata
    "ash":              "#888e90",       # Tertiary text / footer copy
    "stone":            "#464a4d",       # Disabled foreground
    "on_light":         "#000000",       # Label inside rare email-mockup white cards
    "on_light_mute":    "#4b5563",       # Secondary text inside email mockups

    # Semantic & Atmospheric Accents (Low-opacity washes / status dots only)
    "orange":           "#ff801f",       # Accent Orange
    "orange_glow":      "#241306",       # Low-opacity warm wash
    "yellow":           "#ffc53d",       # Accent Yellow / key callouts
    "amber":            "#ffc53d",       # Warning amber
    "amber_h":          "#e6b032",
    "blue":             "#3b9eff",       # Accent Blue / inline link
    "blue_glow":        "#081426",       # Low-opacity cool wash
    "link":             "#3b9eff",       # Inline link
    "green":            "#11ff99",       # Accent Green / success status dot
    "green_glow":       "#072014",       # Low-opacity delivery glow
    "green_h":          "#0fe085",
    "red":              "#ff2047",       # Accent Red / error attention
    "red_glow":         "#26090e",       # Low-opacity alert glow
    "red_h":            "#e01a3c",
    "purple":           "#c084fc",       # Context accent
    "cyan":             "#38bdf8",       # Cool accent

    # Pills & Badges
    "chip":             "#101012",       # Surface Elevated
    "chip_border":      "#26262b",       # Hairline Strong
    "chip_text":        "#fcfdff",       # Ink
}

# ── Typography Hierarchy (Domaine Editorial Serif + ABC Favorit / Inter + Geist Mono) ──
F = {
    "display_xxl": ("Georgia", 28, "bold"),   # Hero Display headline (Domaine Display substitute)
    "display_xl":  ("Georgia", 22, "bold"),   # Section openers ("Email reimagined")
    "display_lg":  ("Georgia", 18, "bold"),   # Display sub-titles
    "h1":          ("Georgia", 18, "bold"),   # Section header headline
    "h2":          ("Segoe UI", 13, "bold"),  # Card titles / section sub-titles
    "h3":          ("Segoe UI", 11, "bold"),  # List headers & field group labels
    "subtitle":    ("Segoe UI", 12),          # Hero subtitles
    "body_lg":     ("Segoe UI", 12),          # Marketing prose
    "body":        ("Segoe UI", 11),          # Standard UI body
    "body_b":      ("Segoe UI", 11, "bold"),  # Bold body
    "sm":          ("Segoe UI", 10),          # Card body / captions
    "sm_b":        ("Segoe UI", 10, "bold"),  # Button labels & table headers
    "xs":          ("Segoe UI", 9),           # Disclosures / metadata
    "xs_b":        ("Segoe UI", 9, "bold"),   # Pill labels & badges
    "mono":        ("Consolas", 10),          # Code window blocks (Geist Mono substitute)
    "mono_sm":     ("Consolas", 9),           # Inline code & terminal output
    "logo":        ("Georgia", 16, "bold"),   # Wordmark brand (editorial serif)
    "metric":      ("Georgia", 26, "bold"),   # Big metric numbers
    "metric_sm":   ("Georgia", 18, "bold"),   # Compact metric numbers
    "nav":         ("Segoe UI", 11),          # Sidebar nav link
    "nav_a":       ("Segoe UI", 11, "bold"),  # Active nav link
}

# ═══════════════════════════════════════════════════════════════
#  Treeview Styling (ttk widgets inside pure black canvas)
# ═══════════════════════════════════════════════════════════════
def configure_treeview_style():
    style = ttk.Style()
    style.theme_use("clam")
    
    style.configure("Dark.Treeview",
        background=C["card"],
        foreground=C["text"],
        fieldbackground=C["card"],
        rowheight=34,
        borderwidth=0,
        font=F["sm"]
    )
    style.configure("Dark.Treeview.Heading",
        background=C["elevated"],
        foreground=C["charcoal"],
        font=F["sm_b"],
        relief="flat",
        borderwidth=0
    )
    style.map("Dark.Treeview",
        background=[("selected", C["elevated"])],
        foreground=[("selected", C["primary"])]
    )
    style.layout("Dark.Treeview", [
        ("Treeview.treearea", {"sticky": "nswe"})
    ])
    
    # Scrollbar: True black trough with subtle hairline-strong thumb
    style.configure("Dark.Vertical.TScrollbar",
        troughcolor=C["bg"],
        background=C["hairline_strong"],
        bordercolor=C["bg"],
        arrowcolor=C["muted"],
        width=7,
        relief="flat"
    )

# ═══════════════════════════════════════════════════════════════
#  Button Component ({component.button-primary}, ghost, outline)
# ═══════════════════════════════════════════════════════════════
def create_action_btn(parent, text, command, color="primary", size="normal"):
    """
    Component: Button (from DESIGN.md)
    - 'primary': Crisp white rectangle (#fcfdff) with black text (#000000).
                 The brightest pixel on the canvas; single visual anchor.
    - 'ghost' / 'secondary': Surface Elevated (#101012) with ink text & 1px hairline border.
    - 'outline': Transparent surface with ink text & 1px hairline border.
    - 'danger': Elevated surface (#101012) with red text & hairline border.
    - 'success': Elevated surface (#101012) with green text & hairline border.
    - 'warning': Elevated surface (#101012) with amber text & hairline border.
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
        border_width=border_w, border_color=bc,
        cursor="hand2"
    )

# ═══════════════════════════════════════════════════════════════
#  Card Frame Helper ({component.feature-card-bordered})
# ═══════════════════════════════════════════════════════════════
def create_card_frame(parent, elevated=False, corner_radius=12):
    """Creates a card container with hairline-strong border and card surface."""
    bg_col = C["elevated"] if elevated else C["card"]
    return ctk.CTkFrame(
        parent,
        fg_color=bg_col,
        corner_radius=corner_radius,
        border_width=1,
        border_color=C["border"]
    )

# ═══════════════════════════════════════════════════════════════
#  Code Window Chrome Helper ({component.code-window})
# ═══════════════════════════════════════════════════════════════
def create_code_window_header(parent, title="terminal", subtitle=""):
    """
    Renders top chrome for a code-window shell:
    3 hairline traffic light dots (Red, Yellow, Green) + monospace label
    """
    bar = ctk.CTkFrame(parent, fg_color="transparent", height=28)
    bar.pack(fill='x', padx=14, pady=(10, 6))
    bar.pack_propagate(False)

    dots = ctk.CTkFrame(bar, fg_color="transparent")
    dots.pack(side='left', pady=4)

    # 3 traffic light dots: Red (#ff2047), Yellow (#ffc53d), Green (#11ff99)
    ctk.CTkLabel(dots, text="●", font=("Arial", 11), text_color=C["red"], width=14).pack(side='left')
    ctk.CTkLabel(dots, text="●", font=("Arial", 11), text_color=C["yellow"], width=14).pack(side='left')
    ctk.CTkLabel(dots, text="●", font=("Arial", 11), text_color=C["green"], width=14).pack(side='left')

    lbl = ctk.CTkLabel(bar, text=f" {title}", font=F["mono_sm"], text_color=C["charcoal"])
    lbl.pack(side='left', padx=(6, 0))

    if subtitle:
        sub = ctk.CTkLabel(bar, text=subtitle, font=F["xs"], text_color=C["dim"])
        sub.pack(side='right')

    return bar

# ═══════════════════════════════════════════════════════════════
#  Badge Pill Helper ({component.badge-pill})
# ═══════════════════════════════════════════════════════════════
def create_badge_pill(parent, text, variant="neutral"):
    """Creates an editorial badge pill with rounded.full (9999px)"""
    colors = {
        "neutral": (C["elevated"], C["border"], C["body"]),
        "success": (C["green_glow"], C["border"], C["green"]),
        "warning": (C["orange_glow"], C["border"], C["amber"]),
        "danger":  (C["red_glow"], C["border"], C["red"]),
        "info":    (C["blue_glow"], C["border"], C["blue"]),
        "active":  (C["primary"], None, C["primary_on"]),
    }
    bg, bc, tc = colors.get(variant, colors["neutral"])
    bw = 1 if bc else 0
    return ctk.CTkLabel(
        parent, text=f"  {text}  ",
        fg_color=bg, text_color=tc,
        font=F["xs_b"], corner_radius=9999,
        height=22
    )

# ═══════════════════════════════════════════════════════════════
#  Form Input Helpers (text-input: 8px radius, hairline border)
# ═══════════════════════════════════════════════════════════════
def add_form_input(parent, label):
    lbl = ctk.CTkLabel(parent, text=label, font=F["sm_b"], text_color=C["muted"], anchor="w")
    lbl.pack(anchor='w', padx=16, pady=(12, 4))
    entry = ctk.CTkEntry(
        parent, fg_color=C["input"], border_color=C["border"],
        text_color=C["text"], font=F["sm"], corner_radius=8, height=38, border_width=1
    )
    entry.pack(fill='x', padx=16)
    return entry

def add_grid_input(parent, label, row, col):
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.grid(row=row, column=col, sticky='nsew', padx=6, pady=6)
    lbl = ctk.CTkLabel(frame, text=label, font=F["sm_b"], text_color=C["muted"], anchor="w")
    lbl.pack(anchor='w', pady=(0, 4))
    entry = ctk.CTkEntry(
        frame, fg_color=C["input"], border_color=C["border"],
        text_color=C["text"], font=F["sm"], corner_radius=8, height=38, border_width=1
    )
    entry.pack(fill='x')
    return entry

def add_section_divider(parent, text):
    f = ctk.CTkFrame(parent, fg_color="transparent")
    f.pack(fill='x', padx=16, pady=(20, 10))
    lbl = ctk.CTkLabel(f, text=text, font=F["h3"], text_color=C["text"])
    lbl.pack(side='left')
    sep = ctk.CTkFrame(f, fg_color=C["hairline"], height=1, corner_radius=0)
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

        self.entry = ctk.CTkEntry(
            self, placeholder_text="Type and press Enter...",
            fg_color=C["input"], border_color=C["border"], text_color=C["text"],
            font=F["sm"], corner_radius=8, height=36, border_width=1
        )
        self.entry.pack(fill='x', padx=16, pady=(4, 6))

        self.entry.bind("<Return>", self.add_item_event)
        self.entry.bind("<KeyPress-comma>", self.add_item_comma)
        self.redraw_chips()

    def redraw_chips(self):
        for widget in self.chips_frame.winfo_children():
            widget.destroy()
        row, col = 0, 0
        for item in self.items:
            chip = ctk.CTkButton(
                self.chips_frame,
                text=f" {item}  ✕", fg_color=C["chip"], hover_color=C["card_hover"],
                border_width=1, border_color=C["chip_border"],
                text_color=C["chip_text"], font=F["xs_b"],
                corner_radius=9999, height=26, width=0,
                command=lambda val=item: self.remove_item(val),
                cursor="hand2"
            )
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

