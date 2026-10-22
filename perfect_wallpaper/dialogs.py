"""The program's extra windows: history, a whole folder at once, finding a sharper copy
online, and installing the stronger AI."""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np
from PIL import Image, ImageTk

from . import APP_NAME, creative, fitting, pipeline, resources, search, state, ui, upscale, wallpaper

log = logging.getLogger(__name__)


def plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"


def show_in_folder(path: Path) -> None:
    if sys.platform == "win32":
        subprocess.Popen(f'explorer /select,"{path}"')
    else:
        subprocess.Popen(["xdg-open", str(Path(path).parent)])


def _thumbnail(path: Path, box=(240, 120)) -> Image.Image | None:
    """A small copy of a picture, cached so the history opens quickly next time."""
    folder = resources.data_dir() / "thumbs"
    folder.mkdir(exist_ok=True)
    stamp = f"{path}|{path.stat().st_mtime_ns}|{box}".encode()
    cached = folder / f"{hashlib.sha1(stamp).hexdigest()}.jpg"
    try:
        if cached.exists():
            return Image.open(cached).copy()
        with Image.open(path) as image:
            image.thumbnail(box)
            small = image.convert("RGB")
        small.save(cached, quality=88)
        return small
    except OSError:
        return None


# History ----------------------------------------------------------------------------------

