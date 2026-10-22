"""The console look: colors, fonts, scaling, and the custom widgets the window is built from.

Other modules read the fonts as ui.FONT and so on at the moment they build a widget,
because pick_fonts() may swap them for fallbacks once Tk is running.
"""

from __future__ import annotations

import ctypes
import queue
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

import cv2
import numpy as np
from PIL import Image

# A starship console, after the picture that started this project: a black sky, an
# orange star and its blue corona. Holographic blue marks what is selected and the
# readouts; the warm orange of a wrist tool marks the things you press.
SPACE, DECK, PANEL, PANEL_HI = "#05080d", "#070b11", "#0b131b", "#112030"
LINE, LINE_HI = "#1c3443", "#2b5468"
ICE, ICE_DIM, MUTED = "#dcefff", "#9fb6c4", "#8099a8"   # MUTED passes 4.5:1 on every panel color
HOLO, HOLO_LO = "#46c8ff", "#1d6f91"
OMNI, OMNI_HI, OMNI_LO = "#ff8a1f", "#ffa952", "#c4600b"
SEL = "#12303f"
OFFLINE = "#ff5a4f"
TRACK = "#16222d"

# Agency FB comes with Microsoft Office; Bahnschrift and Cascadia Mono come with
# Windows 10 and 11. pick_fonts swaps in the nearest face when one is missing.
FONT, FONT_B, FONT_SM = ("Bahnschrift", 10), ("Bahnschrift SemiBold", 10), ("Bahnschrift", 9)
FONT_SIGN = ("Bahnschrift SemiCondensed", 9, "bold")    # small console capitals
FONT_BIG = ("Bahnschrift SemiBold", 12)
FONT_MAST, FONT_READOUT, FONT_HERO = ("Agency FB", 28, "bold"), ("Agency FB", 21, "bold"), ("Agency FB", 30, "bold")
FONT_TITLE = ("Agency FB", 22, "bold")
FONT_MONO = ("Cascadia Mono", 9)

UI = 1.0  # display scaling; pixel sizes are multiplied by it


def px(n: float) -> int:
    return int(round(n * UI))


def set_ui_scale(root: tk.Tk) -> None:
    global UI
    UI = max(1.0, root.winfo_fpixels("1i") / 96)


def pick_fonts(root: tk.Tk) -> None:
    global FONT, FONT_B, FONT_SM, FONT_SIGN, FONT_BIG, FONT_MAST, FONT_READOUT, FONT_HERO, FONT_TITLE, FONT_MONO
    have = set(tkfont.families(root))
    if "Bahnschrift" not in have:
        FONT, FONT_B, FONT_SM = ("Segoe UI", 10), ("Segoe UI Semibold", 10), ("Segoe UI", 9)
        FONT_SIGN, FONT_BIG = ("Segoe UI Semibold", 9), ("Segoe UI Semibold", 12)
    if "Agency FB" not in have:
        narrow = "Bahnschrift SemiCondensed" if "Bahnschrift" in have else "Segoe UI Semibold"
        FONT_MAST, FONT_READOUT = (narrow, 22, "bold"), (narrow, 16, "bold")
        FONT_HERO, FONT_TITLE = (narrow, 22, "bold"), (narrow, 17, "bold")
    if "Cascadia Mono" not in have:
        FONT_MONO = ("Consolas", 9)


