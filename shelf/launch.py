"""
What happens to a disc once it is accepted: launch the game if it is
installed, otherwise open its store page (or the install dialog). Also how
this program starts its other modes (agent, prompt card) as new processes.

Everything goes through Steam's own URIs (steam://rungameid/…): on Windows the
shell opens them, on Linux xdg-open hands them to whichever Steam is installed
(native, Flatpak or Snap all register the steam:// handler).
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path

import config
from shelf import collection, settings
from shelf.disc import DiscTag
from shelf.stores import store_for

log = logging.getLogger("shelf.launch")


@dataclass
class Action:
    kind: str        # "play" | "store" | "install" | "running" | "missing"
    uri: str
    fallback: str = ""   # web page if the client URI cannot be opened


def plan(tag: DiscTag, prefs: dict | None = None) -> Action:
    prefs = prefs or settings.load()
    st = store_for(tag.store)
    if st.is_running(tag.game_id):
        return Action("running", "")
    if st.available() and st.is_installed(tag.game_id):
        return Action("play", st.launch_uri(tag.game_id))
    if tag.store == "nonsteam":                      # ids differ between PCs: try the title
        sc = st.find(tag.game_id, tag.title) if st.available() else None
        if sc:
            return Action("play", st.launch_uri(sc.app_id))
        return Action("missing", "")                 # no store page to open for your own game
    if st.available() and prefs.get("not_installed") == "install" and hasattr(st, "install_uri"):
        return Action("install", st.install_uri(tag.game_id), st.web_page(tag.game_id, tag.title))
    web = st.web_page(tag.game_id, tag.title)
    if st.available() and st.page_uri(tag.game_id):
        return Action("store", st.page_uri(tag.game_id), web)
    return Action("store", web)                      # no client (or no in-client page): the website


OPEN_WAIT = 5.0     # s to see whether xdg-open found a handler (it may keep running: Steam starting)


def _posix_open(uri: str) -> bool:
    """xdg-open (or gio) with the URI. They exit non-zero at once when nothing handles it;
    still running after OPEN_WAIT means the handler (Steam) took it."""
    for cmd in (["xdg-open", uri], ["gio", "open", uri]):
        try:
            p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            continue                                   # not installed: try the next one
        try:
            if p.wait(timeout=OPEN_WAIT) == 0:
                return True
        except subprocess.TimeoutExpired:
            return True
        log.warning("%s could not open %s (exit %s)", cmd[0], uri, p.returncode)
        return False
    log.warning("no xdg-open or gio to open %s", uri)
    return False


def open_uri(uri: str) -> bool:
    try:
        if sys.platform == "win32":
            os.startfile(uri)                          # noqa: S606 — a URI we built from a validated id
            return True
        if sys.platform == "darwin":
            subprocess.Popen(["open", uri])
            return True
        return _posix_open(uri)
    except OSError as e:
        log.warning("could not open %s: %s", uri, e)
        return False


def run(tag: DiscTag, prefs: dict | None = None) -> Action:
    a = plan(tag, prefs)
    log.info("%s -> %s %s", tag.key, a.kind, a.uri)
    if a.kind in ("running", "missing"):
        return a
    if not open_uri(a.uri) and a.fallback:
        webbrowser.open(a.fallback)
    if a.kind == "play":
        from datetime import datetime, timezone
        try:
            collection.mark(tag.disc_id, last_played=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        except OSError:
            pass
    return a


# ── our own processes ─────────────────────────────────────────────────────────

def self_command(*args: str, windowless: bool = True) -> list[str]:
    """How to start this program again with other arguments (AppImage, frozen exe or source)."""
    appimage = os.environ.get("APPIMAGE")              # the .AppImage file itself, not its temporary mount
    if appimage and sys.platform.startswith("linux") and Path(appimage).is_file():
        return [appimage, *args]
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    exe = Path(sys.executable)
    if windowless and sys.platform == "win32":
        pyw = exe.with_name("pythonw.exe")
        if pyw.exists():
            exe = pyw
    return [str(exe), str(Path(config.__file__).resolve().parent / "main.py"), *args]


def spawn(*args: str) -> None:
    """Start another mode of this program, detached: it outlives whoever started it."""
    if sys.platform == "win32":
        flags = 0x00000008 | 0x00000200 | 0x08000000   # DETACHED_PROCESS | NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        subprocess.Popen(self_command(*args), close_fds=True, creationflags=flags,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    subprocess.Popen(self_command(*args), close_fds=True, start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
