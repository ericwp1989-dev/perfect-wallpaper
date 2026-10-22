"""The "Make a perfect wallpaper" entry in File Explorer's right click menu.

Written to HKEY_CURRENT_USER only, so it needs no administrator rights and affects only
you. On Windows 11 it appears under "Show more options". The installer adds the same
entry for the installed program and removes it on uninstall.
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import resources

KEY = r"Software\Classes\SystemFileAssociations\image\shell\PerfectWallpaper"
LABEL = "Make a perfect wallpaper"


def command() -> str:
    """How Explorer should start the program with the clicked picture."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" "%1"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    launcher = resources.base_dir() / "launcher.py"
    return f'"{pythonw}" "{launcher}" "%1"'


def is_registered() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY + r"\command"):
            return True
    except OSError:
        return False


def register() -> None:
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY) as key:
        winreg.SetValueEx(key, "MUIVerb", 0, winreg.REG_SZ, LABEL)
        winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, str(resources.asset("icon.ico")))
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY + r"\command") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command())


def unregister() -> None:
    import winreg

    for sub in (KEY + r"\command", KEY):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
        except OSError:
            pass