def apply_style(root: tk.Tk) -> None:
    st = ttk.Style(root)
    st.theme_use("clam")  # the built in theme that honors colors everywhere
    root.configure(background=SPACE)
    st.configure(".", background=PANEL, foreground=ICE, font=FONT, bordercolor=LINE_HI, lightcolor=PANEL_HI,
                 darkcolor=PANEL_HI, troughcolor=PANEL, focuscolor=HOLO, selectbackground=SEL,
                 selectforeground=ICE, insertcolor=ICE, fieldbackground=SPACE, arrowcolor=HOLO)
    st.configure("TButton", padding=(px(12), px(5)), background=PANEL_HI, foreground=ICE)
    st.map("TButton", background=[("disabled", PANEL), ("pressed", SEL), ("active", "#16303f")],
           foreground=[("disabled", MUTED)], bordercolor=[("disabled", LINE), ("active", HOLO)],
           lightcolor=[("active", "#16303f")], darkcolor=[("active", "#16303f")])
    for widget in ("TCombobox", "TSpinbox", "TEntry"):
        st.configure(widget, fieldbackground=SPACE, background=PANEL_HI, foreground=ICE, padding=px(4))
        st.map(widget, fieldbackground=[("disabled", PANEL), ("readonly", SPACE)],
               foreground=[("disabled", MUTED), ("readonly", ICE)], selectbackground=[("readonly", SPACE)],
               selectforeground=[("readonly", ICE)], bordercolor=[("focus", HOLO), ("hover", HOLO_LO)],
               arrowcolor=[("disabled", MUTED)])
    for bar in ("TScrollbar", "Vertical.TScrollbar"):
        st.configure(bar, background=PANEL_HI, troughcolor=SPACE, bordercolor=SPACE, arrowcolor=HOLO,
                     lightcolor=PANEL_HI, darkcolor=PANEL_HI, gripcount=0, arrowsize=px(12))
        st.map(bar, background=[("active", SEL), ("pressed", SEL)])
    root.option_add("*TCombobox*Listbox.background", PANEL)
    root.option_add("*TCombobox*Listbox.foreground", ICE)
    root.option_add("*TCombobox*Listbox.selectBackground", SEL)
    root.option_add("*TCombobox*Listbox.selectForeground", HOLO)
    root.option_add("*TCombobox*Listbox.font", FONT)
    root.option_add("*Menu.background", PANEL)
    root.option_add("*Menu.foreground", ICE)
    root.option_add("*Menu.activeBackground", SEL)
    root.option_add("*Menu.activeForeground", HOLO)
    root.option_add("*Menu.font", FONT)


def colorref(color: str) -> int:
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    return r | (g << 8) | (b << 16)


def tint_title_bar(window: tk.Misc) -> None:
    """Paint the Windows title bar to match the console (dark on Windows 10, the deck
    color on Windows 11). Older versions ignore this."""
    if sys.platform != "win32":
        return
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        for attribute, value in ((20, 1), (35, colorref(DECK)), (36, colorref(ICE))):
            v = ctypes.c_int(value)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(v), ctypes.sizeof(v))
    except (AttributeError, OSError):
        pass


def fit_inside(image: np.ndarray, box) -> np.ndarray:
    h, w = image.shape[:2]
    s = min(box[0] / w, box[1] / h, 1.0)
    size = (max(1, round(w * s)), max(1, round(h * s)))
    return cv2.resize(image, size, interpolation=cv2.INTER_AREA)


# Drawing ----------------------------------------------------------------------------------

def chamfer(x0, y0, x1, y1, cut):
    """A rectangle with its top left and bottom right corners clipped, as polygon points."""
    return [x0 + cut, y0, x1, y0, x1, y1 - cut, x1 - cut, y1, x0, y1, x0, y0 + cut]


def draw_brackets(c, x0, y0, x1, y1, color, arm, width=2):
    for x, y, dx, dy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        c.create_line(x, y + dy * arm, x, y, x + dx * arm, y, fill=color, width=width, capstyle="projecting")


def draw_rail(c, width, upward=False):
    """Console trim: a thin holographic line with a lit segment, tick marks and an
    orange marker, like the edge of a heads up display. upward is the bottom edition."""
    c.delete("all")
    h = int(c["height"])
    y = 1 if not upward else h - 2
    t = 1 if not upward else -1  # which way the shapes grow
    c.create_line(0, y, width, y, fill=LINE_HI)
    a, b = px(20), px(240)
    c.create_polygon(a, y, b, y, b + px(6), y + t * px(4), a, y + t * px(4), fill=HOLO, outline="")
    for k, x in enumerate(range(int(width * 0.55), width - px(140), px(8))):
        c.create_line(x, y, x, y + t * (px(7) if k % 5 == 0 else px(3)), fill=LINE_HI)
    c.create_polygon(width - px(120), y, width - px(20), y, width - px(20), y + t * px(4),
                     width - px(114), y + t * px(4), fill=OMNI, outline="")


