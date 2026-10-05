"""
New disc: pick one of YOUR games (installed ones first, then the rest of your
library when your PimpMySteam account is connected; a store link or an app id
works too), see its cover and whether it is already on a disc, then test it
with a virtual disc, burn it, or just put it on the shelf. Games you don't own
can't go on a disc: they show "not in your library" and a link to the store.

pick_only=True turns it into a game picker ("put another game on this disc"):
it only sets .picked = (store, game_id, title).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPixmap
from PySide6.QtWidgets import QDialog, QListWidget, QListWidgetItem

import config
from shelf import account, collection, family, history, library, media
from shelf.collection import ShelfEntry
from shelf.disc import DiscTag, clean_title
from shelf.i18n import t
from shelf.stores import local_games, store_for
from ui import icons, theme
from ui.async_bridge import run_async
from ui.components import Button, CoverImage, Pill, SearchField, hbox, label, vbox
from ui.theme import C, SP

ROLE = Qt.ItemDataRole.UserRole
_APP_LINK = re.compile(r"store\.steampowered\.com/app/(\d{1,10})|^\s*(\d{1,10})\s*$")


class NewDiscDialog(QDialog):
    def __init__(self, parent=None, preset: Optional[library.LibGame] = None, pick_only: bool = False):
        super().__init__(parent)
        self.pick_only = pick_only
        self.setWindowTitle(t("new.pick_title") if pick_only else t("new.title"))
        self.resize(840, 580)
        self.created: Optional[DiscTag] = None
        self.picked: Optional[tuple[str, str, str]] = None
        self.next_step = ""
        self._pick: Optional[dict] = None
        self._games: list[library.LibGame] = []

        lay = hbox(self, (SP["xl"],) * 4, SP["xl"])

        # left: search + list
        left = vbox(spacing=SP["sm"])
        left.addWidget(label(t("new.pick"), "eyebrow"))
        self.search = SearchField(t("new.search"))
        self.search.textChanged.connect(self._typed)
        left.addWidget(self.search)
        self.list = QListWidget()
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.currentItemChanged.connect(self._selected)
        left.addWidget(self.list, 1)
        self.hint = label("", "muted", wrap=True)
        left.addWidget(self.hint)
        self.list.setMinimumWidth(360)
        lay.addLayout(left, 3)

        # right: preview + actions
        right = vbox(spacing=SP["md"])
        self.cover = CoverImage(220, 330)
        right.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignHCenter)
        self.title = label(t("new.none_picked"), "h2", wrap=True)
        self.title.setFont(theme.font("lg", QFont.Weight.DemiBold))
        right.addWidget(self.title)
        pills = hbox(spacing=SP["xs"])
        self.pill_id, self.pill_state, self.pill_disc = Pill("", "neutral"), Pill("", "neutral"), Pill("", "neutral")
        for p in (self.pill_id, self.pill_state, self.pill_disc):
            pills.addWidget(p)
            p.hide()
        pills.addStretch()
        right.addLayout(pills)
        right.addStretch()
        if pick_only:
            self.btn_pick = Button(t("new.use_game"), "primary", "check", on_click=self._use)
            self.buttons = (self.btn_pick,)
        else:
            self.btn_burn = Button(t("new.burn"), "primary", "disc-3", on_click=lambda: self._create("burn"))
            self.btn_test = Button(t("new.test"), "default", "flask-conical", on_click=lambda: self._create("test"))
            self.btn_add = Button(t("new.add"), "ghost", "plus", on_click=lambda: self._create(""))
            self.buttons = (self.btn_burn, self.btn_test, self.btn_add)
        for b in self.buttons:
            b.setEnabled(False)
            right.addWidget(b)
        self.btn_store = Button(t("new.view_store"), "link", "external-link", on_click=self._open_store)
        self.btn_store.hide()
        right.addWidget(self.btn_store)
        self.pill_state.setMaximumWidth(260)
        lay.addLayout(right, 2)
        lay.setStretch(0, 3)

        self.hint.setText(t("new.reading"))
        run_async(self, lambda: local_games(), self._got_installed)
        if preset is not None:
            self._show(self._data(preset))

    # ── list ──────────────────────────────────────────────────────────────────
    def _got_installed(self, res, owned=None):
        installed = [] if isinstance(res, Exception) else res
        self._installed = installed
        if owned is None:
            owned = account.cached_games()
            if account.connected() and not owned:          # first time: fetch the library once
                run_async(self, account.owned_games,
                          lambda r: None if isinstance(r, Exception) else self._got_installed(self._installed, r))
        self._games = [g for g in library.build(owned, installed, collection.load(), history.keys(),
                                                family.cached_shared_games())
                       if g.burnable]
        if not self._games:
            self.hint.setText(t("new.nothing_installed"))
        else:
            self.hint.setText("" if account.connected() else t("new.connect_hint"))
        self._render()

    def _header(self, text: str):
        it = QListWidgetItem(text)
        it.setFlags(Qt.ItemFlag.NoItemFlags)
        it.setForeground(QColor(C["text_muted"]))
        it.setFont(theme.font("2xs", QFont.Weight.Bold, "mono", 1.5))
        self.list.addItem(it)

    def _row(self, text: str, data: dict):
        it = QListWidgetItem(text)
        it.setData(ROLE, data)
        status = data.get("status", "none")
        if status != "none":
            it.setIcon(icons.icon("disc-3", C["green"] if status == "burned" else C["gold"], 14))
            it.setToolTip(t("status.burned") if status == "burned" else t("status.ready"))
        self.list.addItem(it)

    @staticmethod
    def _data(g: library.LibGame) -> dict:
        return {"store": g.store, "id": g.game_id, "name": g.title, "installed": g.installed, "status": g.status,
                "mine": g.burnable, "shared": g.shared}

    def _render(self):
        q = self.search.text().strip().lower()
        self.list.clear()
        m = _APP_LINK.search(self.search.text())
        app_id = (m.group(1) or m.group(2)) if m else ""
        if app_id:
            hits = [g for g in self._games if g.game_id == app_id]
            if not hits:
                self._header(t("new.h_app_id"))
                self._row(t("new.steam_app", id=app_id),
                          {"store": "steam", "id": app_id, "name": "", "installed": None, "mine": False})
                return
        else:
            hits = [g for g in self._games if not q or q in g.title.lower()]
        installed = [g for g in hits if g.installed and g.store == "steam"]
        shortcuts = [g for g in hits if g.store == "nonsteam"]
        rest = [g for g in hits if not g.installed and g.store == "steam" and not g.shared]
        fam = [g for g in hits if not g.installed and g.shared]
        if installed:
            self._header(t("new.h_installed"))
            for g in installed[:300]:
                self._row(g.title, self._data(g))
        if shortcuts:
            self._header(t("new.h_nonsteam"))
            for g in shortcuts[:300]:
                self._row(g.title, self._data(g))
        if rest:
            self._header(t("new.h_library"))
            for g in rest[:300]:
                self._row(g.title, self._data(g))
        if fam:
            self._header(t("new.h_family"))
            for g in fam[:300]:
                self._row(g.title, self._data(g))

    def _typed(self, _text):
        self._render()

    # ── preview ───────────────────────────────────────────────────────────────
    def _selected(self, cur: Optional[QListWidgetItem], _prev):
        data = cur.data(ROLE) if cur else None
        if data:
            self._show(data)

    def _show(self, data: dict):
        self._pick = dict(data)
        st = store_for(data["store"])
        self.title.setText(data["name"] or t("new.steam_app", id=data["id"]))
        self.pill_id.setText(f"{st.label.upper()} {data['id']}")
        self.pill_id.show()
        mine = data.get("mine", True)
        installed = data["installed"]
        if installed is None:
            installed = st.is_installed(data["id"]) if st.available() else False
        if not mine:
            self.pill_state.setText(t("new.not_yours"))
            self.pill_state.set_tone("red")
        elif data["store"] == "nonsteam":
            self.pill_state.setText(t("new.nonsteam"))
            self.pill_state.set_tone("violet")
        elif data.get("shared"):
            self.pill_state.setText(t("new.family_installed") if installed else t("new.family"))
            self.pill_state.set_tone("violet")
        else:
            self.pill_state.setText(t("new.installed") if installed else t("new.not_installed"))
            self.pill_state.set_tone("green" if installed else "gold")
        self.pill_state.show()
        self.btn_store.setVisible(not mine and bool(st.web_page(data["id"])))
        status = data.get("status") or "none"
        if status == "none":
            discs = [e for e in collection.load() if (e.store, e.game_id) == (data["store"], data["id"])]
            status = "burned" if any(e.burned for e in discs) else "image" if discs else "none"
        self.pill_disc.setVisible(status != "none")
        if status != "none":
            self.pill_disc.setText({"burned": t("status.burned"), "image": t("status.ready")}.get(status, t("status.was")))
            self.pill_disc.set_tone({"burned": "green", "image": "gold"}.get(status, "neutral"))
        for b in self.buttons:
            b.setEnabled(mine)
        if not self.pick_only:
            self.btn_burn.setText(t("new.burn_again") if status == "burned" else t("new.burn"))
        self.cover.set_pixmap(None)
        self.cover.set_placeholder(data["name"] or "")
        key = (data["store"], data["id"])
        run_async(self, lambda: media.fetch_cover(*key), lambda res: self._got_cover(key, res))
        if not data["name"]:
            run_async(self, lambda: _app_name(data["id"]), self._got_name)

    def _got_cover(self, key, res):
        if self._pick and (self._pick["store"], self._pick["id"]) == key and isinstance(res, Path):
            self.cover.set_pixmap(QPixmap(str(res)))

    def _got_name(self, res):
        if isinstance(res, str) and res and self._pick and not self._pick["name"]:
            self._pick["name"] = res
            self.title.setText(res)

    def _open_store(self):
        if self._pick:
            QDesktopServices.openUrl(QUrl(store_for(self._pick["store"]).web_page(self._pick["id"])))

    # ── result ────────────────────────────────────────────────────────────────
    def _title(self) -> str:
        return clean_title(self._pick["name"] or self.title.text()) or f"Steam app {self._pick['id']}"

    def _use(self):
        if self._pick and self._pick.get("mine", True):
            self.picked = (self._pick["store"], self._pick["id"], self._title())
            self.accept()

    def _create(self, step: str):
        if not self._pick or not self._pick.get("mine", True):
            return
        tag = DiscTag(store=self._pick["store"], game_id=self._pick["id"], title=self._title(),
                      app=f"Steam Shelf {config.VERSION}")
        collection.upsert(ShelfEntry.from_tag(tag))
        self.created, self.next_step = tag, step
        self.accept()


def _app_name(app_id: str) -> str:
    """Name of a Steam app from the public appdetails endpoint ('' if offline)."""
    import json
    try:
        data = json.loads(media._get(f"https://store.steampowered.com/api/appdetails?appids={app_id}&filters=basic"))
        return str(data.get(app_id, {}).get("data", {}).get("name", ""))[:120]
    except (OSError, ValueError, AttributeError):
        return ""
