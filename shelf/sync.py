"""
Your Steam Shelf on pimpmysteam.com: the app sends the games that reached a
disc (shelf.history) to POST /shelf/sync with the Steam Family members' ids.
The server verifies every game against your Steam library (or your family's)
and shows the verified ones on your profile. Needs the PimpMySteam account.

Covers: for every accepted game whose cover is yours (the art you set in Steam,
e.g. with the Grunge Editor, or the one you picked in Steam Shelf for a
third-party game) a small WebP thumbnail (300x450, ~20-30 KB) goes up too, so
the profile shows *your* cover. The server keeps 60 per account (supporters on
Ko-fi: no limit) and re-encodes whatever it gets. Nothing is sent twice: the
thumbnail's hash is kept in the history.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import config
from shelf import account, family, history

log = logging.getLogger("shelf.sync")
SHELF_PAGE = f"{account.WEB}/profile/{{user}}"
THUMB = (300, 450)
THUMB_MAX = 60 * 1024          # bytes; quality steps down until it fits
COVERS_PER_SYNC = 40           # the server allows 120 an hour
_STATE = config.DATA_DIR / "sync_state.json"


def pending() -> list[dict]:
    return [x for x in history.load() if not x.get("synced")]


def sync(force: bool = False) -> dict:
    """Send what the server does not have yet (everything with force). Returns the server's answer
    ({accepted, unverified, steam_linked, profile: {shown, visible, cap}}) or {} when there is
    nothing to send / no account."""
    if not account.connected():
        return {}
    items = history.load() if force else pending()
    if not items:
        return {}
    body = {"items": [{"store": x["store"], "game_id": str(x["game_id"]), "title": x.get("title") or "Untitled",
                       "first_disc": x.get("first_disc"), "shared": bool(x.get("shared")),
                       "hidden": bool(x.get("hidden"))} for x in items][:500],
            "family": [m["id"] for m in family.members()][:10]}
    res = account.api("/shelf/sync", method="POST", body=body, timeout=60)
    done = {(a["store"], str(a["game_id"])) for a in (res.get("accepted") or []) + (res.get("unverified") or [])}
    all_items = history.load()
    for x in all_items:
        if (x["store"], str(x["game_id"])) in done:
            x["synced"] = True
            x["verified"] = next((a["verified"] for a in (res.get("accepted") or []) + (res.get("unverified") or [])
                                  if (a["store"], str(a["game_id"])) == (x["store"], str(x["game_id"]))), "")
    tmp = history._FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(all_items, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, history._FILE)
    log.info("shelf sync: %d accepted, %d unverified", len(res.get("accepted") or []), len(res.get("unverified") or []))
    return res


# ── covers ────────────────────────────────────────────────────────────────────

def thumbnail(src: Path) -> Optional[bytes]:
    """The cover as a 300x450 WebP small enough for the profile (None if unreadable)."""
    from PIL import Image
    try:
        with Image.open(src) as im:
            im = im.convert("RGB")
            im.thumbnail(THUMB, Image.LANCZOS)
            for q in (82, 72, 62, 50):
                buf = io.BytesIO()
                im.save(buf, "WEBP", quality=q, method=4)
                if buf.tell() <= THUMB_MAX:
                    return buf.getvalue()
            return buf.getvalue()
    except (OSError, ValueError):
        return None


def _state() -> dict:
    try:
        d = json.loads(_STATE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(d: dict) -> None:
    tmp = _STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d), encoding="utf-8")
    os.replace(tmp, _STATE)


def cover_candidates(accepted: list[dict]) -> list[tuple[dict, Path, str]]:
    """(history item, cover file, SteamGridDB author or '') for accepted games whose cover is
    yours: Steam games with the art you set in Steam; third-party games with any cover at all."""
    from shelf import artwork, media
    keys = {(a["store"], str(a["game_id"])) for a in accepted}
    out = []
    for x in history.load():
        key = (x["store"], str(x["game_id"]))
        if key not in keys:
            continue
        own = media.own_cover(*key)
        if x["store"] == "steam" and not own:
            continue                                    # Steam's own art: the website already has it
        cover = media.fetch_cover(*key) if (own or x["store"] != "steam") else None
        if cover and cover.is_file():
            out.append((x, cover, "" if own else artwork.credit(*key)))
    return out


def upload_covers(accepted: list[dict], force: bool = False) -> dict:
    """Send the thumbnails that changed since the last sync. Returns {sent, skipped, cap}."""
    state = _state()
    if not force and state.get("cover_cap_until", 0) > time.time():
        return {"sent": 0, "skipped": 0, "cap": True}      # the account is at its limit: try tomorrow
    sent = skipped = 0
    cap = False
    items = history.load()
    by_key = {(x["store"], str(x["game_id"])): x for x in items}
    for x, cover, author in cover_candidates(accepted)[:COVERS_PER_SYNC]:
        data = thumbnail(cover)
        if not data:
            continue
        sha = hashlib.sha256(data).hexdigest()[:32]
        key = (x["store"], str(x["game_id"]))
        if not force and by_key[key].get("cover_sha") == sha:
            skipped += 1
            continue
        try:
            account.api_upload(f"/shelf/cover/{key[0]}/{key[1]}", f"{sha}.webp", data, "image/webp",
                               {"author": author[:60]})
        except account.AccountError as e:
            if e.args[0] == "cover_cap":
                cap = True
                state["cover_cap_until"] = time.time() + 24 * 3600
                _save_state(state)
                break
            raise
        by_key[key]["cover_sha"] = sha
        sent += 1
    if sent:
        tmp = history._FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, history._FILE)
    if not cap and "cover_cap_until" in state:
        state.pop("cover_cap_until", None)
        _save_state(state)
    log.info("shelf covers: %d sent, %d unchanged%s", sent, skipped, ", at the limit" if cap else "")
    return {"sent": sent, "skipped": skipped, "cap": cap}


def shelf_url() -> str:
    return SHELF_PAGE.format(user=account.username()) if account.username() else account.WEB
