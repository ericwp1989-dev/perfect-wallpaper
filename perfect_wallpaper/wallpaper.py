"""Setting the Windows desktop wallpaper, for one display, all of them, or spanned across them.

Uses the shell's IDesktopWallpaper interface (Windows 8 and later), which can set a
different picture on each display. Falls back to the older SystemParametersInfo call,
which sets the same picture everywhere.
"""

from __future__ import annotations

import ctypes
import shutil
import sys
from ctypes import wintypes
from pathlib import Path

from . import _win
from .screens import Screen, physical_pixels

CLSID_DESKTOP_WALLPAPER = "{C2CF3110-460E-4FC1-B9D0-8A1C0C9CC4BD}"
IID_DESKTOP_WALLPAPER = "{B92B56A9-8B55-4E14-9A89-0199BBB6F93B}"
IID_SHELL_ITEM = "{43826D1E-E718-42EE-BC55-A1E261C37BFE}"
IID_SHELL_ITEM_ARRAY = "{B63EA76D-1F85-456F-A19C-48159EFA858B}"
CLSCTX_ALL = 0x17
FILL, SPAN = 4, 5  # DESKTOP_WALLPAPER_POSITION values


class _DesktopWallpaper:
    """Minimal ctypes binding for IDesktopWallpaper. Methods are called by vtable slot."""

    def __init__(self):
        ole32 = ctypes.oledll.ole32
        try:
            ole32.CoInitializeEx(None, 2)  # apartment threaded
        except OSError:
            pass  # COM was already set up on this thread in another mode; that still works
        self.pointer = ctypes.c_void_p()
        clsid, iid = _win.guid(CLSID_DESKTOP_WALLPAPER), _win.guid(IID_DESKTOP_WALLPAPER)
        ole32.CoCreateInstance(
            ctypes.byref(clsid), None, CLSCTX_ALL, ctypes.byref(iid), ctypes.byref(self.pointer)
        )
        self.vtable = ctypes.cast(self.pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents

    def _call(self, slot, argtypes, *args):
        method = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)(self.vtable[slot])
        return method(self.pointer, *args)

    def set_wallpaper(self, monitor_id, path):
        self._call(3, (wintypes.LPCWSTR, wintypes.LPCWSTR), monitor_id, path)

    def get_wallpaper(self, monitor_id) -> str:
        out = wintypes.LPWSTR()
        self._call(4, (wintypes.LPCWSTR, ctypes.POINTER(wintypes.LPWSTR)), monitor_id, ctypes.byref(out))
        try:
            return out.value or ""
        finally:
            _win.free(out)

    def monitor_ids(self) -> list[str]:
        count = wintypes.UINT()
        self._call(6, (ctypes.POINTER(wintypes.UINT),), ctypes.byref(count))
        ids = []
        for index in range(count.value):
            out = wintypes.LPWSTR()
            self._call(5, (wintypes.UINT, ctypes.POINTER(wintypes.LPWSTR)), index, ctypes.byref(out))
            ids.append(out.value)
            _win.free(out)
        return ids

    def monitor_rect(self, monitor_id) -> tuple[int, int, int, int]:
        rect = wintypes.RECT()
        self._call(7, (wintypes.LPCWSTR, ctypes.POINTER(wintypes.RECT)), monitor_id, ctypes.byref(rect))
        return rect.left, rect.top, rect.right, rect.bottom

    def set_position(self, position: int):
        self._call(10, (ctypes.c_int,), position)

    def get_position(self) -> int:
        out = ctypes.c_int()
        self._call(11, (ctypes.POINTER(ctypes.c_int),), ctypes.byref(out))
        return out.value

    def set_slideshow(self, items: ctypes.c_void_p):
        self._call(12, (ctypes.c_void_p,), items)

    def set_slideshow_options(self, shuffle: bool, milliseconds: int):
        self._call(14, (ctypes.c_int, wintypes.UINT), 1 if shuffle else 0, milliseconds)

    def close(self):
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(self.vtable[2])
        release(self.pointer)


