"""The agent's flow with a fake Windows layer: what gets launched, what only gets offered."""
import pytest

from shelf import agent as agent_mod, launch, settings, sources
from shelf.disc import DiscTag
from shelf.policy import Verdict


class FakeWin:
    def __init__(self, drives, media):
        self.drives, self.media = drives, media
    def optical_drives(self): return list(self.drives)
    def drives_with_media(self): return set(self.media)
    def uptime(self): return 10_000.0
    def volume_info(self, d): return ("X", 1) if d in self.media else None


@pytest.fixture
def world(tmp_path, monkeypatch):
    roots = {}
    def mkdisc(drive, tag):
        r = tmp_path / drive.strip(":")
        (r / "STEAMSHELF").mkdir(parents=True)
        (r / "STEAMSHELF" / "DISC.JSON").write_text(tag.to_json(), encoding="utf-8")
        roots[drive] = r
    monkeypatch.setattr(sources, "drive_root", lambda d: roots.get(d, tmp_path / "empty"))
    calls = []
    monkeypatch.setattr(launch, "spawn", lambda *a: calls.append(("spawn",) + a))
    monkeypatch.setattr(launch, "run", lambda tag, prefs=None: calls.append(("run", tag.game_id)))
    s = settings.load(); s.update(countdown=5, startup_disc="ask", enabled=True); settings.save(s)
    return mkdisc, calls


def test_insert_shows_countdown_card(world):
    mkdisc, calls = world
    a = agent_mod.Agent(FakeWin(["D:"], []))
    a.start()
    a.policy.quiet_until = 0
    mkdisc("D:", DiscTag("steam", "1259420", "Days Gone"))
    a.handle("D:", a.policy.on_arrival("D:", 100.0))
    assert calls == [("spawn", "--prompt", "D:", "--mode", "auto")]


def test_disc_present_at_startup_is_only_offered(world):
    mkdisc, calls = world
    mkdisc("D:", DiscTag("steam", "1259420", "Days Gone"))
    a = agent_mod.Agent(FakeWin(["D:"], ["D:"]))
    a.start()
    v = a.policy.on_arrival("D:", 1000.0)
    assert v is Verdict.PRESENT
    a.handle("D:", v)
    assert calls == [("spawn", "--prompt", "D:", "--mode", "ask")]


def test_countdown_zero_launches_directly_and_debounces(world):
    mkdisc, calls = world
    s = settings.load(); s["countdown"] = 0; settings.save(s)
    mkdisc("E:", DiscTag("steam", "1593500", "God of War"))
    a = agent_mod.Agent(FakeWin(["E:"], []))
    a.start(); a.policy.quiet_until = 0
    a.handle("E:", Verdict.LAUNCH)
    a.handle("E:", Verdict.LAUNCH)
    assert calls == [("run", "1593500")]


def test_other_discs_and_bad_tags_do_nothing(world, tmp_path, monkeypatch):
    mkdisc, calls = world
    a = agent_mod.Agent(FakeWin(["F:", "G:"], ["F:"]))
    a.start(); a.policy.quiet_until = 0
    a.handle("F:", Verdict.LAUNCH)                      # readable disc without a tag (a music CD)
    bad = tmp_path / "G"; (bad / "STEAMSHELF").mkdir(parents=True)
    (bad / "STEAMSHELF" / "DISC.JSON").write_text(
        '{"format":"steam-shelf-disc","version":1,"store":"steam","game_id":"1;calc"}')
    monkeypatch.setattr(sources, "drive_root", lambda d: bad)
    a.handle("G:", Verdict.LAUNCH)                      # a Shelf disc with a forged id
    assert calls == []
