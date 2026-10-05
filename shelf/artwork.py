"""
SteamGridDB covers (optional). With your own free API key from
steamgriddb.com › Preferences › API, Steam Shelf can:
  - use community art when Steam has no 600x900 cover for a game,
  - let you pick another cover for a disc (Change cover), with the artist's name.

The key is yours and stays on this PC (DATA_DIR/creds.json, next to the
PimpMySteam token). Images are fetched only from steamgriddb.com's API and CDN.
Credits: DATA_DIR/covers/credits.json  {"steam_1259420": {"author", "sgdb_id"}}.
"""
from __future__ import annotations

import io
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import config

API = "https://www.steamgriddb.com/api/v2"
KEY_PAGE = "https://www.steamgriddb.com/profile/preferences/api"
_IMG_HOSTS = (".steamgriddb.com",)
_CREDITS = config.COVERS_DIR / "credits.json"


class ArtworkError(Exception):
    """bad_key · offline · server"""


# ── key ───────────────────────────────────────────────────────────────────────

def _creds_path() -> Path:
    return config.DATA_DIR / "creds.json"


def _creds() -> dict:
    try:
        d = json.loads(_creds_path().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_creds(c: dict) -> None:
    p = _creds_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(c, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def key() -> str:
    return str(_creds().get("sgdb_key") or "")


def has_key() -> bool:
    return bool(key())


def set_key(k: str) -> None:
    """Check the key with one real request, then keep it."""
    k = k.strip()
    if not re.fullmatch(r"[A-Za-z0-9]{16,128}", k):
        raise ArtworkError("bad_key")
    _api("/grids/steam/620?dimensions=600x900", k)          # Portal 2: always has grids
    c = _creds()
    c["sgdb_key"] = k
    _save_creds(c)


def clear_key() -> None:
    c = _creds()
    c.pop("sgdb_key", None)
    _save_creds(c)


# ── API ───────────────────────────────────────────────────────────────────────

def _api(path: str, k: str | None = None) -> dict:
    req = urllib.request.Request(API + path, headers={
        "Authorization": f"Bearer {k if k is not None else key()}",
        "User-Agent": f"SteamShelf/{config.VERSION} (+https://pimpmysteam.com)"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:       # noqa: S310 — fixed https host
            return json.loads(r.read(4 * 1024 * 1024) or b"{}")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise ArtworkError("bad_key") from None
        if e.code == 404:
            return {"success": True, "data": []}             # game unknown to SteamGridDB
        raise ArtworkError("server") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ArtworkError("offline") from None
    except ValueError:
        raise ArtworkError("server") from None


def _safe_img(url: str) -> bool:
    u = urlparse(url)
    return u.scheme == "https" and any(u.hostname and (u.hostname == h[1:] or u.hostname.endswith(h)) for h in _IMG_HOSTS)


def parse_grids(data: dict) -> list[dict]:
    """Portrait, static, safe-for-work, not joke covers; best score first."""
    out = []
    for g in data.get("data") or []:
        if not isinstance(g, dict) or g.get("nsfw") or g.get("humor") or g.get("epilepsy"):
            continue
        url, thumb = str(g.get("url") or ""), str(g.get("thumb") or "")
        if not (_safe_img(url) and _safe_img(thumb)) or url.lower().endswith((".webm", ".gif")):
            continue
        w, h = int(g.get("width") or 0), int(g.get("height") or 0)
        if w and h and h < w:                       # we want the tall ones
            continue
        author = g.get("author") if isinstance(g.get("author"), dict) else {}
        out.append({"id": int(g.get("id") or 0), "url": url, "thumb": thumb, "style": str(g.get("style") or ""),
                    "score": int(g.get("score") or 0), "author": str(author.get("name") or "")[:60]})
    return sorted(out, key=lambda g: -g["score"])


def title_for(store: str, game_id: str) -> str:
    """What to search SteamGridDB for: the launcher's name of the game, else the shelf's."""
    from shelf import collection
    from shelf.stores import STORE_IMPLS
    st = STORE_IMPLS.get(store)
    name = st.title_of(str(game_id)) if st is not None and hasattr(st, "title_of") else ""
    if not name:
        name = next((e.title for e in collection.load() if (e.store, str(e.game_id)) == (store, str(game_id))), "")
    return name


def grids(store: str, game_id: str) -> list[dict]:
    if store != "steam":
        title = title_for(store, game_id)
        return grids_by_title(title) if title else []
    if not str(game_id).isdigit():
        return []
    return parse_grids(_api(f"/grids/steam/{game_id}?dimensions=600x900,342x482,660x930&types=static"
                            "&nsfw=false&humor=false&epilepsy=false"))


def grids_by_title(title: str) -> list[dict]:
    """For games Steam does not know (non-Steam shortcuts): SteamGridDB's own search, best match."""
    from urllib.parse import quote
    title = title.strip()
    if not title:
        return []
    hits = _api(f"/search/autocomplete/{quote(title[:80])}").get("data") or []
    hit = next((h for h in hits if isinstance(h, dict) and str(h.get("name", "")).lower() == title.lower()), None) \
        or next((h for h in hits if isinstance(h, dict)), None)
    if not hit or not str(hit.get("id", "")).isdigit():
        return []
    return parse_grids(_api(f"/grids/game/{hit['id']}?dimensions=600x900,342x482,660x930&types=static"
                            "&nsfw=false&humor=false&epilepsy=false"))


def fetch(url: str, limit: int = 12 * 1024 * 1024) -> bytes:
    if not _safe_img(url):
        raise ArtworkError("server")
    req = urllib.request.Request(url, headers={"User-Agent": f"SteamShelf/{config.VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:       # noqa: S310 — SteamGridDB CDN only
            return r.read(limit)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ArtworkError("offline") from None


# ── covers ────────────────────────────────────────────────────────────────────

def credits() -> dict:
    try:
        d = json.loads(_CREDITS.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def credit(store: str, game_id: str) -> str:
    return str((credits().get(f"{store}_{game_id}") or {}).get("author") or "")


def _set_credit(store: str, game_id: str, value: dict | None) -> None:
    c = credits()
    k = f"{store}_{game_id}"
    if value is None:
        c.pop(k, None)
    else:
        c[k] = value
    _CREDITS.parent.mkdir(parents=True, exist_ok=True)
    tmp = _CREDITS.with_suffix(".tmp")
    tmp.write_text(json.dumps(c, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, _CREDITS)


def use(store: str, game_id: str, grid: dict) -> bool:
    """Make this grid the cover of the game (converted to JPEG). False if it could not be fetched."""
    from PIL import Image
    from shelf import media
    try:
        raw = fetch(grid["url"])
        with Image.open(io.BytesIO(raw)) as im:
            im = im.convert("RGB")
            if im.width > 900:
                im = im.resize((900, round(im.height * 900 / im.width)))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=90)
    except (ArtworkError, OSError, ValueError, Image.DecompressionBombError):
        return False
    p = media.cover_path(store, game_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(buf.getvalue())
    _set_credit(store, game_id, {"author": grid.get("author", ""), "sgdb_id": grid.get("id", 0)})
    return True


def forget_credit(store: str, game_id: str) -> None:
    if credit(store, game_id):
        _set_credit(store, game_id, None)


def reset(store: str, game_id: str) -> None:
    """Back to Steam's own cover (fetched again on next use)."""
    from shelf import media
    try:
        media.cover_path(store, game_id).unlink()
    except OSError:
        pass
    _set_credit(store, game_id, None)
