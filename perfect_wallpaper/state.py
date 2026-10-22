"""What the program remembers between runs: your last choices, the window size, the
wallpapers you made, and the wallpaper each new one replaced (for Undo).

Kept as JSON in %LOCALAPPDATA%\\Perfect Wallpaper\\state.json.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from . import resources

log = logging.getLogger(__name__)
HISTORY_LIMIT = 60


def _path() -> Path:
    return resources.data_dir() / "state.json"


def load() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        log.warning("Settings file unreadable, starting fresh: %s", error)
        return {}


def save(data: dict) -> None:
    path = _path()
    temp = path.with_suffix(".tmp")
    try:
        temp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(temp, path)  # all or nothing, so a crash never leaves half a file
    except OSError as error:
        log.warning("Could not save settings: %s", error)


def history(data: dict) -> list[dict]:
    """Recent wallpapers, newest first, leaving out any whose file was deleted."""
    return [entry for entry in data.get("history", []) if Path(entry.get("path", "")).exists()]


def add_history(data: dict, path: Path, source: str, settings: dict) -> None:
    entry = {"path": str(path), "source": source, "made": datetime.now().isoformat(timespec="seconds"),
             "settings": settings}
    data["history"] = [entry] + [e for e in history(data) if e["path"] != str(path)][:HISTORY_LIMIT - 1]
