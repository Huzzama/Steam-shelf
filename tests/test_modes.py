"""Burner mode, ownership, history and SteamGridDB parsing."""
import config
from shelf import agent as agent_mod, artwork, collection, history, library, modes, virtual
from shelf.collection import ShelfEntry
from shelf.disc import DiscTag, build_iso
from shelf.policy import Verdict
from tests.test_agent import FakeWin, world  # noqa: F401 — fixture


class BurnerWin(FakeWin):
    def __init__(self, *a, burner=True):
        super().__init__(*a)
        self.burner = burner
    def burner_mode_on(self): return self.burner


def test_burner_mode_leaves_discs_alone(world):  # noqa: F811
    mkdisc, calls = world
    try:
        (config.DATA_DIR / "test_allow.json").unlink()
    except OSError:
        pass
    a = agent_mod.Agent(BurnerWin(["D:"], []))
    a.start(); a.policy.quiet_until = 0
    tag = DiscTag("steam", "1259420", "Days Gone")
    mkdisc("D:", tag)
    a.handle("D:", a.policy.on_arrival("D:", 100.0))
    assert calls == []


def test_burner_mode_lets_the_test_disc_through(world, tmp_path):  # noqa: F811
    mkdisc, calls = world
    a = agent_mod.Agent(BurnerWin(["D:"], []))
    a.start()                                     # just started: the quiet period is on, a test ignores it
    tag = DiscTag("steam", "1259420", "Days Gone")
    modes.allow_test(tag.disc_id)
    virtual.insert(build_iso(tag, tmp_path / "t.iso"))
    try:
        a.handle(virtual.VIRTUAL, Verdict.LAUNCH)
        a.handle(virtual.VIRTUAL, Verdict.LAUNCH)          # a test can run again right away
        assert calls == [("spawn", "--prompt", "VIRTUAL", "--mode", "auto")] * 2
        modes.allow_test(tag.disc_id, seconds=-1)
        assert not modes.test_allowed(tag.disc_id)
        a.handle(virtual.VIRTUAL, Verdict.LAUNCH)          # no allowance: an image left in the drive
        assert len(calls) == 2
    finally:
        virtual.eject()


def test_virtual_arrival_skips_the_startup_rules(world, tmp_path, monkeypatch):  # noqa: F811
    _mkdisc, _calls = world
    seen = []
    monkeypatch.setattr(agent_mod.threading, "Thread",
                        lambda target, args, daemon: type("T", (), {"start": lambda self: seen.append(args)})())
    a = agent_mod.Agent(BurnerWin(["D:"], []))
    a.start()
    a.on_volume("arrival", ["D:"], True)
    a.on_volume("arrival", [virtual.VIRTUAL], True)
    a.on_volume("arrival", ["Z:"], True)                   # not an optical drive
    assert seen == [("D:", Verdict.PRESENT), (virtual.VIRTUAL, Verdict.LAUNCH)]


def test_pending_test_goes_off_when_the_agent_starts(world, tmp_path):  # noqa: F811
    _mkdisc, _calls = world
    tag = DiscTag("steam", "1593500", "God of War")
    virtual.insert(build_iso(tag, tmp_path / "g.iso"))
    try:
        a = agent_mod.Agent(BurnerWin([], []))
        assert a.start() is False and "VIRTUAL" in a.policy.present      # leftover image: present, quiet
        modes.allow_test(tag.disc_id)
        a = agent_mod.Agent(BurnerWin([], []))
        assert a.start() is True                                          # the app's test: fire it
        fired = []
        w = virtual.Watcher(lambda *ev: fired.append(ev), fire_existing=True)
        w.check()
        w.check()
        assert fired == [("arrival", ["VIRTUAL"], True)]
    finally:
        virtual.eject()
        modes.allow_test(tag.disc_id, seconds=-1)


def test_burner_mode_does_not_even_read_real_discs(world, monkeypatch):  # noqa: F811
    mkdisc, calls = world
    mkdisc("D:", DiscTag("steam", "1259420", "Days Gone"))
    reads = []
    monkeypatch.setattr(agent_mod, "wait_for_tag", lambda *a, **k: reads.append(a))
    a = agent_mod.Agent(BurnerWin(["D:"], []))
    a.start(); a.policy.quiet_until = 0
    a.handle("D:", Verdict.LAUNCH)
    assert reads == [] and calls == []


def test_game_mode_when_window_closed(world):  # noqa: F811
    mkdisc, calls = world
    a = agent_mod.Agent(BurnerWin(["D:"], [], burner=False))
    a.start(); a.policy.quiet_until = 0
    mkdisc("D:", DiscTag("steam", "1259420", "Days Gone"))
    a.handle("D:", a.policy.on_arrival("D:", 100.0))
    assert calls and calls[0][0] == "spawn"


def test_history_survives_reassign_and_remove():
    for f in (config.SHELF_FILE, history._FILE):
        try:
            f.unlink()
        except OSError:
            pass
    tag = DiscTag("steam", "1593500", "God of War")
    collection.upsert(ShelfEntry.from_tag(tag))
    assert history.keys() == set()                       # only an image: not in the history yet
    collection.mark(tag.disc_id, burned=True)
    collection.reassign(tag.disc_id, "steam", "1262350", "SIGNALIS")
    collection.remove(tag.disc_id)
    assert history.keys() == {("steam", "1593500")}
    assert history.record("steam", "1593500", "God of War") is False
    g = {x.game_id: x for x in library.build([{"appid": "1593500", "name": "God of War"}], [], [], history.keys())}
    assert g["1593500"].status == "was" and library.matches(g["1593500"], "", "not_on_disc")


def test_only_own_games_are_burnable():
    games = {g.game_id: g for g in library.build(
        [{"appid": "1", "name": "Owned"}], [], [ShelfEntry("d", "steam", "9", "Friend's disc", "x")])}
    assert games["1"].burnable and not games["9"].burnable


def test_sgdb_grids_are_filtered_and_sorted():
    cdn = "https://cdn2.steamgriddb.com/grid/"
    data = {"success": True, "data": [
        {"id": 1, "score": 2, "url": cdn + "a.png", "thumb": cdn + "t_a.png", "width": 600, "height": 900,
         "author": {"name": "artist1"}},
        {"id": 2, "score": 9, "url": cdn + "b.jpg", "thumb": cdn + "t_b.jpg", "width": 600, "height": 900,
         "author": {"name": "artist2"}},
        {"id": 3, "score": 99, "url": cdn + "c.png", "thumb": cdn + "t_c.png", "nsfw": True},
        {"id": 4, "score": 99, "url": cdn + "d.png", "thumb": cdn + "t_d.png", "humor": True},
        {"id": 5, "score": 99, "url": "https://evil.example/x.png", "thumb": cdn + "t.png"},
        {"id": 6, "score": 99, "url": cdn + "wide.png", "thumb": cdn + "t.png", "width": 920, "height": 430},
        {"id": 7, "score": 99, "url": cdn + "anim.webm", "thumb": cdn + "t.png"},
    ]}
    got = artwork.parse_grids(data)
    assert [g["id"] for g in got] == [2, 1] and got[0]["author"] == "artist2"


def test_sgdb_key_checks_format(monkeypatch):
    import pytest
    with pytest.raises(artwork.ArtworkError):
        artwork.set_key("nope")
    monkeypatch.setattr(artwork, "_api", lambda path, k=None: {"success": True, "data": []})
    artwork.set_key("a" * 32)
    assert artwork.has_key()
    artwork.clear_key()
    assert not artwork.has_key()
