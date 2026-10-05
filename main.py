"""
Steam Shelf: put a disc in, the game starts.

    python main.py                      the app (your shelf, new discs, settings)
    python main.py --agent              the background watcher (starts when you log in)
    python main.py --prompt D: --mode auto|ask   the "starting…" card (the agent opens it;
                                                 /dev/sr0 on Linux, VIRTUAL for a test)
    python main.py --prompt-image x.iso          the same card for a disc image (no drive: "Simulate")
    python main.py --desktop-entry      Linux: put Steam Shelf in the applications menu
    python main.py --version
"""
from __future__ import annotations

import argparse
import os
import sys


def _card_platform() -> None:
    """The card sits bottom-right and stays on top. Wayland lets no app place its windows,
    so under Wayland the card asks for XWayland when there is one (and falls back)."""
    if sys.platform.startswith("linux") and os.environ.get("WAYLAND_DISPLAY") and os.environ.get("DISPLAY") \
            and not os.environ.get("QT_QPA_PLATFORM"):
        os.environ["QT_QPA_PLATFORM"] = "xcb;wayland"


def main() -> int:
    ap = argparse.ArgumentParser(prog="SteamShelf", add_help=True)
    ap.add_argument("--agent", action="store_true")
    ap.add_argument("--prompt", metavar="DRIVE")
    ap.add_argument("--prompt-image", metavar="ISO")        # the card for an image file: no drive needed
    ap.add_argument("--mode", choices=("auto", "ask"), default="auto")
    ap.add_argument("--desktop-entry", action="store_true")
    ap.add_argument("--version", action="store_true")
    args = ap.parse_args()

    import config
    if args.version:
        print(config.VERSION)
        return 0
    if args.desktop_entry:
        if not sys.platform.startswith("linux"):
            print("--desktop-entry is for Linux", file=sys.stderr)
            return 2
        from shelf import autostart
        print(autostart.install_menu_entry())
        return 0
    if args.agent:
        from shelf import agent
        return agent.main()

    if args.prompt or args.prompt_image:
        _card_platform()
    from PySide6.QtWidgets import QApplication
    from ui import theme

    from shelf import i18n, settings
    i18n.set_language(settings.load()["language"])

    app = QApplication(sys.argv)
    app.setApplicationName("Steam Shelf")
    app.setOrganizationName("PimpMySteam")
    if sys.platform.startswith("linux"):
        app.setDesktopFileName("steam-shelf")       # Wayland/X11 docks match the window to the menu entry
    theme.apply(app)

    if args.prompt or args.prompt_image:
        from ui import prompt
        return prompt.run(app, args.prompt or args.prompt_image, args.mode, image=bool(args.prompt_image))

    from PySide6.QtGui import QIcon
    from shelf import autostart
    from ui.app_window import MainWindow
    icon = config.BUNDLE_DIR / "assets" / "icon.png"
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    prefs = settings.load()
    if autostart.supported():
        try:
            if prefs["autostart"] != autostart.enabled():
                autostart.set_enabled(prefs["autostart"])
            autostart.refresh()
        except OSError:
            pass
    w = MainWindow()
    if prefs["enabled"]:
        w.ensure_agent()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
