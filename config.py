"""Paths and version. Everything Steam Shelf writes goes under DATA_DIR."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "SteamShelf"


def _data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home()) / APP_NAME
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / APP_NAME
    override = os.environ.get("STEAMSHELF_DATA_DIR")      # tests and portable runs
    if override:
        base = Path(override)
    base.mkdir(parents=True, exist_ok=True)
    return base


def _bundle_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


DATA_DIR = _data_dir()
BUNDLE_DIR = _bundle_dir()
COVERS_DIR = DATA_DIR / "covers"
ISO_DIR = DATA_DIR / "iso"
SETTINGS_FILE = DATA_DIR / "settings.json"
SHELF_FILE = DATA_DIR / "shelf.json"
AGENT_LOG = DATA_DIR / "agent.log"

try:
    VERSION = (BUNDLE_DIR / "VERSION").read_text(encoding="utf-8").strip()
except OSError:
    VERSION = "0.0.0"
