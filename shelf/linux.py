"""
The Linux side of Steam Shelf, standard library only (no udev or D-Bus packages):
CD/DVD drives, whether a disc is in one, a watcher that turns "disc in" / "disc
out" into the same events the Windows agent gets, uptime and wake-ups, the
single-instance and burner-mode locks, and stopping the agent.

Drives are /dev/sr0, /dev/sr1… (SATA, IDE and USB drives alike). Whether a disc
is in is asked with the CDROM_DRIVE_STATUS ioctl on a non-blocking open, which
neither spins the disc up nor closes an open tray. The disc is then read raw by
shelf.disc's ISO 9660 reader, so it does not matter whether the desktop mounts
discs or not. Both need the drive's permissions: on a normal desktop login
systemd-logind gives them to the active user ("uaccess"); otherwise the user
must be in the "cdrom" group ("optical" on Arch).

The kernel announces media changes as uevents (netlink) when in-kernel polling
is on, which systemd enables (block.events_dfl_poll_msecs = 2000). The watcher
listens to them, re-checks quickly while a disc spins up, and falls back to
polling every 2 s where uevents are not available (sandboxes, other inits).

Imported only on Linux.
"""
from __future__ import annotations

import fcntl
import logging
import os
import re
import select
import signal
import socket
import time
from pathlib import Path
from typing import Callable, Optional

import config

log = logging.getLogger("shelf.agent")

CDROM_DRIVE_STATUS = 0x5326
CDSL_CURRENT = 0x7FFFFFFF
CDS_NO_INFO, CDS_NO_DISC, CDS_TRAY_OPEN, CDS_DRIVE_NOT_READY, CDS_DISC_OK = 0, 1, 2, 3, 4
NETLINK_KOBJECT_UEVENT = 15
SYS_BLOCK = Path("/sys/block")
DEV = Path("/dev")
DFL_POLL = Path("/sys/module/block/parameters/events_dfl_poll_msecs")
RUN = config.DATA_DIR / "run"
# s a new agent waits for the lock: the agent of a session that just ended leaves within seconds
TAKEOVER_WAIT = float(os.environ.get("STEAMSHELF_TAKEOVER_WAIT") or 30)


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


# ── drives ────────────────────────────────────────────────────────────────────

def optical_drives() -> list[str]:
    """['/dev/sr0', …] — every CD/DVD/BD drive the kernel knows, internal or USB."""
    out = []
    try:
        for p in sorted(SYS_BLOCK.glob("sr[0-9]*"), key=lambda x: int(x.name[2:]) if x.name[2:].isdigit() else 0):
            dev = DEV / p.name
            if dev.exists():
                out.append(str(dev))
    except OSError:
        pass
    return out


def drive_label(dev: str) -> str:
    """'HL-DT-ST DVDRAM GP65NB60' (vendor + model from sysfs), or 'sr0'."""
    name = os.path.basename(dev)
    parts = [_read(SYS_BLOCK / name / "device" / f) for f in ("vendor", "model")]
    label = " ".join(p for p in parts if p)
    return label or name


def drive_status(dev: str) -> Optional[int]:
    """CDS_* of the drive, or None when this user may not open it."""
    try:
        fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    except PermissionError:
        return None
    except OSError:
        return CDS_NO_INFO
    try:
        return fcntl.ioctl(fd, CDROM_DRIVE_STATUS, CDSL_CURRENT)
    except OSError:
        return CDS_NO_INFO
    finally:
        os.close(fd)


def has_media(dev: str) -> Optional[bool]:
    st = drive_status(dev)
    if st is None:
        return None
    if st == CDS_DISC_OK:
        return True
    if st == CDS_NO_INFO:                       # drive does not answer the ioctl: the kernel's size
        try:
            return int(_read(SYS_BLOCK / os.path.basename(dev) / "size") or 0) > 0
        except ValueError:
            return False
    return False


def drives_with_media() -> set[str]:
    return {d for d in optical_drives() if has_media(d)}


def drive_name(dev: str) -> str:
    """'sr0': how the window and the card name a drive."""
    return os.path.basename(dev)


def access_problem() -> bool:
    """A drive is there but this user may not read it (not at the seat, not in 'cdrom').
    access() honours the ACL logind gives the user at the seat, and touches no drive."""
    return any(not os.access(d, os.R_OK) for d in optical_drives())


def volume_info(dev: str) -> Optional[tuple[str, int]]:
    """Something when the drive holds a disc and is ready (the Windows agent asks the same).
    The agent stops waiting for a tag once a ready disc turns out to have none (a music CD)."""
    return ("", 0) if drive_status(dev) == CDS_DISC_OK else None


