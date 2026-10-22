"""Finding the user's displays and their real pixel sizes."""

from __future__ import annotations

import ctypes
import re
import sys
from ctypes import wintypes
from dataclasses import dataclass


@dataclass(frozen=True)
class Screen:
    name: str      # "Display 1"
    device: str    # Windows device name, such as \\.\DISPLAY1
    left: int
    top: int
    width: int
    height: int
    primary: bool

    @property
    def size(self) -> tuple[int, int]:
        return self.width, self.height

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.left + self.width, self.top + self.height


SYSTEM_AWARE, PER_MONITOR_AWARE_V2 = -2, -4  # DPI_AWARENESS_CONTEXT values


def enable_dpi_awareness() -> None:
    """Draw the window sharply at the main display's scaling.

    The window is "system aware": on a second monitor with different scaling, Windows
    resizes it to look right there (a little softer) instead of leaving it too small or
    too large, which Tk cannot fix by itself. Screen sizes are still read in real
    pixels; see physical_pixels().
    """
    if sys.platform != "win32":
        return
    user32 = ctypes.windll.user32
    try:
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(SYSTEM_AWARE)):
            return
    except AttributeError:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        user32.SetProcessDPIAware()


class physical_pixels:
    """While inside this block, Windows reports every monitor in its real pixels, even
    one whose scaling differs from the main display's."""

    def __enter__(self):
        self.previous = None
        if sys.platform == "win32":
            try:
                fn = ctypes.windll.user32.SetThreadDpiAwarenessContext
                fn.argtypes, fn.restype = [ctypes.c_void_p], ctypes.c_void_p
                self.previous = fn(ctypes.c_void_p(PER_MONITOR_AWARE_V2))
            except AttributeError:
                pass
        return self

    def __exit__(self, *exc):
        if self.previous:
            ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(self.previous))


class _MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


def list_screens() -> list[Screen]:
    """All displays, main display first. Empty when not on Windows."""
    if sys.platform != "win32":
        return []
    user32 = ctypes.windll.user32
    found: list[Screen] = []
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
    )

    def on_monitor(handle, _dc, _rect, _data):
        info = _MonitorInfo()
        info.cbSize = ctypes.sizeof(_MonitorInfo)
        if user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            r = info.rcMonitor
            number = re.search(r"(\d+)$", info.szDevice)
            found.append(
                Screen(
                    name=f"Display {number.group(1) if number else len(found) + 1}",
                    device=info.szDevice,
                    left=r.left,
                    top=r.top,
                    width=r.right - r.left,
                    height=r.bottom - r.top,
                    primary=bool(info.dwFlags & 1),
                )
            )
        return True

    with physical_pixels():
        user32.EnumDisplayMonitors(None, None, callback_type(on_monitor), 0)
    return sorted(found, key=lambda s: (not s.primary, s.left, s.top))


def combined_size(screens: list[Screen]) -> tuple[int, int]:
    """Size of one picture that spans every display, as Windows' Span setting expects."""
    left = min(s.left for s in screens)
    top = min(s.top for s in screens)
    right = max(s.left + s.width for s in screens)
    bottom = max(s.top + s.height for s in screens)
    return right - left, bottom - top


# Spanning with a gap ---------------------------------------------------------------------
# The frames between monitors hide a strip of a spanned picture, so straight lines jump
# at each edge. With a gap, the picture is made wider by that strip at every edge, and
# the strips are then cut out, so lines carry straight on from one screen to the next.

def _gapped_positions(screens: list[Screen], gap: int) -> dict[str, tuple[int, int]]:
    """Each screen's top left corner on the wider, gapped picture."""
    out = {}
    for s in screens:
        left_of = sum(1 for o in screens if o.left + o.width <= s.left)
        above = sum(1 for o in screens if o.top + o.height <= s.top)
        out[s.device] = (s.left + gap * left_of, s.top + gap * above)
    return out


def span_size(screens: list[Screen], gap: int = 0) -> tuple[int, int]:
    """The size to make a spanned picture at, including the gaps."""
    if not gap:
        return combined_size(screens)
    pos = _gapped_positions(screens, gap)
    left = min(pos[s.device][0] for s in screens)
    top = min(pos[s.device][1] for s in screens)
    right = max(pos[s.device][0] + s.width for s in screens)
    bottom = max(pos[s.device][1] + s.height for s in screens)
    return right - left, bottom - top


def cut_gaps(image, screens: list[Screen], gap: int):
    """Turn a picture made at span_size(..., gap) into the real spanned picture."""
    import numpy as np

    if not gap:
        return image
    pos = _gapped_positions(screens, gap)
    gx, gy = min(p[0] for p in pos.values()), min(p[1] for p in pos.values())
    rx, ry = min(s.left for s in screens), min(s.top for s in screens)
    w, h = combined_size(screens)
    out = np.zeros((h, w, 3), np.uint8)
    for s in screens:
        sx, sy = pos[s.device][0] - gx, pos[s.device][1] - gy
        dx, dy = s.left - rx, s.top - ry
        out[dy:dy + s.height, dx:dx + s.width] = image[sy:sy + s.height, sx:sx + s.width]
    return out
