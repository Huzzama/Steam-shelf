"""
shelf-agent: the background process that starts when you log in (Windows or
Linux) and watches the CD/DVD drives, plus the virtual drive "Test" uses. No Qt
here (a few MB of RAM, no CPU while idle); when something has to be shown it
starts this program again in prompt mode.

    python main.py --agent        (SteamShelf.exe --agent when packaged)

Log: DATA_DIR/agent.log
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from logging.handlers import RotatingFileHandler

import config
from shelf import collection, host, launch, modes, settings, sources, virtual
from shelf.disc import TagError
from shelf.policy import LaunchPolicy, Verdict

log = logging.getLogger("shelf.agent")


def setup_logging() -> None:
    h = RotatingFileHandler(config.AGENT_LOG, maxBytes=256 * 1024, backupCount=1, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(h)
    if sys.stderr is not None and sys.stderr.isatty():      # run from a terminal: show it live too
        c = logging.StreamHandler()
        c.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
        root.addHandler(c)
    root.setLevel(logging.INFO)


def wait_for_tag(drive: str, volume_info, tries: int = 24, delay: float = 0.75):
    """Drives take a moment to spin up after the arrival event. Returns the tag or None."""
    for i in range(tries):
        tag, readable = sources.read(drive, volume_info)   # TagError propagates: a Shelf disc, but a bad one
        if tag:
            return tag
        if readable and i >= 3:
            return None               # a disc without a tag: some other disc
        time.sleep(delay)
    return None


class Agent:
    def __init__(self, w):
        self.w = w                    # shelf.win32 / shelf.linux (or a fake in the tests)
        self.policy = LaunchPolicy()
        self.lock = threading.Lock()

    def start(self) -> bool:
        """Takes stock of the drives. True when the virtual drive already holds a test the
        app started while this agent was starting up: that one must still go off."""
        present = set(self.w.drives_with_media())
        pending = self.pending_test()
        if virtual.inserted() and not pending:
            present.add(virtual.VIRTUAL)
        with self.lock:
            self.policy.start(time.monotonic(), self.w.uptime(), present)
        log.info("agent %s up, uptime %.0fs, optical drives %s, with a disc %s%s",
                 config.VERSION, self.w.uptime(), self.w.optical_drives(), sorted(present),
                 ", a test disc waiting" if pending else "")
        return pending

    @staticmethod
    def pending_test() -> bool:
        if not virtual.inserted():
            return False
        try:
            tag, _ = sources.read(virtual.VIRTUAL)
        except TagError:
            return False
        return tag is not None and modes.test_allowed(tag.disc_id)

    def on_volume(self, kind: str, drives: list[str], is_media: bool) -> None:
        now = time.monotonic()
        for d in drives:
            if kind == "removal":
                with self.lock:
                    self.policy.on_removed(d)
                log.info("%s emptied", d)
                continue
            test = d == virtual.VIRTUAL
            if not test and d not in self.w.optical_drives():
                continue                              # a USB stick, not our business
            with self.lock:
                # a test from the app is a disc going in, whatever the start-up rules say
                verdict = Verdict.LAUNCH if test else self.policy.on_arrival(d, now)
            log.info("%s disc in (media=%s) -> %s", d, is_media, verdict.value)
            threading.Thread(target=self.handle, args=(d, verdict), daemon=True).start()

    def on_power(self, event: str) -> None:
        log.info("power: %s", event)
        if event == "resume":
            with self.lock:
                self.policy.on_resume(time.monotonic())

    def handle(self, drive: str, verdict: Verdict) -> None:
        test = drive == virtual.VIRTUAL
        try:
            prefs = settings.load()
            if not test and not prefs["enabled"]:
                return
            if not test and modes.burner_mode(self.w):
                log.info("%s: burner mode (Steam Shelf is open): disc left alone", drive)
                return
            try:
                tag = wait_for_tag(drive, self.w.volume_info)
            except TagError as e:
                log.warning("%s: rejected disc: %s", drive, e)
                return
            if not tag:
                return
            if test and not modes.test_allowed(tag.disc_id):
                log.info("virtual drive: %s is not a test started from the app: left alone", tag.title)
                return
            burned = tag
            tag = collection.resolve(tag)
            log.info("%s: %s (%s)%s", drive, tag.title, tag.key,
                     f", disc says {burned.key}" if burned.key != tag.key else "")
            if verdict is Verdict.PRESENT:
                if prefs["startup_disc"] == "ask":
                    launch.spawn("--prompt", drive, "--mode", "ask")
                return
            if not test:                     # a test may run again and again
                with self.lock:
                    go = self.policy.should_launch(tag.disc_id, time.monotonic())
                if not go:
                    log.info("%s: same disc again, ignored", drive)
                    return
            if prefs["countdown"] > 0:
                launch.spawn("--prompt", drive, "--mode", "auto")
            else:
                launch.run(tag, prefs)
        except Exception:
            log.exception("%s: handling the disc failed", drive)


def main() -> int:
    setup_logging()
    w = host.impl()
    if w is None:
        log.error("discs are watched on Windows and Linux only")
        print("Steam Shelf agent: discs work on Windows and Linux.", file=sys.stderr)
        return 2
    w.quiet_errors()
    lock = w.single_instance()          # held (a local) until main() returns
    wait = getattr(w, "TAKEOVER_WAIT", 0.0)
    while lock is None and wait > 0:    # Linux: maybe the agent of a session that just ended, leaving
        time.sleep(2.0)
        wait -= 2.0
        lock = w.single_instance()
    if lock is None:
        log.info("another agent is already running")
        return 0
    agent = Agent(w)
    pending = agent.start()
    vdrive = virtual.Watcher(agent.on_volume, fire_existing=pending)
    vdrive.start()
    try:
        w.watch(agent.on_volume, agent.on_power)       # blocks until stopped
    finally:
        vdrive.stop()
    log.info("agent stopped")
    return 0