def uptime() -> float:
    return time.clock_gettime(time.CLOCK_BOOTTIME)


def session_alive(env=None) -> bool:
    """False once the desktop session the agent started in is over: its Wayland socket or
    local X server is gone. Some setups leave a session's processes running after you log
    out; the agent must not linger there (it would hold the lock the next login needs)."""
    env = os.environ if env is None else env
    wl, rt = env.get("WAYLAND_DISPLAY", ""), env.get("XDG_RUNTIME_DIR", "")
    if wl and (wl.startswith("/") or rt):
        return (Path(wl) if wl.startswith("/") else Path(rt) / wl).exists()
    m = re.match(r"^(?:unix)?:(\d+)(?:\.\d+)?$", env.get("DISPLAY", ""))
    if m:
        return Path(f"/tmp/.X11-unix/X{m.group(1)}").exists()
    return True                                 # a console, SSH, a remote X: nothing to watch


def quiet_errors() -> None:
    pass


# ── locks: one agent, burner mode ─────────────────────────────────────────────
# flock() on a file in DATA_DIR/run: the kernel drops it when the process ends,
# however it ends, so neither can stay stuck.

def _lock_path(name: str) -> Path:
    RUN.mkdir(parents=True, exist_ok=True)
    return RUN / f"{name}.lock"