class HistoryDialog(ui.Dialog):
    """Every wallpaper you made, newest first, ready to set again or reopen."""

    def __init__(self, app):
        super().__init__(app.root, "Wallpaper history", width=900, height=640)
        self.app = app
        self.photos = []
        entries = state.history(app.state)
        if not entries:
            tk.Label(self.body, text="Wallpapers you make will appear here.", background=ui.SPACE,
                     foreground=ui.ICE_DIM, font=ui.FONT).pack(pady=ui.px(40))
            return
        tk.Label(self.body, text=f"{plural(len(entries), 'wallpaper')}, newest first. They are kept in your Pictures folder, "
                                 "under Perfect Wallpaper.", background=ui.SPACE, foreground=ui.ICE_DIM,
                 font=ui.FONT_SM).pack(anchor="w", pady=(0, ui.px(8)))
        grid = ui.ScrollGrid(self.body)
        grid.pack(fill="both", expand=True)
        columns = 3
        for i, entry in enumerate(entries):
            card = tk.Frame(grid.inner, background=ui.PANEL, highlightthickness=1, highlightbackground=ui.LINE)
            card.grid(row=i // columns, column=i % columns, padx=ui.px(6), pady=ui.px(6), sticky="nsew")
            grid.inner.columnconfigure(i % columns, weight=1)
            holder = tk.Label(card, background=ui.PANEL, height=ui.px(8))
            holder.pack(padx=ui.px(8), pady=(ui.px(8), ui.px(4)))
            path = Path(entry["path"])
            made = datetime.fromisoformat(entry["made"]).strftime("%b %d, %Y %I:%M %p")
            tk.Label(card, text=path.name, background=ui.PANEL, foreground=ui.ICE, font=ui.FONT_SM,
                     wraplength=ui.px(250)).pack(padx=ui.px(8))
            tk.Label(card, text=made, background=ui.PANEL, foreground=ui.MUTED, font=ui.FONT_SM).pack()
            row = tk.Frame(card, background=ui.PANEL)
            row.pack(pady=ui.px(8))
            ui.HudButton(row, "Set", lambda p=path: self._set(p), "panel", font=ui.FONT_SM, padx=10, pady=4,
                         tip="Set this as your wallpaper on the display chosen in the main window").pack(side="left")
            ui.HudButton(row, "Show file", lambda p=path: show_in_folder(p), "panel", font=ui.FONT_SM, padx=10,
                         pady=4).pack(side="left", padx=ui.px(6))
            source = entry.get("source", "")
            if source and Path(source).exists():
                ui.HudButton(row, "Open again", lambda e=entry: self._reopen(e), "panel", font=ui.FONT_SM, padx=10,
                             pady=4, tip="Load the original picture with the settings used for this wallpaper"
                             ).pack(side="left")
            threading.Thread(target=self._load_thumb, args=(holder, path), daemon=True).start()

    def _load_thumb(self, holder, path):
        image = _thumbnail(path)
        if image is not None:
            self.post(lambda: self._place(holder, image))

    def _place(self, holder, image):
        if not holder.winfo_exists():
            return
        photo = ImageTk.PhotoImage(image)
        self.photos.append(photo)
        holder.configure(image=photo, height=photo.height())

    def _set(self, path):
        self.app.apply_file(path)

    def _reopen(self, entry):
        self.destroy()
        self.app.reopen(entry)


# A whole folder ----------------------------------------------------------------------------

SLIDESHOW_TIMES = [("1 minute", 1), ("10 minutes", 10), ("30 minutes", 30), ("1 hour", 60), ("6 hours", 360),
                   ("1 day", 1440)]


class FolderDialog(ui.Dialog):
    """Make wallpapers from every picture in a folder with the current settings, and
    optionally hand them to Windows as a slideshow."""

    def __init__(self, app, folder: Path):
        super().__init__(app.root, "Fit a whole folder", width=640, height=470)
        self.app, self.folder = app, folder
        self.cancel = threading.Event()
        self.worker = None
        patterns = pipeline.PICTURE_PATTERNS.replace("*", "").split()
        self.pictures = sorted(p for p in folder.iterdir() if p.suffix.lower() in patterns)
        settings = app.settings_for_batch()
        w, h = settings.target
        self.out = resources.output_dir() / f"{folder.name} {w}x{h}"
        self.settings = settings

        tk.Label(self.body, text=f"{plural(len(self.pictures), 'picture')} in \"{folder.name}\"", background=ui.SPACE,
                 foreground=ui.ICE, font=ui.FONT_B).pack(anchor="w")
        model = upscale.model_for(settings.enhance)
        summary = (f"Each one is made at {w} × {h} with the fit, AI and look settings from the main window "
                   f"({'AI: ' + model.label if model else 'no AI'}), and Fill mode picks the best crop for each. "
                   f"They are saved in Pictures, Perfect Wallpaper, \"{self.out.name}\".")
        tk.Label(self.body, text=summary, background=ui.SPACE, foreground=ui.ICE_DIM, font=ui.FONT_SM,
                 justify="left", wraplength=ui.px(580)).pack(anchor="w", pady=(ui.px(6), ui.px(14)))

        self.slideshow = tk.BooleanVar(value=True)
        self.shuffle = tk.BooleanVar(value=True)
        self.every = tk.StringVar(value="30 minutes")
        opts = tk.Frame(self.body, background=ui.SPACE)
        opts.pack(anchor="w")
        ui.Toggle(opts, "Use them as a Windows slideshow when done", self.slideshow, lambda: None).pack(anchor="w")
        row = tk.Frame(opts, background=ui.SPACE)
        row.pack(anchor="w", pady=ui.px(8), padx=(ui.px(37), 0))
        tk.Label(row, text="Change every", background=ui.SPACE, foreground=ui.ICE_DIM, font=ui.FONT_SM).pack(
            side="left")
        ttk.Combobox(row, textvariable=self.every, values=[t for t, _ in SLIDESHOW_TIMES], state="readonly",
                     width=12).pack(side="left", padx=ui.px(8))
        ui.Toggle(row, "Shuffle", self.shuffle, lambda: None).pack(side="left", padx=ui.px(10))

        self.status = tk.StringVar(value="Ready.")
        tk.Label(self.body, textvariable=self.status, background=ui.SPACE, foreground=ui.ICE_DIM, font=ui.FONT_MONO,
                 anchor="w", width=1).pack(fill="x", pady=(ui.px(18), ui.px(6)))
        self.meter = ui.Meter(self.body)
        self.meter.pack(fill="x")
        buttons = tk.Frame(self.body, background=ui.SPACE)
        buttons.pack(anchor="e", pady=(ui.px(16), 0))
        self.go = ui.HudButton(buttons, "Make them all", self.start, "primary", ui.FONT_BIG, padx=22, pady=8)
        self.go.pack(side="right")
        self.show = ui.HudButton(buttons, "Show folder", lambda: show_in_folder(self.out), "quiet")
        if not self.pictures:
            self.go.set_enabled(False)
            self.status.set("This folder has no pictures the program can open.")
        self.protocol("WM_DELETE_WINDOW", self.close)

    def start(self):
        if self.worker:
            self.cancel.set()
            self.status.set("Stopping after this picture...")
            return
        self.cancel.clear()
        self.go.set_text("Cancel")
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()

    def _run(self):
        made, failed = 0, 0
        total = len(self.pictures)
        for i, path in enumerate(self.pictures):
            if self.cancel.is_set():
                break
            self.post(self.status.set, f"Picture {i + 1} of {total}: {path.name}")
            try:
                picture = pipeline.load_picture(path)
                part = lambda p, i=i: self.post(self.meter.set, (i + p) / total)  # noqa: E731
                image, _ = pipeline.render(picture, self.settings, progress=part, cancel=self.cancel)
                out = pipeline.unique_path(self.out / f"{path.stem}.png")
                pipeline.save(image, out)
                made += 1
            except upscale.Cancelled:
                break
            except Exception as error:  # one bad file should not stop the rest
                log.exception("Folder: %s failed", path)
                failed += 1
                self.post(self.status.set, f"Skipped {path.name}: {error}")
        self.post(self._done, made, failed)

    def _done(self, made, failed):
        self.worker = None
        self.go.set_text("Make them all")
        self.meter.set(1 if made else 0)
        text = f"Made {plural(made, 'wallpaper')}" + (f", skipped {failed}" if failed else "") + "."
        if made and self.slideshow.get():
            minutes = dict(SLIDESHOW_TIMES).get(self.every.get(), 30)
            try:
                wallpaper.set_slideshow(self.out, minutes, self.shuffle.get(), span=self.app.choice_is_span())
                text += f" Windows now shows them as a slideshow, changing every {self.every.get()}."
            except OSError as error:
                log.exception("Slideshow failed")
                text += f" The slideshow could not be set ({error})."
        self.status.set(text)
        if made:
            self.show.pack(side="right", padx=ui.px(8))

    def close(self):
        self.cancel.set()
        self.destroy()


# Finding a sharper copy --------------------------------------------------------------------

class SearchDialog(ui.Dialog):
    """Look for bigger copies of the loaded picture on Wallhaven, or hand the picture to a
    web image search."""

    def __init__(self, app):
        super().__init__(app.root, "Find a sharper copy", width=980, height=700)
        self.app = app
        self.picture = app.rotated_picture()  # the reduced copy is plenty for matching
        self.size = app.full_size()           # but compare sizes with the real picture
        self.cancel = threading.Event()
        self.photos = []
        self.worker = None

        top = tk.Frame(self.body, background=ui.SPACE)
        top.pack(fill="x")
        tk.Label(top, text="Search words", background=ui.SPACE, foreground=ui.ICE_DIM, font=ui.FONT_SM).pack(
            side="left")
        self.words = tk.StringVar(value=app.search_words())
        entry = ttk.Entry(top, textvariable=self.words, width=34, font=ui.FONT)
        entry.pack(side="left", padx=ui.px(8))
        entry.bind("<Return>", lambda _e: self.run())
        self.go = ui.HudButton(top, "Search", self.run, "primary", padx=18, pady=6)
        self.go.pack(side="left")
        web = tk.Frame(top, background=ui.SPACE)
        web.pack(side="right")
        tk.Label(web, text="Or search the whole web:", background=ui.SPACE, foreground=ui.MUTED,
                 font=ui.FONT_SM).pack(side="left", padx=(0, ui.px(6)))
        for name, url in search.WEB_SEARCHES.items():
            ui.HudButton(web, name, lambda u=url, n=name: self.web(n, u), "secondary", font=ui.FONT_SM, padx=10,
                         pady=4).pack(side="left", padx=(ui.px(4), 0))

        tk.Label(self.body, text=f"Your picture is {self.size[0]} × {self.size[1]}. Copies of the same picture come "
                                 "first, the ones that would look sharpest on your screen first. Searching Wallhaven, "
                                 "a free wallpaper site.",
                 background=ui.SPACE, foreground=ui.MUTED, font=ui.FONT_SM).pack(anchor="w", pady=(ui.px(8), 0))
        self.status = tk.StringVar(value="Check the search words, then press Search.")
        tk.Label(self.body, textvariable=self.status, background=ui.SPACE, foreground=ui.ICE_DIM, font=ui.FONT_MONO,
                 anchor="w", width=1).pack(fill="x", pady=(ui.px(8), ui.px(4)))
        self.meter = ui.Meter(self.body)
        self.meter.pack(fill="x", pady=(0, ui.px(8)))
        self.grid = ui.ScrollGrid(self.body)
        self.grid.pack(fill="both", expand=True)
        self.protocol("WM_DELETE_WINDOW", self.close)
        if self.words.get():
            self.after(200, self.run)

    def web(self, name, url):
        if search.copy_to_clipboard(self.picture):
            self.status.set(f"Your picture is on the clipboard. In {name}, press Ctrl+V to search with it.")
        else:
            self.status.set(f"Could not copy the picture. In {name}, upload it from {self.app.source_hint()}.")
        webbrowser.open(url)

    def run(self):
        words = self.words.get().strip()
        if not words or self.worker:
            return
        for child in self.grid.inner.winfo_children():
            child.destroy()
        self.photos.clear()
        self.cancel.clear()
        self.go.set_enabled(False)

        def work():
            try:
                found = search.find_copies(words, self.picture, progress=lambda f, t: self.post(self._progress, f, t),
                                           cancel=self.cancel)
                self.post(self._show, found)
            except OSError as error:
                log.warning("Search failed: %s", error)
                self.post(self._failed, f"The search could not reach Wallhaven ({error}).")

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _progress(self, fraction, text):
        if self.winfo_exists():
            self.meter.set(fraction)
            self.status.set(text)

    def _failed(self, text):
        self.worker = None
        self.go.set_enabled(True)
        self.status.set(text)

    def sharper(self, c: search.Candidate) -> float:
        """How much sharper this copy would look on the chosen screen with the current fit:
        how much your picture must be enlarged, over how much this copy must be."""
        settings = self.app.settings_for_batch()
        need = lambda w, h: fitting.make_plan((w, h), settings.target, settings.mode).scale  # noqa: E731
        return need(*self.size) / need(c.width, c.height)

    def _show(self, found):
        if not self.winfo_exists():
            return
        self.worker = None
        self.go.set_enabled(True)
        found.sort(key=lambda c: (c.match == "Same picture", c.match == "Similar", self.sharper(c)), reverse=True)
        same = [c for c in found if c.match == "Same picture"]
        better = [c for c in same if self.sharper(c) > 1.05]
        if not found:
            self.status.set("No results. Try fewer or different words.")
        elif better:
            self.status.set(f"Found {plural(len(better), 'copy', 'copies')} of your picture that would look sharper "
                            f"on your screen, among {plural(len(found), 'result')}.")
        elif same:
            self.status.set(f"Found {plural(len(same), 'copy', 'copies')} of your picture, but none would look "
                            "sharper on your screen with this fit. A different fit, such as blurred sides, may change "
                            "that.")
        else:
            self.status.set(f"{plural(len(found), 'result')}, none recognized as your picture. Try other words, or "
                            "the web search buttons above.")
        columns = 4
        for i, c in enumerate(found[:40]):
            self._card(c, i // columns, i % columns)
            self.grid.inner.columnconfigure(i % columns, weight=1)

    def _card(self, c: search.Candidate, row, column):
        match_color = {"Same picture": ui.OMNI, "Similar": ui.HOLO}.get(c.match, ui.MUTED)
        card = tk.Frame(self.grid.inner, background=ui.PANEL, highlightthickness=1 if c.match != "Same picture" else 2,
                        highlightbackground=match_color if c.match != "Different" else ui.LINE)
        card.grid(row=row, column=column, padx=ui.px(5), pady=ui.px(5), sticky="nsew")
        thumb = Image.fromarray(ui.fit_inside(c.thumb, (ui.px(210), ui.px(130))))
        photo = ImageTk.PhotoImage(thumb)
        self.photos.append(photo)
        tk.Label(card, image=photo, background=ui.PANEL).pack(padx=ui.px(6), pady=(ui.px(6), ui.px(4)))
        tk.Label(card, text=c.match.upper(), background=ui.PANEL, foreground=match_color, font=ui.FONT_SIGN).pack()
        tk.Label(card, text=f"{c.width} × {c.height}", background=ui.PANEL, foreground=ui.ICE, font=ui.FONT_SM).pack()
        ratio = self.sharper(c)
        if ratio > 1.05:
            note, color = f"{ratio:.1f}× sharper on your screen", ui.OMNI_HI
        elif ratio > 0.95:
            note, color = "about as sharp on your screen", ui.ICE_DIM
        else:
            note, color = "less sharp on your screen", ui.MUTED
        tk.Label(card, text=note, background=ui.PANEL, foreground=color, font=ui.FONT_SM).pack()
        row_ = tk.Frame(card, background=ui.PANEL)
        row_.pack(pady=ui.px(6))
        ui.HudButton(row_, "Use this", lambda: self.use(c), "primary" if c.match == "Same picture" else "panel",
                     font=ui.FONT_SM, padx=10, pady=4).pack(side="left")
        ui.HudButton(row_, "Open page", lambda: webbrowser.open(c.page_url), "quiet", font=ui.FONT_SM, padx=8,
                     pady=4).pack(side="left", padx=(ui.px(4), 0))

    def use(self, c: search.Candidate):
        self.status.set(f"Downloading {c.width} × {c.height}...")

        def work():
            try:
                path = search.download(c, resources.output_dir() / "Sources")
                self.post(self._loaded, path)
            except OSError as error:
                self.post(self.status.set, f"The download failed ({error}).")

        threading.Thread(target=work, daemon=True).start()

    def _loaded(self, path):
        self.destroy()
        self.app.open_picture(path, keep_settings=True)
        self.app.set_status(f"Loaded the sharper copy, saved in Pictures, Perfect Wallpaper, Sources, as \"{path.name}\".")

    def close(self):
        self.cancel.set()
        self.destroy()


# Installing the stronger AI ---------------------------------------------------------------

class CreativeDialog(ui.Dialog):
    """Explains the stronger AI and downloads it on request."""

    def __init__(self, app, on_ready):
        super().__init__(app.root, "The stronger AI", width=640, height=470)
        self.app, self.on_ready = app, on_ready
        self.cancel = threading.Event()
        self.worker = None
        text = ("The stronger AI repaints the enlarged picture in small squares with Stable Diffusion, an image "
                "generating AI, guided so it keeps every shape and color, and adds the finest texture it paints to "
                "the regular result. The difference is subtle: crisper grain and edges up close. It takes a few "
                "minutes per wallpaper and can change tiny details.\n\nIt needs an NVIDIA graphics card and a one "
                "time download "
                f"of {creative.SIZE_TEXT} (Python, PyTorch and two models), kept in your user folder. You can "
                "remove it again from the Options menu.")
        tk.Label(self.body, text=text, background=ui.SPACE, foreground=ui.ICE_DIM, font=ui.FONT, justify="left",
                 wraplength=ui.px(580)).pack(anchor="w")
        self.status = tk.StringVar(value="" if creative.has_nvidia_card()
                                   else "No NVIDIA graphics card was found, so the stronger AI cannot run here.")
        tk.Label(self.body, textvariable=self.status, background=ui.SPACE, foreground=ui.ICE_DIM, font=ui.FONT_MONO,
                 anchor="w", width=1).pack(fill="x", pady=(ui.px(18), ui.px(6)))
        self.meter = ui.Meter(self.body)
        self.meter.pack(fill="x")
        buttons = tk.Frame(self.body, background=ui.SPACE)
        buttons.pack(anchor="e", pady=(ui.px(16), 0))
        self.go = ui.HudButton(buttons, f"Download ({creative.SIZE_TEXT})", self.start, "primary", ui.FONT_BIG,
                               padx=22, pady=8)
        self.go.pack(side="right")
        if not creative.has_nvidia_card():
            self.go.set_enabled(False)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def start(self):
        if self.worker:
            self.cancel.set()
            self.status.set("Stopping...")
            return
        self.cancel.clear()
        self.go.set_text("Cancel")

        def say(fraction, text):
            self.post(self._progress, fraction, text)

        def work():
            try:
                creative.install(say, self.cancel)
                self.post(self._done, None)
            except upscale.Cancelled:
                self.post(self._done, "Stopped. Pressing Download again picks up where it left off.")
            except Exception as error:
                log.exception("Stronger AI install failed")
                self.post(self._done, f"The download failed: {error}")

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _progress(self, fraction, text):
        if self.winfo_exists():
            if fraction is not None:
                self.meter.set(fraction)
            self.status.set(text)

    def _done(self, problem):
        self.worker = None
        if not self.winfo_exists():
            return
        if problem:
            self.go.set_text(f"Download ({creative.SIZE_TEXT})")
            self.status.set(problem)
            return
        self.destroy()
        self.on_ready()

    def close(self):
        if self.worker and not messagebox.askyesno(APP_NAME, "Stop the download? It can resume later.", parent=self):
            return
        self.cancel.set()
        self.destroy()
