"""
The card the agent shows when a disc goes in (main.py --prompt D: --mode auto|ask;
/dev/sr0 on Linux, VIRTUAL for a test):

  auto  "DAYS GONE  Starting in 5"  [Play now] [Cancel]   then launches by itself
  ask   "DAYS GONE  In the drive"   [Play]     [Dismiss]  (disc was there at startup / wake)

Bottom-right, on top, does not steal the keyboard. It reads the disc itself
(the agent only passes the drive's name) and launches through shelf.launch.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QProgressBar, QWidget

from shelf import collection, host, launch, media, settings, sources, virtual
from shelf.disc import DiscTag, TagError
from shelf.i18n import t
from ui.async_bridge import run_async
from ui.components import Button, CoverImage, hbox, label, vbox
from ui.theme import C, R, SP


def load_image(path: str) -> tuple[DiscTag | None, Path | None]:
    """A disc image instead of a drive: 'Simulate the disc going in' from the app."""
    from shelf.disc import read_tag_from_iso
    p = Path(path)
    try:
        tag = read_tag_from_iso(p) if p.is_file() else None
    except (OSError, TagError, ValueError):
        tag = None
    if not tag:
        return None, None
    tag = collection.resolve(tag)
    return tag, media.fetch_cover(tag.store, tag.game_id)


def load(drive: str) -> tuple[DiscTag | None, Path | None]:
    if not sources.valid(drive):
        return None, None
    if sources.kind(drive) == "letter":
        drive = drive.upper()
    try:
        tag, _ = sources.read(drive)
    except TagError:
        return None, None
    if not tag:
        return None, None
    burned = tag
    tag = collection.resolve(tag)
    cover = sources.cover(drive, burned.disc_id) if burned.key == tag.key else None
    return tag, cover or media.fetch_cover(tag.store, tag.game_id)


def drive_caption(drive: str) -> str:
    if drive == "SIM":
        return t("prompt.simulated")
    if drive == virtual.VIRTUAL:
        return t("prompt.virtual")
    return t("prompt.disc_in", drive=host.drive_name(drive).upper())


class PromptCard(QWidget):
    def __init__(self, tag: DiscTag, cover: Path | None, drive: str, mode: str):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.tag, self.mode = tag, mode
        self.prefs = settings.load()
        self.left = max(1, self.prefs["countdown"]) if mode == "auto" else 25
        self.total = self.left
        plan = launch.plan(tag, self.prefs)

        outer = vbox(self)
        card = QFrame()
        card.setObjectName("card")
        card.setStyleSheet(f"#card {{ background: {C['surface_2']}; border: 1px solid {C['border_strong']};"
                           f" border-radius: {R['lg']}px; }}")
        outer.addWidget(card)
        row = hbox(card, (SP["md"],) * 4, SP["lg"])
        art = CoverImage(84, 126, R["sm"])
        if cover:
            art.set_pixmap(QPixmap(str(cover)))
        row.addWidget(art)
        col = vbox(spacing=SP["xs"])
        col.addWidget(label(drive_caption(drive), "eyebrow"))
        col.addWidget(label(tag.title.upper(), "title", family="display", size="2xl", wrap=True))
        what = {"play": "", "running": t("prompt.running"), "store": t("prompt.not_installed_store"),
                "install": t("prompt.not_installed_install"), "missing": t("prompt.missing")}[plan.kind]
        self.line = label("", "dim", wrap=True)
        col.addWidget(self.line)
        if what:
            col.addWidget(label(what, "muted", wrap=True))
        self.bar = QProgressBar(); self.bar.setRange(0, self.total * 10); self.bar.setValue(self.total * 10)
        self.bar.setTextVisible(False)
        self.bar.setVisible(mode == "auto")
        col.addWidget(self.bar)
        btns = hbox(spacing=SP["sm"])
        go_text = t("prompt.play_now") if mode == "auto" else t("prompt.play")
        if plan.kind in ("store", "install"):
            go_text = t("prompt.open_store") if plan.kind == "store" else t("prompt.install")
        self.go = Button(go_text, "primary", "play", on_click=self.fire)
        btns.addWidget(self.go)
        btns.addWidget(Button(t("common.cancel") if mode == "auto" else t("prompt.dismiss"), "ghost", on_click=self.close))
        btns.addStretch()
        col.addLayout(btns)
        row.addLayout(col, 1)
        if plan.kind in ("running", "missing"):
            self.go.setEnabled(False)
            self.mode = "ask"
            self.bar.hide()

        self._t = self.total * 10
        self._update_line()                     # before sizing: the card fits its longest line
        self.setFixedWidth(460)
        self.adjustSize()
        scr = QGuiApplication.primaryScreen().availableGeometry()
        self.move(scr.right() - self.width() - SP["xl"], scr.bottom() - self.height() - SP["xl"])
        self._tick = QTimer(self, interval=100, timeout=self._step)
        self._tick.start()

    def _update_line(self):
        secs = (self._t + 9) // 10
        if self.mode == "auto":
            self.line.setText(t("prompt.starting_in", n=secs))
        else:
            self.line.setText(t("prompt.was_inside") if secs > 0 else "")

    def _step(self):
        self._t -= 1
        self.bar.setValue(max(0, self._t))
        self._update_line()
        if self._t <= 0:
            self._tick.stop()
            if self.mode == "auto":
                self.fire()
            else:
                self.close()

    def fire(self):
        self._tick.stop()
        self.go.setEnabled(False)
        # off the GUI thread: on Linux xdg-open may take a few seconds when Steam has to start
        run_async(self, lambda: launch.run(self.tag, self.prefs), lambda _r: QTimer.singleShot(300, self.close))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()
        super().keyPressEvent(e)

    def closeEvent(self, e):
        super().closeEvent(e)
        # a Qt.Tool window does not count as the "last window": end the process ourselves
        QTimer.singleShot(0, QApplication.instance().quit)


def run(app, drive: str, mode: str, image: bool = False) -> int:
    tag, cover = load_image(drive) if image else load(drive)
    if not tag:
        return 0
    w = PromptCard(tag, cover, "SIM" if image else drive, "ask" if mode == "ask" else "auto")
    w.show()
    w.raise_()
    return app.exec()
