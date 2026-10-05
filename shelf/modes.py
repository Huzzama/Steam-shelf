"""
Game mode and burner mode.

  game mode    Steam Shelf's window is closed; the background agent starts the
               game when a disc goes in.
  burner mode  the window is open: you are making discs, so the agent leaves
               every disc alone (no card, no Steam). "Test" uses the virtual drive
               (shelf.virtual) and allow_test, so a test behaves like game mode.

The window holds a lock while it is open (host.hold_burner_mode: a named mutex on
Windows, a flock on Linux); the system releases it when the app exits or crashes,
so the agent can never get stuck in burner mode.
"""
from __future__ import annotations

import json
import os
import time

import config

TEST_WINDOW = 120         # s a test disc may take to show up after "Test"
_ALLOW = config.DATA_DIR / "test_allow.json"


def allow_test(disc_id: str, seconds: float = TEST_WINDOW) -> None:
    tmp = _ALLOW.with_suffix(".tmp")
    tmp.write_text(json.dumps({"disc_id": disc_id, "until": time.time() + seconds}), encoding="utf-8")
    os.replace(tmp, _ALLOW)


def test_allowed(disc_id: str) -> bool:
    try:
        d = json.loads(_ALLOW.read_text(encoding="utf-8"))
        return d.get("disc_id") == disc_id and time.time() < float(d.get("until", 0))
    except (OSError, ValueError, TypeError):
        return False


def burner_mode(w=None) -> bool:
    """True while the Steam Shelf window is open. w: shelf.win32 / shelf.linux (or a fake)."""
    if w is None:
        from shelf import host
        return host.burner_mode_on()
    fn = getattr(w, "burner_mode_on", None)
    return bool(fn and fn())
