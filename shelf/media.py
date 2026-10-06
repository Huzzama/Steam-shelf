"""
Making the disc: cover art, the drive icon, the image file, then burning it:
Windows Disc Image Burner (isoburn.exe) on Windows, xorriso on Linux. To try a
disc without burning one, the app puts the image in the virtual drive
(shelf.virtual), which the agent watches like a real drive.
"""
from __future__ import annotations

import io
import logging
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Optional

import config
from shelf.disc import DiscTag, build_iso, disc_files, volume_label
from shelf.stores import Steam

log = logging.getLogger("shelf.media")
UA = {"User-Agent": f"SteamShelf/{config.VERSION} (+https://pimpmysteam.com)"}


def _get(url: str, timeout: float = 12) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:    # noqa: S310 — https Steam URLs only
        return r.read(8 * 1024 * 1024)


def cover_path(store: str, game_id: str) -> Path:
    return config.COVERS_DIR / f"{store}_{game_id}.jpg"


def forget_cover(store: str, game_id: str) -> None:
    """Drop the cached cover (and its SteamGridDB credit) so the next fetch_cover looks again."""
    try:
        cover_path(store, game_id).unlink()
    except OSError:
        pass
    from shelf import artwork
    artwork.forget_credit(store, game_id)


def own_cover(store: str, game_id: str) -> Optional[Path]:
    """The art you set yourself in Steam: Grunge Editor's cover for a Steam game, or the
    art of a third-party game you added to Steam (userdata/<you>/config/grid/<appid>p.png)."""
    if store == "steam":
        return Steam().custom_cover(game_id)
    if store == "nonsteam":
        from shelf.stores import NonSteam
        return NonSteam().grid_image(game_id)
    return None


def fetch_cover(store: str, game_id: str) -> Optional[Path]:
    """Cached cover (JPEG, ≤ 900 px wide). Order: the art you set in Steam yourself (always
    wins, and is picked up again when it changes) → for Steam games, the portrait in Steam's
    appcache/librarycache, then Steam's 600x900 from the CDN, then the wide header → for
    third-party games, SteamGridDB by title when you gave the app a key.
    None when there is nothing (the UI shows the title instead)."""
    p = cover_path(store, game_id)
    own = own_cover(store, game_id)
    if own:
        try:
            stale = not p.is_file() or p.stat().st_size == 0 or own.stat().st_mtime > p.stat().st_mtime
        except OSError:
            stale = True
        if stale and _save_image(own, p):
            from shelf import artwork
            artwork.forget_credit(store, game_id)        # your own art: no SteamGridDB credit
        if p.is_file() and p.stat().st_size > 0:
            return p
    if p.is_file() and p.stat().st_size > 0:
        return p
    if store == "steam":
        cached = Steam().cached_cover(game_id)          # Steam's own cache (or art you dropped there)
        if cached and _save_image(cached, p):
            return p
        urls = Steam.cover_urls(game_id)
        for u in urls:                                  # 600x900 (2x, 1x), then the wide header
            if _save_jpeg(u, p):
                return p
        return None
    from shelf import artwork                           # third-party: the community's covers, credited
    if artwork.has_key():
        try:
            grids = artwork.grids(store, game_id)
        except artwork.ArtworkError:
            grids = []
        if grids and artwork.use(store, game_id, grids[0]):
            return p
    return None


def _save_image(src: Path, p: Path) -> bool:
    """Any image file → the cached JPEG cover (≤ 900 px wide)."""
    from PIL import Image
    try:
        with Image.open(src) as im:
            im = im.convert("RGB")
            if im.width > 900:
                im = im.resize((900, round(im.height * 900 / im.width)))
            p.parent.mkdir(parents=True, exist_ok=True)
            im.save(p, "JPEG", quality=90)
        return True
    except (OSError, ValueError):
        return False


def _save_jpeg(url: str, p: Path) -> bool:
    try:
        data = _get(url)
    except OSError:
        return False
    if data[:3] != b"\xff\xd8\xff":
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return True


def disc_assets(cover: Optional[Path]) -> tuple[Optional[bytes], Optional[bytes]]:
    """(cover.jpg ≤ 600 px wide, icon.ico) for the disc, from the cached cover."""
    if not cover or not cover.is_file():
        return None, None
    from PIL import Image
    with Image.open(cover) as im:
        im = im.convert("RGB")
        if im.width > 600:
            im = im.resize((600, round(im.height * 600 / im.width)), Image.LANCZOS)
        jpg = io.BytesIO()
        im.save(jpg, "JPEG", quality=86)
        # square icon: the cover centred on black, like a case seen from the front
        side = max(im.size)
        sq = Image.new("RGB", (side, side), (9, 9, 11))
        sq.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
        ico = io.BytesIO()
        sq.save(ico, "ICO", sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])
    return jpg.getvalue(), ico.getvalue()


