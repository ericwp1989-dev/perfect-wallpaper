"""Open the app with a picture loaded and save a screenshot of the whole window.

    python scripts/screenshot_ui.py [picture.jpg] docs/screenshot.png [--rotate left] [--fit blur]
"""

import argparse
import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import ImageGrab  # noqa: E402

from perfect_wallpaper import app, screens  # noqa: E402


def window_bounds(root):
    """The window's outer edges, title bar included, without the invisible resize border."""
    hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
    rect = wintypes.RECT()
    ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("picture", nargs="?")
    parser.add_argument("output")
    parser.add_argument("--rotate", choices=["left", "right"])
    parser.add_argument("--fit", default="fill")
    args = parser.parse_args()

    screens.enable_dpi_awareness()
    root, dnd = app.create_root()
    app.prepare(root)
    window = app.App(root, None, dnd)
    root.attributes("-topmost", True)
    if args.picture:
        window.open_picture(args.picture)
        if args.rotate:
            window.rotate(90 if args.rotate == "left" else -90)
        window._pick_mode(args.fit)
    window._save_state = lambda: None  # a screenshot run should not change the saved settings

    def capture():
        root.update()
        ImageGrab.grab(window_bounds(root)).save(args.output)
        root.destroy()

    root.after(1800, capture)
    root.mainloop()


if __name__ == "__main__":
    main()
