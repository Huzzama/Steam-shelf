"""
Start the agent when you log in, without admin rights:

  Windows  one value under HKCU\\...\\Run (the user sees it in Task Manager > Startup)
  Linux    an XDG autostart entry, ~/.config/autostart/steam-shelf-agent.desktop
           (GNOME, KDE Plasma, Xfce, Cinnamon, MATE, LXQt, Budgie… show it in their
           startup settings; tiling compositors need an exec line, see the README)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import config
from shelf.launch import self_command

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "SteamShelfAgent"
DESKTOP_NAME = "steam-shelf-agent.desktop"


def supported() -> bool:
    return sys.platform == "win32" or sys.platform.startswith("linux")


def command() -> str:
    return subprocess.list2cmdline(self_command("--agent"))


# ── Linux: XDG autostart ──────────────────────────────────────────────────────

def desktop_file() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "autostart" / DESKTOP_NAME


_RESERVED = set(" \t\n\"'\\><~|&;$*?#()`")


def exec_arg(arg: str) -> str:
    """One argument of a desktop entry's Exec key (freedesktop Desktop Entry spec):
    quoted when needed, '%' doubled, then the string escaping applied to backslashes."""
    arg = arg.replace("%", "%%")
    if arg and not any(c in _RESERVED for c in arg):
        return arg
    inner = "".join("\\" + c if c in '"`$\\' else c for c in arg)
    return ('"' + inner + '"').replace("\\", "\\\\")


def desktop_entry(menu: bool = False) -> str:
    """The agent's autostart entry, or (menu=True) the app's entry for the applications menu."""
    icon = config.BUNDLE_DIR / "assets" / "icon.png"
    args = self_command() if menu else self_command("--agent")
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Name=Steam Shelf",
        "Comment=" + ("Burn your games to discs" if menu else "Put a Steam Shelf disc in, its game starts"),
        "Exec=" + " ".join(exec_arg(a) for a in args),
        "Terminal=false",
    ]
    if menu:
        lines += ["Categories=Game;", "Keywords=steam;disc;cd;dvd;burn;"]
    else:
        lines += ["NoDisplay=true", "X-GNOME-Autostart-enabled=true"]
    if icon.is_file():
        lines.append(f"Icon={icon}")
    return "\n".join(lines) + "\n"


def install_menu_entry() -> Path:
    """Linux: Steam Shelf in the applications menu (~/.local/share/applications)."""
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    f = base / "applications" / "steam-shelf.desktop"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(desktop_entry(menu=True), encoding="utf-8")
    return f


def _linux_enabled() -> bool:
    try:
        text = desktop_file().read_text(encoding="utf-8")
    except OSError:
        return False
    keys = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    return keys.get("Hidden", "false").strip().lower() != "true" and \
        keys.get("X-GNOME-Autostart-enabled", "true").strip().lower() != "false"


def _linux_set(on: bool) -> None:
    f = desktop_file()
    if on:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(desktop_entry(), encoding="utf-8")
        os.replace(tmp, f)
    else:
        try:
            f.unlink()
        except FileNotFoundError:
            pass


# ── both ──────────────────────────────────────────────────────────────────────

def enabled() -> bool:
    if sys.platform.startswith("linux"):
        return _linux_enabled()
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, VALUE)
            return True
    except OSError:
        return False


def set_enabled(on: bool) -> None:
    if sys.platform.startswith("linux"):
        _linux_set(on)
        return
    if sys.platform != "win32":
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, VALUE, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(k, VALUE)
            except OSError:
                pass


def refresh() -> None:
    """Keep the entry's command current (the app may have moved, or now runs from another venv)."""
    if sys.platform.startswith("linux") and _linux_enabled():
        try:
            if desktop_file().read_text(encoding="utf-8") != desktop_entry():
                _linux_set(True)
        except OSError:
            pass
