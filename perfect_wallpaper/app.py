"""The Perfect Wallpaper window, styled as a starship console."""

from __future__ import annotations

import ctypes
import logging
import os
import queue
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cv2
import numpy as np
from PIL import Image, ImageGrab, ImageTk

from . import (APP_NAME, __version__, applog, creative, dialogs, fitting, pipeline, resources, screens, search,
               shell, state, ui, upscale, wallpaper)
from .ui import px

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:  # drag and drop is a nicety; the app works without it
    TkinterDnD = None

log = logging.getLogger(__name__)
APP_ID = "PerfectWallpaper.App"  # groups the taskbar button under our icon, not Python's

PRESETS = [
    ((1920, 1080), "Full HD"),
    ((2560, 1080), "Ultrawide"),
    ((2560, 1440), "QHD"),
    ((3440, 1440), "Ultrawide QHD"),
    ((3840, 1600), "Ultrawide"),
    ((3840, 2160), "4K"),
    ((5120, 1440), "Super ultrawide"),
    ((5120, 2160), "Ultrawide 5K"),
    ((5120, 2880), "5K"),
    ((7680, 2160), "Super ultrawide 4K"),
    ((7680, 4320), "8K"),
]
CUSTOM = "Custom size"
FIT_CARDS = [
    ("fill", "Fill the screen", "crops the edges"),
    ("blur", "Blurred sides", "shows all of it"),
    ("mirror", "Mirrored sides", "shows all of it"),
    ("bars", "Black bars", "shows all of it"),
]
MODEL_CHOICES = [("natural", "Natural"), ("clean", "Clean"), ("fast", "Fast"), ("art", "Art"), ("off", "Off")]
PREVIEW_SOURCE = 1600  # longest side of the reduced copy used for live previews
MIN_SIDE, MAX_SIDE = 16, 16384
LOUPE = 220            # size of each half of the magnifier, in screen pixels
REMEMBERED = ("mode", "enhance", "detail", "grain", "brightness", "contrast", "dim_icons", "creative", "gap")


