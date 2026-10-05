"""
The virtual drive: how "Test with a virtual disc" works on any PC. The app puts
the disc image in DATA_DIR/virtual-drive/disc.iso (that is "inserting" it) and
deletes it ("ejecting" it); the agent watches that folder like one more drive
and handles the disc exactly as if it had gone into a real CD/DVD drive: same
rules, same countdown card, same launch.

It replaces mounting the image with Windows (Mount-DiskImage), which some PCs
refuse, and on Linux would need root or polkit. The real drives are tested
with real discs.
"""
from __future__ import annotations

import logging
import os
import shutil
import threading
from pathlib import Path
from typing import Callable, Optional

import config

VIRTUAL = "VIRTUAL"                  # the drive name the agent and the policy see
DIR = config.DATA_DIR / "virtual-drive"
IMAGE = DIR / "disc.iso"

log = logging.getLogger("shelf.virtual")


def insert(iso: Path) -> None:
    """Put an image in the virtual drive (replacing whatever was in it)."""
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = IMAGE.with_suffix(".tmp")
    shutil.copyfile(iso, tmp)
    os.replace(tmp, IMAGE)           # atomic: the agent never sees half an image


def eject() -> bool:
    try:
        IMAGE.unlink()
        return True
    except OSError:
        return False


def inserted() -> bool:
    return IMAGE.is_file()


def _signature() -> Optional[tuple[int, int]]:
    try:
        st = IMAGE.stat()
        return st.st_mtime_ns, st.st_size
    except OSError:
        return None


class Watcher(threading.Thread):
    """Calls on_volume("arrival"/"removal", [VIRTUAL], True) when an image appears,
    disappears or is replaced. A stat() every `interval` seconds: no cost.
    fire_existing: an image already in the drive counts as just inserted (a test the
    app started while the agent was still starting up)."""

    def __init__(self, on_volume: Callable[[str, list[str], bool], None], interval: float = 0.75,
                 fire_existing: bool = False):
        super().__init__(name="virtual-drive", daemon=True)
        self.on_volume, self.interval = on_volume, interval
        self.last = None if fire_existing else _signature()
        self._stop = threading.Event()

    def check(self) -> None:
        now = _signature()
        if now == self.last:
            return
        if self.last is not None:
            self.on_volume("removal", [VIRTUAL], True)
        if now is not None:
            self.on_volume("arrival", [VIRTUAL], True)
        self.last = now

    def run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.check()
            except Exception:       # noqa: BLE001 — the watcher must outlive any one bad check
                log.exception("virtual drive")

    def stop(self) -> None:
        self._stop.set()
