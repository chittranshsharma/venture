import customtkinter as ctk
from tkinter import ttk
import tkinter as tk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Warm Ink / Premium Dark Design System
C = {
    "bg":               "#151210",
    "canvas":           "#151210",
    "sidebar":          "#111009",
    "card":             "#1E1B17",
    "card_hover":       "#252118",
    "elevated":         "#2A2620",
    "input":            "#1E1B17",
    "deep":             "#0E0C0A",
    "hairline":         "#1C1A16",
    "hairline_strong":  "#2E2B26",
    "border":           "#2E2B26",
    "divider_soft":     "#181612",
    "focus":            "#F0EBE3",
    "primary":          "#F0EBE3",
    "primary_on":       "#151210",
    "primary_p":        "#E8E0D5",
    "accent":           "#F0EBE3",
    "accent_h":         "#DDD4C8",
    "accent_d":         "#C9BFB2",
    "text":             "#F0EBE3",
    "ink":              "#F0EBE3",
    "body":             "#C4BDB4",
    "charcoal":         "#9A938A",
    "muted":            "#7A746C",
    "dim":              "#514D48",
    "ash":              "#615D58",
    "stone":            "#3E3B37",
    "on_light":         "#151210",
    "on_light_mute":    "#4A4540",
    "orange":           "#E8923A",
    "orange_glow":      "#1E1108",
    "yellow":           "#D4A843",
    "amber":            "#D4A843",
    "amber_h":          "#BD9438",
    "blue":             "#4E9CFF",
    "blue_glow":        "#0A1520",
    "link":             "#4E9CFF",
    "green":            "#2DD4A0",
    "green_glow":       "#0A1E18",
    "green_h":          "#28BC8F",
    "red":              "#E85454",
    "red_glow":         "#1E0E0E",
    "red_h":            "#D04646",
    "purple":           "#A78BFA",
    "cyan":             "#38C4D8",
    "chip":             "#2A2620",
    "chip_border":      "#2E2B26",
    "chip_text":        "#F0EBE3",
}

F = {
    "display_xxl": ("Segoe UI", 26, "bold"),
    "display_xl":  ("Segoe UI", 21, "bold"),
    "display_lg":  ("Segoe UI", 17, "bold"),
    "h1":          ("Segoe UI", 16, "bold"),
    "h2":          ("Segoe UI", 12, "bold"),
    "h3":          ("Segoe UI", 11, "bold"),
    "subtitle":    ("Segoe UI", 11),
    "body_lg":     ("Segoe UI", 11),
    "body":        ("Segoe UI", 10),
    "body_b":      ("Segoe UI", 10, "bold"),
    "sm":          ("Segoe UI", 10),
    "sm_b":        ("Segoe UI", 10, "bold"),
    "xs":          ("Segoe UI", 9),
    "xs_b":        ("Segoe UI", 9, "bold"),
    "mono":        ("Cascadia Code", 10),
    "mono_sm":     ("Cascadia Code", 9),
    "logo":        ("Segoe UI", 14, "bold"),
    "metric":      ("Segoe UI", 24, "bold"),
    "metric_sm":   ("Segoe UI", 17, "bold"),
    "nav":         ("Segoe UI", 10),
    "nav_a":       ("Segoe UI", 10, "bold"),
}


def configure_treeview_style():
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("Dark.Treeview",
        background=C["card"], foreground=C["text"], fieldbackground=C["card"],
        rowheight=34, borderwidth=0, font=F["sm"])
    style.configure("Dark.Treeview.Heading",
        background=C["elevated"], foreground=C["charcoal"],
        font=F["sm_b"], relief="flat", borderwidth=0)
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
    orig = C["bg"]
    dim_col = "#0F0D0B"

    def _do_switch():
        callback()
        animate_fade_color(container, dim_col, orig, duration_ms=duration_ms)

    animate_fade_color(container, orig, dim_col, duration_ms=duration_ms // 2)
    container.after(duration_ms // 2, _do_switch)


def create_action_btn(parent, text, command, color="primary", size="normal"):
    color_map = {
        "primary":   (C["primary"],   C["primary_p"],  C["primary_on"], None),
        "secondary": (C["elevated"],  C["card_hover"], C["ink"],        C["border"]),
        "ghost":     (C["elevated"],  C["card_hover"], C["ink"],        C["border"]),
        "outline":   ("transparent",  C["card_hover"], C["ink"],        C["border"]),
        "success":   (C["elevated"],  C["card_hover"], C["green"],      C["border"]),
        "danger":    (C["elevated"],  C["card_hover"], C["red"],        C["border"]),
        "warning":   (C["elevated"],  C["card_hover"], C["amber"],      C["border"]),
    }
    fg, hover, tc, bc = color_map.get(color, color_map["primary"])
    dim = {"small": (28, 6), "normal": (36, 8), "large": (40, 10)}
    h, cr = dim.get(size, dim["normal"])
    font = F["xs_b"] if size == "small" else F["sm_b"]
    border_w = 1 if bc else 0
    return ctk.CTkButton(
        parent, text=text, command=command,
        fg_color=fg, hover_color=hover, text_color=tc,
        font=font, corner_radius=cr, height=h,
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
