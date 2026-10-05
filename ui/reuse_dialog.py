"""
"Put another game on this disc". Two ways, because most blank discs are write-once:

  point   any disc (CD-R, DVD-R…): this PC opens the new game when the disc goes in.
          Nothing is written to the disc; its label and cover still show the old game,
          and on another PC it still opens the old one.
  erase   only rewritable discs (CD-RW, DVD-RW, DVD+RW): erase it in the drive and burn
          the new game. Works on any PC with Steam Shelf.
"""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QRadioButton

from shelf.collection import ShelfEntry
from shelf.i18n import t
from ui.components import Button, Card, hbox, label, vbox
from ui.theme import SP


class ReuseDialog(QDialog):
    def __init__(self, parent, entry: ShelfEntry, new_title: str):
        super().__init__(parent)
        self.setWindowTitle(t("reuse.title"))
        self.setMinimumWidth(560)
        self.choice = ""
        old = entry.disc_title or entry.title
        lay = vbox(self, (SP["xl"],) * 4, SP["md"])
        lay.addWidget(label(t("reuse.eyebrow"), "eyebrow"))
        lay.addWidget(label(t("reuse.headline", old=old, new=new_title), "h2", wrap=True))

        self.opt_point = QRadioButton(t("reuse.point"))
        self.opt_erase = QRadioButton(t("reuse.erase"))
        self.opt_point.setChecked(True)
        for radio, text in ((self.opt_point, t("reuse.point_text", old=old)),
                            (self.opt_erase, t("reuse.erase_text"))):
            c = Card(padding=SP["md"], spacing=SP["xs"])
            c.body.addWidget(radio)
            c.body.addWidget(label(text, "muted", wrap=True))
            lay.addWidget(c)
        if not entry.burned:
            self.opt_erase.setEnabled(False)
            lay.addWidget(label(t("reuse.not_burned"), "dim", wrap=True))

        lay.addStretch()
        btns = hbox(spacing=SP["sm"])
        btns.addStretch()
        btns.addWidget(Button(t("common.cancel"), "ghost", on_click=self.reject))
        btns.addWidget(Button(t("reuse.go"), "primary", "refresh-cw", on_click=self._go))
        lay.addLayout(btns)

    def _go(self):
        self.choice = "erase" if self.opt_erase.isChecked() else "point"
        self.accept()
