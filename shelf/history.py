"""
Your Steam Shelf history: every game that was ever burned to a disc on this PC,
with the date of its first disc. Putting another game on that disc, erasing it
or removing it from the shelf does not take the game out: you had it on a disc.
This is what the "Steam Shelf" section of a pimpmysteam.com profile will show
(the sync comes later; 'synced' marks what the server already has).

DATA_DIR/history.json: [{store, game_id, title, first_disc, synced}]
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import config

_FILE = config.DATA_DIR / "history.json"


def _from_family(app_id: str) -> bool:
    """Owned by a Steam Family member and not by you (what the profile will tag)."""
    from shelf import account, family
    if any(g["appid"] == app_id for g in account.cached_games()):
        return False
    return any(g["appid"] == app_id for g in family.cached_shared_games())


def load() -> list[dict]:
    try:
        d = json.loads(_FILE.read_text(encoding="utf-8"))
        return [x for x in d if isinstance(x, dict) and x.get("store") and x.get("game_id")] if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def keys() -> set[tuple[str, str]]:
    return {(x["store"], str(x["game_id"])) for x in load()}


def record(store: str, game_id: str, title: str) -> bool:
    """Add a game the first time it reaches a disc. True if it was new."""
    items = load()
    shared = store == "steam" and _from_family(str(game_id))
    if any((x["store"], str(x["game_id"])) == (store, str(game_id)) for x in items):
        return False
    items.append({"store": store, "game_id": str(game_id), "title": title,
                  "first_disc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "synced": False,
                  "shared": bool(shared)})      # from your Steam Family (the profile can say so)
    tmp = _FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, _FILE)
    return True
