"""
Build Steam Shelf for the system this runs on:

    python tools/build.py                 PyInstaller folder + installer / AppImage
    python tools/build.py --folder-only   just dist/SteamShelf/

Windows  dist/SteamShelf/            the folder (portable: run SteamShelf.exe)
         dist/SteamShelf-<ver>-setup.exe   Inno Setup installer, if ISCC.exe is installed
                                     (https://jrsoftware.org/isinfo.php; or winget install JRSoftware.InnoSetup)
Linux    dist/SteamShelf/            the folder
         dist/SteamShelf-<ver>-x86_64.AppImage   with appimagetool (downloaded into tools/ if missing)

Needs: pip install pyinstaller (and the app's requirements) in the same venv.
Build on the oldest system you want to support: PyInstaller bundles Python and Qt but not glibc,
so an AppImage built on Ubuntu 22.04 runs on anything newer.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
APPIMAGETOOL_URL = "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"


def run(cmd: list[str], **kw) -> None:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def folder() -> Path:
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(ROOT / "steamshelf.spec")], cwd=ROOT)
    out = DIST / "SteamShelf"
    if not (out / ("SteamShelf.exe" if sys.platform == "win32" else "SteamShelf")).exists():
        sys.exit("PyInstaller produced no executable")
    return out


# ── Windows: Inno Setup ───────────────────────────────────────────────────────

def iscc() -> str | None:
    for c in (shutil.which("ISCC"), shutil.which("iscc"),
              os.path.expandvars(r"%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"),
              os.path.expandvars(r"%ProgramFiles%\Inno Setup 6\ISCC.exe"),
              os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe")):
        if c and Path(c).is_file():
            return c
    return None


def installer_windows() -> None:
    exe = iscc()
    if not exe:
        print("Inno Setup (ISCC.exe) not found: the folder dist/SteamShelf is the portable build. "
              "Install Inno Setup 6 to also get the installer.")
        return
    run([exe, f"/DAppVersion={VERSION}", f"/DSourceDir={DIST / 'SteamShelf'}", f"/DOutDir={DIST}",
         str(ROOT / "tools" / "installer.iss")])


# ── Linux: AppImage ───────────────────────────────────────────────────────────

def appimagetool() -> Path:
    tool = ROOT / "tools" / "appimagetool-x86_64.AppImage"
    if not tool.is_file():
        print("downloading appimagetool…")
        urllib.request.urlretrieve(APPIMAGETOOL_URL, tool)      # noqa: S310 — the project's own release URL
    tool.chmod(0o755)
    return tool


def appimage() -> None:
    appdir = DIST / "SteamShelf.AppDir"
    shutil.rmtree(appdir, ignore_errors=True)
    shutil.copytree(DIST / "SteamShelf", appdir / "usr" / "bin")
    (appdir / "AppRun").write_text("#!/bin/sh\n"
                                   'HERE="$(dirname "$(readlink -f "$0")")"\n'
                                   'exec "$HERE/usr/bin/SteamShelf" "$@"\n', encoding="utf-8")
    (appdir / "AppRun").chmod(0o755)
    (appdir / "steam-shelf.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Steam Shelf\nComment=Put a Steam Shelf disc in, its game starts\n"
        "Exec=SteamShelf\nIcon=steam-shelf\nTerminal=false\nCategories=Game;\nKeywords=steam;disc;cd;dvd;burn;\n",
        encoding="utf-8")
    shutil.copyfile(ROOT / "assets" / "icon.png", appdir / "steam-shelf.png")
    shutil.copyfile(ROOT / "assets" / "icon.png", appdir / ".DirIcon")
    out = DIST / f"SteamShelf-{VERSION}-x86_64.AppImage"
    env = dict(os.environ, ARCH="x86_64")
    tool = appimagetool()
    try:
        run([str(tool), "--no-appstream", str(appdir), str(out)], env=env)
    except (OSError, subprocess.CalledProcessError):
        # no FUSE (containers, some distros): the AppImage can extract itself and run from there
        run([str(tool), "--appimage-extract-and-run", "--no-appstream", str(appdir), str(out)], env=env)
    out.chmod(0o755)
    print("built", out)


def main() -> int:
    folder()
    if "--folder-only" in sys.argv:
        return 0
    if sys.platform == "win32":
        installer_windows()
    elif sys.platform.startswith("linux"):
        appimage()
    return 0


if __name__ == "__main__":
    sys.exit(main())
