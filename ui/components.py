import customtkinter as ctk
from tkinter import ttk
import tkinter as tk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Linear / Raycast / Palantir Restrained Technical Dark Palette
C = {
    "bg":               "#101318",
    "canvas":           "#101318",
    "sidebar":          "#14181F",
    "card":             "#191E26",
    "surface":          "#191E26",
    "surface_hover":    "#252D39",
    "card_hover":       "#252D39",
    "elevated":         "#222A35",
    "input":            "#141920",
    "deep":             "#141920",
    "hairline":         "#252D38",
    "hairline_strong":  "#35404F",
    "border":           "#303A48",
    "divider_soft":     "#252D38",
    "focus":            "#E8E5DE",
    "primary":          "#E8E5DE",
    "primary_on":       "#101823",
    "primary_p":        "#D6D0C4",
    "accent":           "#A9C4E8",
    "accent_h":         "#C0D6F0",
    "accent_hover":     "#C0D6F0",
    "accent_d":         "#8AAAD2",
    "text":             "#F0F3F8",
    "ink":              "#F0F3F8",
    "body":             "#CCD3DE",
    "secondary":        "#A6B1C2",
    "charcoal":         "#A6B1C2",
    "tertiary":         "#94A0B2",
    "muted":            "#94A0B2",
    "dim":              "#78869B",
    "ash":              "#94A0B2",
    "stone":            "#33312C",
    "on_light":         "#0F0F0D",
    "on_light_mute":    "#47453F",
    "orange":           "#B5A06A",
    "orange_glow":      "#1C180E",
    "yellow":           "#B5A06A",
    "amber":            "#B5A06A",
    "amber_h":          "#A38E5A",
    "blue":             "#7E9DB5",
    "blue_glow":        "#10161C",
    "link":             "#7E9DB5",
    "green":            "#8FAF9A",
    "green_glow":       "#121A15",
    "green_h":          "#7D9D88",
    "red":              "#A87575",
    "red_glow":         "#1A1212",
    "red_h":            "#966565",
    "purple":           "#9E8FA8",
    "cyan":             "#7E9DB5",
    "chip":             "#222A35",
    "chip_border":      "#35404F",
    "chip_text":        "#CCD3DE",
}

F = {
    "display_xxl": ("Segoe UI", 32, "bold"),
    "display_xl":  ("Segoe UI", 28, "bold"),
    "display_lg":  ("Segoe UI", 22, "bold"),
    "h1":          ("Segoe UI", 24, "bold"),
    "h2":          ("Segoe UI", 18, "bold"),
    "h3":          ("Segoe UI", 14, "bold"),
    "subtitle":    ("Segoe UI", 13),
    "body_lg":     ("Segoe UI", 15),
    "body":        ("Segoe UI", 14),
    "body_b":      ("Segoe UI", 14, "bold"),
    "sm":          ("Segoe UI", 13),
    "sm_b":        ("Segoe UI", 13, "bold"),
    "xs":          ("Segoe UI", 12),
    "xs_b":        ("Segoe UI", 12, "bold"),
    "mono":        ("Consolas", 13),
    "mono_sm":     ("Consolas", 12),
    "logo":        ("Segoe UI", 20, "bold"),
    "metric":      ("Segoe UI", 32, "bold"),
    "metric_sm":   ("Segoe UI", 24, "bold"),
    "nav":         ("Segoe UI", 14),
    "nav_a":       ("Segoe UI", 14, "bold"),
}


def configure_treeview_style():
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("Dark.Treeview",
        background=C["card"], foreground=C["text"], fieldbackground=C["card"],
        rowheight=44, borderwidth=0, font=F["sm"])
    style.configure("Dark.Treeview.Heading",
        background=C["elevated"], foreground=C["charcoal"],
        font=F["sm_b"], relief="flat", borderwidth=0, padding=(10, 12))
    style.map("Dark.Treeview",
        background=[("selected", C["elevated"])],
        foreground=[("selected", C["ink"])])
    style.layout("Dark.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    style.configure("Dark.Vertical.TScrollbar",
        troughcolor=C["card"], background=C["elevated"],
        bordercolor=C["card"], arrowcolor=C["muted"], width=6, relief="flat")


