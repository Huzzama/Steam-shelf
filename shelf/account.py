"""
PimpMySteam account: the same app token Steam Curator uses (pimpmysteam.com ›
Settings › Apps). With it Steam Shelf can list every game you own, not only
the installed ones; the Steam Web API key stays on the server (/steam/me/games).
Without an account it still works with what Steam has installed on this PC.

Token file: DATA_DIR/creds.json (owner-only permissions where the OS has them).
Owned games are cached in DATA_DIR/library.json (the endpoint allows 30 calls an hour).
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Optional

import config

DEFAULT_API = "https://api.pimpmysteam.com"
WEB = "https://pimpmysteam.com"
TOKEN_PAGE = f"{WEB}/settings"
LIBRARY_TTL = 15 * 60
_CREDS = config.DATA_DIR / "creds.json"
_LIBRARY = config.DATA_DIR / "library.json"


class AccountError(Exception):
    """A reason the user can read (bad token, offline, private profile)."""


# ── token ─────────────────────────────────────────────────────────────────────

def _read(path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def creds() -> dict:
    return _read(_CREDS)


def token() -> str:
    return str(creds().get("app_token") or "")


def api_url() -> str:
    return str(creds().get("api_url") or os.environ.get("STEAMSHELF_API_URL") or DEFAULT_API).rstrip("/")


def connected() -> bool:
    return bool(token())


def username() -> str:
    return str(creds().get("username") or "")


def disconnect() -> None:
    c = creds()
    for k in ("app_token", "username", "steam_id64"):
        c.pop(k, None)
    _write(_CREDS, c)
    try:
        _LIBRARY.unlink()
    except OSError:
        pass


# ── calls ─────────────────────────────────────────────────────────────────────

def api(path: str, tok: Optional[str] = None, timeout: float = 20, method: str = "GET",
        body: Optional[dict] = None, raw: Optional[bytes] = None, content_type: str = "") -> dict:
    """One call to the PimpMySteam API. body → JSON; raw + content_type → as is (multipart)."""
    tok = tok if tok is not None else token()
    data = json.dumps(body).encode("utf-8") if body is not None else raw
    headers = {"Authorization": f"Bearer {tok}", "Accept": "application/json",
               "User-Agent": f"SteamShelf/{config.VERSION} (+{WEB})"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    elif raw is not None:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(api_url() + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:      # noqa: S310 — our own https API
            return json.loads(r.read(16 * 1024 * 1024) or b"{}")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = str(json.loads(e.read(64 * 1024) or b"{}").get("detail") or "")
        except (ValueError, OSError, AttributeError):
            pass
        if e.code == 401:
            raise AccountError("bad_token") from None
        if e.code == 403:
            raise AccountError(detail if detail in SERVER_CODES else "bad_token") from None
        if e.code == 404 and path.startswith("/steam/"):
            raise AccountError("no_steam") from None
        if e.code == 429:
            raise AccountError("rate_limited") from None
        raise AccountError("server") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise AccountError("offline") from None
    except ValueError:
        raise AccountError("server") from None


SERVER_CODES = ("cover_cap",)      # 403 details the app understands beyond "bad token"


def api_upload(path: str, filename: str, data: bytes, mime: str, fields: Optional[dict] = None,
               timeout: float = 40) -> dict:
    """POST one file (multipart/form-data) plus plain fields."""
    import secrets
    boundary = "----SteamShelf" + secrets.token_hex(12)
    out = bytearray()
    for k, v in (fields or {}).items():
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode("utf-8")
    out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {mime}\r\n\r\n").encode("utf-8")
    out += data
    out += f"\r\n--{boundary}--\r\n".encode("utf-8")
    return api(path, method="POST", raw=bytes(out), content_type=f"multipart/form-data; boundary={boundary}",
               timeout=timeout)


def connect(tok: str) -> dict:
    """Check the token against /auth/me and keep it. Returns the user."""
    tok = tok.strip()
    if not re.fullmatch(r"[A-Za-z0-9._\-]{16,4096}", tok):
        raise AccountError("bad_token")
    user = api("/auth/me", tok=tok)
    c = creds()
    c.update(app_token=tok, username=str(user.get("username") or ""), steam_id64=str(user.get("steam_id") or ""))
    _write(_CREDS, c)
    return user


def owned_games(force: bool = False) -> list[dict]:
    """[{appid, name, playtime}] of every Steam game on the account, cached LIBRARY_TTL."""
    if not connected():
        return []
    cache = _read(_LIBRARY)
    if not force and cache.get("user") == username() and time.time() - float(cache.get("at", 0)) < LIBRARY_TTL:
        return cache.get("games", [])
    data = api("/steam/me/games", timeout=40)
    if data.get("private"):
        raise AccountError("private")
    games = []
    for g in data.get("games") or []:
        appid = str(g.get("appid", ""))
        if appid.isdigit():
            games.append({"appid": appid, "name": str(g.get("name") or "")[:120],
                          "playtime": int(g.get("playtime_forever") or 0)})
    _write(_LIBRARY, {"user": username(), "at": time.time(), "games": games})
    return games


def cached_games() -> list[dict]:
    """Whatever was fetched last, instantly (the UI shows it while refreshing)."""
    cache = _read(_LIBRARY)
    return cache.get("games", []) if cache.get("user") == username() else []