def draw_scene(c, x0, y0, x1, y1, faded=False, flip=False):
    """A tiny space scene for the fit cards: a star rising over a horizon."""
    w, h = x1 - x0, y1 - y0
    c.create_rectangle(x0, y0, x1, y1, fill="#152230" if faded else "#0a1420", outline="")
    for fx, fy in ((0.12, 0.18), (0.86, 0.14), (0.3, 0.42), (0.7, 0.3), (0.52, 0.1)):
        x, y = x0 + w * fx, y0 + h * fy
        c.create_rectangle(x, y, x + 1, y + 1, fill=MUTED if faded else ICE_DIM, outline="")
    horizon = y0 + h * 0.72
    cx = x0 + w * (0.42 if flip else 0.58)
    r = min(w * 0.36, h * 0.55)
    star, core, rim = ("#8a5a33", "#a98a68", "#3d6a80") if faded else (OMNI, "#ffd08a", HOLO)
    c.create_arc(cx - r, horizon - r, cx + r, horizon + r, start=0, extent=180, fill=star, outline="")
    rc = r * 0.55
    c.create_arc(cx - rc, horizon - rc, cx + rc, horizon + rc, start=0, extent=180, fill=core, outline="")
    c.create_rectangle(x0, horizon, x1, y1, fill="#0d151e" if faded else "#04070c", outline="")
    c.create_line(x0, horizon, x1, horizon, fill=rim)


def draw_sample(c, mode, x0, y0, x1, y1):
    """A diagram of one fit choice: the screen, the picture, and what fills the rest."""
    c.create_rectangle(x0 - 2, y0 - 2, x1 + 1, y1 + 1, fill="#02040a", outline=LINE_HI)
    if mode == "fill":
        draw_scene(c, x0, y0, x1, y1)
        c.create_rectangle(x0, y0 - px(7), x1, y1 + px(7), outline=OMNI, dash=(2, 2))  # the cropped parts
        return
    third = (x1 - x0) / 3
    a, b = x0 + third, x1 - third
    if mode == "blur":
        for left, right in ((x0, a), (b, x1)):
            c.create_rectangle(left, y0, right, y1, fill="#14202c", outline="")
            c.create_rectangle(left, y0 + (y1 - y0) * 0.55, right, y1, fill="#3a2a22", outline="")
    elif mode == "mirror":
        draw_scene(c, x0, y0, a, y1, faded=True, flip=True)
        draw_scene(c, b, y0, x1, y1, faded=True, flip=True)
    else:
        c.create_rectangle(x0, y0, a, y1, fill="#000000", outline="")
        c.create_rectangle(b, y0, x1, y1, fill="#000000", outline="")
    draw_scene(c, a, y0, b, y1)