def disc_payload(tag: DiscTag) -> dict[str, bytes]:
    """The files that go on this disc (shelf.disc.disc_files with the cover and icon)."""
    jpg, ico = disc_assets(fetch_cover(tag.store, tag.game_id))
    return disc_files(tag, jpg, ico)


def make_iso(tag: DiscTag) -> Path:
    cover = fetch_cover(tag.store, tag.game_id)
    jpg, ico = disc_assets(cover)
    return build_iso(tag, config.ISO_DIR / f"{tag.store}_{tag.game_id}_{tag.disc_id[:8]}.iso", jpg, ico)


# ── burning and erasing ───────────────────────────────────────────────────────

class BurnError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code          # "no_isoburn" | "no_xorriso" | "no_access" | "no_disc" | "not_blank" | "failed"
        self.detail = detail


class EraseError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code          # "no_drive" | "not_rewritable" | "no_xorriso" | "no_access" | "failed"
        self.detail = detail


_LINUX_DRIVE = re.compile(r"^/dev/sr[0-9]{1,3}$")


def burn(iso: Path, drive: str, tag: Optional[DiscTag] = None) -> str:
    """Burn the disc and wait for it (1-2 min); the disc is ejected at the end. Returns "burned".
    Windows: IMAPI2 writes the files straight to the disc (what Explorer's "Burn to disc" does;
    no image file for Windows to validate), so `tag` is needed there. Linux: xorriso burns the
    image. Raises BurnError."""
    if sys.platform == "win32":
        if tag is None:
            raise BurnError("failed", "no disc tag")
        from shelf import imapi
        imapi.burn(disc_payload(tag), volume_label(tag.title), drive)
        return "burned"
    _burn_linux(iso, drive)
    return "burned"


# Windows: IMAPI2 through PowerShell
_ERASE_PS = r"""
$ErrorActionPreference = 'Stop'
$want = '{drive}\'
$master = New-Object -ComObject IMAPI2.MsftDiscMaster2
$rec = $null
foreach ($id in $master) {{
  $r = New-Object -ComObject IMAPI2.MsftDiscRecorder2
  $r.InitializeDiscRecorder($id)
  if (@($r.VolumePathNames) -contains $want) {{ $rec = $r }}
}}
if ($rec -eq $null) {{ Write-Output 'NO_DRIVE'; exit 2 }}
$er = New-Object -ComObject IMAPI2.MsftDiscFormat2Erase
if (-not $er.IsCurrentMediaSupported($rec)) {{ Write-Output 'NOT_REWRITABLE'; exit 3 }}
$er.Recorder = $rec
$er.ClientName = 'Steam Shelf'
$er.FullErase = $false
$er.EraseMedia()
Write-Output 'ERASED'
"""


def erase(drive: str) -> None:
    """Quick-erase a CD-RW / DVD-RW / DVD+RW / BD-RE in `drive` (~1-2 min). CD-R and DVD-R
    cannot be erased. Windows: IMAPI2. Linux: xorriso. Raises EraseError."""
    if sys.platform.startswith("linux"):
        _erase_linux(drive)
        return
    if sys.platform != "win32":
        raise EraseError("failed")
    if not re.fullmatch(r"[A-Z]:", drive.upper()):
        raise EraseError("no_drive")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                        _ERASE_PS.format(drive=drive.upper())],
                       capture_output=True, text=True, timeout=900, creationflags=0x08000000)
    out = (r.stdout or "").strip().splitlines()
    last = out[-1] if out else ""
    if last == "ERASED":
        return
    raise EraseError({"NO_DRIVE": "no_drive", "NOT_REWRITABLE": "not_rewritable"}.get(last, "failed"))


# ── Linux: xorriso ────────────────────────────────────────────────────────────
# xorriso (libburnia) burns CD, DVD and BD on any distribution: "sudo apt install xorriso",
# "sudo dnf install xorriso", "sudo pacman -S libisoburn". It needs read/write access to
# /dev/srN, which a desktop login gives the user at the seat (or the cdrom/optical group).

_OVERWRITEABLE = ("DVD+RW", "DVD-RW restricted overwrite", "DVD-RAM", "BD-RE")