def set_wallpaper(path, screen: Screen | None = None, span: bool = False) -> None:
    """Set path as the wallpaper on one screen, on every screen, or spanned across all of them."""
    if sys.platform != "win32":
        raise OSError("Setting the wallpaper is only supported on Windows.")
    path = str(Path(path).resolve())
    try:
        desktop = _DesktopWallpaper()
    except OSError:
        _set_everywhere(path, span)
        return
    try:
        desktop.set_position(SPAN if span else FILL)
        monitor = _find_monitor(desktop, screen) if screen and not span else None
        desktop.set_wallpaper(monitor, path)
    finally:
        desktop.close()


def _find_monitor(desktop: _DesktopWallpaper, screen: Screen) -> str | None:
    with physical_pixels():  # the same real pixel rectangles screens.list_screens() reports
        for monitor in desktop.monitor_ids():
            try:
                if desktop.monitor_rect(monitor) == screen.rect:
                    return monitor
            except OSError:
                continue  # a display that is listed but switched off
    return None  # no exact match: set every display rather than guess


# Undo -----------------------------------------------------------------------------------------

def snapshot(folder: Path) -> dict | None:
    """Remember the current wallpaper on every display, copying the files into folder,
    because Windows overwrites its own copy when a new wallpaper is set."""
    if sys.platform != "win32":
        return None
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*"):
        old.unlink(missing_ok=True)
    try:
        desktop = _DesktopWallpaper()
    except OSError:
        return None
    try:
        saved = {"position": desktop.get_position(), "monitors": []}
        for n, monitor in enumerate(desktop.monitor_ids()):
            try:
                current = desktop.get_wallpaper(monitor)
            except OSError:
                continue
            copy = ""
            if current and Path(current).exists():
                copy = str(folder / f"display {n + 1}{Path(current).suffix or '.jpg'}")
                shutil.copy2(current, copy)
            saved["monitors"].append({"id": monitor, "path": copy})
        return saved
    finally:
        desktop.close()


def restore(saved: dict) -> None:
    """Put back the wallpapers a snapshot() recorded."""
    desktop = _DesktopWallpaper()
    try:
        desktop.set_position(saved.get("position", FILL))
        known = set(desktop.monitor_ids())
        for entry in saved.get("monitors", []):
            if entry["path"] and Path(entry["path"]).exists():
                desktop.set_wallpaper(entry["id"] if entry["id"] in known else None, entry["path"])
    finally:
        desktop.close()


# Slideshows -----------------------------------------------------------------------------------

def set_slideshow(folder: Path, minutes: int = 30, shuffle: bool = True, span: bool = False) -> None:
    """Make Windows rotate through every picture in folder."""
    shell32 = ctypes.oledll.shell32
    item, items = ctypes.c_void_p(), ctypes.c_void_p()
    shell32.SHCreateItemFromParsingName(str(Path(folder).resolve()), None,
                                        ctypes.byref(_win.guid(IID_SHELL_ITEM)), ctypes.byref(item))
    try:
        shell32.SHCreateShellItemArrayFromShellItem(item, ctypes.byref(_win.guid(IID_SHELL_ITEM_ARRAY)),
                                                    ctypes.byref(items))
        desktop = _DesktopWallpaper()
        try:
            desktop.set_position(SPAN if span else FILL)
            desktop.set_slideshow(items)
            desktop.set_slideshow_options(shuffle, minutes * 60_000)
        finally:
            desktop.close()
    finally:
        for pointer in (items, item):
            if pointer.value:
                release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(
                    ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents[2])
                release(pointer)


def _set_everywhere(path: str, span: bool) -> None:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop", 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "WallpaperStyle", 0, winreg.REG_SZ, "22" if span else "10")
        winreg.SetValueEx(key, "TileWallpaper", 0, winreg.REG_SZ, "0")
    spi_set_desk_wallpaper, update_and_notify = 20, 3
    if not ctypes.windll.user32.SystemParametersInfoW(spi_set_desk_wallpaper, 0, path, update_and_notify):
        raise ctypes.WinError()


def current_wallpapers() -> dict[tuple[int, int, int, int], str]:
    """The wallpaper on each display, keyed by its rectangle. Read only; used for checks."""
    desktop = _DesktopWallpaper()
    try:
        return {desktop.monitor_rect(m): desktop.get_wallpaper(m) for m in desktop.monitor_ids()}
    finally:
        desktop.close()
