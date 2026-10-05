"""
The one place that knows which system Steam Shelf runs on. Discs work on
Windows (shelf.win32) and Linux (shelf.linux); both modules offer the same
functions, and on anything else (macOS) the app still makes discs but no
drive is watched.
"""
from __future__ import annotations

import sys
from typing import Optional

WINDOWS = sys.platform == "win32"
LINUX = sys.platform.startswith("linux")
SUPPORTED = WINDOWS or LINUX


def impl():
    """shelf.win32 or shelf.linux, None elsewhere."""
    if WINDOWS:
        from shelf import win32
        return win32
    if LINUX:
        from shelf import linux
        return linux
    return None


def optical_drives() -> list[str]:
    w = impl()
    return w.optical_drives() if w else []


def drive_name(drive: str) -> str:
    """'D:' on Windows, 'sr0' on Linux."""
    w = impl()
    return w.drive_name(drive) if w else drive


def drive_label(drive: str) -> str:
    """Linux: the drive's vendor and model ('HL-DT-ST DVDRAM GP65NB60')."""
    w = impl()
    return w.drive_label(drive) if w else drive


def agent_running() -> bool:
    w = impl()
    return bool(w and w.agent_running())


def stop_agent() -> bool:
    w = impl()
    return bool(w and w.stop_agent())


def hold_burner_mode() -> Optional[int]:
    """The window takes this once and keeps it: burner mode until the process ends, however it ends."""
    w = impl()
    return w.hold_burner_mode() if w else None


def burner_mode_on() -> bool:
    w = impl()
    return bool(w and w.burner_mode_on())


def access_problem() -> bool:
    """Linux: a drive is there but this user may not read it."""
    w = impl()
    return bool(w and w.access_problem())
