"""Where the app finds its bundled files and where it saves wallpapers.

Works the same whether it runs from source or from the single .exe that PyInstaller
builds (which unpacks its files into a temporary folder named by sys._MEIPASS).
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

FOLDERID_PICTURES = "{33E28130-4E1E-4676-835A-98395C3BC3BB}"


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def engine_dir() -> Path:
    override = os.environ.get("PERFECT_WALLPAPER_ENGINE")
    return Path(override) if override else base_dir() / "engine"


def asset(name: str) -> Path:
    return base_dir() / "assets" / name


def pictures_dir() -> Path:
    """The user's Pictures folder, even when Windows or OneDrive has moved it."""
    if sys.platform == "win32":
        try:
            from . import _win

            folder = _win.guid(FOLDERID_PICTURES)
            path = ctypes.c_wchar_p()
            ctypes.oledll.shell32.SHGetKnownFolderPath(ctypes.byref(folder), 0, None, ctypes.byref(path))
            try:
                return Path(path.value)
            finally:
                _win.free(path)
        except OSError:
            pass
    return Path.home() / "Pictures"


def output_dir() -> Path:
    folder = pictures_dir() / "Perfect Wallpaper"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def data_dir() -> Path:
    """Where the program keeps its settings, history, log and Undo copies."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    folder = Path(base) / "Perfect Wallpaper"
    folder.mkdir(parents=True, exist_ok=True)
    return folder
