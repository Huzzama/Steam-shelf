import json
import re

import config
from shelf import account, collection, i18n, library, settings
from shelf.collection import ShelfEntry
from shelf.disc import DiscTag
from shelf.stores import Game


def _reset():
    for f in (config.SHELF_FILE, config.SETTINGS_FILE, account._CREDS, account._LIBRARY):
        try:
            f.unlink()
        except OSError:
            pass


def test_library_status_and_filters():
    _reset()
    owned = [{"appid": "1", "name": "Alpha", "playtime": 60}, {"appid": "2", "name": "Beta", "playtime": 0}]
    installed = [Game("steam", "2", "Beta", True), Game("steam", "3", "Gamma", True)]
    entries = [ShelfEntry("d1", "steam", "1", "Alpha", "x", burned=True),
               ShelfEntry("d2", "steam", "3", "Gamma", "x"), ShelfEntry("d3", "steam", "1", "Alpha", "x", burned=True)]
    games = {g.game_id: g for g in library.build(owned, installed, entries)}
    assert games["1"].status == "burned" and len(games["1"].discs) == 2 and games["1"].owned
    assert games["2"].status == "none" and games["2"].installed
    assert games["3"].status == "image" and not games["3"].owned
    pick = lambda flt, q="": sorted(g.game_id for g in games.values() if library.matches(g, q, flt))
    assert pick("on_disc") == ["1", "3"] and pick("not_on_disc") == ["2"]
    assert pick("installed") == ["2", "3"] and pick("all", "alp") == ["1"]


def test_reassign_and_resolve():
    _reset()
    tag = DiscTag(store="steam", game_id="1259420", title="Days Gone")
    e = ShelfEntry.from_tag(tag); e.burned = True
    collection.upsert(e)
    assert collection.resolve(tag) == tag
    collection.reassign(tag.disc_id, "steam", "1593500", "God of War")
    r = collection.resolve(tag)
    assert (r.game_id, r.title, r.disc_id) == ("1593500", "God of War", tag.disc_id)
    got = collection.find(tag.disc_id)
    assert got.disc_game == "steam:1259420" and got.disc_title == "Days Gone" and got.burned
    collection.reassign(tag.disc_id, "steam", "1259420", "Days Gone")     # back to what is burned
    got = collection.find(tag.disc_id)
    assert got.disc_game == "" and collection.resolve(tag).game_id == "1259420"


def test_resolve_rejects_bad_local_ids():
    _reset()
    tag = DiscTag(store="steam", game_id="10", title="X")
    collection.upsert(ShelfEntry(tag.disc_id, "steam", "rm -rf", "Evil", "x"))
    assert collection.resolve(tag).game_id == "10"


def test_reburned_replaces_entry():
    _reset()
    old = DiscTag(store="steam", game_id="10", title="Old")
    collection.upsert(ShelfEntry.from_tag(old))
    collection.reassign(old.disc_id, "steam", "20", "New")
    new = DiscTag(store="steam", game_id="20", title="New", disc_id=old.disc_id)
    collection.reburned(old.disc_id, new)
    (e,) = collection.load()
    assert (e.game_id, e.burned, e.disc_game) == ("20", True, "")


def test_account_parses_and_caches(monkeypatch):
    _reset()
    calls = []

    def fake_api(path, tok=None, timeout=20):
        calls.append(path)
        if path == "/auth/me":
            return {"username": "ryu", "steam_id": "7656"}
        return {"games": [{"appid": 10, "name": "CS", "playtime_forever": 90}, {"appid": "bad"}]}
    monkeypatch.setattr(account, "api", fake_api)
    account.connect("a" * 20)
    assert account.connected() and account.username() == "ryu"
    assert account.owned_games() == [{"appid": "10", "name": "CS", "playtime": 90}]
    account.owned_games()
    assert calls.count("/steam/me/games") == 1            # cached
    assert account.cached_games()[0]["appid"] == "10"
    account.disconnect()
    assert not account.connected() and account.cached_games() == []


def test_account_errors(monkeypatch):
    _reset()
    import pytest
    with pytest.raises(account.AccountError):
        account.connect("short")
    account._write(account._CREDS, {"app_token": "x" * 20, "username": "ryu"})
    monkeypatch.setattr(account, "api", lambda *a, **k: {"private": True, "games": []})
    with pytest.raises(account.AccountError) as e:
        account.owned_games(force=True)
    assert e.value.args[0] == "private"


def test_i18n_all_locales_complete():
    en = json.loads((config.BUNDLE_DIR / "locales" / "en.json").read_text(encoding="utf-8"))
    ph = re.compile(r"\{\w+\}")
    for code in i18n.LANGUAGES:
        loc = json.loads((config.BUNDLE_DIR / "locales" / f"{code}.json").read_text(encoding="utf-8"))
        assert set(loc) == set(en), code
        for k, v in en.items():
            assert set(ph.findall(v)) <= set(ph.findall(loc[k])), (code, k)


def test_i18n_fallback_and_format():
    assert i18n.set_language("es") == "es"
    assert i18n.t("prompt.starting_in", n=3).endswith("3")
    assert i18n.t("no.such.key") == "no.such.key"
    assert i18n.set_language("xx") == "en"
    assert i18n.t("prompt.starting_in", n=5) == "Starting in 5"


def test_settings_language_validated():
    _reset()
    config.SETTINGS_FILE.write_text(json.dumps({"language": "klingon"}))
    assert settings.load()["language"] == "auto"
    config.SETTINGS_FILE.write_text(json.dumps({"language": "zh_TW"}))
    assert settings.load()["language"] == "zh_TW"
