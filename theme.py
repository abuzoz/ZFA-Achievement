"""Modern dark theme: palette, fonts, and styled widget helpers.

The whole app pulls its colours from the constants here, so restyling is
centralised. HoverButton and the ttk styling below give the flat, high-contrast
look of a current dark UI without needing a non-standard toolkit.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# ----------------------------------------------------------------- palette
# Deep, near-black base with layered surfaces -- the standard "elevation"
# model of modern dark UIs. Accent is a vivid modern blue.
BG = "#0f1116"        # app background (deepest)
BG_ALT = "#161922"    # header / footer bars
SURFACE = "#1b1f2a"   # cards, rows, inputs
SURFACE_HI = "#232838"  # hovered surface / selected row
BORDER = "#2a2f3d"

FG = "#e8ecf4"        # primary text
FG_DIM = "#8b93a7"    # secondary text
FG_FAINT = "#5b6273"  # tertiary / disabled

ACCENT = "#7c5cff"    # primary action (indigo)
ACCENT_HI = "#9a80ff"  # hovered accent
ACCENT_DIM = "#5f45cc"

SUCCESS = "#3fb950"
WARNING = "#e3b341"
DANGER = "#f85149"

# Gradient endpoints for the header banner and primary surfaces.
GRAD_A = "#7c5cff"    # indigo
GRAD_B = "#b14cff"    # violet-magenta
SIDEBAR = "#12141c"   # navigation rail (a touch darker than BG_ALT)

# Back-compat aliases (older modules import these names).
ACCENT_DIM = ACCENT_DIM  # noqa: PLW0127

FONT_FAMILY = "Segoe UI"


def font(size: int = 10, weight: str = "normal") -> tuple:
    return (FONT_FAMILY, size, weight)


def bar(fraction: float, width: int = 10) -> str:
    """A compact unicode progress bar, e.g. bar(0.6) -> '██████░░░░'."""
    fraction = max(0.0, min(1.0, fraction))
    filled = round(fraction * width)
    return "█" * filled + "░" * (width - filled)


# ---------------------------------------------------------- colour helpers


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(rgb) -> str:
    return "#%02x%02x%02x" % (int(rgb[0]), int(rgb[1]), int(rgb[2]))


def mix(c1: str, c2: str, t: float) -> str:
    """Blend two hex colours; t=0 -> c1, t=1 -> c2."""
    a, b = _hex_to_rgb(c1), _hex_to_rgb(c2)
    return _rgb_to_hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))


# --------------------------------------------------------------- glow FX

try:
    from PIL import Image

    HAS_PIL = True
except ImportError:
    HAS_PIL = False

_glow_cache: dict = {}


def radial_glow(size: int, hex_color: str, max_alpha: int = 130):
    """A soft radial-gradient RGBA image (PIL) for a mouse-follow spotlight.
    Cached per (size, colour). Returns None when Pillow is unavailable."""
    if not HAS_PIL:
        return None
    key = (size, hex_color, max_alpha)
    if key in _glow_cache:
        return _glow_cache[key]
    r, g, b = _hex_to_rgb(hex_color)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = img.load()
    c = size / 2
    for y in range(size):
        dy2 = (y - c) ** 2
        for x in range(size):
            d = ((x - c) ** 2 + dy2) ** 0.5 / c
            if d >= 1:
                continue
            fade = (1 - d) ** 2  # soft falloff
            px[x, y] = (r, g, b, int(max_alpha * fade))
    _glow_cache[key] = img
    return img


class BreathingBorder:
    """Animates a widget's background between two colours to make a glowing
    'rim' pulse gently. Used on the thin frame around the whole window."""

    def __init__(self, widget, c_dim: str, c_bright: str, period_ms: int = 2600):
        self.widget = widget
        self.c_dim = c_dim
        self.c_bright = c_bright
        self.period = period_ms
        self._step = 0
        self._steps = 48
        self._running = True
        self._tick()

    def _tick(self):
        if not self._running:
            return
        import math

        # 0..1..0 triangle via cosine for a smooth breathe.
        phase = (1 - math.cos(2 * math.pi * self._step / self._steps)) / 2
        try:
            self.widget.configure(bg=mix(self.c_dim, self.c_bright, phase))
        except tk.TclError:
            self._running = False
            return
        self._step = (self._step + 1) % self._steps
        self.widget.after(self.period // self._steps, self._tick)

    def stop(self):
        self._running = False


# ----------------------------------------------------------- canvas shapes


def round_rect(canvas, x1, y1, x2, y2, r, **kwargs):
    """Draw a rounded rectangle on a canvas via a smoothed polygon."""
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, splinesteps=24, **kwargs)


class RoundedButton(tk.Canvas):
    """A rounded, flat button with hover feedback. Draws itself on a canvas so
    it gets real rounded corners Tk's stock Button can't."""

    def __init__(
        self, master, text="", command=None, kind="primary",
        width=140, height=40, radius=12, bg=None, font_=None,
    ):
        parent_bg = bg or master["bg"]
        super().__init__(
            master, width=width, height=height, highlightthickness=0, bd=0,
            bg=parent_bg,
        )
        looks = {
            "primary": (ACCENT, ACCENT_HI, "#ffffff"),
            "secondary": (SURFACE, SURFACE_HI, FG),
            "ghost": (parent_bg, SURFACE, FG_DIM),
            "danger": (mix(DANGER, BG, 0.75), mix(DANGER, BG, 0.55), "#ff9d97"),
        }
        self._fill, self._hover, self._fg = looks.get(kind, looks["primary"])
        self._command = command
        self._font = font_ or font(10, "bold")
        self._text = text
        # Grow the button so the label always fits (Arabic + DPI scaling make
        # text wider than a fixed pixel width -> otherwise it clips/overlaps).
        try:
            text_w = tkfont.Font(font=self._font).measure(text)
        except tk.TclError:
            text_w = len(text) * 8
        width = max(width, text_w + 34)
        # NB: not self._w -- tkinter uses that internally for the widget path.
        self._bw, self._bh, self._r = width, height, radius
        self.configure(width=width)
        self._draw(self._fill)
        self.bind("<Enter>", lambda _: self._draw(self._hover))
        self.bind("<Leave>", lambda _: self._draw(self._fill))
        self.bind("<Button-1>", self._click)
        self.configure(cursor="hand2")

    def _draw(self, fill):
        self.delete("all")
        round_rect(self, 1, 1, self._bw - 1, self._bh - 1, self._r, fill=fill, outline="")
        self.create_text(
            self._bw / 2, self._bh / 2, text=self._text, fill=self._fg, font=self._font,
        )

    def _click(self, _):
        if self._command:
            self._command()

    def set_text(self, text: str):
        self._text = text
        self._draw(self._fill)


def gradient_h(canvas, w, h, c1, c2):
    """Paint a smooth horizontal gradient across a canvas."""
    canvas.delete("grad")
    steps = max(1, w)
    for i in range(steps):
        canvas.create_line(
            i, 0, i, h, fill=mix(c1, c2, i / steps), tags="grad"
        )
    canvas.tag_lower("grad")


class StatCard(tk.Canvas):
    """A small rounded card: a big value with a caption beneath. Optionally an
    accent-tinted background for the highlighted stat."""

    def __init__(self, master, value="", caption="", width=118, height=74,
                 accent=False, bg=None):
        parent_bg = bg or master["bg"]
        super().__init__(
            master, width=width, height=height, highlightthickness=0, bd=0,
            bg=parent_bg,
        )
        fill = mix(ACCENT, BG, 0.72) if accent else SURFACE
        value_fg = "#ffffff" if accent else FG
        round_rect(self, 1, 1, width - 1, height - 1, 14, fill=fill, outline="")
        self.create_text(
            18, height / 2 - 8, text=value, fill=value_fg, anchor="w",
            font=font(19, "bold"),
        )
        self.create_text(
            18, height / 2 + 16, text=caption, fill=FG_DIM, anchor="w",
            font=font(8),
        )


# --------------------------------------------------------------- widgets


class HoverButton(tk.Button):
    """Flat button with a hover colour shift. Three looks:
    primary (accent fill), secondary (surface), ghost (bare)."""

    def __init__(self, master, text="", command=None, kind="secondary", **kwargs):
        looks = {
            "primary": (ACCENT, ACCENT_HI, "#ffffff"),
            "secondary": (SURFACE, SURFACE_HI, FG),
            "ghost": (BG_ALT, SURFACE, FG_DIM),
            "danger": (SURFACE, "#3a2226", DANGER),
        }
        self._bg, self._hover, fg = looks.get(kind, looks["secondary"])
        super().__init__(
            master,
            text=text,
            command=command,
            bg=self._bg,
            fg=fg,
            activebackground=self._hover,
            activeforeground=fg,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            cursor="hand2",
            font=kwargs.pop("font", font(10, "bold" if kind == "primary" else "normal")),
            padx=kwargs.pop("padx", 16),
            pady=kwargs.pop("pady", 7),
            **kwargs,
        )
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _on_enter(self, _):
        if str(self["state"]) != "disabled":
            self.configure(bg=self._hover)

    def _on_leave(self, _):
        self.configure(bg=self._bg)


def entry(master, textvariable=None, **kwargs) -> tk.Entry:
    """A soft, borderless input with an accent caret."""
    return tk.Entry(
        master,
        textvariable=textvariable,
        bg=SURFACE,
        fg=FG,
        insertbackground=ACCENT,
        relief="flat",
        borderwidth=0,
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=ACCENT,
        font=font(10),
        **kwargs,
    )


def check(master, text, variable, command=None) -> tk.Checkbutton:
    return tk.Checkbutton(
        master,
        text=text,
        variable=variable,
        command=command,
        bg=BG_ALT,
        fg=FG_DIM,
        activebackground=BG_ALT,
        activeforeground=FG,
        selectcolor=SURFACE,
        highlightthickness=0,
        bd=0,
        cursor="hand2",
        font=font(9),
    )


def apply_theme(root: tk.Misc) -> None:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    # Base font a touch larger for a more spacious, modern feel.
    try:
        default = tkfont.nametofont("TkDefaultFont")
        default.configure(family=FONT_FAMILY, size=10)
        root.option_add("*Font", default)
    except tk.TclError:
        pass

    style.configure(
        "Vertical.TScrollbar",
        background=SURFACE,
        troughcolor=BG,
        bordercolor=BG,
        arrowcolor=FG_FAINT,
        relief="flat",
        borderwidth=0,
    )
    style.map(
        "Vertical.TScrollbar",
        background=[("active", SURFACE_HI), ("pressed", ACCENT_DIM)],
    )

    # Roomy, borderless table rows with a clear selection colour.
    style.configure(
        "Treeview",
        background=SURFACE,
        fieldbackground=SURFACE,
        foreground=FG,
        borderwidth=0,
        relief="flat",
        rowheight=32,
        font=font(10),
    )
    style.configure(
        "Treeview.Heading",
        background=BG_ALT,
        foreground=FG_DIM,
        relief="flat",
        borderwidth=0,
        padding=(8, 8),
        font=font(9, "bold"),
    )
    style.map(
        "Treeview.Heading",
        background=[("active", SURFACE)],
        foreground=[("active", FG)],
    )
    style.map(
        "Treeview",
        # Strong indigo highlight so the selected row is unmistakable, even
        # over the zebra stripes (verified it renders on top of tag colours).
        background=[("selected", ACCENT_DIM)],
        foreground=[("selected", "#ffffff")],
    )

    style.configure(
        "TCombobox",
        fieldbackground=SURFACE,
        background=SURFACE,
        foreground=FG,
        arrowcolor=FG_DIM,
        bordercolor=BORDER,
        relief="flat",
        padding=4,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", SURFACE)],
        foreground=[("readonly", FG)],
        selectbackground=[("readonly", SURFACE)],
        selectforeground=[("readonly", FG)],
    )
    # The dropdown list is a classic Tk listbox, not ttk -- style it via the
    # option database or it renders white-on-white and looks "missing".
    root.option_add("*TCombobox*Listbox.background", SURFACE)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    root.option_add("*TCombobox*Listbox.font", font(10))

    style.configure(
        "Accent.Horizontal.TProgressbar",
        troughcolor=SURFACE,
        background=ACCENT,
        bordercolor=SURFACE,
        lightcolor=ACCENT,
        darkcolor=ACCENT,
    )