class Sky:
    """A star field with faint orange and blue nebulae, the same at every window size."""

    def __init__(self):
        rng = np.random.default_rng(42)
        self.stars = rng.random((7000, 2))
        self.brightness = rng.random(7000) ** 4 * 210 + 20
        self.tints = np.array([(1.0, 1.0, 1.0), (0.78, 0.9, 1.0), (1.0, 0.88, 0.72)])[rng.integers(0, 3, 7000)]
        self.clouds = []
        for color, strength, (cx, cy) in (((255, 138, 31), 34, (0.55, 1.1)), ((70, 200, 255), 20, (0.0, 0.0)),
                                          ((70, 200, 255), 14, (1.0, 0.45))):
            noise = cv2.GaussianBlur(rng.random((40, 64)).astype(np.float32), (0, 0), 2.2)
            noise = (noise - noise.min()) / (np.ptp(noise) + 1e-6)
            yy, xx = np.mgrid[0:40, 0:64].astype(np.float32)
            falloff = np.exp(-(((xx / 64 - cx) ** 2) / 0.16 + ((yy / 40 - cy) ** 2) / 0.22))
            self.clouds.append((noise ** 2 * falloff, np.array(color, np.float32) / 255 * strength))

    def render(self, w: int, h: int) -> Image.Image:
        image = np.empty((h, w, 3), np.float32)
        image[:] = (5, 8, 13)
        for cloud, color in self.clouds:
            image += cv2.resize(cloud, (w, h), interpolation=cv2.INTER_CUBIC)[..., None] * color
        n = min(len(self.stars), w * h // 650)
        xs = (self.stars[:n, 0] * (w - 1)).astype(int)
        ys = (self.stars[:n, 1] * (h - 1)).astype(int)
        image[ys, xs] += self.brightness[:n, None] * self.tints[:n]
        halo = np.zeros((h, w), np.float32)
        k = min(n, max(4, n // 90))
        halo[ys[:k], xs[:k]] = self.brightness[:k] * 6 + 400
        image += cv2.GaussianBlur(halo, (0, 0), 1.7)[..., None] * np.array([0.85, 0.93, 1.0], np.float32)
        yy, xx = np.ogrid[0:h, 0:w]
        vignette = 1 - 0.25 * ((((xx / w) - 0.5) * 2) ** 2 + (((yy / h) - 0.5) * 2) ** 2)
        image *= vignette[..., None]
        return Image.fromarray(np.clip(image, 0, 255).astype(np.uint8))


# Widgets ----------------------------------------------------------------------------------

class HudButton(tk.Canvas):
    """A console button with clipped corners, drawn so its face can light up on hover."""

    KINDS = {
        "primary": dict(fill=OMNI, hover=OMNI_HI, press=OMNI_LO, text=SPACE, hover_text=SPACE, outline=""),
        "secondary": dict(fill=DECK, hover=SEL, press=PANEL, text=HOLO, hover_text=HOLO, outline=HOLO),
        "quiet": dict(fill=DECK, hover=DECK, press=DECK, text=ICE_DIM, hover_text=HOLO, outline=""),
        "panel": dict(fill=PANEL_HI, hover="#16303f", press=SEL, text=ICE, hover_text=ICE, outline=LINE_HI),
    }

    def __init__(self, master, text, command, kind="primary", font=None, padx=20, pady=8, tip=None):
        super().__init__(master, highlightthickness=0, background=master["background"], cursor="hand2")
        self.kind, self.command = self.KINDS[kind], command
        self.font = tkfont.Font(root=self, font=font or FONT_B)
        self.padx, self.pady = px(padx), px(pady)
        self.enabled, self.look = True, "fill"
        self.bind("<Enter>", lambda _e: self._show("hover"))
        self.bind("<Leave>", lambda _e: self._show("fill"))
        self.bind("<ButtonPress-1>", lambda _e: self._show("press"))
        self.bind("<ButtonRelease-1>", self._release)
        self.set_text(text)
        if tip:
            Tooltip(self, tip)

    def set_text(self, text):
        self.text = text
        self.configure(width=self.font.measure(text) + 2 * self.padx,
                       height=self.font.metrics("linespace") + 2 * self.pady)
        self._draw()

    def set_enabled(self, on: bool):
        self.enabled = on
        self.configure(cursor="hand2" if on else "arrow")
        self._draw()

    def _show(self, look):
        self.look = look
        self._draw()

    def _release(self, event):
        inside = 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()
        self._show("hover" if inside else "fill")
        if inside and self.enabled:
            self.command()

    def _draw(self):
        self.delete("all")
        w, h = int(self["width"]), int(self["height"])
        k = self.kind
        if self.enabled:
            fill, outline = k[self.look], k["outline"]
            text = k["hover_text"] if self.look == "hover" else k["text"]
        else:
            fill = PANEL if k is self.KINDS["primary"] else k["fill"]
            outline, text = (LINE if k["outline"] or k is self.KINDS["primary"] else ""), MUTED
        self.create_polygon(chamfer(1, 1, w - 1, h - 1, px(8)), fill=fill, outline=outline or fill)
        self.create_text(w / 2, h / 2, text=self.text, font=self.font, fill=text)


class Tooltip:
    """A small note that appears when the pointer rests on a widget."""

    def __init__(self, widget, text):
        self.widget, self.text, self.window, self.job = widget, text, None, None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event):
        self.job = self.widget.after(600, self._show)

    def _show(self):
        if self.window:
            return
        x = self.widget.winfo_rootx() + px(8)
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + px(6)
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.geometry(f"+{x}+{y}")
        tk.Label(self.window, text=self.text, background=PANEL_HI, foreground=ICE, font=FONT_SM, justify="left",
                 padx=px(8), pady=px(5), highlightthickness=1, highlightbackground=LINE_HI,
                 wraplength=px(320)).pack()

    def _hide(self, _event=None):
        if self.job:
            self.widget.after_cancel(self.job)
            self.job = None
        if self.window:
            self.window.destroy()
            self.window = None


class FitCard(tk.Canvas):
    """One fit choice: a small diagram with a name under it."""

    W, H = 138, 100

    def __init__(self, master, mode, title, note, on_pick):
        super().__init__(master, width=px(self.W), height=px(self.H), background=PANEL, highlightthickness=0,
                         cursor="hand2")
        self.mode, self.title, self.note, self.on_pick = mode, title, note, on_pick
        self.selected = self.hover = False
        self.enabled = True
        self.bind("<Enter>", lambda _e: self._hover(True))
        self.bind("<Leave>", lambda _e: self._hover(False))
        self.bind("<Button-1>", lambda _e: self.enabled and self.on_pick(self.mode))
        self.draw()

    def _hover(self, on):
        self.hover = on
        self.draw()

    def draw(self):
        self.delete("all")
        w, h = px(self.W), px(self.H)
        lit = self.hover and self.enabled and not self.selected
        border = HOLO if self.selected else (HOLO_LO if lit else LINE)
        fill = SEL if self.selected else (PANEL_HI if lit else PANEL)
        self.create_polygon(chamfer(1, 1, w - 2, h - 2, px(10)), fill=fill, outline=border,
                            width=2 if self.selected else 1)
        draw_sample(self, self.mode, px(16), px(13), w - px(16), px(56))
        self.create_text(w / 2, px(73), text=self.title, font=FONT_B,
                         fill=HOLO if self.selected else (ICE if self.enabled else MUTED))
        self.create_text(w / 2, px(89), text=self.note, font=FONT_SM, fill=MUTED)


class Segmented(tk.Frame):
    """A row of joined choices, one lit at a time."""

    def __init__(self, master, options, variable, command, padx=14):
        super().__init__(master, background=LINE, padx=1, pady=1)
        self.variable, self.command, self.enabled = variable, command, True
        self.items = []
        for i, (key, label) in enumerate(options):
            item = tk.Label(self, text=label, font=FONT, padx=px(padx), pady=px(6), cursor="hand2")
            item.pack(side="left", padx=(1 if i else 0, 0))
            item.bind("<Button-1>", lambda _e, k=key: self._pick(k))
            item.bind("<Enter>", lambda _e, k=key: self.paint(hover=k))
            item.bind("<Leave>", lambda _e: self.paint())
            self.items.append((key, item))
        self.paint()

    def _pick(self, key):
        if self.enabled:
            self.variable.set(key)
            self.paint()
            self.command()

    def set_enabled(self, on: bool):
        self.enabled = on
        self.paint()

    def paint(self, hover=None):
        for key, item in self.items:
            on = self.variable.get() == key
            item.configure(
                background=SEL if on else (PANEL_HI if hover == key and self.enabled else PANEL),
                foreground=HOLO if on else (ICE if self.enabled else MUTED),
                cursor="hand2" if self.enabled else "arrow",
            )


class HudSlider(tk.Canvas):
    """A console slider: its name and value above a thin track that lights up to the knob.
    Drag or click to set it, use the mouse wheel to nudge it, double click to reset it."""

    def __init__(self, master, label, variable: tk.DoubleVar, from_, to, command, width=200, fmt=None,
                 default=None, centered=False, step=None, tip=None):
        super().__init__(master, width=px(width), height=px(40), background=master["background"],
                         highlightthickness=0, cursor="hand2")
        self.label, self.variable, self.lo, self.hi = label, variable, from_, to
        self.command, self.fmt = command, fmt or (lambda v: f"{v:.0%}")
        self.default = from_ if default is None else default
        self.centered, self.step = centered, step or (to - from_) / 20
        self.enabled = True
        self.margin = px(7)
        for event in ("<ButtonPress-1>", "<B1-Motion>"):
            self.bind(event, self._drag)
        self.bind("<Double-Button-1>", lambda _e: self.set(self.default, notify=True))
        self.bind("<MouseWheel>", self._wheel)
        variable.trace_add("write", lambda *_: self.draw())
        self.draw()
        if tip:
            Tooltip(self, tip)

    def set(self, value, notify=False):
        self.variable.set(min(self.hi, max(self.lo, value)))
        if notify:
            self.command()

    def set_enabled(self, on: bool):
        self.enabled = on
        self.configure(cursor="hand2" if on else "arrow")
        self.draw()

    def _x_for(self, value):
        w = int(self["width"])
        return self.margin + (value - self.lo) / (self.hi - self.lo) * (w - 2 * self.margin)

    def _drag(self, event):
        if not self.enabled:
            return
        w = int(self["width"])
        t = (event.x - self.margin) / max(1, w - 2 * self.margin)
        self.set(self.lo + min(1, max(0, t)) * (self.hi - self.lo), notify=True)

    def _wheel(self, event):
        if self.enabled:
            self.set(self.variable.get() + (self.step if event.delta > 0 else -self.step), notify=True)

    def draw(self):
        self.delete("all")
        w = int(self["width"])
        value = self.variable.get()
        on = self.enabled
        self.create_text(0, px(9), text=self.label, anchor="w", font=FONT_SM, fill=ICE_DIM if on else MUTED)
        self.create_text(w, px(9), text=self.fmt(value), anchor="e", font=FONT_MONO, fill=ICE if on else MUTED)
        y = px(28)
        self.create_line(self.margin, y, w - self.margin, y, fill=TRACK, width=px(4), capstyle="round")
        start = self._x_for(0 if self.centered else self.lo)
        knob = self._x_for(value)
        color = (OMNI if on else LINE_HI)
        if abs(knob - start) > 1:
            self.create_line(start, y, knob, y, fill=color, width=px(4), capstyle="round")
        r = px(6)
        self.create_polygon(knob, y - r, knob + r, y, knob, y + r, knob - r, y, fill=ICE if on else MUTED,
                            outline=color)


class Toggle(tk.Frame):
    """An on and off switch with its label, for a BooleanVar."""

    def __init__(self, master, label, variable: tk.BooleanVar, command, tip=None):
        super().__init__(master, background=master["background"], cursor="hand2")
        self.variable, self.command, self.enabled = variable, command, True
        self.box = tk.Canvas(self, width=px(30), height=px(16), background=master["background"], highlightthickness=0)
        self.box.pack(side="left")
        self.text = tk.Label(self, text=label, background=master["background"], font=FONT_SM)
        self.text.pack(side="left", padx=(px(7), 0))
        for widget in (self, self.box, self.text):
            widget.bind("<Button-1>", self._flip)
        variable.trace_add("write", lambda *_: self.draw())
        self.draw()
        if tip:
            Tooltip(self, tip)

    def _flip(self, _event):
        if self.enabled:
            self.variable.set(not self.variable.get())
            self.command()

    def set_enabled(self, on: bool):
        self.enabled = on
        self.draw()

    def draw(self):
        c = self.box
        c.delete("all")
        on = self.variable.get()
        w, h = px(30), px(16)
        c.create_polygon(chamfer(1, 1, w - 1, h - 1, px(4)), fill=SEL if on else TRACK,
                         outline=HOLO if on else LINE_HI)
        kx = w - px(9) if on else px(9)
        c.create_rectangle(kx - px(4), px(4), kx + px(4), h - px(4), fill=HOLO if on else MUTED, outline="")
        self.text.configure(foreground=(ICE if on else ICE_DIM) if self.enabled else MUTED)


class Meter(tk.Canvas):
    """A progress bar made of short segments, like a console charge meter."""

    def __init__(self, master):
        super().__init__(master, height=px(8), background=master["background"], highlightthickness=0)
        self.value = 0.0
        self.bind("<Configure>", lambda _e: self.draw())

    def set(self, value: float):
        self.value = max(0.0, min(1.0, value))
        self.draw()

    def draw(self):
        self.delete("all")
        w, h = self.winfo_width(), int(self["height"])
        seg, gap = px(6), px(2)
        count = max(1, (w + gap) // (seg + gap))
        lit = round(self.value * count)
        for i in range(count):
            x = i * (seg + gap)
            self.create_rectangle(x, 0, x + seg, h, fill=OMNI if i < lit else TRACK, outline="")


class MonitorMap(tk.Canvas):
    """Your displays as Windows arranges them, the chosen one lit. Click one to choose it."""

    def __init__(self, master, screens, on_pick, width=250, height=64):
        super().__init__(master, width=px(width), height=px(height), background=master["background"],
                         highlightthickness=0)
        self.screens, self.on_pick = screens, on_pick
        self.boxes = []
        self.bind("<Button-1>", self._click)
        self.show(None, False)

    def show(self, selected, span: bool, custom=False):
        self.delete("all")
        self.boxes = []
        if not self.screens:
            return
        w, h = int(self["width"]), int(self["height"])
        left = min(s.left for s in self.screens)
        top = min(s.top for s in self.screens)
        right = max(s.left + s.width for s in self.screens)
        bottom = max(s.top + s.height for s in self.screens)
        scale = min((w - px(8)) / (right - left), (h - px(8)) / (bottom - top))
        ox = (w - (right - left) * scale) / 2
        oy = (h - (bottom - top) * scale) / 2
        for s in self.screens:
            x0, y0 = ox + (s.left - left) * scale + 2, oy + (s.top - top) * scale + 2
            x1, y1 = x0 + s.width * scale - 4, y0 + s.height * scale - 4
            lit = span or (selected is not None and s.device == selected.device)
            dim = custom
            self.create_rectangle(x0, y0, x1, y1, fill=SEL if lit and not dim else PANEL,
                                  outline=(HOLO if lit and not dim else LINE_HI), width=2 if lit and not dim else 1)
            self.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=s.name.split()[-1], font=FONT_B,
                             fill=(HOLO if lit and not dim else MUTED))
            self.boxes.append((x0, y0, x1, y1, s))
        if span and len(self.screens) > 1:
            self.create_rectangle(ox, oy, ox + (right - left) * scale, oy + (bottom - top) * scale,
                                  outline=OMNI, dash=(3, 3))
        self.configure(cursor="hand2" if len(self.screens) > 1 else "arrow")

    def _click(self, event):
        for x0, y0, x1, y1, s in self.boxes:
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                self.on_pick(s)
                return


def section(parent, text):
    """A heading for a group of controls: console capitals after a short orange bar."""
    row = tk.Frame(parent, background=parent["background"])
    tk.Frame(row, background=OMNI, width=px(3), height=px(13)).pack(side="left", padx=(0, px(8)))
    tk.Label(row, text=text, background=parent["background"], foreground=OMNI, font=FONT_SIGN).pack(side="left")
    return row


class Dialog(tk.Toplevel):
    """A window in the console style that sits over the main one until closed."""

    def __init__(self, master, title, width=820, height=620):
        super().__init__(master, background=SPACE)
        self.title(title)
        self.transient(master)
        self.geometry(f"{px(width)}x{px(height)}+{master.winfo_rootx() + px(60)}+{master.winfo_rooty() + px(40)}")
        self.minsize(px(520), px(360))
        tint_title_bar(self)
        head = tk.Frame(self, background=DECK)
        head.pack(fill="x")
        tk.Label(head, text=title.upper(), background=DECK, foreground=ICE, font=FONT_TITLE).pack(
            side="left", padx=px(18), pady=px(10))
        rail = tk.Canvas(self, height=px(16), background=SPACE, highlightthickness=0)
        rail.pack(fill="x")
        rail.bind("<Configure>", lambda e: draw_rail(rail, e.width))
        self.body = tk.Frame(self, background=SPACE)
        self.body.pack(fill="both", expand=True, padx=px(18), pady=(0, px(14)))
        self.bind("<Escape>", lambda _e: self.destroy())
        self.focus_set()
        self._inbox: queue.Queue = queue.Queue()
        self.after(50, self._drain)

    def post(self, fn, *args):
        """Run fn(*args) on the window's own thread. Background tasks call this, because
        Tk widgets may only be touched from the thread that made them."""
        self._inbox.put((fn, args))

    def _drain(self):
        try:
            while True:
                fn, args = self._inbox.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(50, self._drain)


class ScrollGrid(tk.Frame):
    """A scrolling area for a grid of cards (history thumbnails, search results)."""

    def __init__(self, master):
        super().__init__(master, background=SPACE)
        self.canvas = tk.Canvas(self, background=SPACE, highlightthickness=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, background=SPACE)
        self.inner.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.window, width=e.width))
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.bind_all("<MouseWheel>", self._wheel, add="+")

    def _wheel(self, event):
        if self.winfo_exists() and str(event.widget).startswith(str(self)):
            self.canvas.yview_scroll(int(-event.delta / 120), "units")
