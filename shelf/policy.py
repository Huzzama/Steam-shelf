"""
When a disc in the drive should start a game. Pure logic, no system calls,
so every rule is unit-tested (tests/test_policy.py).

The problem it solves: the PC loses power with a disc inside, comes back,
and the first thing it does is launch a game. So a game only starts when a
disc is *inserted* while the PC is already up:

  1. Discs that are in a drive when the agent starts are "present", not inserted.
     They stay ignored until that drive is emptied and a disc goes in again.
  2. Right after the agent starts (login) and right after the PC wakes from
     sleep, drives re-announce their discs. Arrivals in that window are
     treated like rule 1.
  3. If the PC itself booted only moments ago, the window is longer: slow
     drives can take a while to report a disc that was there all along.
  4. The same disc twice within `debounce` seconds starts the game once.

Discs ignored by rules 1-3 can still be offered ("Days Gone is in the drive,
Play?") instead of being silent; that is the `startup_disc` setting.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Verdict(str, Enum):
    LAUNCH = "launch"      # inserted while running: go (with the countdown card)
    PRESENT = "present"    # was there at startup / wake: do not auto-launch
    IGNORE = "ignore"      # duplicate, or the drive is not one we watch


@dataclass
class LaunchPolicy:
    boot_grace: float = 45.0        # s after the agent starts
    resume_grace: float = 25.0      # s after the PC wakes up
    uptime_grace: float = 150.0     # if the PC booted less than this before the agent, wait until then
    debounce: float = 20.0          # same disc again within this: ignore
    present: set = field(default_factory=set)       # drives holding a disc we must not auto-launch
    quiet_until: float = 0.0
    _last: dict = field(default_factory=dict)       # disc_id -> time it last launched

    def start(self, now: float, uptime: float, drives_with_media: set) -> None:
        self.present = {d.upper() for d in drives_with_media}
        boot_left = max(0.0, self.uptime_grace - uptime)
        self.quiet_until = now + max(self.boot_grace, boot_left)

    def on_resume(self, now: float) -> None:
        self.quiet_until = max(self.quiet_until, now + self.resume_grace)

    def on_removed(self, drive: str) -> None:
        self.present.discard(drive.upper())

    def on_arrival(self, drive: str, now: float) -> Verdict:
        d = drive.upper()
        if d in self.present:
            return Verdict.PRESENT
        if now < self.quiet_until:
            self.present.add(d)                  # needs a real re-insert to auto-launch
            return Verdict.PRESENT
        return Verdict.LAUNCH

    def should_launch(self, disc_id: str, now: float) -> bool:
        """Second gate, once the disc is read: the debounce."""
        last = self._last.get(disc_id)
        if last is not None and now - last < self.debounce:
            return False
        self._last[disc_id] = now
        return True