def _take(name: str) -> Optional[int]:
    fd = os.open(_lock_path(name), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def _held(name: str) -> bool:
    try:
        fd = os.open(_lock_path(name), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except OSError:
        return True
    finally:
        os.close(fd)


def single_instance() -> Optional[int]:
    """The lock's fd if we are the only agent (keep it open), None if one already runs."""
    fd = _take("agent")
    if fd is not None:
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
    return fd


def agent_running() -> bool:
    return _held("agent")


def stop_agent() -> bool:
    if not agent_running():
        return False
    try:
        pid = int(_lock_path("agent").read_text().strip() or 0)
    except (OSError, ValueError):
        return False
    if pid <= 1:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except OSError:
        return False


def hold_burner_mode() -> Optional[int]:
    """The app window takes this once and keeps it: burner mode until the process ends."""
    return _take("burner")


def burner_mode_on() -> bool:
    return _held("burner")


# ── kernel uevents ────────────────────────────────────────────────────────────

def open_uevents() -> Optional[socket.socket]:
    """A netlink socket receiving the kernel's device events (no privileges needed)."""
    try:
        s = socket.socket(socket.AF_NETLINK, socket.SOCK_DGRAM, NETLINK_KOBJECT_UEVENT)
        s.bind((0, 1))
        s.setblocking(False)
        return s
    except (OSError, AttributeError, ValueError):
        return None


def parse_uevent(data: bytes) -> dict[str, str]:
    fields = data.split(b"\0")
    ev: dict[str, str] = {}
    if fields and b"@" in fields[0]:
        action, _, path = fields[0].decode("utf-8", "replace").partition("@")
        ev["ACTION"], ev["DEVPATH"] = action, path
    for f in fields[1:]:
        k, sep, v = f.decode("utf-8", "replace").partition("=")
        if sep:
            ev[k] = v
    return ev


def is_optical_event(ev: dict[str, str]) -> bool:
    if ev.get("SUBSYSTEM") != "block":
        return False
    name = os.path.basename(ev.get("DEVNAME", "") or ev.get("DEVPATH", ""))
    return name.startswith("sr")


def kernel_reports_media(dev: str) -> bool:
    """Whether the kernel will send a uevent when a disc goes in or out of this drive."""
    base = SYS_BLOCK / os.path.basename(dev)
    if "media_change" in _read(base / "events_async"):
        return True
    if "media_change" not in _read(base / "events"):
        return False
    try:
        poll = int(_read(base / "events_poll_msecs") or -1)
        if poll == -1:
            poll = int(_read(DFL_POLL) or 0)
    except ValueError:
        return False
    return poll > 0


# ── the watcher ───────────────────────────────────────────────────────────────

class DriveWatcher:
    """
    Calls on_volume("arrival"/"removal", [dev], True) when a disc goes in or out of a
    drive (or a drive holding one is plugged in / unplugged), and on_power("resume")
    after the PC slept: CLOCK_BOOTTIME keeps counting through suspend and
    CLOCK_MONOTONIC does not, so a jump between them is a wake-up.

    While paused() (burner mode: the window is open, maybe burning) the drives are not
    touched at all; afterwards the watcher takes them as they are, without events, the
    way Windows' events during burner mode are ignored.
    run() blocks until SIGTERM / SIGINT (or stop()).
    """
    FAST = 1.0          # s between checks while a disc may be spinning up
    POLL = 2.0          # s between checks when the kernel does not announce media changes
    SAFETY = 15.0       # s between checks when it does (a missed event, an odd drive)
    SETTLE = 20.0       # s of fast checks after an event or a wake-up
    RESUME_JUMP = 5.0   # s of sleep that count as a wake-up
    ALIVE = 5.0         # s between checks that the desktop session is still there

    def __init__(self, on_volume: Callable[[str, list[str], bool], None], on_power: Callable[[str], None],
                 drives: Callable[[], list[str]] = optical_drives,
                 media: Callable[[str], Optional[bool]] = has_media,
                 clock: Callable[[], float] = time.monotonic, boottime: Callable[[], float] = uptime,
                 uevents: Callable[[], Optional[socket.socket]] = open_uevents,
                 paused: Callable[[], bool] = lambda: False,
                 announces: Callable[[str], bool] = kernel_reports_media,
                 alive: Callable[[], bool] = lambda: True):
        self.on_volume, self.on_power = on_volume, on_power
        self.drives, self.media, self.clock, self.boottime, self.uevents = drives, media, clock, boottime, uevents
        self.paused, self.announces, self.alive = paused, announces, alive
        self.state: dict[str, bool] = {}
        self.rebaseline()
        self._gap = boottime() - clock()
        self.settle_until = 0.0
        self._stop = False
        self._was_paused = False
        self._sock: Optional[socket.socket] = None
        self.events_ok = False

    def rebaseline(self) -> None:
        """Take the drives as they are now, without events."""
        self.state = {d: bool(self.media(d)) for d in self.drives()}

    def check(self) -> None:
        current = self.drives()
        for d in current:
            now_in = bool(self.media(d))
            was_in = self.state.get(d, False)
            if now_in and not was_in:
                self.on_volume("arrival", [d], True)
            elif was_in and not now_in:
                self.on_volume("removal", [d], True)
            self.state[d] = now_in
        for d in [d for d in self.state if d not in current]:
            if self.state.pop(d):
                self.on_volume("removal", [d], True)

    def check_resume(self) -> bool:
        gap = self.boottime() - self.clock()
        woke = gap - self._gap > self.RESUME_JUMP
        self._gap = gap
        if woke:
            self.on_power("resume")
            self.settle_until = self.clock() + self.SETTLE
        return woke

    def stop(self, *_a) -> None:
        self._stop = True

    def tick(self, woke: bool, due: bool) -> bool:
        """One round after waiting (at least once a second). True when the drives' timer restarts."""
        self.check_resume()
        if self.paused():                           # a cheap lock probe, so burner mode ends within a second
            self._was_paused = True
            return woke or due
        if self._was_paused:
            self._was_paused = False
            self.rebaseline()
            return True
        if not (woke or due):
            return False
        known = set(self.state)
        self.check()
        if set(self.state) != known:                # a drive came or went: does it announce discs?
            self._events(self._sock is not None)
        return True

    def _events(self, have_socket: bool) -> None:
        self.events_ok = have_socket and all(self.announces(d) for d in self.drives())

    def run(self) -> None:
        sock = self._sock = self.uevents()
        self._events(sock is not None)
        log.info("drive watcher: %s", "kernel events" if self.events_ok else
                 ("kernel events + polling" if sock else "polling"))
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, self.stop)
            except (ValueError, OSError):         # not the main thread (tests)
                pass
        last = checked_alive = self.clock()
        try:
            while not self._stop:
                now = self.clock()
                if now - checked_alive >= self.ALIVE:
                    checked_alive = now
                    if not self.alive():
                        log.info("the desktop session ended: agent leaving")
                        break
                interval = self.FAST if now < self.settle_until else (self.SAFETY if self.events_ok else self.POLL)
                timeout = max(0.05, min(1.0, last + interval - now))
                woke = False
                if sock is not None:
                    try:
                        ready, _, _ = select.select([sock], [], [], timeout)
                    except InterruptedError:
                        ready = []
                    while ready:
                        try:
                            data = sock.recv(65536)
                        except OSError:            # drained (EAGAIN), or the buffer overflowed: SAFETY covers it
                            break
                        if is_optical_event(parse_uevent(data)):
                            woke = True
                    if woke:
                        self.settle_until = self.clock() + self.SETTLE
                else:
                    time.sleep(timeout)
                if self.tick(woke, self.clock() - last >= interval):
                    last = self.clock()
        finally:
            if sock is not None:
                sock.close()


def watch(on_volume: Callable[[str, list[str], bool], None], on_power: Callable[[str], None]) -> None:
    """The agent's main loop on Linux: blocks until SIGTERM / SIGINT, or until the session ends."""
    DriveWatcher(on_volume, on_power, paused=burner_mode_on, alive=session_alive).run()