class App:
    def __init__(self, root: tk.Tk, initial: str | None = None, drag_and_drop: bool = False):
        self.root = root
        self.drag_and_drop = drag_and_drop
        self.screens = screens.list_screens()
        self.state = state.load()

        self.picture = None        # full size RGB array, upright according to the file's EXIF data
        self.small = None          # reduced copy for previews
        self.name = "wallpaper"
        self.source_path: Path | None = None
        self.rotation = 0
        self.focus = None
        self.focus_auto = True     # False once the user drags the crop
        self.result = None
        self.result_path: Path | None = None
        self.result_settings = None
        self.worker = None
        self.cancel = threading.Event()
        self.events: queue.Queue = queue.Queue()
        self.sky = ui.Sky()
        self._backdrop = self._backdrop_size = None
        self._photo = None
        self._preview_box = (0, 0, 1, 1)
        self._drag = None
        self._drop_hover = False
        self._preview_job = self._save_job = None
        self.compare_center = None  # where the compare view looks, in wallpaper pixels
        self.divider = 0.5
        self.loupe = None           # (x, y on canvas, without image, with image) or a pending marker
        self.f_sign, self.f_bold = tkfont.Font(font=ui.FONT_SIGN), tkfont.Font(font=ui.FONT_B)

        saved = self.state.get("settings", {})
        self.choice = tk.StringVar()
        self.width = tk.StringVar()
        self.height = tk.StringVar()
        self.mode = tk.StringVar(value=saved.get("mode", "fill"))
        enhance = upscale.ALIASES.get(saved.get("enhance"), saved.get("enhance"))
        self.enhance = tk.StringVar(value=enhance if enhance in dict(MODEL_CHOICES) else upscale.DEFAULT_MODEL)
        self.zoom = tk.DoubleVar(value=1.0)
        self.detail = tk.DoubleVar(value=float(saved.get("detail", 0.0)))
        self.grain = tk.DoubleVar(value=float(saved.get("grain", 0.0)))
        self.brightness = tk.DoubleVar(value=float(saved.get("brightness", 0.0)))
        self.contrast = tk.DoubleVar(value=float(saved.get("contrast", 0.0)))
        self.dim_icons = tk.BooleanVar(value=bool(saved.get("dim_icons", False)))
        self.creative = tk.DoubleVar(value=float(saved.get("creative", 0.0)) if creative.installed() else 0.0)
        self.gap = tk.DoubleVar(value=float(saved.get("gap", 0)))
        self.compare = tk.BooleanVar(value=False)
        self.magnify = tk.BooleanVar(value=False)
        self.info = tk.StringVar()
        self.status = tk.StringVar(value="Ready.")
        self.screen_value = tk.StringVar()
        self.screen_note = tk.StringVar()
        self.engine_value = tk.StringVar(value="STARTING")
        self.engine_note = tk.StringVar(value="Loading the AI on your graphics card")

        self._build()
        self._load_choices(saved)
        self._refresh()
        self._bind_keys()
        if initial:
            self.root.after(100, lambda: self.open_picture(initial))
        self.root.after(50, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        threading.Thread(target=self._start_engine, daemon=True).start()

    # Layout ----------------------------------------------------------------------------

    def _build(self):
        root = self.root
        root.title(APP_NAME)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        geometry = self.state.get("window")
        w, h = min(px(1440), sw - px(40)), min(px(940), sh - px(80))
        root.geometry(geometry or f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2 - px(20))}")
        root.minsize(min(px(1240), w), min(px(760), h))
        icon = resources.asset("icon.ico")
        if sys.platform == "win32" and icon.exists():
            root.iconbitmap(default=str(icon))

        self._build_masthead()
        self._build_deck()
        body = tk.Frame(root, background=ui.SPACE)
        body.pack(fill="both", expand=True, padx=px(20), pady=(px(2), px(8)))
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(body, background=ui.SPACE, highlightthickness=0, cursor="hand2")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda _e: self._schedule_preview())
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Motion>", self._hover)
        self.canvas.bind("<MouseWheel>", self._wheel)
        if self.drag_and_drop:
            root.drop_target_register(DND_FILES)
            root.dnd_bind("<<Drop>>", self._drop)
            self.canvas.drop_target_register(DND_FILES)
            self.canvas.dnd_bind("<<DropEnter>>", lambda e: self._hover_drop(e, True))
            self.canvas.dnd_bind("<<DropLeave>>", lambda e: self._hover_drop(e, False))
            self.canvas.dnd_bind("<<Drop>>", self._drop)
        self._build_bench(body)
        self._update_result_buttons()

    def _build_masthead(self):
        """The command band across the top: the badge and name, live readouts for the AI
        engine and the display, and the Options menu."""
        band = tk.Frame(self.root, background=ui.DECK)
        band.pack(fill="x", side="top")
        top = tk.Frame(band, background=ui.DECK)
        top.pack(fill="x", padx=px(20), pady=(px(12), px(10)))

        emblem = resources.asset("icon.png")
        if emblem.exists():
            self._emblem = ImageTk.PhotoImage(Image.open(emblem).resize((px(56), px(56)), Image.Resampling.LANCZOS))
            tk.Label(top, image=self._emblem, background=ui.DECK).pack(side="left")
        name = tk.Frame(top, background=ui.DECK)
        name.pack(side="left", padx=(px(12), 0))
        tk.Label(name, text="PERFECT WALLPAPER", background=ui.DECK, foreground=ui.ICE, font=ui.FONT_MAST).pack(
            anchor="w")
        tk.Label(name, text="AI ENHANCEMENT  AND  DISPLAY FITTING", background=ui.DECK, foreground=ui.OMNI,
                 font=ui.FONT_SIGN).pack(anchor="w", padx=(px(2), 0))

        options = ui.HudButton(top, "OPTIONS", self._options_menu, "quiet", font=ui.FONT_SIGN, padx=10, pady=4)
        options.pack(side="right", anchor="n", padx=(px(28), 0))
        self.options_button = options

        def readout(title, value_var, note_var):
            box = tk.Frame(top, background=ui.DECK)
            box.pack(side="right", padx=(px(36), 0))
            tk.Label(box, text=title, background=ui.DECK, foreground=ui.OMNI, font=ui.FONT_SIGN).pack(anchor="e")
            label = tk.Label(box, textvariable=value_var, background=ui.DECK, foreground=ui.ICE, font=ui.FONT_READOUT)
            label.pack(anchor="e")
            tk.Label(box, textvariable=note_var, background=ui.DECK, foreground=ui.ICE_DIM, font=ui.FONT_SM).pack(
                anchor="e")
            return label

        readout("DISPLAY LINK", self.screen_value, self.screen_note)
        self.engine_label = readout("AI ENGINE", self.engine_value, self.engine_note)

        rail = tk.Canvas(self.root, height=px(16), background=ui.SPACE, highlightthickness=0)
        rail.pack(fill="x", side="top")
        rail.bind("<Configure>", lambda e: ui.draw_rail(rail, e.width))

    def _build_deck(self):
        """The control deck along the bottom: the big button, status and progress, and
        what to do with the finished wallpaper."""
        deck = tk.Frame(self.root, background=ui.DECK)
        deck.pack(fill="x", side="bottom")
        rail = tk.Canvas(self.root, height=px(16), background=ui.SPACE, highlightthickness=0)
        rail.pack(fill="x", side="bottom")
        rail.bind("<Configure>", lambda e: ui.draw_rail(rail, e.width, upward=True))

        inner = tk.Frame(deck, background=ui.DECK)
        inner.pack(fill="x", padx=px(20), pady=(px(10), px(12)))
        inner.columnconfigure(1, weight=1)
        self.make_button = ui.HudButton(inner, "Make wallpaper", self.make, "primary", ui.FONT_BIG, padx=28, pady=10,
                                        tip="Make the full size wallpaper (Enter)")
        self.make_button.grid(row=0, column=0)
        middle = tk.Frame(inner, background=ui.DECK)
        middle.grid(row=0, column=1, sticky="ew", padx=px(20))
        status = tk.Label(middle, textvariable=self.status, background=ui.DECK, foreground=ui.ICE_DIM,
                          font=ui.FONT_MONO, anchor="w", justify="left", width=1, height=2)
        status.pack(fill="x")
        status.bind("<Configure>", lambda e: status.configure(wraplength=e.width))
        self.meter = ui.Meter(middle)
        self.meter.pack(fill="x", pady=(px(7), 0))

        buttons = tk.Frame(inner, background=ui.DECK)
        buttons.grid(row=0, column=2)
        self.compare_button = ui.HudButton(buttons, "Compare", self.toggle_compare, "quiet", padx=10,
                                           tip="Before and after at full size: move the mouse to sweep, drag to "
                                               "look around (C)")
        self.magnify_button = ui.HudButton(buttons, "Magnifier", self.toggle_magnifier, "quiet", padx=10,
                                           tip="Click the preview to see that spot at full size, without and with "
                                               "the AI (M)")
        self.set_button = ui.HudButton(buttons, "Set as wallpaper", self.apply, "secondary",
                                       tip="Put this on your desktop (Ctrl+W)")
        self.undo_button = ui.HudButton(buttons, "Undo", self.undo, "quiet", padx=10,
                                        tip="Put back the wallpaper you had before (Ctrl+Z)")
        self.history_button = ui.HudButton(buttons, "History", self.history, "quiet", padx=10,
                                           tip="Every wallpaper you made (Ctrl+H)")
        self.show_button = ui.HudButton(buttons, "Show file", self.show_file, "quiet", padx=10)
        self.save_button = ui.HudButton(buttons, "Save a copy", self.save_copy, "quiet", padx=10,
                                        tip="Save the wallpaper somewhere else (Ctrl+S)")
        for i, b in enumerate((self.compare_button, self.magnify_button, self.set_button, self.undo_button,
                               self.history_button, self.show_button, self.save_button)):
            b.pack(side="left", padx=(px(10) if b is self.set_button else px(2), px(10) if b is self.set_button else 0))

    def _build_bench(self, body):
        bench = tk.Frame(body, background=ui.PANEL, highlightthickness=1, highlightbackground=ui.LINE)
        bench.grid(row=1, column=0, sticky="ew", pady=(px(10), 0))
        inner = tk.Frame(bench, background=ui.PANEL)
        inner.pack(fill="x", padx=px(18), pady=px(12))
        columns = []
        for i in range(3):
            if i:
                tk.Frame(inner, background=ui.LINE, width=1).grid(row=0, column=2 * i - 1, sticky="ns", padx=px(18))
            col = tk.Frame(inner, background=ui.PANEL)
            col.grid(row=0, column=2 * i, sticky="nw")
            columns.append(col)
        left, middle, right = columns
        self.busy_widgets = []

        # Display: the size, the monitor map, and the gap for spanned pictures
        ui.section(left, "DISPLAY").pack(anchor="w")
        row = tk.Frame(left, background=ui.PANEL)
        row.pack(anchor="w", pady=(px(7), px(6)))
        self.choice_box = ttk.Combobox(row, textvariable=self.choice, state="readonly", width=36)
        self.choice_box.pack(side="left")
        self.choice_box.bind("<<ComboboxSelected>>", lambda _e: self._choice_changed())
        boxes = []
        for label, var in (("W", self.width), ("H", self.height)):
            tk.Label(row, text=label, background=ui.PANEL, foreground=ui.ICE_DIM, font=ui.FONT_SM).pack(
                side="left", padx=(px(10), px(4)))
            box = ttk.Spinbox(row, from_=MIN_SIDE, to=MAX_SIDE, textvariable=var, width=6, command=self._size_typed)
            box.pack(side="left")
            box.bind("<KeyRelease>", lambda _e: self._size_typed())
            boxes.append(box)
        self.busy_widgets += [self.choice_box, *boxes]
        row = tk.Frame(left, background=ui.PANEL)
        row.pack(anchor="w", pady=(0, px(10)), fill="x")
        self.monitor_map = ui.MonitorMap(row, self.screens, self._pick_screen, width=250, height=56)
        self.monitor_map.pack(side="left")
        self.gap_slider = ui.HudSlider(row, "Gap between monitors", self.gap, 0, 200, self._refresh, width=180,
                                       fmt=lambda v: f"{int(v)} px", step=5,
                                       tip="For a picture spread across several monitors: the width of the frames "
                                           "between them, so lines stay straight from screen to screen")
        self.gap_slider.pack(side="left", padx=(px(18), 0))

        ui.section(left, "FIT").pack(anchor="w")
        cards = tk.Frame(left, background=ui.PANEL)
        cards.pack(anchor="w", pady=(px(7), px(4)))
        self.cards = []
        for mode, title, note in FIT_CARDS:
            card = ui.FitCard(cards, mode, title, note, self._pick_mode)
            card.pack(side="left", padx=(0, px(8)))
            self.cards.append(card)
        self.zoom_slider = ui.HudSlider(left, "Zoom (Fill only, or scroll on the preview)", self.zoom, 1.0,
                                        fitting.MAX_ZOOM, self._zoom_changed, width=300,
                                        fmt=lambda v: f"{v:.2f}×", default=1.0, step=0.1)
        self.zoom_slider.pack(anchor="w")

        # Picture and AI
        ui.section(middle, "IMAGE").pack(anchor="w")
        grid = tk.Frame(middle, background=ui.PANEL)
        grid.pack(anchor="w", pady=(px(7), px(10)))
        buttons = [
            ttk.Button(grid, text="Open a picture", command=self.browse),
            ttk.Button(grid, text="Find a sharper copy", command=self.find_copy),
            ttk.Button(grid, text="Fit a folder", command=self.fit_folder),
            ttk.Button(grid, text="Rotate left", command=lambda: self.rotate(90)),
            ttk.Button(grid, text="Rotate right", command=lambda: self.rotate(-90)),
            ttk.Button(grid, text="Auto position", command=self.recenter),
        ]
        for i, button in enumerate(buttons):
            button.grid(row=i // 3, column=i % 3, sticky="ew", padx=(0, px(6)), pady=(0, px(6)))
        ui.Tooltip(buttons[1], "Search the web for a bigger copy of this picture (Ctrl+F)")
        ui.Tooltip(buttons[2], "Make wallpapers from every picture in a folder, and optionally a slideshow")
        self.picture_buttons = buttons[1:]
        self.busy_widgets += buttons

        ui.section(middle, "AI ENHANCEMENT").pack(anchor="w")
        self.model_bar = ui.Segmented(middle, MODEL_CHOICES, self.enhance, self._refresh, padx=11)
        self.model_bar.pack(anchor="w", pady=(px(7), px(4)))
        for key, item in self.model_bar.items:
            model = upscale.MODELS.get(key)
            ui.Tooltip(item, f"{model.label}: {model.note}" if model else "No AI: a careful plain resize")
        sliders = tk.Frame(middle, background=ui.PANEL)
        sliders.pack(anchor="w")
        self.detail_slider = ui.HudSlider(sliders, "Detail", self.detail, 0, 1, self._refresh, width=150,
                                          tip="Adds back the original's own fine texture, which the AI smooths away")
        self.detail_slider.grid(row=0, column=0, padx=(0, px(14)))
        self.grain_slider = ui.HudSlider(sliders, "Film grain", self.grain, 0, 1, self._refresh, width=150,
                                         tip="A light, even grain that hides softness on a big screen")
        self.grain_slider.grid(row=0, column=1)
        self.creative_slider = ui.HudSlider(sliders, "Stronger AI", self.creative, 0, 1, self._creative_changed,
                                            width=314, fmt=lambda v: "off" if v <= 0 else f"{v:.0%}",
                                            tip="Paints in new fine detail with an image generating AI. Slower, and "
                                                "it can change small details. Needs a one time download.")
        self.creative_slider.grid(row=1, column=0, columnspan=2, sticky="w")

        # Look
        ui.section(right, "LOOK").pack(anchor="w")
        signed = lambda v: "0" if abs(v) < 0.005 else f"{v * 100:+.0f}"  # noqa: E731
        self.brightness_slider = ui.HudSlider(right, "Brightness", self.brightness, -1, 1, self._refresh, width=200,
                                              fmt=signed, default=0, centered=True)
        self.brightness_slider.pack(anchor="w", pady=(px(4), 0))
        self.contrast_slider = ui.HudSlider(right, "Contrast", self.contrast, -1, 1, self._refresh, width=200,
                                            fmt=signed, default=0, centered=True)
        self.contrast_slider.pack(anchor="w")
        self.dim_toggle = ui.Toggle(right, "Darken behind desktop icons", self.dim_icons, self._refresh,
                                    tip="Darkens the left edge, where Windows lines up desktop icons, so their "
                                        "names stay readable over a busy picture")
        self.dim_toggle.pack(anchor="w", pady=(px(10), 0))
        self.sliders = [self.zoom_slider, self.detail_slider, self.grain_slider, self.creative_slider,
                        self.brightness_slider, self.contrast_slider, self.gap_slider]

        info = tk.Label(inner, textvariable=self.info, background=ui.PANEL, foreground=ui.ICE_DIM, font=ui.FONT_SM,
                        anchor="w", justify="left")
        info.grid(row=1, column=0, columnspan=5, sticky="ew", pady=(px(10), 0))
        inner.bind("<Configure>", lambda e: info.configure(wraplength=e.width))

    def _bind_keys(self):
        root = self.root

        def typing():
            return isinstance(root.focus_get(), (tk.Entry, ttk.Entry, ttk.Spinbox, ttk.Combobox))

        def key(sequence, action, when_typing=False):
            root.bind(sequence, lambda e: None if (typing() and not when_typing) else (action(), "break")[1])

        key("<Control-o>", self.browse, True)
        key("<Control-v>", self.paste)
        key("<Control-s>", self.save_copy, True)
        key("<Control-z>", self.undo)
        key("<Control-h>", self.history, True)
        key("<Control-f>", self.find_copy, True)
        key("<Control-w>", self.apply, True)
        key("<Return>", self.make)
        key("<Escape>", self._escape, True)
        key("<r>", lambda: self.rotate(-90))
        key("<R>", lambda: self.rotate(90))
        key("<c>", self.toggle_compare)
        key("<m>", self.toggle_magnifier)
        for i, (mode, *_rest) in enumerate(FIT_CARDS):
            key(f"<Key-{i + 1}>", lambda m=mode: self._pick_mode(m))

    def _options_menu(self):
        menu = tk.Menu(self.root, tearoff=False)
        registered = tk.BooleanVar(value=shell.is_registered())
        menu.add_checkbutton(label="Add \"Make a perfect wallpaper\" to the right click menu", variable=registered,
                             command=lambda: self._toggle_shell(registered.get()))
        menu.add_separator()
        if creative.installed():
            menu.add_command(label="Remove the stronger AI (frees about 6 GB)", command=self._remove_creative)
        else:
            menu.add_command(label="Set up the stronger AI...", command=lambda: self._creative_setup(0.5))
        menu.add_command(label="Open the log folder", command=lambda: os.startfile(applog.log_dir()))
        menu.add_command(label="Open the wallpapers folder", command=lambda: os.startfile(resources.output_dir()))
        menu.add_separator()
        menu.add_command(label=f"About {APP_NAME} {__version__}", command=self._about)
        b = self.options_button
        menu.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())

    def _toggle_shell(self, on):
        try:
            shell.register() if on else shell.unregister()
            self.set_status("Added to the right click menu for pictures. On Windows 11 it is under Show more "
                            "options." if on else "Removed from the right click menu.")
        except OSError as error:
            messagebox.showerror(APP_NAME, f"Windows did not accept the change.\n\n{error}")

    def _about(self):
        client = upscale.EngineClient._shared
        gpu = client.gpu_name() if client else "not loaded yet"
        messagebox.showinfo(APP_NAME, f"{APP_NAME} {__version__}\n\nEnlarges pictures with AI and fits them to "
                                      f"your screen.\n\nGraphics card in use: {gpu}\nLog: {applog.log_dir()}\n\n"
                                      "AI models: Real-ESRGAN (Xintao Wang), Nomos8kSC and LSDIRplusC (Helaman). "
                                      "Free and open source under the MIT License.")

    # Screen sizes ------------------------------------------------------------------------

    def _load_choices(self, saved):
        self.choices: list[tuple[str, str, object, str]] = []
        for screen in self.screens:
            main = screen.primary and len(self.screens) > 1
            label = f"{screen.name}: {screen.width} × {screen.height}{', main' if main else ''}"
            note = f"{screen.name}, your main display" if screen.primary else screen.name
            self.choices.append((label, "screen", screen, note))
        if len(self.screens) > 1:
            w, h = screens.combined_size(self.screens)
            self.choices.append((f"All displays as one picture: {w} × {h}", "span", (w, h), "All displays as one"))
        if not self.screens:
            w, h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            self.choices.append((f"This screen: {w} × {h}", "preset", (w, h), "This screen"))
        for (w, h), name in PRESETS:
            self.choices.append((f"{w} × {h} ({name})", "preset", (w, h), name))
        self.choices.append((CUSTOM, "custom", None, "Custom size"))
        self.choice_box["values"] = [c[0] for c in self.choices]
        labels = [c[0] for c in self.choices]
        remembered = saved.get("choice")
        if remembered == CUSTOM and saved.get("size"):
            self.choice.set(CUSTOM)
            self.width.set(str(saved["size"][0]))
            self.height.set(str(saved["size"][1]))
        else:
            self.choice.set(remembered if remembered in labels else labels[0])
            self._choice_changed()

    def _current_choice(self):
        for label, kind, value, note in self.choices:
            if label == self.choice.get():
                return kind, value, note
        return "custom", None, "Custom size"

    def choice_is_span(self) -> bool:
        return self._current_choice()[0] == "span"

    def _choice_changed(self):
        kind, value, _ = self._current_choice()
        size = value.size if kind == "screen" else value
        if size:
            self.width.set(str(size[0]))
            self.height.set(str(size[1]))
        self._refresh()

    def _pick_screen(self, screen):
        for label, kind, value, _ in self.choices:
            if kind == "screen" and value.device == screen.device:
                self.choice.set(label)
                self._choice_changed()
                return

    def _size_typed(self):
        target = self._target(raw=True)
        match = next((label for label, kind, value, _ in self.choices
                      if target and kind != "custom" and (value.size if kind == "screen" else value) == target), CUSTOM)
        self.choice.set(match)
        self._refresh()

    def _target(self, raw=False):
        """The size to make the wallpaper at. A spanned picture with a gap is made wider
        (see screens.span_size); raw gives the size typed in the boxes."""
        try:
            w, h = int(self.width.get()), int(self.height.get())
        except ValueError:
            return None
        if not (MIN_SIDE <= w <= MAX_SIDE and MIN_SIDE <= h <= MAX_SIDE):
            return None
        if not raw and self.choice_is_span() and int(self.gap.get()):
            return screens.span_size(self.screens, int(self.gap.get()))
        return w, h

    # State -------------------------------------------------------------------------------

    def _settings(self):
        target = self._target()
        if target is None:
            return None
        return pipeline.Settings(
            target=target, mode=self.mode.get(), rotation=self.rotation, focus=self.focus,
            enhance=self.enhance.get(), zoom=round(self.zoom.get(), 3) if self.mode.get() == "fill" else 1.0,
            detail=round(self.detail.get(), 3), grain=round(self.grain.get(), 3),
            brightness=round(self.brightness.get(), 3), contrast=round(self.contrast.get(), 3),
            dim_icons=self.dim_icons.get(), creative=round(self.creative.get(), 3))

    def settings_for_batch(self):
        """The current settings for other pictures: no rotation, crop or zoom of this one's."""
        settings = self._settings() or pipeline.Settings(target=(1920, 1080))
        from dataclasses import replace

        return replace(settings, rotation=0, focus=None, zoom=1.0)

    def _rotated_small(self):
        return pipeline.rotate(self.small, self.rotation)

    def rotated_picture(self):
        return self._rotated_small()

    def full_size(self) -> tuple[int, int]:
        return self._rotated_size()

    def search_words(self) -> str:
        return self.state.get("search_words", {}).get(str(self.source_path), "") or search.suggest_keywords(self.name)

    def source_hint(self) -> str:
        return str(self.source_path) if self.source_path else "the picture you loaded"

    def _pick_mode(self, mode):
        if self.worker:
            return
        self.mode.set(mode)
        self._refresh()

    def _zoom_changed(self):
        self._refresh()

    def _refresh(self):
        """Recompute everything that depends on the settings and redraw."""
        target = self._target()
        zoom = self.zoom.get() if self.mode.get() == "fill" else 1.0
        if self.picture is not None and target:
            rotated = self._rotated_small()
            size = (rotated.shape[1], rotated.shape[0])
            if self.focus_auto:
                self.focus = fitting.smart_focus(rotated, target, zoom)
            elif self.focus is not None:
                self.focus = fitting.clamp_focus(size, target, self.focus, zoom)
        for card in self.cards:
            card.selected = card.mode == self.mode.get()
            card.draw()
        self.model_bar.paint()
        kind, value, note = self._current_choice()
        raw = self._target(raw=True)
        self.screen_value.set(f"{raw[0]} × {raw[1]}" if raw else "NO SIZE")
        self.screen_note.set(note)
        self.monitor_map.show(value if kind == "screen" else None, kind == "span", custom=kind in ("preset", "custom"))
        if not self.worker:
            self.zoom_slider.set_enabled(self.mode.get() == "fill" and self.picture is not None)
            self.gap_slider.set_enabled(kind == "span")
            ai = self.enhance.get() != "off"
            self.detail_slider.set_enabled(ai)
            self.creative_slider.set_enabled(True)
            for button in self.picture_buttons:
                button.state(["!disabled"] if self.picture is not None or button.cget("text") == "Fit a folder"
                             else ["disabled"])
        self.info.set(self._describe())
        if self.picture is None:
            self.canvas.configure(cursor="hand2")
        elif not self.worker:
            cursor = "crosshair" if self.magnify.get() else (
                "sb_h_double_arrow" if self._comparing() else ("fleur" if self.mode.get() == "fill" else "arrow"))
            self.canvas.configure(cursor=cursor)
        self._update_result_buttons()
        self._schedule_preview()
        self._schedule_save()

    def _rotated_size(self):
        h, w = self.picture.shape[:2]
        return (h, w) if self.rotation % 180 else (w, h)

    def _plan(self):
        settings = self._settings()
        if self.picture is None or settings is None:
            return None
        return fitting.make_plan(self._rotated_size(), settings.target, settings.mode, self.focus or (0.5, 0.5),
                                 settings.zoom)

    def _describe(self) -> str:
        if self.picture is None:
            return ("Drop a picture on this window, click the empty screen above, or paste one with Ctrl+V. "
                    "Shortcuts: Enter makes the wallpaper, R rotates, 1 to 4 pick the fit, C compares, M magnifies.")
        w, h = self._rotated_size()
        target = self._target()
        if target is None:
            return f"Picture {w} × {h}. Enter a screen width and height between {MIN_SIDE} and {MAX_SIDE}."
        plan = self._plan()
        scale = plan.scale
        text = f"Picture {w} × {h}, screen {target[0]} × {target[1]}. "
        if scale <= 1:
            text += "The picture will be shrunk to fit, so it needs no AI."
        elif scale <= upscale.AI_THRESHOLD:
            text += f"It only needs a slight enlargement ({scale:.2f} times), so it needs no AI."
        else:
            text += f"It needs to be enlarged {scale:.1f} times. "
            if self.enhance.get() == "off":
                text += "AI is off, so it will be resized and sharpened without AI."
            elif not upscale.ai_available():
                text += "The AI engine is missing, so it will be resized and sharpened without AI."
            else:
                model = upscale.model_for(self.enhance.get())
                text += f"The {model.label.lower()} AI model will add detail on your graphics card."
            if scale > 8:
                text += " That is a big jump, so expect a soft result."
        if self.creative.get() > 0:
            text += " The stronger AI will then paint in extra fine texture, which takes a few minutes."
        if self.choice_is_span() and int(self.gap.get()):
            text += f" The preview includes the {int(self.gap.get())} pixel gaps, which are cut out at the end."
        left, top, right, bottom = plan.crop
        if self.mode.get() == "fill" and (right - left < w or bottom - top < h):
            text += " Drag the preview to choose what stays in view."
        return text

    def _result_current(self) -> bool:
        return self.result is not None and self.result_settings == self._settings()

    def _comparing(self) -> bool:
        return self.compare.get() and self._result_current()

    def _update_result_buttons(self):
        if self.worker:
            return
        current = self._result_current()
        for button in (self.set_button, self.show_button, self.save_button, self.compare_button):
            button.set_enabled(current)
        self.undo_button.set_enabled(bool(self.state.get("undo")))
        self.history_button.set_enabled(bool(state.history(self.state)))
        self.magnify_button.set_enabled(self.picture is not None)
        self.compare_button.kind = ui.HudButton.KINDS["secondary" if self._comparing() else "quiet"]
        self.compare_button._draw()
        self.magnify_button.kind = ui.HudButton.KINDS["secondary" if self.magnify.get() else "quiet"]
        self.magnify_button._draw()
        if self.result is not None and not current:
            self.status.set("Settings changed. Press Make wallpaper to update it.")
            self.compare.set(False)

    def set_status(self, text):
        self.status.set(text)

    def _schedule_save(self):
        if self._save_job is not None:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(800, self._save_state)

    def _save_state(self):
        self._save_job = None
        settings = {
            "mode": self.mode.get(), "enhance": self.enhance.get(), "detail": self.detail.get(),
            "grain": self.grain.get(), "brightness": self.brightness.get(), "contrast": self.contrast.get(),
            "dim_icons": self.dim_icons.get(), "creative": self.creative.get(), "gap": self.gap.get(),
            "choice": self.choice.get(), "size": self._target(raw=True),
        }
        self.state["settings"] = settings
        if self.root.state() == "normal":
            self.state["window"] = self.root.geometry()
        state.save(self.state)

    # Preview -----------------------------------------------------------------------------

    def _schedule_preview(self):
        if self._preview_job is not None:
            self.root.after_cancel(self._preview_job)
        self._preview_job = self.root.after(30, self._draw)

    def _frame(self):
        """Where the screen rectangle sits on the canvas, at the screen's shape."""
        c = self.canvas
        cw, ch = max(c.winfo_width(), 50), max(c.winfo_height(), 50)
        settings = self._settings()
        tw, th = settings.target if settings else (16, 9)
        top_room, bottom_room, side = px(34), px(52), px(36)
        box_w, box_h = cw - 2 * side, ch - top_room - bottom_room
        s = min(box_w / tw, box_h / th)
        pw, ph = max(1, round(tw * s)), max(1, round(th * s))
        x0, y0 = (cw - pw) // 2, top_room + (box_h - ph) // 2
        return cw, ch, x0, y0, pw, ph

    def _draw(self):
        self._preview_job = None
        c = self.canvas
        c.delete("all")
        cw, ch, x0, y0, pw, ph = self._frame()
        if self._backdrop_size != (cw, ch):
            self._backdrop = ImageTk.PhotoImage(self.sky.render(cw, ch))
            self._backdrop_size = (cw, ch)
        c.create_image(0, 0, image=self._backdrop, anchor="nw")
        settings = self._settings()
        x1, y1 = x0 + pw, y0 + ph
        self._preview_box = (x0, y0, pw, ph)
        busy = self.worker is not None
        hot = self._drop_hover or busy

        if self.picture is None:
            c.create_rectangle(x0, y0, x1, y1, fill="#060b12", outline=ui.LINE)
            middle = (y0 + y1) / 2
            c.create_text(cw / 2, middle - px(14), text="Drop a picture here", font=ui.FONT_HERO,
                          fill=ui.OMNI_HI if self._drop_hover else ui.ICE)
            c.create_text(cw / 2, middle + px(24), text="or click to choose one. Ctrl+V pastes one.",
                          font=ui.FONT, fill=ui.ICE_DIM)
            label = "AWAITING IMAGE"
        elif self._comparing():
            image = self._compare_image(pw, ph)
            self._photo = ImageTk.PhotoImage(Image.fromarray(image))
            c.create_image(x0, y0, image=self._photo, anchor="nw")
            split = x0 + round(self.divider * pw)
            c.create_line(split, y0, split, y1, fill=ui.OMNI, width=2)
            c.create_text(x0 + px(10), y0 + px(10), text="WITHOUT AI", anchor="nw", font=ui.FONT_SIGN, fill=ui.ICE)
            c.create_text(x1 - px(10), y0 + px(10), text="WITH AI", anchor="ne", font=ui.FONT_SIGN, fill=ui.OMNI)
            c.create_rectangle(x0 - 1, y0 - 1, x1, y1, outline=ui.LINE_HI)
            c.create_text(x0 - px(8), y0 - px(16), text="FULL SIZE   MOVE THE MOUSE TO SWEEP, DRAG TO LOOK AROUND",
                          anchor="sw", font=ui.FONT_MONO, fill=ui.MUTED)
            label = "COMPARE"
        else:
            if self._result_current():
                image, label = ui.fit_inside(self.result, (pw, ph)), "FINAL WALLPAPER"
            elif settings is not None:
                image, label = pipeline.preview(self.small, settings, (pw, ph)), "PREVIEW"
            else:
                image, label = None, "ENTER A SCREEN SIZE"
            if image is not None:
                self._photo = ImageTk.PhotoImage(Image.fromarray(image))
                c.create_image(x0, y0, image=self._photo, anchor="nw")
            c.create_rectangle(x0 - 1, y0 - 1, x1, y1, outline=ui.LINE_HI)
            w, h = self._rotated_size()
            source = f"SOURCE  {w} × {h}" + (f"   TURNED {self.rotation}°" if self.rotation else "")
            c.create_text(x0 - px(8), y0 - px(16), text=source, anchor="sw", font=ui.FONT_MONO, fill=ui.MUTED)
            plan = self._plan()
            if plan:
                verb = "ENLARGE" if plan.scale > 1 else "SHRINK"
                zoom = f"   ZOOM {settings.zoom:.2f}×" if settings and settings.zoom > 1.001 else ""
                c.create_text(x1 + px(8), y0 - px(16), text=f"{verb}  {plan.scale:.2f}×{zoom}", anchor="se",
                              font=ui.FONT_MONO, fill=ui.MUTED)
            if busy:
                label = "PROCESSING"
            self._draw_loupe(c)
        ui.draw_brackets(c, x0 - px(8), y0 - px(8), x1 + px(8), y1 + px(8), ui.OMNI if hot else ui.HOLO, arm=px(26))
        size = self._target(raw=True)
        self._draw_plate(c, cw / 2, y1 + px(32), label, f"{size[0]} × {size[1]}" if size else "")

    def _draw_plate(self, c, cx, cy, label, value):
        """The caption plate under the preview: what it shows and at what size."""
        gap = px(12) if value else 0
        width = self.f_sign.measure(label) + gap + self.f_bold.measure(value) + 2 * px(16)
        height = px(26)
        x0, y0 = cx - width / 2, cy - height / 2
        c.create_polygon(ui.chamfer(x0, y0, x0 + width, y0 + height, px(7)), fill=ui.PANEL, outline=ui.LINE_HI)
        c.create_text(x0 + px(16), cy, text=label, anchor="w", font=ui.FONT_SIGN, fill=ui.OMNI)
        if value:
            c.create_text(x0 + width - px(16), cy, text=value, anchor="e", font=ui.FONT_B, fill=ui.ICE)

    # Compare: the finished wallpaper at full size beside a plain resize ------------------------

    def _plain_region(self, x, y, w, h):
        """What the wallpaper's region (x, y, w, h) looks like with a plain resize, no AI."""
        plan = self._plan()
        pic = pipeline.rotate(self.picture, self.rotation)
        left, top, right, bottom = plan.crop
        ox, oy = plan.offset
        sx, sy = plan.size[0] / (right - left), plan.size[1] / (bottom - top)
        # the source pixels under the region, with a margin for the resize filter
        a, b = left + (x - ox) / sx, top + (y - oy) / sy
        c, d = left + (x + w - ox) / sx, top + (y + h - oy) / sy
        ia, ib = max(0, int(a) - 2), max(0, int(b) - 2)
        ic, id_ = min(pic.shape[1], int(c) + 3), min(pic.shape[0], int(d) + 3)
        if ic <= ia or id_ <= ib:
            return np.zeros((h, w, 3), np.uint8)
        piece = pic[ib:id_, ia:ic]
        big = cv2.resize(piece, (max(1, round((ic - ia) * sx)), max(1, round((id_ - ib) * sy))),
                         interpolation=cv2.INTER_CUBIC)
        offx, offy = round((a - ia) * sx), round((b - ib) * sy)
        out = np.zeros((h, w, 3), np.uint8)
        part = big[offy:offy + h, offx:offx + w]
        out[:part.shape[0], :part.shape[1]] = part
        return out

    def _compare_image(self, pw, ph):
        rh, rw = self.result.shape[:2]
        if self.compare_center is None:
            plan = self._plan()
            fx, fy = self.focus or (0.5, 0.5)
            self.compare_center = (plan.offset[0] + plan.size[0] / 2, plan.offset[1] + plan.size[1] * fy)
        w, h = min(pw, rw), min(ph, rh)
        cx = min(max(self.compare_center[0], w / 2), rw - w / 2)
        cy = min(max(self.compare_center[1], h / 2), rh - h / 2)
        self.compare_center = (cx, cy)
        x, y = int(cx - w / 2), int(cy - h / 2)
        after = self.result[y:y + h, x:x + w]
        before = pipeline.finish(self._plain_region(x, y, w, h), self.result_settings)
        split = round(self.divider * w)
        view = after.copy()
        view[:, :split] = before[:, :split]
        if (w, h) != (pw, ph):
            canvas = np.full((ph, pw, 3), 6, np.uint8)
            canvas[(ph - h) // 2:(ph - h) // 2 + h, (pw - w) // 2:(pw - w) // 2 + w] = view
            view = canvas
        return view

    def toggle_compare(self):
        if not self._result_current() and not self.compare.get():
            self.set_status("Make the wallpaper first, then Compare shows it beside a plain resize.")
            return
        self.compare.set(not self.compare.get())
        self.magnify.set(False)
        self.loupe = None
        self.compare_center = None
        self._refresh()

    # Magnifier: one spot at full size, without and with the AI ---------------------------------

    def toggle_magnifier(self):
        if self.picture is None:
            return
        self.magnify.set(not self.magnify.get())
        self.compare.set(False)
        self.loupe = None
        if self.magnify.get():
            self.set_status("Magnifier on: click any spot in the preview to see it at full size.")
        self._refresh()

    def _loupe_at(self, cx, cy):
        """Start rendering the magnifier for the canvas point (cx, cy)."""
        x0, y0, pw, ph = self._preview_box
        settings = self._settings()
        if settings is None:
            return
        tw, th = settings.target
        wx, wy = (cx - x0) / pw * tw, (cy - y0) / ph * th
        size = px(LOUPE)
        x, y = int(min(max(0, wx - size / 2), max(0, tw - size))), int(min(max(0, wy - size / 2), max(0, th - size)))
        w, h = min(size, tw), min(size, th)
        plain = pipeline.finish(self._plain_region(x, y, w, h), settings)
        self.loupe = (cx, cy, plain, None)
        self._draw()
        if self._result_current():
            self.loupe = (cx, cy, plain, self.result[y:y + h, x:x + w].copy())
            self._draw()
            return
        model = upscale.model_for(settings.enhance)
        if model is None:
            self.loupe = (cx, cy, plain, plain)
            self._draw()
            return
        plan = self._plan()
        pic = pipeline.rotate(self.picture, self.rotation)
        left, top, right, bottom = plan.crop
        ox, oy = plan.offset
        sx, sy = plan.size[0] / (right - left), plan.size[1] / (bottom - top)
        a, b = left + (x - ox) / sx, top + (y - oy) / sy
        margin = 12
        ia, ib = max(0, int(a) - margin), max(0, int(b) - margin)
        ic, id_ = min(pic.shape[1], int(a + w / sx) + margin), min(pic.shape[0], int(b + h / sy) + margin)
        piece = pic[ib:id_, ia:ic].copy()
        token = object()
        self._loupe_token = token

        def work():
            try:
                big = upscale.ai_upscale(piece, model.file)
                if settings.detail > 0:
                    big = upscale.add_texture(big, piece, settings.detail)
                scaled = cv2.resize(big, (max(1, round((ic - ia) * sx)), max(1, round((id_ - ib) * sy))),
                                    interpolation=cv2.INTER_AREA)
                offx, offy = round((a - ia) * sx), round((b - ib) * sy)
                crop = np.zeros((h, w, 3), np.uint8)
                part = scaled[offy:offy + h, offx:offx + w]
                crop[:part.shape[0], :part.shape[1]] = part
                self.events.put(("loupe", token, cx, cy, plain, pipeline.finish(crop, settings)))
            except Exception as error:  # the magnifier is a nicety; report and carry on
                log.warning("Magnifier failed: %s", error)
                self.events.put(("loupe", token, cx, cy, plain, plain))

        threading.Thread(target=work, daemon=True).start()

    def _draw_loupe(self, c):
        if not self.loupe or not self.magnify.get():
            return
        cx, cy, plain, enhanced = self.loupe
        size = px(LOUPE)
        cw, ch = c.winfo_width(), c.winfo_height()
        bx = min(max(px(10), cx - size - px(6)), cw - 2 * size - px(22))
        by = min(max(px(10), cy + px(16)), ch - size - px(40))
        c.create_rectangle(bx - px(6), by - px(26), bx + 2 * size + px(10), by + size + px(6), fill=ui.PANEL,
                           outline=ui.HOLO)
        c.create_text(bx, by - px(13), text="WITHOUT AI", anchor="w", font=ui.FONT_SIGN, fill=ui.ICE_DIM)
        c.create_text(bx + size + px(4), by - px(13), text="WITH AI", anchor="w", font=ui.FONT_SIGN, fill=ui.OMNI)
        self._loupe_photos = [ImageTk.PhotoImage(Image.fromarray(plain))]
        c.create_image(bx, by, image=self._loupe_photos[0], anchor="nw")
        if enhanced is None:
            c.create_rectangle(bx + size + px(4), by, bx + 2 * size + px(4), by + size, fill="#060b12", outline="")
            c.create_text(bx + size * 1.5 + px(4), by + size / 2, text="ENHANCING...", font=ui.FONT_SIGN,
                          fill=ui.OMNI)
        else:
            self._loupe_photos.append(ImageTk.PhotoImage(Image.fromarray(enhanced)))
            c.create_image(bx + size + px(4), by, image=self._loupe_photos[1], anchor="nw")
        c.create_oval(cx - px(5), cy - px(5), cx + px(5), cy + px(5), outline=ui.OMNI, width=2)

    # Mouse on the preview -----------------------------------------------------------------------

    def _press(self, event):
        if self.worker:
            return
        if self.picture is None:
            self.browse()
            return
        x0, y0, pw, ph = self._preview_box
        inside = x0 <= event.x <= x0 + pw and y0 <= event.y <= y0 + ph
        if self.magnify.get():
            if inside:
                self._loupe_at(event.x, event.y)
            return
        if self._comparing() or (self.mode.get() == "fill" and inside):
            self._drag = (event.x, event.y)

    def _motion(self, event):
        if not self._drag:
            return
        dx_px, dy_px = event.x - self._drag[0], event.y - self._drag[1]
        self._drag = (event.x, event.y)
        if self._comparing():
            cx, cy = self.compare_center
            self.compare_center = (cx - dx_px, cy - dy_px)
            self._draw()
            return
        if self._target() is None:
            return
        _, _, pw, ph = self._preview_box
        rotated = self._rotated_small()
        self.focus_auto = False
        self.focus = fitting.pan((rotated.shape[1], rotated.shape[0]), self._target(), self.focus or (0.5, 0.5),
                                 dx_px / pw, dy_px / ph, self.zoom.get())
        self._update_result_buttons()
        self._draw()

    def _hover(self, event):
        if self._comparing() and not self._drag:
            x0, _, pw, _ = self._preview_box
            self.divider = min(1, max(0, (event.x - x0) / pw))
            self._draw()

    def _release(self, _event):
        if self._drag:
            self._drag = None
            if not self._comparing():
                self._refresh()

    def _wheel(self, event):
        if self.picture is None or self.worker or self.mode.get() != "fill" or self._comparing():
            return
        self.zoom_slider.set(self.zoom.get() + (0.1 if event.delta > 0 else -0.1), notify=True)

    # Opening pictures -----------------------------------------------------------------------

    def browse(self):
        if self.worker:
            return
        path = filedialog.askopenfilename(title="Choose a picture", initialdir=self.state.get("last_dir"),
                                          filetypes=[("Pictures", pipeline.PICTURE_PATTERNS), ("All files", "*.*")])
        if path:
            self.open_picture(path)

    def _hover_drop(self, event, on):
        self._drop_hover = on and not self.worker
        self._draw()
        return event.action

    def _drop(self, event):
        self._drop_hover = False
        paths = self.root.tk.splitlist(event.data)
        if paths and not self.worker:
            target = Path(paths[0])
            if target.is_dir():
                dialogs.FolderDialog(self, target)
            else:
                self.open_picture(target)
        else:
            self._draw()
        return event.action

    def paste(self):
        if self.worker:
            return
        try:
            content = ImageGrab.grabclipboard()
        except OSError:
            content = None
        if isinstance(content, Image.Image):
            self._use_picture(pipeline.to_rgb(content), "pasted picture", None)
        elif isinstance(content, list) and content:
            self.open_picture(content[0])
        else:
            self.status.set("The clipboard does not hold a picture.")

    def open_picture(self, path, keep_settings=False):
        path = Path(path)
        try:
            picture = pipeline.load_picture(path)
        except Exception as error:  # Pillow raises many kinds of errors for bad files
            log.warning("Could not open %s: %s", path, error)
            messagebox.showerror(APP_NAME, f"That file could not be opened as a picture.\n\n{error}")
            return
        self.state["last_dir"] = str(path.parent)
        self._use_picture(picture, path.stem, path)

    def _use_picture(self, picture, name, path):
        self.picture = picture
        self.small = pipeline.shrink(picture, PREVIEW_SOURCE)
        self.name = name
        self.source_path = path
        self.rotation = 0
        self.focus, self.focus_auto = None, True
        self.zoom.set(1.0)
        self.result = self.result_path = self.result_settings = None
        self.compare.set(False)
        self.loupe = None
        self.meter.set(0)
        self.status.set(f"Loaded \"{name}\".")
        log.info("Opened %s (%d x %d)", path or name, picture.shape[1], picture.shape[0])
        self._refresh()

    def reopen(self, entry):
        """Load a past wallpaper's source picture with the settings it was made with."""
        self.open_picture(entry["source"])
        saved = entry.get("settings", {})
        self.rotation = int(saved.get("rotation", 0))
        if saved.get("focus"):
            self.focus, self.focus_auto = tuple(saved["focus"]), False
        for name in ("mode", "enhance"):
            if name in saved:
                getattr(self, name).set(saved[name])
        for name in ("zoom", "detail", "grain", "brightness", "contrast", "creative"):
            if name in saved:
                getattr(self, name).set(float(saved[name]))
        self.dim_icons.set(bool(saved.get("dim_icons", False)))
        self._refresh()

    def rotate(self, degrees):
        if self.picture is None or self.worker:
            return
        self.rotation = (self.rotation + degrees) % 360
        self.focus, self.focus_auto = None, True
        self._refresh()

    def recenter(self):
        self.focus_auto = True
        self._refresh()

    def find_copy(self):
        if self.picture is None or self.worker:
            return
        dialogs.SearchDialog(self)

    def fit_folder(self):
        if self.worker:
            return
        folder = filedialog.askdirectory(title="Choose a folder of pictures", initialdir=self.state.get("last_dir"))
        if folder:
            dialogs.FolderDialog(self, Path(folder))

    def history(self):
        dialogs.HistoryDialog(self)

    def _creative_changed(self):
        if self.creative.get() > 0 and not creative.installed():
            wanted = self.creative.get()
            self.creative.set(0.0)
            self._creative_setup(wanted)
            return
        self._refresh()

    def _creative_setup(self, wanted):
        def ready():
            self._creative_dialog = None
            self.creative.set(max(0.3, min(1.0, wanted)))
            self.set_status("The stronger AI is ready. Its strength slider is under AI enhancement.")
            self._refresh()

        if creative.installed():
            ready()
        elif getattr(self, "_creative_dialog", None) is None or not self._creative_dialog.winfo_exists():
            self._creative_dialog = dialogs.CreativeDialog(self, ready)

    def _remove_creative(self):
        if messagebox.askyesno(APP_NAME, "Remove the stronger AI? This frees about 6 GB. You can download it "
                                         "again later."):
            creative.remove()
            self.creative.set(0.0)
            self._refresh()

    # Making the wallpaper -------------------------------------------------------------------

    def make(self):
        if self.worker:
            self.cancel.set()
            self.status.set("Stopping...")
            return
        if self.picture is None:
            self.browse()
            return
        settings = self._settings()
        if settings is None:
            messagebox.showinfo(APP_NAME, f"Enter a screen width and height between {MIN_SIDE} and {MAX_SIDE} pixels.")
            return
        raw = self._target(raw=True)
        path = pipeline.unique_path(resources.output_dir() / f"{self.name} {raw[0]}x{raw[1]}.png")
        uses_ai = (upscale.model_for(settings.enhance) is not None and upscale.ai_available()
                   and pipeline.plan_for(self.picture, settings).scale > upscale.AI_THRESHOLD)
        gap = int(self.gap.get()) if self.choice_is_span() else 0
        self.cancel.clear()
        self.meter.set(0)
        self.status.set("Enlarging with AI on your graphics card..." if uses_ai else "Resizing...")
        picture, span_screens = self.picture, list(self.screens)
        log.info("Making %s with %s", path.name, settings)

        def work():
            try:
                image, report = pipeline.render(
                    picture, settings, progress=lambda p: self.events.put(("progress", p, uses_ai, settings)),
                    cancel=self.cancel,
                )
                if gap:
                    image = screens.cut_gaps(image, span_screens, gap)
                self.events.put(("saving",))
                pipeline.save(image, path)
                self.events.put(("done", image, report, path, settings))
            except upscale.Cancelled:
                self.events.put(("cancelled",))
            except Exception as error:  # report anything unexpected instead of failing silently
                log.exception("Making the wallpaper failed")
                self.events.put(("error", error))

        self.worker = threading.Thread(target=work, daemon=True)
        self._set_busy(True)
        self.worker.start()

    def _poll(self):
        try:
            while True:
                self._handle(*self.events.get_nowait())
        except queue.Empty:
            pass
        self.root.after(50, self._poll)

    def _handle(self, kind, *data):
        if kind == "progress":
            fraction, uses_ai, settings = data
            self.meter.set(fraction)
            if fraction < 1:
                if settings.creative > 0 and fraction >= 0.5:
                    self.status.set(f"The stronger AI is painting in detail, {fraction:.0%} done...")
                elif uses_ai:
                    self.status.set(f"Enlarging with AI on your graphics card, {fraction:.0%} done...")
        elif kind == "saving":
            self.status.set("Saving...")
        elif kind == "done":
            image, report, path, settings = data
            self.result, self.result_path, self.result_settings = image, path, settings
            state.add_history(self.state, path, str(self.source_path or ""),
                              {**settings.__dict__, "target": list(settings.target)})
            self._finish()
            model = upscale.model_for(settings.enhance)
            if report.ai_passes:
                how = f"Enlarged {report.scale:.1f} times with the {model.label.lower()} AI model"
            elif report.scale > 1:
                how = f"Enlarged {report.scale:.1f} times without AI"
            else:
                how = "Shrunk to fit"
            note = f" {report.note}" if report.note else ""
            self.status.set(f"{how}. Saved as \"{path.name}\" in Pictures, Perfect Wallpaper.{note}")
        elif kind == "cancelled":
            self._finish()
            self.meter.set(0)
            self.status.set("Stopped.")
        elif kind == "error":
            self._finish()
            self.meter.set(0)
            self.status.set("Something went wrong. Details are in the log file (Options, Open the log folder).")
            messagebox.showerror(APP_NAME, f"The wallpaper could not be made.\n\n{data[0]}")
        elif kind == "loupe":
            token, cx, cy, plain, enhanced = data
            if getattr(self, "_loupe_token", None) is token and self.magnify.get():
                self.loupe = (cx, cy, plain, enhanced)
                self._draw()
        elif kind == "engine":
            value, note, good = data
            self.engine_value.set(value)
            self.engine_note.set(note)
            self.engine_label.configure(foreground=ui.HOLO if good else ui.OFFLINE)
            self.info.set(self._describe())

    def _finish(self):
        self.worker = None
        self._set_busy(False)
        self._refresh()

    def _set_busy(self, busy: bool):
        for widget in self.busy_widgets:
            if isinstance(widget, ttk.Combobox):
                widget.state(["disabled"] if busy else ["!disabled", "readonly"])
            else:
                widget.state(["disabled"] if busy else ["!disabled"])
        for card in self.cards:
            card.enabled = not busy
            card.configure(cursor="arrow" if busy else "hand2")
            card.draw()
        self.model_bar.set_enabled(not busy)
        for slider in self.sliders:
            slider.set_enabled(not busy)
        self.dim_toggle.set_enabled(not busy)
        for button in (self.set_button, self.show_button, self.save_button, self.compare_button, self.undo_button,
                       self.magnify_button, self.history_button):
            button.set_enabled(False)
        self.make_button.set_text("Cancel" if busy else "Make wallpaper")
        self.canvas.configure(cursor="watch" if busy else "arrow")
        self._draw()

    def _start_engine(self):
        """Load the AI on the graphics card while the window opens, so the first wallpaper
        does not wait for it."""
        client = upscale.EngineClient.shared()
        if client is not None:
            self.events.put(("engine", "ONLINE", client.gpu_name(), True))
        elif upscale.engine_exe() is not None:
            self.events.put(("engine", "ONLINE", "Real-ESRGAN command line engine", True))
        else:
            self.events.put(("engine", "OFFLINE", "Plain resizing only", False))

    # After it is made ------------------------------------------------------------------------

    def apply(self):
        if not self._result_current():
            return
        self.apply_file(self.result_path)

    def apply_file(self, path: Path):
        """Set path as the wallpaper on the chosen display, remembering the old one for Undo."""
        kind, value, _ = self._current_choice()
        try:
            snap = wallpaper.snapshot(resources.data_dir() / "undo")
            if kind == "span":
                wallpaper.set_wallpaper(path, span=True)
                where = "across all your displays"
            elif kind == "screen" and len(self.screens) > 1:
                wallpaper.set_wallpaper(path, screen=value)
                where = f"on {value.name}"
            else:
                wallpaper.set_wallpaper(path)
                where = "on your desktop" if len(self.screens) <= 1 else "on all your displays"
        except OSError as error:
            log.exception("Setting the wallpaper failed")
            messagebox.showerror(APP_NAME, f"Windows did not accept the wallpaper.\n\n{error}")
            return
        if snap:
            self.state["undo"] = snap
            state.save(self.state)
        log.info("Wallpaper set %s: %s", where, path)
        self.status.set(f"Your new wallpaper is set {where}. Undo puts the old one back.")
        self._update_result_buttons()

    def undo(self):
        saved = self.state.get("undo")
        if not saved or self.worker:
            return
        try:
            wallpaper.restore(saved)
        except OSError as error:
            log.exception("Undo failed")
            messagebox.showerror(APP_NAME, f"Windows did not accept the old wallpaper.\n\n{error}")
            return
        self.state.pop("undo", None)
        state.save(self.state)
        self.status.set("Your previous wallpaper is back.")
        self._update_result_buttons()

    def show_file(self):
        if self.result_path and self.result_path.exists():
            dialogs.show_in_folder(self.result_path)

    def save_copy(self):
        if not self._result_current():
            return
        path = filedialog.asksaveasfilename(
            title="Save a copy", initialfile=self.result_path.name, defaultextension=".png",
            filetypes=[("PNG picture", "*.png"), ("JPEG picture", "*.jpg")],
        )
        if path:
            pipeline.save(self.result, path)
            self.status.set(f"Saved a copy as \"{Path(path).name}\".")

    def _escape(self):
        if self.worker:
            self.make()
        elif self.magnify.get() or self.compare.get():
            self.magnify.set(False)
            self.compare.set(False)
            self.loupe = None
            self._refresh()

    def _close(self):
        if self.worker:
            if not messagebox.askyesno(APP_NAME, "A wallpaper is still being made. Stop and close?"):
                return
            self.cancel.set()
        self._save_state()
        upscale.EngineClient.stop_shared()
        self.root.destroy()


def create_root():
    """The main window, with drag and drop when tkinterdnd2 can load."""
    if TkinterDnD is not None:
        try:
            return TkinterDnD.Tk(), True
        except (tk.TclError, RuntimeError):
            pass
    return tk.Tk(), False


def prepare(root: tk.Tk) -> None:
    """Scale, fonts and colors; call before building the window."""
    ui.set_ui_scale(root)
    ui.pick_fonts(root)
    ui.apply_style(root)
    ui.tint_title_bar(root)


def main(initial: str | None = None):
    applog.setup()
    screens.enable_dpi_awareness()
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except (AttributeError, OSError):
            pass
    root, drag_and_drop = create_root()
    prepare(root)
    App(root, initial, drag_and_drop)
    root.mainloop()
