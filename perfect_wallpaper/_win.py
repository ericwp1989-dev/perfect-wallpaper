"""Small Windows API helpers shared by the modules that talk to the shell."""

from __future__ import annotations

import ctypes
from ctypes import wintypes


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def guid(text: str) -> GUID:
    value = GUID()
    ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(value))
    return value


def free(pointer) -> None:
    """Release a string the shell allocated for us."""
    ctypes.windll.ole32.CoTaskMemFree(pointer)
