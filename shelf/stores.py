"""
Stores: where a disc's game lives, whether it is installed, and the URI that
launches it or opens its page. Two of them, both through Steam: Steam's own games,
and "non-Steam" games, the third-party ones you add to Steam yourself (GOG, Epic,
emulators, anything). Other launchers are deliberately not read: adding the game
to Steam is the one simple path, on Windows and on Linux.

Every URI is built from a validated id (disc.STORES), never copied from a disc.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from shelf import vdf
from shelf.disc import STORES


@dataclass
class Game:
    store: str
    game_id: str
    title: str
    installed: bool = False


class Store:
    key = ""
    label = ""

    def available(self) -> bool: ...
    def is_installed(self, game_id: str) -> bool: ...
    def is_running(self, game_id: str) -> bool: return False
    def launch_uri(self, game_id: str) -> str: ...
    def page_uri(self, game_id: str) -> str: ...
    def web_page(self, game_id: str, title: str = "") -> str: ...
    def installed_games(self) -> list[Game]: return []

    def check(self, game_id: str) -> str:
        if not STORES[self.key].match(str(game_id)):
            raise ValueError(f"bad {self.key} id {game_id!r}")
        return str(game_id)


# ── Steam ─────────────────────────────────────────────────────────────────────

def _registry(root, path: str, name: str):
    try:
        import winreg
        with winreg.OpenKey(root, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


class Steam(Store):
    key, label = "steam", "Steam"

    def __init__(self, root: Optional[Path] = None):
        self._root = root

    # where Steam is
    def root(self) -> Optional[Path]:
        if self._root:
            return self._root
        cands: list[Path] = []
        if sys.platform == "win32":
            import winreg
            for hive, path, name in [(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                                     (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                                     (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath")]:
                v = _registry(hive, path, name)
                if v:
                    cands.append(Path(v))
            cands.append(Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam")
        elif sys.platform == "darwin":
            cands.append(Path.home() / "Library" / "Application Support" / "Steam")
        else:
            home = Path.home()
            cands += [home / ".steam" / "steam", home / ".local" / "share" / "Steam", home / ".steam" / "root",
                      home / ".steam" / "debian-installation",
                      home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",   # Flatpak
                      home / "snap" / "steam" / "common" / ".local" / "share" / "Steam"]               # Snap
        for c in cands:
            if (c / "steamapps").is_dir():
                return c
        return None

    def available(self) -> bool:
        return self.root() is not None

    def libraries(self) -> list[Path]:
        root = self.root()
        if not root:
            return []
        libs = [root / "steamapps"]
        f = root / "steamapps" / "libraryfolders.vdf"
        try:
            data = vdf.lower_keys(vdf.loads(f.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            data = {}
        for entry in (data.get("libraryfolders") or {}).values():
            path = entry.get("path") if isinstance(entry, dict) else entry   # old format: "1" "D:\\Games"
            if isinstance(path, str) and path:
                p = Path(path) / "steamapps"
                if p.is_dir() and p not in libs:
                    libs.append(p)
        return libs

    def _manifest(self, app_id: str) -> Optional[dict]:
        for lib in self.libraries():
            f = lib / f"appmanifest_{app_id}.acf"
            if f.is_file():
                try:
                    return vdf.lower_keys(vdf.loads(f.read_text(encoding="utf-8", errors="replace"))).get("appstate", {})
                except OSError:
                    continue
        return None

    def is_installed(self, game_id: str) -> bool:
        m = self._manifest(self.check(game_id))
        if not m:
            return False
        try:
            return int(m.get("stateflags", "0")) & 4 == 4          # 4 = fully installed
        except ValueError:
            return False

    def is_running(self, game_id: str) -> bool:
        if sys.platform == "win32":
            import winreg
            v = _registry(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "RunningAppID")
            return str(v or "0") == self.check(game_id)
        return self.running_app_id() == self.check(game_id)

    def client_running(self) -> bool:
        """Whether the Steam client itself is open (not a game)."""
        if sys.platform == "win32":
            import ctypes
            import winreg
            pid = _registry(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam\ActiveProcess", "pid")
            if not pid:
                return False
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            h = k32.OpenProcess(0x1000, False, int(pid))         # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return False
            code = ctypes.c_ulong()
            ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
            k32.CloseHandle(h)
            return bool(ok) and code.value == 259                # STILL_ACTIVE
        return _linux_steam_running()

    def registry_files(self) -> list[Path]:
        """Linux: Steam keeps its 'registry' in ~/.steam/registry.vdf (inside the sandbox for Flatpak / Snap)."""
        home = Path.home()
        cands = [home / ".steam" / "registry.vdf",
                 home / ".var" / "app" / "com.valvesoftware.Steam" / ".steam" / "registry.vdf",
                 home / "snap" / "steam" / "common" / ".steam" / "registry.vdf"]
        root = self.root()
        if root is not None and len(root.parents) > 2:
            cands.insert(0, root.parents[2] / ".steam" / "registry.vdf")
        out: list[Path] = []
        for c in cands:
            if c not in out and c.is_file():
                out.append(c)
        return out

    def running_app_id(self) -> str:
        """The game Steam is running ('0' for none), from the newest registry.vdf (Linux)."""
        files = self.registry_files()
        if not files:
            return "0"
        f = max(files, key=lambda x: x.stat().st_mtime)
        try:
            data = vdf.lower_keys(vdf.loads(f.read_text(encoding="utf-8", errors="replace")))
        except (OSError, ValueError):
            return "0"
        node = data
        for k in ("registry", "hkcu", "software", "valve", "steam"):
            node = node.get(k) if isinstance(node, dict) else None
        v = node.get("runningappid") if isinstance(node, dict) else None
        return str(v or "0").strip()

    def launch_uri(self, game_id: str) -> str:
        return f"steam://rungameid/{self.check(game_id)}"

    def page_uri(self, game_id: str) -> str:
        return f"steam://store/{self.check(game_id)}"

    def install_uri(self, game_id: str) -> str:
        return f"steam://install/{self.check(game_id)}"

    def web_page(self, game_id: str, title: str = "") -> str:
        return f"https://store.steampowered.com/app/{self.check(game_id)}/"

    def custom_cover(self, app_id: str) -> Optional[Path]:
        """The portrait you set in Steam for this game (Grunge Editor writes it there):
        userdata/<user>/config/grid/<appid>p.png|jpg. The most recent one wins."""
        root = self.root()
        if not root or not STORES["steam"].match(str(app_id)):
            return None
        best = None
        for d in (root / "userdata").glob("*/config/grid"):
            for ext in ("png", "jpg", "jpeg", "webp"):
                f = d / f"{app_id}p.{ext}"
                if f.is_file() and (best is None or f.stat().st_mtime > best.stat().st_mtime):
                    best = f
        return best

    def cached_cover(self, app_id: str) -> Optional[Path]:
        """The portrait Steam keeps in appcache/librarycache (people also drop their own art there).
        Old layout: librarycache/<appid>_library_600x900.jpg. New layout: librarycache/<appid>/…,
        either named library_600x900*.jpg or by hash, in which case the 2:3 image is the portrait."""
        root = self.root()
        if not root or not STORES["steam"].match(str(app_id)):
            return None
        cache = root / "appcache" / "librarycache"
        cands: list[Path] = []
        for ext in ("jpg", "png", "webp"):
            cands += sorted(cache.glob(f"{app_id}_library_600x900*.{ext}"))
            cands += sorted((cache / str(app_id)).glob(f"library_600x900*.{ext}"))
        best = next((c for c in cands if c.is_file()), None)
        if best is not None:
            return best
        sub = cache / str(app_id)
        if not sub.is_dir():
            return None
        try:
            from PIL import Image
            for f in sorted(sub.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                if f.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
                    continue
                try:
                    with Image.open(f) as im:
                        w, h = im.size
                except (OSError, ValueError):
                    continue
                if w >= 300 and 1.4 <= h / w <= 1.6:
                    return f
        except OSError:
            pass
        return None

    def installed_games(self) -> list[Game]:
        out: dict[str, Game] = {}
        for lib in self.libraries():
            for f in lib.glob("appmanifest_*.acf"):
                try:
                    st = vdf.lower_keys(vdf.loads(f.read_text(encoding="utf-8", errors="replace"))).get("appstate", {})
                except OSError:
                    continue
                app_id, name = str(st.get("appid", "")), st.get("name", "")
                if not STORES["steam"].match(app_id) or not name or app_id in out:
                    continue
                if _is_tool(app_id, name):
                    continue
                flags = int(st.get("stateflags", "0") or 0) if str(st.get("stateflags", "0")).isdigit() else 0
                out[app_id] = Game("steam", app_id, name, installed=flags & 4 == 4)
        return sorted(out.values(), key=lambda g: g.title.lower())

    @staticmethod
    def cover_urls(app_id: str) -> list[str]:
        a = STORES["steam"].match(app_id) and app_id
        base = "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps"
        return [f"{base}/{a}/library_600x900_2x.jpg", f"{base}/{a}/library_600x900.jpg", f"{base}/{a}/header.jpg"] if a else []


def _linux_steam_running(proc: Path = Path("/proc")) -> bool:
    """Linux: any process called 'steam' (native, Flatpak and Snap all show up in the host's /proc)."""
    try:
        for d in proc.iterdir():
            if d.name.isdigit():
                try:
                    if (d / "comm").read_text().strip() == "steam":
                        return True
                except OSError:
                    continue
    except OSError:
        pass
    return False


# Steam installs these next to games; nobody wants a disc for them
_TOOLS = {"228980", "1070560", "1391110", "1628350", "1493710", "2180100", "2348590", "1826330", "250820"}


def _is_tool(app_id: str, name: str) -> bool:
    n = name.lower()
    return app_id in _TOOLS or "redistributable" in n or n.startswith("proton ") or "steam linux runtime" in n \
        or n.startswith("steamworks") or "soundtrack" in n


# ── Non-Steam games (added to Steam: emulators, GOG installs, anything) ─────────

@dataclass
class Shortcut:
    app_id: str          # Steam's 32-bit shortcut id, unsigned
    title: str
    exe: str
    user: str            # the userdata folder it lives in


def shortcut_app_id(exe: str, name: str) -> str:
    """How Steam numbers a shortcut when shortcuts.vdf has no 'appid' field."""
    import zlib
    return str((zlib.crc32((exe + name).encode("utf-8")) | 0x80000000) & 0xFFFFFFFF)


def shortcut_game_id(app_id: str) -> int:
    """The 64-bit id steam://rungameid wants for a shortcut."""
    return (int(app_id) << 32) | 0x02000000


class NonSteam(Store):
    """Games you added to Steam yourself ("Add a Non-Steam Game"): Steam launches them
    through steam://rungameid/<64-bit shortcut id>. Their ids depend on the path and
    name on each PC, so a disc is also matched by title when the id is not found."""
    key, label = "nonsteam", "Non-Steam"

    def __init__(self, steam: Optional[Steam] = None):
        self.steam = steam or Steam()

    def available(self) -> bool:
        return self.steam.available()

    def shortcuts(self) -> list[Shortcut]:
        root = self.steam.root()
        if not root:
            return []
        out: list[Shortcut] = []
        for f in sorted((root / "userdata").glob("*/config/shortcuts.vdf")):
            try:
                data = vdf.loads_binary(f.read_bytes())
            except OSError:
                continue
            for sc in (data.get("shortcuts") or {}).values():
                if not isinstance(sc, dict):
                    continue
                name = str(sc.get("appname") or "").strip()
                exe = str(sc.get("exe") or "")
                if not name:
                    continue
                raw = sc.get("appid")
                app_id = str(raw & 0xFFFFFFFF) if isinstance(raw, int) and raw else shortcut_app_id(exe, name)
                out.append(Shortcut(app_id, name, exe, f.parts[-3]))
        return out

    def find(self, game_id: str, title: str = "") -> Optional[Shortcut]:
        scs = self.shortcuts()
        for sc in scs:
            if sc.app_id == game_id:
                return sc
        if title:                                   # same game, other PC: ids differ, names don't
            key = title.strip().lower()
            for sc in scs:
                if sc.title.lower() == key:
                    return sc
        return None

    def is_installed(self, game_id: str) -> bool:
        return self.find(self.check(game_id)) is not None

    def launch_uri(self, game_id: str) -> str:
        return f"steam://rungameid/{shortcut_game_id(self.check(game_id))}"

    def page_uri(self, game_id: str) -> str:
        return ""                                   # nothing to buy: it is already yours

    def web_page(self, game_id: str, title: str = "") -> str:
        return ""

    def installed_games(self) -> list[Game]:
        seen: dict[str, Game] = {}
        for sc in self.shortcuts():
            seen.setdefault(sc.app_id, Game("nonsteam", sc.app_id, sc.title, installed=True))
        return sorted(seen.values(), key=lambda g: g.title.lower())

    def title_of(self, game_id: str) -> str:
        sc = self.find(str(game_id))
        return sc.title if sc else ""

    def grid_image(self, game_id: str) -> Optional[Path]:
        """The portrait art you set in Steam for the shortcut (userdata/<id>/config/grid/<appid>p.*)."""
        root = self.steam.root()
        sc = self.find(self.check(game_id))
        if not root or not sc:
            return None
        for ext in ("png", "jpg", "jpeg", "webp"):
            p = root / "userdata" / sc.user / "config" / "grid" / f"{sc.app_id}p.{ext}"
            if p.is_file():
                return p
        return None


_steam = Steam()
STORE_IMPLS: dict[str, Store] = {"steam": _steam, "nonsteam": NonSteam(_steam)}


def local_games() -> list[Game]:
    """Everything playable through Steam on this PC: Steam's games and the third-party games you
    added to it ("Add a Non-Steam Game": GOG, Epic, emulators, anything). That is the one way
    third-party games reach a disc: no launcher of their own is read."""
    out: list[Game] = []
    for key in ("steam", "nonsteam"):
        try:
            out += STORE_IMPLS[key].installed_games()
        except Exception:   # noqa: BLE001 — one launcher misbehaving must not hide the others
            continue
    return out


def store_for(key: str) -> Store:
    s = STORE_IMPLS.get(key)
    if s is None:
        raise ValueError(f"{key} discs are not supported yet")
    return s
