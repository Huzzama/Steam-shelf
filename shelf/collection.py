"""
The shelf: every disc made on this PC (DATA_DIR/shelf.json). The agent does
not need it (a disc carries its own tag); it feeds the app's grid and, later,
the "Shelf" tab on pimpmysteam.com.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Optional

import config
from shelf.disc import DiscTag


@dataclass
class ShelfEntry:
    disc_id: str
    store: str
    game_id: str
    title: str
    created: str
    burned: bool = False        # actually written to a disc (vs only a test image)
    last_played: str = ""
    # "put another game on this disc" without burning: the disc still says disc_game,
    # this PC opens store/game_id instead (see resolve())
    disc_game: str = ""         # "steam:1259420" as burned, when it differs from the current game
    disc_title: str = ""

    @classmethod
    def from_tag(cls, t: DiscTag) -> "ShelfEntry":
        return cls(t.disc_id, t.store, t.game_id, t.title, t.created)


def load() -> list[ShelfEntry]:
    try:
        raw = json.loads(config.SHELF_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    from shelf.disc import STORES
    out = []
    for d in raw if isinstance(raw, list) else []:
        if not isinstance(d, dict) or d.get("store") not in STORES:
            continue                 # e.g. a GOG/Epic disc made with 0.7.0: those launchers are gone
        try:
            out.append(ShelfEntry(**{k: d[k] for k in ShelfEntry.__dataclass_fields__ if k in d}))
        except TypeError:
            continue
    return out


def save(entries: list[ShelfEntry]) -> None:
    tmp = config.SHELF_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps([asdict(e) for e in entries], indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, config.SHELF_FILE)


def upsert(entry: ShelfEntry) -> list[ShelfEntry]:
    entries = [e for e in load() if e.disc_id != entry.disc_id]
    entries.append(entry)
    save(entries)
    return entries


def resolve(tag: DiscTag) -> DiscTag:
    """The game this PC should open for a disc: the one burned on it, unless the user
    reassigned the disc here. The shelf is local, trusted data; ids are re-validated anyway."""
    e = find(tag.disc_id)
    if e is None or (e.store, e.game_id) == (tag.store, tag.game_id):
        return tag
    from shelf.disc import STORES, clean_title
    if e.store not in STORES or not STORES[e.store].match(str(e.game_id)):
        return tag
    return DiscTag(store=e.store, game_id=str(e.game_id), title=clean_title(e.title) or tag.title,
                   disc_id=tag.disc_id, created=tag.created, app=tag.app)


def reassign(disc_id: str, store: str, game_id: str, title: str) -> None:
    """Point a disc at another game on this PC (works with write-once discs)."""
    entries = load()
    for e in entries:
        if e.disc_id == disc_id:
            if not e.disc_game:
                e.disc_game, e.disc_title = f"{e.store}:{e.game_id}", e.title
            if e.disc_game == f"{store}:{game_id}":          # back to what is burned on it
                e.disc_game, e.disc_title = "", ""
            e.store, e.game_id, e.title = store, game_id, title
    save(entries)


def reburned(disc_id: str, tag: DiscTag) -> None:
    """The disc was erased and the new game burned on it: no more reassignment."""
    entries = [e for e in load() if e.disc_id != disc_id]
    new = ShelfEntry.from_tag(tag)
    new.burned = True
    entries.append(new)
    save(entries)
    from shelf import history
    history.record(tag.store, tag.game_id, tag.title)


def find(disc_id: str) -> Optional[ShelfEntry]:
    return next((e for e in load() if e.disc_id == disc_id), None)


def remove(disc_id: str) -> None:
    save([e for e in load() if e.disc_id != disc_id])


def mark(disc_id: str, **changes) -> None:
    entries = load()
    for e in entries:
        if e.disc_id == disc_id:
            for k, v in changes.items():
                setattr(e, k, v)
            if changes.get("burned"):
                from shelf import history
                history.record(e.store, e.game_id, e.title)
    save(entries)