def xorriso() -> Optional[str]:
    return shutil.which("xorriso")


def media_state(text: str) -> dict:
    """What `xorriso -outdev /dev/srN -toc` says about the disc:
    {"present", "blank", "profile", "overwriteable", "rewritable"}."""
    profile = status = ""
    for line in text.splitlines():
        if line.startswith("Media current:"):
            profile = line.split(":", 1)[1].strip()
        elif line.startswith("Media status :"):
            status = line.split(":", 1)[1].strip()
    present = bool(profile) and "is not present" not in profile and "is not present" not in status
    overwriteable = "overwriteable" in profile or any(profile.startswith(p) for p in _OVERWRITEABLE)
    rewritable = overwriteable or any(k in profile.split(",")[0] for k in ("RW", "BD-RE", "RAM"))
    return {"present": present, "blank": present and status.startswith("is blank"), "profile": profile,
            "overwriteable": overwriteable, "rewritable": rewritable}


def _last_problem(text: str) -> str:
    """The line worth showing from xorriso's chatter: its last FAILURE/SORRY."""
    hits = [line.split(":", 2)[-1].strip() for line in text.splitlines()
            if " : FAILURE : " in line or " : SORRY : " in line or " : FATAL : " in line]
    return (hits[-1] if hits else "")[:200]


def _run(args: list[str], timeout: float) -> tuple[int, str]:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL, errors="replace")
    except subprocess.TimeoutExpired:
        return -1, "timed out"
    except OSError as e:
        return -1, str(e)
    return r.returncode, (r.stdout or "") + "\n" + (r.stderr or "")


def _mounted(dev: str) -> bool:
    real = os.path.realpath(dev)
    try:
        with open("/proc/self/mounts", encoding="utf-8", errors="replace") as f:
            return any(line.split(" ", 1)[0] in (dev, real) for line in f)
    except OSError:
        return False


def _release(dev: str) -> None:
    """The desktop mounts data discs when they go in; a mounted drive cannot be written."""
    if _mounted(dev) and shutil.which("udisksctl"):
        _run(["udisksctl", "unmount", "--block-device", dev, "--no-user-interaction"], 30)


def _prepare(drive: str, error) -> tuple[str, dict]:
    exe = xorriso()
    if not exe:
        raise error("no_xorriso")
    if not _LINUX_DRIVE.match(drive):
        raise error("no_drive" if error is EraseError else "no_disc")
    if not os.access(drive, os.R_OK | os.W_OK):
        raise error("no_access")
    _release(drive)
    rc, out = _run([exe, "-outdev", drive, "-toc"], 120)
    state = media_state(out)
    log.info("%s: %s / %s", drive, state["profile"] or "?", "blank" if state["blank"] else "written")
    if rc != 0 and not state["profile"]:
        raise error("failed", _last_problem(out) or out.strip()[-200:])
    return exe, state


def _burn_linux(iso: Path, drive: str) -> None:
    exe, state = _prepare(drive, BurnError)
    if not state["present"]:
        raise BurnError("no_disc")
    if not state["blank"] and not state["overwriteable"]:
        raise BurnError("not_blank", state["profile"])
    # cdrecord emulation: one closed session, readable in every drive; overwriteable
    # media (DVD+RW, BD-RE) are simply written again from the start
    rc, out = _run([exe, "-as", "cdrecord", "-v", "-eject", f"dev={drive}", str(iso)], 1800)
    if rc != 0:
        problem = _last_problem(out)
        low = out.lower()
        if "no media" in low or "is not present" in low:
            raise BurnError("no_disc")
        if "not blank" in low or "closed or not recordable" in low or "unsuitable for writing" in low:
            raise BurnError("not_blank", problem)
        raise BurnError("failed", problem or f"xorriso exit {rc}")


def _erase_linux(drive: str) -> None:
    exe, state = _prepare(drive, EraseError)
    if not state["present"]:
        raise EraseError("no_drive")
    if state["blank"]:
        return                                        # nothing on it
    if not state["rewritable"]:
        raise EraseError("not_rewritable", state["profile"])
    rc, out = _run([exe, "-outdev", drive, "-blank", "as_needed"], 1800)
    if rc != 0:
        low = out.lower()
        if "not of erasable type" in low or "unsuitable for blanking" in low:
            raise EraseError("not_rewritable", _last_problem(out))
        raise EraseError("failed", _last_problem(out) or f"xorriso exit {rc}")
