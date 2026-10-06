"""
The Steam Shelf window. Two pages:
  Shelf    your discs as covers (test, burn, put another game on a disc, remove)
  Library  every game you own, with what is already on a disc
plus the agent switch, settings and "New disc". Drive and network work runs off
the GUI thread (ui.async_bridge). Windows and Linux alike: shelf.host knows which.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QFont, QPixmap
from PySide6.QtWidgets import QFileDialog, QMainWindow, QMenu, QStackedWidget, QWidget

import config
from shelf import account, artwork, collection, family, history, host, library, media, modes, sync, virtual
from shelf.collection import ShelfEntry
from shelf.disc import DiscTag
from shelf.i18n import t
from shelf.launch import spawn
from shelf.stores import local_games, store_for
from ui import icons, theme
from ui.async_bridge import run_async
from ui.components import (Button, Card, ChipGroup, CoverImage, EmptyState, FlowLayout, IconButton, ListRow, Pill,
                           SearchField, Segmented, ToastHost, hbox, label, scroll_area, vbox)
from ui.theme import C, SP

PAGE = 150      # library rows rendered at a time


def tag_of(e: ShelfEntry) -> DiscTag:
    return DiscTag(store=e.store, game_id=e.game_id, title=e.title, disc_id=e.disc_id, created=e.created,
                   app=f"Steam Shelf {config.VERSION}")


class DiscCard(Card):
    W, H = 168, 252

    def __init__(self, entry: ShelfEntry, window: "MainWindow"):
        super().__init__(padding=SP["sm"], spacing=SP["sm"])
        self.entry, self.win = entry, window
        self.setFixedWidth(self.W + 2 * SP["sm"])
        self.cover = CoverImage(self.W, self.H)
        self.cover.set_placeholder(entry.title)
        self.body.addWidget(self.cover)
        p = media.cover_path(entry.store, entry.game_id)
        if p.is_file():
            self.cover.set_pixmap(QPixmap(str(p)))
        by = artwork.credit(entry.store, entry.game_id)
        if by:
            self.cover.setToolTip(t("cover.by", author=by) + "  ·  SteamGridDB")
        # always ask again: a cover you changed in Steam (Grunge Editor) replaces the cached one
        run_async(self, lambda: media.fetch_cover(entry.store, entry.game_id), self._got_cover)
        self.body.addWidget(label(store_for(entry.store).label.upper(), "eyebrow"))
        title = label(entry.title, "body", elide=True)
        title.setFont(theme.font("base", QFont.Weight.DemiBold))
        self.body.addWidget(title)
        if entry.disc_game:
            note = label(t("shelf.disc_says", title=entry.disc_title), "muted", elide=True)
            note.setToolTip(t("shelf.disc_says_tip"))
            self.body.addWidget(note)
        row = hbox(spacing=SP["xs"])
        row.addWidget(Pill(t("status.burned") if entry.burned else t("status.image"),
                           "green" if entry.burned else "neutral"))
        row.addStretch()
        self._more = IconButton("ellipsis", t("shelf.actions"), 14, on_click=self._menu)
        row.addWidget(self._more)
        self.body.addLayout(row)

    def _got_cover(self, res):
        if isinstance(res, Path):
            self.cover.set_pixmap(QPixmap(str(res)))

    def _menu(self):
        m = QMenu(self)
        tag = tag_of(self.entry)

        def act(text, icon_name, fn):
            a = QAction(icons.icon(icon_name, C["text_2"], 14), text, m)
            a.triggered.connect(fn)
            m.addAction(a)
        act(t("action.test"), "flask-conical", lambda: self.win.test_disc(tag))
        act(t("action.simulate"), "play", lambda: self.win.simulate_disc(tag))
        act(t("action.eject"), "log-out", lambda: self.win.eject_test(tag))
        act(t("action.burn"), "disc-3", lambda: self.win.burn_disc(tag))
        act(t("action.another_game"), "refresh-cw", lambda: self.win.another_game(self.entry))
        if self.entry.store != "steam":          # Steam games: change it in Steam / Grunge Editor instead
            act(t("action.cover"), "image", lambda: self.win.change_cover(self.entry))
        act(t("action.reload_cover"), "refresh-cw", lambda: self.win.reload_cover(self.entry))
        act(t("action.save_iso"), "save", lambda: self.win.save_iso(tag))
        on = history.on_profile(tag.store, tag.game_id)
        if on is not None:                       # it reached a disc: it can be on the profile
            a = QAction(icons.icon("eye" if on else "eye-off", C["text_2"], 14), t("action.on_profile"), m)
            a.setCheckable(True)
            a.setChecked(on)
            a.toggled.connect(lambda v: self.win.set_on_profile(tag.store, tag.game_id, v))
            m.addAction(a)
        m.addSeparator()
        if store_for(tag.store).web_page(tag.game_id):
            act(t("action.store_page"), "external-link",
                lambda: QDesktopServices.openUrl(QUrl(store_for(tag.store).web_page(tag.game_id))))
        act(t("action.remove"), "trash", lambda: self.win.remove(self.entry))
        m.exec(self._more.mapToGlobal(self._more.rect().bottomLeft()))


class LibraryPage(QWidget):
    """Owned + installed games with their shelf status."""

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.games: list[library.LibGame] = []
        self.shown = PAGE
        lay = vbox(self, spacing=SP["md"])

        self.banner = Card(padding=SP["md"])
        brow = hbox(spacing=SP["md"])
        self.banner_text = label("", "body", wrap=True)
        brow.addWidget(self.banner_text, 1)
        self.banner_btn = Button(t("library.connect"), "primary", "link", on_click=win.open_settings)
        brow.addWidget(self.banner_btn)
        self.banner.body.addLayout(brow)
        lay.addWidget(self.banner)

        top = hbox(spacing=SP["md"])
        self.search = SearchField(t("library.search"))
        self.search.textChanged.connect(lambda _x: self.render(reset=True))
        top.addWidget(self.search, 1)
        self.filter = ChipGroup([("all", t("library.f_all")), ("not_on_disc", t("library.f_not_on_disc")),
                                 ("on_disc", t("library.f_on_disc")), ("installed", t("library.f_installed")),
                                 ("family", t("library.f_family"))], "all")
        self.filter.changed.connect(lambda _k: self.render(reset=True))
        top.addWidget(self.filter)
        self.refresh_btn = IconButton("refresh-cw", t("library.refresh"), 16, on_click=lambda: self.load(force=True))
        top.addWidget(self.refresh_btn)
        lay.addLayout(top)

        self.count = label("", "eyebrow")
        lay.addWidget(self.count)
        self.rows_host = QWidget()
        self.rows = vbox(self.rows_host, spacing=SP["xs"])
        self.rows.addStretch()
        lay.addWidget(scroll_area(self.rows_host), 1)

    def load(self, force: bool = False):
        connected = account.connected()
        self.banner.setVisible(not connected)
        self.banner_text.setText(t("library.banner"))
        owned = account.cached_games()
        installed = local_games()
        self.games = library.build(owned, installed, collection.load(), history.keys(), family.cached_shared_games())
        self.render(reset=True)
        if (connected and (force or not owned)) or (family.members() and force):
            self.refresh_btn.set_loading(True)
            run_async(self, lambda: (account.owned_games(force=force), family.shared_games(force=force)),
                      self._got_owned)

    def _got_owned(self, res):
        self.refresh_btn.set_loading(False)
        if isinstance(res, Exception):
            code = res.args[0] if isinstance(res, account.AccountError) else "server"
            self.win.toasts.show(t(f"account.err_{code}"), "warning", 5000)
            return
        owned, shared = res
        self.games = library.build(owned, local_games(), collection.load(), history.keys(), shared)
        self.render(reset=True)

    def render(self, reset: bool = False):
        if reset:
            self.shown = PAGE
        while self.rows.count() > 1:
            it = self.rows.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        q, flt = self.search.text().strip(), self.filter.current()
        hits = [g for g in self.games if library.matches(g, q, flt)]
        on_disc = sum(1 for g in self.games if g.status in ("burned", "image"))
        self.count.setText(t("library.count", n=len(self.games), discs=on_disc))
        for g in hits[:self.shown]:
            self.rows.insertWidget(self.rows.count() - 1, self._row(g))
        if len(hits) > self.shown:
            more = Button(t("library.more", n=len(hits) - self.shown), "ghost", on_click=self._more)
            self.rows.insertWidget(self.rows.count() - 1, more)
        if not hits:
            self.rows.insertWidget(0, label(t("library.none"), "dim"))

    def _more(self):
        self.shown += PAGE
        self.render()

    def _row(self, g: library.LibGame) -> ListRow:
        sub = t("library.installed") if g.installed else t("library.not_installed")
        if g.store == "nonsteam":
            sub = t("library.nonsteam")
        elif g.shared:
            sub = t("library.family_of", names=", ".join(g.shared_from[:3]))
        if g.playtime:
            sub += f"  ·  {g.playtime // 60} h"
        trailing = QWidget()
        tl = hbox(trailing, spacing=SP["sm"])
        if g.status == "burned":
            n = sum(1 for d in g.discs if d.burned)
            tl.addWidget(Pill(t("status.on_discs", n=n) if n > 1 else t("status.burned"), "green"))
        elif g.status == "image":
            tl.addWidget(Pill(t("status.ready"), "gold"))
        elif g.status == "was":
            was = Pill(t("status.was"), "neutral")
            was.setToolTip(t("status.was_tip"))
            tl.addWidget(was)
        if g.shared:
            tl.addWidget(Pill(t("status.family"), "violet"))
        on = history.on_profile(g.store, g.game_id)
        if on is not None:
            eye = IconButton("eye" if on else "eye-off", t("action.on_profile_tip_on" if on else "action.on_profile_tip_off"), 14,
                             on_click=lambda _c=False, game=g, now=on: self.win.set_on_profile(game.store, game.game_id, not now))
            tl.addWidget(eye)
        if g.burnable:
            fresh = g.status in ("none", "was")
            tl.addWidget(Button(t("library.make_disc") if fresh else t("library.another_copy"),
                                "default", "disc-3",
                                on_click=lambda _c=False, game=g: self.win.new_disc(preset=game)))
        row = ListRow(g.title, sub, trailing=trailing, clickable=False)
        return row


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Steam Shelf")
        self.resize(1080, 720)
        self.setMinimumSize(760, 540)
        root = QWidget()
        self.setCentralWidget(root)
        lay = vbox(root, (SP["2xl"], SP["xl"], SP["2xl"], SP["lg"]), SP["lg"])

        head = hbox(spacing=SP["md"])
        brand = vbox(spacing=0)
        tagline = label(t("app.tagline"), "eyebrow")
        tagline.setMinimumWidth(tagline.sizeHint().width())
        brand.addWidget(tagline)
        brand.addWidget(label("STEAM SHELF", "title", family="display", size="3xl"))
        head.addLayout(brand)
        head.addSpacing(SP["xl"])
        self.tabs = Segmented([("shelf", t("tab.shelf")), ("library", t("tab.library"))], "shelf")
        self.tabs.changed.connect(self._tab)
        head.addWidget(self.tabs, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addStretch(1)
        self.agent_btn = Button("", "ghost", "power", on_click=self.toggle_agent)
        head.addWidget(self.agent_btn)
        head.addSpacing(SP["xs"])
        head.addWidget(IconButton("settings", t("settings.title"), 18, on_click=self.open_settings))
        head.addWidget(Button(t("new.button"), "primary", "plus", on_click=lambda: self.new_disc()))
        lay.addLayout(head)

        self.pages = QStackedWidget()
        # shelf
        self.shelf_stack = QStackedWidget()
        self.empty = EmptyState("disc-3", t("shelf.empty_title"), t("shelf.empty_text"),
                                Button(t("new.button"), "primary", "plus", on_click=lambda: self.new_disc()))
        self.grid_host = QWidget()
        self.grid = FlowLayout(self.grid_host, SP["lg"], SP["lg"])
        self.shelf_stack.addWidget(self.empty)
        self.shelf_stack.addWidget(scroll_area(self.grid_host))
        self.pages.addWidget(self.shelf_stack)
        # library
        self.library = LibraryPage(self)
        self.pages.addWidget(self.library)
        lay.addWidget(self.pages, 1)

        foot = hbox(spacing=SP["md"])
        self.mode_pill = Pill(t("mode.burner"), "gold")
        self.mode_pill.setToolTip(t("mode.burner_tip"))
        foot.addWidget(self.mode_pill)
        self.status = label("", "eyebrow")
        self.status.setToolTip(t("mode.burner_tip"))
        foot.addWidget(self.status, 1)
        lay.addLayout(foot)

        self.toasts = ToastHost(self)
        # burner mode: while this window exists the agent leaves discs alone (shelf.modes)
        self._burner = host.hold_burner_mode()
        virtual.eject()                                     # a test left over from a crash
        self._busy = ""                                     # a drive being burned or erased
        self._library_loaded = False
        self.refresh()
        self._tick = QTimer(self, interval=2000, timeout=self.refresh_status)
        self._tick.start()
        self.refresh_status()

    def _tab(self, key: str):
        self.pages.setCurrentIndex(0 if key == "shelf" else 1)
        if key == "library" and not self._library_loaded:
            self._library_loaded = True
            self.library.load()
            self.sync_shelf()

    # ── shelf ─────────────────────────────────────────────────────────────────
    def refresh(self):
        while self.grid.count():
            it = self.grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        entries = sorted(collection.load(), key=lambda e: e.title.lower())
        for e in entries:
            self.grid.addWidget(DiscCard(e, self))
        self.shelf_stack.setCurrentIndex(1 if entries else 0)
        if self._library_loaded:
            self.library.load()

    def refresh_status(self):
        on = host.agent_running()
        text = t("agent.on") if on else t("agent.off")
        self.agent_btn.setText(text)
        self.agent_btn.ensurePolished()
        self.agent_btn.setMinimumWidth(self.agent_btn.fontMetrics().horizontalAdvance(text) + 52)
        self.agent_btn.set_icon("power", C["green"] if on else C["text_muted"])
        self.agent_btn.setToolTip(t("agent.on_tip") if on else t("agent.off_tip"))
        drives = host.optical_drives()
        tip = t("mode.burner_tip")
        if not host.SUPPORTED:
            txt = t("status.unsupported")
        elif not drives:
            txt = t("status.no_drive")
        elif host.access_problem():
            txt = t("status.no_access_short")
            tip = t("status.no_access")
        else:
            names = "  ".join(host.drive_name(d) for d in drives)
            txt = t("status.drives", drives=names) + "  //  " + (t("status.watching") if on else t("status.agent_off"))
            if host.LINUX:
                tip += "\n\n" + "\n".join(f"{host.drive_name(d)}: {host.drive_label(d)}" for d in drives)
        if virtual.inserted():
            txt += "  //  " + t("status.virtual_in")
        self.status.setText(txt.upper())
        self.status.setToolTip(tip)

    def remove(self, e: ShelfEntry):
        collection.remove(e.disc_id)
        self.refresh()
        self.toasts.show(t("shelf.removed", title=e.title), "info")

    # ── agent ─────────────────────────────────────────────────────────────────
    def toggle_agent(self):
        if not host.SUPPORTED:
            self.toasts.show(t("status.unsupported"), "warning")
            return
        if host.agent_running():
            host.stop_agent()
        else:
            spawn("--agent")
        QTimer.singleShot(800, self.refresh_status)

    def ensure_agent(self):
        if host.SUPPORTED and not host.agent_running():
            spawn("--agent")

    # ── dialogs ───────────────────────────────────────────────────────────────
    def new_disc(self, preset: "library.LibGame | None" = None):
        from ui.new_disc import NewDiscDialog
        dlg = NewDiscDialog(self, preset=preset)
        if dlg.exec() and dlg.created:
            self.refresh()
            tag = dlg.created
            if dlg.next_step == "test":
                self.test_disc(tag)
            elif dlg.next_step == "burn":
                self.burn_disc(tag)

    def open_settings(self):
        from ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self)
        dlg.exec()
        if dlg.language_changed:
            self.toasts.show(t("settings.restart_language"), "info", 5000)
        self.refresh_status()
        if self._library_loaded:
            self.library.load(force=dlg.account_changed or dlg.family_changed)

    def change_cover(self, entry: ShelfEntry):
        if not artwork.has_key():
            self.toasts.show(t("cover.need_key"), "info", 6000)
            self.open_settings()
            if not artwork.has_key():
                return
        from ui.cover_dialog import CoverDialog
        dlg = CoverDialog(self, entry.store, entry.game_id, entry.title)
        dlg.exec()
        if dlg.changed:
            self.refresh()

    def reload_cover(self, entry: ShelfEntry):
        """Forget the cached cover and look for it again (you changed it in Steam, or it never loaded)."""
        media.forget_cover(entry.store, entry.game_id)
        self.refresh()
        self.toasts.show(t("cover.reloaded"), "info")

    def another_game(self, entry: ShelfEntry):
        """Put another game on a disc you already have: point it elsewhere, or erase and burn."""
        from ui.new_disc import NewDiscDialog
        from ui.reuse_dialog import ReuseDialog
        pick = NewDiscDialog(self, pick_only=True)
        if not pick.exec() or not pick.picked:
            return
        store, game_id, title = pick.picked
        how = ReuseDialog(self, entry, title)
        if not how.exec():
            return
        if how.choice == "point":
            collection.reassign(entry.disc_id, store, game_id, title)
            self.refresh()
            self.toasts.show(t("reuse.pointed", old=entry.disc_title or entry.title, new=title), "success", 5000)
        elif how.choice == "erase":
            self._erase_and_burn(entry, DiscTag(store=store, game_id=game_id, title=title, disc_id=entry.disc_id,
                                                app=f"Steam Shelf {config.VERSION}"))

    def _drive(self) -> str:
        """The drive to burn or erase in ('' with a toast when there is none, or it is busy)."""
        if self._busy:
            self.toasts.show(t("burn.busy", drive=host.drive_name(self._busy)), "warning", 4500)
            return ""
        drives = host.optical_drives()
        if not drives:
            self.toasts.show(t("burn.no_drive"), "warning", 4500)
            return ""
        return drives[0]

    def _erase_and_burn(self, entry: ShelfEntry, tag: DiscTag):
        drive = self._drive()
        if not drive:
            return
        self._busy = drive
        note = self.toasts.show(t("reuse.erasing", drive=host.drive_name(drive)), "info", 0)

        def done(res):
            self._busy = ""
            self.toasts.dismiss(note)
            if isinstance(res, Exception):
                code = getattr(res, "code", "failed")
                key = f"burn.err_{code}" if code in ("no_xorriso", "no_access") else f"reuse.err_{code}"
                self.toasts.show(t(key), "error", 8000)
                return
            collection.reburned(entry.disc_id, tag)
            self.refresh()
            self.burn_disc(tag)
        run_async(self, lambda: media.erase(drive), done)

    # ── disc actions ──────────────────────────────────────────────────────────
    def _with_iso(self, tag: DiscTag, then, busy: str):
        self.toasts.show(busy, "info", 1800)
        run_async(self, lambda: media.make_iso(tag), lambda res: self._iso_done(res, then))

    def _iso_done(self, res, then):
        if isinstance(res, Exception):
            self.toasts.show(t("iso.failed", error=res), "error", 5000)
            return
        then(res)

    def test_disc(self, tag: DiscTag):
        """The whole path of a real disc, without burning one: the image goes in the virtual
        drive, the agent sees a disc go in, reads it, shows the card and starts the game."""
        if not host.SUPPORTED:
            self.toasts.show(t("status.unsupported"), "warning")
            return
        self.ensure_agent()

        def insert(iso: Path):
            def done(res):
                if isinstance(res, Exception):
                    self.toasts.show(t("test.failed", error=res), "error", 6000)
                    return
                self.toasts.show(t("test.inserted"), "success", 6000)
                self.refresh_status()
            modes.allow_test(tag.disc_id)    # burner mode lets this one disc through
            run_async(self, lambda: virtual.insert(iso), done)
        self._with_iso(tag, insert, t("iso.making", title=tag.title))

    def simulate_disc(self, tag: DiscTag):
        """The card and the launch, without any drive: what happens when this disc goes in."""
        def go(iso: Path):
            spawn("--prompt-image", str(iso), "--mode", "auto")
        self._with_iso(tag, go, t("iso.making", title=tag.title))

    def eject_test(self, _tag: DiscTag | None = None):
        if virtual.eject():
            self.toasts.show(t("test.ejected"), "info")
        self.refresh_status()

    def burn_disc(self, tag: DiscTag):
        drive = self._drive()
        if not drive:
            return
        name = host.drive_name(drive)

        def burn(iso: Path):
            self._busy = drive
            note = self.toasts.show(t("burn.burning", title=tag.title, drive=name), "info", 0)

            def done(res):
                self._busy = ""
                self.toasts.dismiss(note)
                if isinstance(res, Exception):
                    code = getattr(res, "code", "failed")
                    detail = getattr(res, "detail", "") or str(res)
                    self.toasts.show(t(f"burn.err_{code}", detail=detail), "error", 9000)
                    return
                collection.mark(tag.disc_id, burned=True)
                self.refresh()
                if res == "opened":
                    self.toasts.show(t("burn.opened", drive=name), "success", 6000)
                else:
                    self.toasts.show(t("burn.done", title=tag.title), "success", 9000)
                self.sync_shelf()
            run_async(self, lambda: media.burn(iso, drive, tag), done)
        self._with_iso(tag, burn, t("iso.preparing"))

    def save_iso(self, tag: DiscTag):
        def save(iso: Path):
            dst, _ = QFileDialog.getSaveFileName(self, t("action.save_iso"), str(Path.home() / iso.name), "ISO (*.iso)")
            if dst:
                Path(dst).write_bytes(iso.read_bytes())
                self.toasts.show(t("iso.saved"), "success")
        self._with_iso(tag, save, t("iso.preparing"))

    # ── pimpmysteam.com ───────────────────────────────────────────────────────
    def set_on_profile(self, store: str, game_id: str, on: bool):
        if history.set_on_profile(store, game_id, on):
            self.toasts.show(t("shelf.profile_on") if on else t("shelf.profile_off"), "info")
            if self._library_loaded:
                self.library.render()
            self.sync_shelf()

    def sync_shelf(self, force: bool = False):
        if not account.connected() or (not force and not sync.pending()):
            return

        def job():
            res = sync.sync(force)
            covers = sync.upload_covers(res.get("accepted") or [], force) if res else {}
            return res, covers

        def done(out):
            if isinstance(out, Exception):
                code = out.args[0] if isinstance(out, account.AccountError) else "server"
                self.toasts.show(t("sync.failed", error=t(f"account.err_{code}")), "warning", 6000)
                return
            res, covers = out
            if res:
                n = len(res.get("accepted") or [])
                self.toasts.show(t("sync.done", n=n) if n else t("sync.none"), "success" if n else "info", 6000)
                prof = res.get("profile") or {}
                if prof.get("cap") and prof.get("visible", 0) > prof["cap"]:
                    self.toasts.show(t("sync.profile_cap", n=prof["visible"], cap=prof["cap"]), "info", 9000)
                elif prof.get("cap"):
                    self.toasts.show(t("sync.profile_count", n=prof.get("shown", 0), cap=prof["cap"]), "info", 6000)
            if covers.get("cap"):
                self.toasts.show(t("sync.cover_cap"), "info", 8000)
            elif covers.get("sent"):
                self.toasts.show(t("sync.covers", n=covers["sent"]), "info", 5000)
        run_async(self, job, done)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.toasts.relayout()

    def closeEvent(self, e):
        if self._busy:                       # a burn or an erase is running: the disc would be lost track of
            self.toasts.show(t("burn.busy", drive=host.drive_name(self._busy)), "warning", 4500)
            e.ignore()
            return
        virtual.eject()                      # tests end with the window: game mode starts clean
        super().closeEvent(e)
