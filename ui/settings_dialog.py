"""Settings: the PimpMySteam account, the language, and the few switches that decide what a disc does."""
from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QWidget

from shelf import account, artwork, autostart, family, i18n, settings
from shelf.i18n import t
from ui.async_bridge import run_async
from ui.components import Button, Card, Divider, IconButton, TextField, hbox, label, scroll_area, vbox
from ui.theme import SP


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("settings.title"))
        self.setFixedWidth(660)
        self.s = settings.load()
        self.language_changed = False
        self.account_changed = False
        outer = vbox(self, (SP["xl"],) * 4, SP["md"])
        self.inner = QWidget()
        lay = vbox(self.inner, (0, 0, SP["sm"], 0), SP["md"])
        self.scroll = scroll_area(self.inner)
        outer.addWidget(self.scroll, 1)

        # account
        lay.addWidget(label(t("settings.account"), "eyebrow"))
        self.acc = Card(padding=SP["md"], spacing=SP["sm"])
        lay.addWidget(self.acc)
        self.acc_status = label("", "body", wrap=True)
        self.acc.body.addWidget(self.acc_status)
        self.token = TextField(t("settings.token_placeholder"), icon="key-round", password=True)
        self.acc.body.addWidget(self.token)
        arow = hbox(spacing=SP["sm"])
        self.btn_get = Button(t("settings.get_token"), "link", "external-link",
                              on_click=lambda: QDesktopServices.openUrl(QUrl(account.TOKEN_PAGE)))
        arow.addWidget(self.btn_get)
        arow.addStretch()
        self.btn_connect = Button(t("settings.connect"), "primary", "link", on_click=self._connect)
        self.btn_disconnect = Button(t("settings.disconnect"), "ghost", "log-out", on_click=self._disconnect)
        arow.addWidget(self.btn_disconnect)
        arow.addWidget(self.btn_connect)
        self.acc.body.addLayout(arow)
        self.acc_help = label(t("settings.account_help"), "muted", wrap=True)
        self.acc.body.addWidget(self.acc_help)
        self._account_ui()

        # Steam Family
        lay.addWidget(label(t("settings.family"), "eyebrow"))
        self.fam = Card(padding=SP["md"], spacing=SP["sm"])
        lay.addWidget(self.fam)
        self.fam.body.addWidget(label(t("settings.family_help"), "muted", wrap=True))
        self.fam_rows = vbox(spacing=SP["xs"])
        self.fam.body.addLayout(self.fam_rows)
        frow = hbox(spacing=SP["sm"])
        self.fam_link = TextField(t("settings.family_placeholder"), icon="user")
        self.fam_link.returnPressed.connect(self._fam_add)
        frow.addWidget(self.fam_link, 1)
        self.fam_add = Button(t("settings.family_add"), "default", "plus", on_click=self._fam_add)
        frow.addWidget(self.fam_add)
        self.fam.body.addLayout(frow)
        self.fam_status = label("", "muted", wrap=True)
        self.fam.body.addWidget(self.fam_status)
        self.family_changed = False
        self._fam_ui()

        # SteamGridDB (optional)
        lay.addWidget(label(t("settings.sgdb"), "eyebrow"))
        self.sg = Card(padding=SP["md"], spacing=SP["sm"])
        lay.addWidget(self.sg)
        self.sg_status = label("", "body", wrap=True)
        self.sg.body.addWidget(self.sg_status)
        self.sg_key = TextField(t("settings.sgdb_placeholder"), icon="key-round", password=True)
        self.sg.body.addWidget(self.sg_key)
        srow = hbox(spacing=SP["sm"])
        self.sg_get = Button(t("settings.sgdb_get"), "link", "external-link",
                             on_click=lambda: QDesktopServices.openUrl(QUrl(artwork.KEY_PAGE)))
        srow.addWidget(self.sg_get)
        srow.addStretch()
        self.sg_remove = Button(t("settings.sgdb_remove"), "ghost", "trash", on_click=self._sg_remove)
        self.sg_save = Button(t("settings.sgdb_save"), "primary", "check", on_click=self._sg_save)
        srow.addWidget(self.sg_remove)
        srow.addWidget(self.sg_save)
        self.sg.body.addLayout(srow)
        self.sg_help = label(t("settings.sgdb_help"), "muted", wrap=True)
        self.sg.body.addWidget(self.sg_help)
        self._sg_ui()

        # language
        row = hbox(spacing=SP["md"])
        row.addWidget(label(t("settings.language"), "body", wrap=True), 1)
        self.lang = QComboBox()
        self.lang.addItem(t("settings.language_auto"), "auto")
        for code, name in i18n.LANGUAGES.items():
            self.lang.addItem(name, code)
        self.lang.setCurrentIndex(max(0, self.lang.findData(self.s["language"])))
        row.addWidget(self.lang)
        lay.addLayout(row)
        lay.addWidget(Divider())

        # discs
        lay.addWidget(label(t("settings.discs"), "eyebrow"))
        self.enabled = QCheckBox(t("settings.enabled"))
        self.enabled.setChecked(self.s["enabled"])
        lay.addWidget(self.enabled)
        self.auto = QCheckBox(t("settings.autostart"))
        self.auto.setChecked(autostart.enabled() if autostart.supported() else self.s["autostart"])
        self.auto.setEnabled(autostart.supported())
        lay.addWidget(self.auto)

        row = hbox(spacing=SP["md"])
        row.addWidget(label(t("settings.countdown"), "body", wrap=True), 1)
        self.countdown = QComboBox()
        self.countdown.addItem(t("settings.countdown_now"), 0)
        for secs in (5, 10, 15):
            self.countdown.addItem(t("settings.countdown_secs", n=secs), secs)
        cur = min((5, 10, 15, 0), key=lambda v: abs(v - self.s["countdown"]) if self.s["countdown"] else 99) \
            if self.s["countdown"] else 0
        self.countdown.setCurrentIndex(max(0, self.countdown.findData(cur)))
        row.addWidget(self.countdown)
        lay.addLayout(row)
        lay.addWidget(label(t("settings.countdown_help"), "muted", wrap=True))

        row = hbox(spacing=SP["md"])
        row.addWidget(label(t("settings.startup"), "body", wrap=True), 1)
        self.startup = QComboBox()
        self.startup.addItem(t("settings.startup_ask"), "ask")
        self.startup.addItem(t("settings.startup_ignore"), "ignore")
        self.startup.setCurrentIndex(0 if self.s["startup_disc"] == "ask" else 1)
        row.addWidget(self.startup)
        lay.addLayout(row)
        lay.addWidget(label(t("settings.startup_help"), "muted", wrap=True))

        row = hbox(spacing=SP["md"])
        row.addWidget(label(t("settings.missing"), "body", wrap=True), 1)
        self.missing = QComboBox()
        self.missing.addItem(t("settings.missing_store"), "store")
        self.missing.addItem(t("settings.missing_install"), "install")
        self.missing.setCurrentIndex(0 if self.s["not_installed"] == "store" else 1)
        row.addWidget(self.missing)
        lay.addLayout(row)

        lay.addStretch()
        btns = hbox(spacing=SP["sm"])
        self.btns = btns
        btns.addStretch()
        btns.addWidget(Button(t("common.cancel"), "ghost", on_click=self.reject))
        btns.addWidget(Button(t("common.save"), "primary", on_click=self._save))
        outer.addLayout(btns)

    # ── account ───────────────────────────────────────────────────────────────
    def _account_ui(self, error: str = ""):
        on = account.connected()
        if error:
            self.acc_status.setText(t(f"account.err_{error}"))
        elif on:
            self.acc_status.setText(t("settings.connected_as", user=account.username() or "?"))
        else:
            self.acc_status.setText(t("settings.not_connected"))
        self.token.setVisible(not on)
        self.btn_get.setVisible(not on)
        self.btn_connect.setVisible(not on)
        self.btn_disconnect.setVisible(on)
        self.acc_help.setVisible(not on)
        self.token.set_error(bool(error))
        QTimer.singleShot(0, self._fit)

    def _fit(self):
        """Wrapped labels need height-for-width; QDialog does not do it by itself."""
        inner = self.inner.layout()
        w = self.width() - 2 * SP["xl"]
        h = inner.heightForWidth(w) if inner.hasHeightForWidth() else inner.sizeHint().height()
        h += self.btns.sizeHint().height() + 2 * SP["xl"] + SP["md"]
        scr = self.screen().availableGeometry().height() if self.screen() else 900
        self.setFixedHeight(min(h, int(scr * 0.9)))

    def showEvent(self, e):
        super().showEvent(e)
        self._fit()

    def _connect(self):
        tok = self.token.text().strip()
        if not tok:
            self._account_ui("bad_token")
            return
        self.btn_connect.set_loading(True)

        def done(res):
            self.btn_connect.set_loading(False)
            if isinstance(res, Exception):
                code = res.args[0] if isinstance(res, account.AccountError) else "server"
                self._account_ui(code)
                return
            self.token.clear()
            self.account_changed = True
            self._account_ui()
        run_async(self, lambda: account.connect(tok), done)

    def _disconnect(self):
        account.disconnect()
        self.account_changed = True
        self._account_ui()

    # ── Steam Family ─────────────────────────────────────────────────────────
    def _fam_ui(self, error: str = ""):
        while self.fam_rows.count():
            it = self.fam_rows.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for m in family.members():
            row = hbox(spacing=SP["sm"])
            row.addWidget(label(m["name"], "body", elide=True), 1)
            row.addWidget(IconButton("x", t("settings.family_remove"), 14,
                                     on_click=lambda _c=False, sid=m["id"]: self._fam_remove(sid)))
            host = Card(padding=SP["xs"])
            host.body.addLayout(row)
            self.fam_rows.addWidget(host)
        self.fam_status.setText(t(f"family.err_{error}") if error else "")
        self.fam_link.set_error(bool(error))
        QTimer.singleShot(0, self._fit)

    def _fam_add(self):
        link = self.fam_link.text().strip()
        if not link:
            return
        self.fam_add.set_loading(True)
        me = str(account.creds().get("steam_id64") or "")

        def done(res):
            self.fam_add.set_loading(False)
            if isinstance(res, Exception):
                self._fam_ui(res.args[0] if isinstance(res, family.FamilyError) else "server")
                return
            self.fam_link.clear()
            self.family_changed = True
            self._fam_ui()
        run_async(self, lambda: family.add(link, me), done)

    def _fam_remove(self, sid: str):
        family.remove(sid)
        self.family_changed = True
        self._fam_ui()

    # ── SteamGridDB ──────────────────────────────────────────────────────────
    def _sg_ui(self, error: str = ""):
        on = artwork.has_key()
        self.sg_status.setText(t(f"cover.err_{error}") if error else
                               t("settings.sgdb_on") if on else t("settings.sgdb_off"))
        for w in (self.sg_key, self.sg_get, self.sg_save, self.sg_help):
            w.setVisible(not on)
        self.sg_remove.setVisible(on)
        self.sg_key.set_error(bool(error))
        QTimer.singleShot(0, self._fit)

    def _sg_save(self):
        k = self.sg_key.text().strip()
        if not k:
            self._sg_ui("bad_key")
            return
        self.sg_save.set_loading(True)

        def done(res):
            self.sg_save.set_loading(False)
            if isinstance(res, Exception):
                self._sg_ui(res.args[0] if isinstance(res, artwork.ArtworkError) else "server")
                return
            self.sg_key.clear()
            self._sg_ui()
        run_async(self, lambda: artwork.set_key(k), done)

    def _sg_remove(self):
        artwork.clear_key()
        self._sg_ui()

    # ── save ──────────────────────────────────────────────────────────────────
    def _save(self):
        lang = self.lang.currentData()
        self.language_changed = lang != self.s["language"]
        self.s.update(enabled=self.enabled.isChecked(), autostart=self.auto.isChecked(),
                      countdown=self.countdown.currentData(), startup_disc=self.startup.currentData(),
                      not_installed=self.missing.currentData(), language=lang)
        settings.save(self.s)
        try:
            autostart.set_enabled(self.s["autostart"])
        except OSError:
            pass
        self.accept()
