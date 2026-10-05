"""
The Library tab: every Steam game you own (PimpMySteam account) plus whatever
is installed on this PC, each with where it stands on the shelf:
  burned  on at least one real disc
  image   made (tested with a virtual disc) but not burned yet
  none    not on a disc
Non-Steam games you added to Steam (emulators, GOG installs…) are listed too:
they are yours by definition, so they can go on a disc.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from shelf.collection import ShelfEntry
from shelf.stores import Game


@dataclass
class LibGame:
    store: str
    game_id: str
    title: str
    installed: bool = False
    owned: bool = False
    playtime: int = 0                     # minutes
    discs: list = field(default_factory=list)
    had_disc: bool = False                # in the history: was on a disc before (shelf.history)
    shared_from: list = field(default_factory=list)   # Steam Family members who own it (you don't)

    @property
    def status(self) -> str:
        if any(d.burned for d in self.discs):
            return "burned"
        if self.discs:
            return "image"
        return "was" if self.had_disc else "none"

    @property
    def burnable(self) -> bool:
        """Only your own games go on a disc: owned on the account, or installed by Steam here."""
        return self.owned or self.installed or bool(self.shared_from)

    @property
    def shared(self) -> bool:
        return bool(self.shared_from) and not self.owned


def build(owned: list[dict], installed: list[Game], entries: list[ShelfEntry],
          had: set[tuple[str, str]] = frozenset(), shared: list[dict] = ()) -> list[LibGame]:
    games: dict[tuple[str, str], LibGame] = {}
    for g in owned:
        games[("steam", g["appid"])] = LibGame("steam", g["appid"], g.get("name") or f"Steam app {g['appid']}",
                                               owned=True, playtime=int(g.get("playtime") or 0))
    for g in shared:                                      # Steam Family: yours wins, counted once
        if ("steam", g["appid"]) in games:
            continue
        lg = LibGame("steam", g["appid"], g.get("name") or f"Steam app {g['appid']}")
        lg.shared_from = list(g.get("from") or [])
        games[("steam", g["appid"])] = lg
    for g in installed:                                   # Steam's games and your non-Steam shortcuts
        lg = games.setdefault((g.store, g.game_id), LibGame(g.store, g.game_id, g.title))
        lg.installed = g.installed
    for e in entries:
        if e.store not in ("steam", "nonsteam"):
            continue
        lg = games.setdefault((e.store, e.game_id), LibGame(e.store, e.game_id, e.title))
        lg.discs.append(e)
    for g in games.values():
        g.had_disc = (g.store, g.game_id) in had
    return sorted(games.values(), key=lambda g: g.title.lower())


def matches(g: LibGame, query: str, flt: str) -> bool:
    if query and query.lower() not in g.title.lower():
        return False
    if flt == "on_disc":
        return g.status in ("burned", "image")
    if flt == "not_on_disc":
        return g.status in ("none", "was")
    if flt == "installed":
        return g.installed
    if flt == "family":
        return g.shared
    return True
