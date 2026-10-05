"""
Change cover: Steam's own cover or any SteamGridDB grid for the game, each with
its artist's name (they made it; we credit them on the card's tooltip too).
Needs your SteamGridDB key (Settings).
"""
from __future__ import annotations

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QWidget

from shelf import artwork
from shelf.i18n import t
from ui.async_bridge import run_async
from ui.components import Button, Card, CoverImage, FlowLayout, hbox, label, scroll_area, vbox
from ui.theme import SP

TW, TH = 132, 198
MAX = 30


class CoverDialog(QDialog):
    def __init__(self, parent, store: str, game_id: str, title: str):
        super().__init__(parent)
        self.store, self.game_id = store, game_id
        self.changed = False
        self.setWindowTitle(t("cover.title"))
        self.resize(860, 620)
        lay = vbox(self, (SP["xl"],) * 4, SP["md"])
        lay.addWidget(label(t("cover.eyebrow"), "eyebrow"))
        lay.addWidget(label(title, "h2", wrap=True))
        self.hint = label(t("cover.loading"), "muted", wrap=True)
        lay.addWidget(self.hint)
        host = QWidget()
        self.flow = FlowLayout(host, SP["md"], SP["md"])
        lay.addWidget(scroll_area(host), 1)
        btns = hbox(spacing=SP["sm"])
        btns.addWidget(Button(t("cover.reset"), "ghost", "refresh-cw", on_click=self._reset))
        btns.addStretch()
        btns.addWidget(Button(t("common.close"), "default", on_click=self.reject))
        lay.addLayout(btns)
        run_async(self, lambda: artwork.grids(store, game_id), self._got)

    def _got(self, res):
        if isinstance(res, Exception):
            code = res.args[0] if isinstance(res, artwork.ArtworkError) else "server"
            self.hint.setText(t(f"cover.err_{code}"))
            return
        if not res:
            self.hint.setText(t("cover.none"))
            return
        self.hint.setText(t("cover.pick"))
        for g in res[:MAX]:
            self.flow.addWidget(self._tile(g))

    def _tile(self, g: dict) -> Card:
        c = Card(padding=SP["xs"], clickable=True, spacing=SP["xs"])
        img = CoverImage(TW, TH)
        c.body.addWidget(img)
        by = label(t("cover.by", author=g["author"]) if g["author"] else t("cover.by_unknown"), "muted", elide=True)
        by.setFixedWidth(TW)
        c.body.addWidget(by)
        c.setToolTip(t("cover.by", author=g["author"] or "?") + "  ·  SteamGridDB")
        c.clicked.connect(lambda g=g, c=c: self._choose(g, c))

        def got(res):
            if isinstance(res, bytes):
                pm = QPixmap()
                if pm.loadFromData(res):
                    img.set_pixmap(pm)
        run_async(self, lambda: artwork.fetch(g["thumb"], 3 * 1024 * 1024), got)
        return c

    def _choose(self, g: dict, c: Card):
        c.setEnabled(False)
        self.hint.setText(t("cover.applying"))

        def done(ok):
            c.setEnabled(True)
            if ok is True:
                self.changed = True
                self.accept()
            else:
                self.hint.setText(t("cover.err_offline"))
        run_async(self, lambda: artwork.use(self.store, self.game_id, g), done)

    def _reset(self):
        artwork.reset(self.store, self.game_id)
        self.changed = True
        self.accept()