def style_option_menu(widget):
    widget.configure(
        fg_color=C["input"],
        button_color=C["elevated"],
        button_hover_color=C["card_hover"],
        text_color=C["ink"],
        dropdown_fg_color=C["card"],
        dropdown_text_color=C["ink"],
        dropdown_hover_color=C["elevated"],
        corner_radius=8,
    )


def animate_count_up(widget, target, suffix="", duration_ms=600, steps=20):
    if target == 0:
        widget.configure(text=f"0{suffix}")
        return
    step_ms = max(1, duration_ms // steps)
    vals = [int(target * (i + 1) / steps) for i in range(steps)]

    def _tick(idx=0):
        if idx < len(vals):
            widget.configure(text=f"{vals[idx]}{suffix}")
            widget.after(step_ms, _tick, idx + 1)
        else:
            widget.configure(text=f"{target}{suffix}")

    widget.configure(text=f"0{suffix}")
    widget.after(step_ms, _tick)


def animate_fade_color(widget, from_color, to_color, duration_ms=180, steps=12, attr="fg_color"):
    def _h2r(h):
        h = h.lstrip("#")
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
    def _r2h(r, g, b):
        return f"#{r:02x}{g:02x}{b:02x}"
    try:
        r1, g1, b1 = _h2r(from_color)
        r2, g2, b2 = _h2r(to_color)
    except Exception:
        return
    step_ms = max(1, duration_ms // steps)

    def _tick(i=1):
        t = i / steps
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        try:
            widget.configure(**{attr: _r2h(r, g, b)})
        except Exception:
            return
        if i < steps:
            widget.after(step_ms, _tick, i + 1)
    widget.after(step_ms, _tick)


def animate_view_transition(container, callback, duration_ms=120):
    callback()


def create_action_btn(parent, text, command, color="primary", size="normal"):
    color_map = {
        "primary":   (C["accent"],       C["accent_h"],   C["primary_on"], None),
        "secondary": (C["elevated"],     C["card_hover"], C["text"],       C["border"]),
        "ghost":     ("transparent",     C["card_hover"], C["secondary"],  None),
        "outline":   ("transparent",     C["card_hover"], C["text"],       C["border"]),
        "success":   ("transparent",     C["card_hover"], C["green"],      C["border"]),
        "danger":    ("transparent",     C["red_glow"],   C["red"],        C["border"]),
        "warning":   ("transparent",     C["card_hover"], C["amber"],      C["border"]),
    }
    fg, hover, tc, bc = color_map.get(color, color_map["primary"])
    dim = {"small": (32, 7), "normal": (38, 8), "large": (44, 8)}
    h, cr = dim.get(size, dim["normal"])
    font = F["xs_b"] if size == "small" else F["sm_b"]
    border_w = 1 if bc else 0
    return ctk.CTkButton(
        parent, text=text, command=command,
        fg_color=fg, hover_color=hover, text_color=tc,
        font=font, corner_radius=cr, height=h, width=112 if size == "small" else 140,
        border_width=border_w, border_color=bc, cursor="hand2"
    )


def create_card_frame(parent, elevated=False, corner_radius=12):
    bg_col = C["elevated"] if elevated else C["card"]
    return ctk.CTkFrame(parent, fg_color=bg_col, corner_radius=corner_radius,
                        border_width=1, border_color=C["border"])


def create_code_window_header(parent, title="terminal", subtitle=""):
    bar = ctk.CTkFrame(parent, fg_color="transparent", height=28)
    bar.pack(fill='x', padx=14, pady=(10, 6))
    bar.pack_propagate(False)
    dots = ctk.CTkFrame(bar, fg_color="transparent")
    dots.pack(side='left', pady=4)
    ctk.CTkLabel(dots, text="\u25cf", font=("Segoe UI", 10), text_color=C["red"],    width=14).pack(side='left')
    ctk.CTkLabel(dots, text="\u25cf", font=("Segoe UI", 10), text_color=C["yellow"], width=14).pack(side='left')
    ctk.CTkLabel(dots, text="\u25cf", font=("Segoe UI", 10), text_color=C["green"],  width=14).pack(side='left')
    ctk.CTkLabel(bar, text=f" {title}", font=F["mono_sm"], text_color=C["charcoal"]).pack(side='left', padx=(6, 0))
    if subtitle:
        ctk.CTkLabel(bar, text=subtitle, font=F["xs"], text_color=C["dim"]).pack(side='right')
    return bar


def create_badge_pill(parent, text, variant="neutral"):
    colors = {
        "neutral": (C["elevated"],    C["border"], C["body"]),
        "success": (C["green_glow"],  C["border"], C["green"]),
        "warning": (C["orange_glow"], C["border"], C["amber"]),
        "danger":  (C["red_glow"],    C["border"], C["red"]),
        "info":    (C["blue_glow"],   C["border"], C["blue"]),
        "active":  (C["primary"],     None,        C["primary_on"]),
    }
    bg, bc, tc = colors.get(variant, colors["neutral"])
    bw = 1 if bc else 0
    return ctk.CTkLabel(parent, text=f"  {text}  ", fg_color=bg, text_color=tc,
                        font=F["xs_b"], corner_radius=9999, height=22)


def add_form_input(parent, label):
    ctk.CTkLabel(parent, text=label, font=F["sm_b"], text_color=C["muted"], anchor="w").pack(anchor='w', padx=16, pady=(12, 4))
    entry = ctk.CTkEntry(parent, fg_color=C["input"], border_color=C["border"],
                         text_color=C["ink"], font=F["sm"], corner_radius=8, height=38, border_width=1)
    entry.pack(fill='x', padx=16)
    return entry


def add_grid_input(parent, label, row, col):
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.grid(row=row, column=col, sticky='nsew', padx=6, pady=6)
    ctk.CTkLabel(frame, text=label, font=F["sm_b"], text_color=C["muted"], anchor="w").pack(anchor='w', pady=(0, 4))
    entry = ctk.CTkEntry(frame, fg_color=C["input"], border_color=C["border"],
                         text_color=C["ink"], font=F["sm"], corner_radius=8, height=38, border_width=1)
    entry.pack(fill='x')
    return entry


def add_section_divider(parent, text):
    f = ctk.CTkFrame(parent, fg_color="transparent")
    f.pack(fill='x', padx=16, pady=(20, 10))
    ctk.CTkLabel(f, text=text, font=F["h3"], text_color=C["ink"]).pack(side='left')
    ctk.CTkFrame(f, fg_color=C["hairline_strong"], height=1, corner_radius=0).pack(side='left', fill='x', expand=True, padx=(12, 0))


def enable_canvas_mousewheel(canvas):
    pass


class TagChipContainer(ctk.CTkFrame):
    def __init__(self, parent, initial_items, label_text, on_change_callback):
        super().__init__(parent, fg_color="transparent")
        self.items = list(initial_items)
        self.on_change = on_change_callback
        ctk.CTkLabel(self, text=label_text, font=F["sm_b"], text_color=C["muted"], anchor="w").pack(anchor='w', padx=16, pady=(10, 5))
        self.chips_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.chips_frame.pack(fill='x', padx=16, pady=3)
        self.entry = ctk.CTkEntry(self, placeholder_text="Type and press Enter...",
                                  fg_color=C["input"], border_color=C["border"], text_color=C["ink"],
                                  font=F["sm"], corner_radius=8, height=36, border_width=1)
        self.entry.pack(fill='x', padx=16, pady=(4, 6))
        self.entry.bind("<Return>", self.add_item_event)
        self.entry.bind("<KeyPress-comma>", self.add_item_comma)
        self.redraw_chips()

    def redraw_chips(self):
        for w in self.chips_frame.winfo_children():
            w.destroy()
        row, col = 0, 0
        for item in self.items:
            chip = ctk.CTkButton(self.chips_frame,
                text=f" {item}  \u2715", fg_color=C["chip"], hover_color=C["card_hover"],
                border_width=1, border_color=C["chip_border"], text_color=C["chip_text"],
                font=F["xs_b"], corner_radius=9999, height=26, width=0,
                command=lambda val=item: self.remove_item(val), cursor="hand2")
            chip.grid(row=row, column=col, padx=4, pady=4, sticky='w')
            col += 1
            if col >= 5:
                col = 0
                row += 1

    def add_item_event(self, event):
        self.add_item(); return "break"

    def add_item_comma(self, event):
        self.after(10, self.add_item); return "break"

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
