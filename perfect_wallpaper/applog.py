"""The program's log file, so a friend who hits a problem can send you the details.

It lives in %LOCALAPPDATA%\\Perfect Wallpaper\\logs and keeps at most four files of 1 MB.
Anything that crashes is written there too, with its traceback.
"""

from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import __version__, resources


def log_dir() -> Path:
    folder = resources.data_dir() / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def setup() -> Path:
    path = log_dir() / "perfect-wallpaper.log"
    root = logging.getLogger()
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
        root.setLevel(logging.INFO)

        def crashed(kind, value, tb):
            logging.getLogger("crash").error("Unhandled error", exc_info=(kind, value, tb))
            sys.__excepthook__(kind, value, tb)

        sys.excepthook = crashed
        threading.excepthook = lambda args: logging.getLogger("crash").error(
            "Unhandled error in a background task", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        logging.getLogger(__name__).info("Perfect Wallpaper %s started", __version__)
    return path
