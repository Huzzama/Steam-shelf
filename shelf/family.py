"""
Steam Family: the people you share a library with. Steam has no public way to
list a family, so you paste their profile links (Settings › Steam Family). The
PimpMySteam server reads each public profile's game list with its own Steam Web
API key (GET /steam/family/games, the same data any Steam calculator site shows;
Valve retired the old community XML), so this needs your PimpMySteam account.
Those games count as burnable, tagged "from your Steam Family". Your own copy
always wins and a game two relatives both own is counted once.

DATA_DIR/family.json      [{id, name, url, added}]
DATA_DIR/family/<id>.json {at, games: [{appid, name, playtime}]}
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import config

TTL = 6 * 60 * 60
_FILE = config.DATA_DIR / "family.json"
_DIR = config.DATA_DIR / "family"
_URL = re.compile(r"(?:https?://)?steamcommunity\.com/(?:(profiles)/(\d{17})|(id)/([A-Za-z0-9_-]{2,64}))/?", re.I)
_ID64 = re.compile(r"^\d{17}$")
_XML_BAD = re.compile("[^\t\n\r\x20-퟿-�\U00010000-\U0010FFFF]")


class FamilyError(Exception):
    """bad_url · no_account · offline · private · not_found · rate_limited · server · yourself · already"""


def _read(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def members() -> list[dict]:
    d = _read(_FILE)
    return [m for m in d if isinstance(m, dict) and m.get("id")] if isinstance(d, list) else []


def community_path(text: str) -> str:
    """'profiles/7656…' or 'id/name' from a pasted link (or a bare SteamID64)."""
    text = text.strip()
    if _ID64.match(text):
        return f"profiles/{text}"
    m = _URL.search(text)
    if not m:
        raise FamilyError("bad_url")
    return f"profiles/{m.group(2)}" if m.group(1) else f"id/{m.group(4)}"


def server_form(path: str) -> str:
    """What the server is sent: the bare SteamID64, or the full link for a custom name
    (both understood by every server version; "profiles/<id>" was not, before 0.8)."""
    if path.startswith("profiles/"):
        return path.split("/", 1)[1]
    return f"https://steamcommunity.com/{path}"


def _call(profile: str) -> tuple[str, str, list[dict]]:
    """(steam_id64, name, games) through the PimpMySteam server."""
    from urllib.parse import quote
    from shelf import account
    if not account.connected():
        raise FamilyError("no_account")
    try:
        data = account.api(f"/steam/family/games?profile={quote(server_form(profile), safe='')}", timeout=40)
    except account.AccountError as e:
        code = e.args[0]
        raise FamilyError({"no_steam": "not_found", "bad_token": "no_account"}.get(code, code)) from None
    if data.get("private"):
        raise FamilyError("private")
    sid = str(data.get("steam_id") or "")
    if not _ID64.match(sid):
        raise FamilyError("not_found")
    games = []
    for g in data.get("games") or []:
        appid = str(g.get("appid", ""))
        if appid.isdigit():
            games.append({"appid": appid, "name": str(g.get("name") or "")[:120],
                          "playtime": int(g.get("playtime_forever") or 0)})
    return sid, str(data.get("name") or sid), games


def fetch(path: str) -> tuple[str, str, list[dict]]:
    return _call(path)


def add(link: str, my_id: str = "") -> dict:
    """Resolve the link, read the games once, remember the member. Returns it."""
    path = community_path(link)
    sid, name, games = fetch(path)
    if my_id and sid == my_id:
        raise FamilyError("yourself")
    ms = members()
    if any(m["id"] == sid for m in ms):
        raise FamilyError("already")
    m = {"id": sid, "name": name or sid, "url": f"https://steamcommunity.com/{path}", "added": int(time.time())}
    ms.append(m)
    _write(_FILE, ms)
    _write(_DIR / f"{sid}.json", {"at": time.time(), "games": games})
    return m


def remove(sid: str) -> None:
    _write(_FILE, [m for m in members() if m["id"] != sid])
    try:
        (_DIR / f"{sid}.json").unlink()
    except OSError:
        pass


def games_of(m: dict, force: bool = False) -> list[dict]:
    cache = _read(_DIR / f"{m['id']}.json") or {}
    if not force and time.time() - float(cache.get("at", 0)) < TTL:
        return cache.get("games", [])
    try:
        _sid, _name, games = fetch(f"profiles/{m['id']}")
    except FamilyError:
        return cache.get("games", [])                        # keep what we had; refresh next time
    _write(_DIR / f"{m['id']}.json", {"at": time.time(), "games": games})
    return games


def shared_games(force: bool = False) -> list[dict]:
    """Every game anyone in the family owns, once each: [{appid, name, playtime, from: [names]}]."""
    out: dict[str, dict] = {}
    for m in members():
        for g in games_of(m, force):
            e = out.setdefault(g["appid"], {"appid": g["appid"], "name": g["name"], "playtime": 0, "from": []})
            e["from"].append(m["name"])
            e["name"] = e["name"] or g["name"]
    return list(out.values())


def cached_shared_games() -> list[dict]:
    out: dict[str, dict] = {}
    for m in members():
        for g in (_read(_DIR / f"{m['id']}.json") or {}).get("games", []):
            e = out.setdefault(g["appid"], {"appid": g["appid"], "name": g["name"], "playtime": 0, "from": []})
            e["from"].append(m["name"])
    return list(out.values())
