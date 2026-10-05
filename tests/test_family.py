"""Steam Family: profile links, the server call, dedupe and 'yours wins'."""
import pytest

from shelf import account, family, history, library
from shelf.stores import Game

ANA = {"steam_id": "76561198000000001", "name": "Ana", "private": False, "games": [
    {"appid": 1086940, "name": "Baldur's Gate 3", "playtime_forever": 74070},
    {"appid": "1222140", "name": "Detroit: Become Human"}, {"appid": "bad"}]}


def _reset():
    for f in (family._FILE, account._LIBRARY, history._FILE):
        try:
            f.unlink()
        except OSError:
            pass
    for f in family._DIR.glob("*.json"):
        f.unlink()
    account._write(account._CREDS, {"app_token": "x" * 24, "username": "ryu", "steam_id64": "76561198999999999"})


def test_links():
    assert family.community_path("https://steamcommunity.com/id/ryu_pms/") == "id/ryu_pms"
    assert family.community_path("steamcommunity.com/profiles/76561198000000001") == "profiles/76561198000000001"
    assert family.community_path("76561198000000001") == "profiles/76561198000000001"
    with pytest.raises(family.FamilyError):
        family.community_path("https://store.steampowered.com/app/1086940")


def test_needs_account_and_maps_errors(monkeypatch):
    _reset()
    account.disconnect()
    with pytest.raises(family.FamilyError) as e:
        family.add("https://steamcommunity.com/id/ana")
    assert e.value.args[0] == "no_account"
    _reset()
    monkeypatch.setattr(account, "api", lambda path, **k: {"private": True, "steam_id": "76561198000000001"})
    with pytest.raises(family.FamilyError) as e:
        family.add("https://steamcommunity.com/id/ana")
    assert e.value.args[0] == "private"

    def boom(path, **k):
        raise account.AccountError("rate_limited")
    monkeypatch.setattr(account, "api", boom)
    with pytest.raises(family.FamilyError) as e:
        family.add("https://steamcommunity.com/id/ana")
    assert e.value.args[0] == "rate_limited"


def test_add_dedupe_and_yours_wins(monkeypatch):
    _reset()
    calls = []
    monkeypatch.setattr(account, "api", lambda path, **k: (calls.append(path), ANA)[1])
    m = family.add("https://steamcommunity.com/id/ana", my_id="76561198999999999")
    assert m["name"] == "Ana" and [x["id"] for x in family.members()] == [m["id"]]
    assert calls[0] == "/steam/family/games?profile=https%3A%2F%2Fsteamcommunity.com%2Fid%2Fana"
    assert family.server_form("profiles/76561198000000002") == "76561198000000002"
    with pytest.raises(family.FamilyError) as e:
        family.add("https://steamcommunity.com/id/ana")
    assert e.value.args[0] == "already"
    with pytest.raises(family.FamilyError) as e:
        family.add("https://steamcommunity.com/id/ana", my_id="76561198000000001")
    assert e.value.args[0] == "yourself"
    games = family.cached_shared_games()
    assert [g["appid"] for g in games] == ["1086940", "1222140"] and games[0]["playtime"] == 0
    # a second member with the same games: counted once
    monkeypatch.setattr(account, "api", lambda path, **k: dict(ANA, steam_id="76561198000000002", name="Bo"))
    family.add("https://steamcommunity.com/profiles/76561198000000002")
    shared = {g["appid"]: g for g in family.cached_shared_games()}
    assert len(shared) == 2 and shared["1086940"]["from"] == ["Ana", "Bo"]
    owned = [{"appid": "1222140", "name": "Detroit: Become Human", "playtime": 10}]
    lib = {g.game_id: g for g in library.build(owned, [Game("steam", "1222140", "Detroit", True)], [],
                                               shared=list(shared.values()))}
    assert lib["1222140"].owned and not lib["1222140"].shared          # yours wins
    assert lib["1086940"].shared and lib["1086940"].burnable and lib["1086940"].shared_from == ["Ana", "Bo"]
    assert library.matches(lib["1086940"], "", "family") and not library.matches(lib["1222140"], "", "family")
    family.remove("76561198000000002")
    assert len(family.members()) == 1


def test_history_marks_family_games(monkeypatch):
    _reset()
    monkeypatch.setattr(account, "api", lambda path, **k: ANA)
    family.add("https://steamcommunity.com/id/ana")
    history.record("steam", "1086940", "Baldur's Gate 3")
    history.record("steam", "999", "Mine")
    h = {x["game_id"]: x for x in history.load()}
    assert h["1086940"]["shared"] is True and h["999"]["shared"] is False
