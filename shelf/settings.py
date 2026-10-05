"""User settings (DATA_DIR/settings.json). The agent re-reads them on every disc, so changes apply at once."""
from __future__ import annotations

import json
import os
from pathlib import Path

import config

DEFAULTS = {
    "enabled": True,              # the agent reacts to discs at all
    "countdown": 5,               # s of "starting in…" card before launching; 0 = launch at once
    "startup_disc": "ask",        # disc already in the drive at startup / wake: "ask" | "ignore"
    "not_installed": "store",     # game not installed: "store" (store page) | "install" (Steam install dialog)
    "autostart": True,            # start the agent when you log in (Windows, Linux)
    "language": "auto",           # "auto" = the system's, or a code from shelf.i18n.LANGUAGES
}

CHOICES = {"startup_disc": ("ask", "ignore"), "not_installed": ("store", "install")}


def _path() -> Path:
    return config.SETTINGS_FILE


def load() -> dict:
    s = dict(DEFAULTS)
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for k, v in data.items():
                if k in DEFAULTS and type(v) is type(DEFAULTS[k]):
                    if k in CHOICES and v not in CHOICES[k]:
                        continue
                    if k == "language":
                        from shelf.i18n import LANGUAGES
                        if v != "auto" and v not in LANGUAGES:
                            continue
                    s[k] = v
    except (OSError, ValueError):
        pass
    s["countdown"] = max(0, min(30, int(s["countdown"])))
    return s


def save(s: dict) -> None:
    clean = {k: s.get(k, v) for k, v in DEFAULTS.items()}
    p = _path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    os.replace(tmp, p)
