"""
The disc format. A Steam Shelf disc is an ordinary data CD/DVD with:

    /STEAMSHELF/DISC.JSON   which game this disc is (the only file we read)
    /STEAMSHELF/COVER.JPG   the cover, shown in the "starting" card
    /STEAMSHELF/ICON.ICO    the drive icon in Explorer
    /AUTORUN.INF            label + icon only (Windows never runs anything from it, and neither do we)
    /README.TXT             a line for whoever opens the disc in Explorer

DISC.JSON is untrusted input: anyone can burn a disc. read_tag() accepts only
known stores and ids that match a strict pattern, and nothing on the disc is
ever executed; the launch URI is built by us from the validated id.
"""
from __future__ import annotations

import io
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

FORMAT = "steam-shelf-disc"
FORMAT_VERSION = 1
TAG_DIR = "STEAMSHELF"
TAG_FILE = "DISC.JSON"
MAX_TAG_BYTES = 64 * 1024

# store -> what a valid game id looks like
STORES = {
    "steam": re.compile(r"^[0-9]{1,10}$"),            # app id
    "nonsteam": re.compile(r"^[0-9]{1,10}$"),         # a third-party game added to Steam (its shortcut app id)
}

_CTRL = re.compile(r"[\x00-\x1f\x7f]")


class TagError(ValueError):
    """The disc has a tag but it is not one we accept."""


@dataclass(frozen=True)
class DiscTag:
    store: str
    game_id: str
    title: str
    disc_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    app: str = ""

    def to_json(self) -> str:
        d = {"format": FORMAT, "version": FORMAT_VERSION, **asdict(self)}
        return json.dumps(d, ensure_ascii=False, indent=2)

    @property
    def key(self) -> str:
        return f"{self.store}:{self.game_id}"


def clean_title(title: str, limit: int = 120) -> str:
    return _CTRL.sub("", str(title or "")).strip()[:limit]


def parse_tag(raw: bytes) -> DiscTag:
    """Validate DISC.JSON bytes. Raises TagError with a reason the log can show."""
    if len(raw) > MAX_TAG_BYTES:
        raise TagError("tag too large")
    try:
        d = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise TagError(f"not JSON: {e}") from None
    if not isinstance(d, dict) or d.get("format") != FORMAT:
        raise TagError("not a Steam Shelf disc")
    if d.get("version") != FORMAT_VERSION:
        raise TagError(f"unsupported version {d.get('version')!r}")
    store = d.get("store")
    if store not in STORES:
        raise TagError(f"unknown store {store!r}")
    game_id = str(d.get("game_id", ""))
    if not STORES[store].match(game_id):
        raise TagError(f"bad {store} id {game_id!r}")
    disc_id = str(d.get("disc_id", ""))
    try:
        disc_id = str(uuid.UUID(disc_id))
    except ValueError:
        raise TagError("bad disc_id") from None
    return DiscTag(store=store, game_id=game_id, title=clean_title(d.get("title", "")) or f"{store} {game_id}",
                   disc_id=disc_id, created=clean_title(d.get("created", ""), 40), app=clean_title(d.get("app", ""), 60))


def find_tag_file(root: Path) -> Optional[Path]:
    """STEAMSHELF/DISC.JSON under a drive root, whatever the case of the names."""
    try:
        for d in root.iterdir():
            if d.is_dir() and d.name.upper() == TAG_DIR:
                for f in d.iterdir():
                    if f.is_file() and f.name.upper().split(";")[0] == TAG_FILE:
                        return f
    except OSError:
        return None
    return None


def read_tag(root: Path) -> Optional[DiscTag]:
    """The tag on a mounted disc, None if it is not a Steam Shelf disc. Raises TagError if it looks like one but is bad."""
    f = find_tag_file(root)
    if f is None:
        return None
    try:
        with open(f, "rb") as fh:
            raw = fh.read(MAX_TAG_BYTES + 1)
    except OSError:
        return None
    return parse_tag(raw)


# ── building the disc image ───────────────────────────────────────────────────

def volume_label(title: str) -> str:
    """Volume id: A-Z 0-9 _, 16 chars (the Joliet limit). Explorer shows the autorun label, which can be longer."""
    s = re.sub(r"[^A-Z0-9]+", "_", clean_title(title).upper()).strip("_")
    return (s or "STEAM_SHELF")[:16].rstrip("_")


def _autorun(title: str, has_icon: bool) -> bytes:
    # only cosmetic keys; Windows ignores open=/shellexecute= on optical media since Win7 and we never write them
    label = re.sub(r"[\r\n=\[\]]", " ", clean_title(title))[:32] or "Steam Shelf"
    lines = ["[autorun]", f"label={label}"]
    if has_icon:
        lines.append(f"icon={TAG_DIR}\\ICON.ICO")
    return ("\r\n".join(lines) + "\r\n").encode("utf-8-sig")


def build_iso(tag: DiscTag, out: Path, cover_jpg: Optional[bytes] = None, icon_ico: Optional[bytes] = None) -> Path:
    """Write the disc image (ISO 9660 + Joliet), padded to a size Windows mounts happily. Fits any CD-R."""
    import pycdlib

    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=3, joliet=3, vol_ident=volume_label(tag.title),
            app_ident_str="STEAM SHELF", preparer_ident_str="PIMPMYSTEAM.COM")

    def add(data: bytes, iso_path: str, joliet_path: str):
        iso.add_fp(io.BytesIO(data), len(data), iso_path, joliet_path=joliet_path)

    iso.add_directory(f"/{TAG_DIR}", joliet_path=f"/{TAG_DIR}")
    add(tag.to_json().encode("utf-8"), f"/{TAG_DIR}/{TAG_FILE};1", f"/{TAG_DIR}/{TAG_FILE}")
    if cover_jpg:
        add(cover_jpg, f"/{TAG_DIR}/COVER.JPG;1", f"/{TAG_DIR}/COVER.JPG")
    if icon_ico:
        add(icon_ico, f"/{TAG_DIR}/ICON.ICO;1", f"/{TAG_DIR}/ICON.ICO")
    add(_autorun(tag.title, bool(icon_ico)), "/AUTORUN.INF;1", "/AUTORUN.INF")
    readme = (f"{clean_title(tag.title)}\r\n\r\nThis disc was made with Steam Shelf (pimpmysteam.com).\r\n"
              f"Put it in a PC running Steam Shelf and the game starts.\r\n")
    add(readme.encode("utf-8"), "/README.TXT;1", "/README.TXT")
    # Windows' virtual DVD refuses tiny volumes: a hidden 2 MB filler makes the volume
    # itself that big (padding only the file was not enough; the descriptor must say so)
    add(b"\0" * MIN_IMAGE, f"/{TAG_DIR}/PAD.BIN;1", f"/{TAG_DIR}/PAD.BIN")
    try:
        iso.set_hidden(iso_path=f"/{TAG_DIR}/PAD.BIN;1")
        iso.set_hidden(joliet_path=f"/{TAG_DIR}/PAD.BIN")
    except Exception:          # noqa: BLE001 — hiding is cosmetic
        pass

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    iso.write(str(tmp))
    iso.close()
    _pad(tmp)
    tmp.replace(out)
    return out


MIN_IMAGE = 2 * 1024 * 1024        # size of the hidden filler inside the volume
PAD_SECTORS = 150                  # trailing padding after the volume (mkisofs -pad): drives read past the end


def _pad(path: Path) -> None:
    size = path.stat().st_size
    want = size + PAD_SECTORS * 2048
    want += (-want) % 2048
    with open(path, "ab") as f:
        left = want - size
        block = b"\0" * 65536
        while left > 0:
            f.write(block[:min(left, len(block))])      # real zeros, not a sparse file
            left -= len(block)


# ── reading a disc without mounting it ────────────────────────────────────────
# A tiny ISO 9660 reader: from a raw drive (/dev/sr0 on Linux) or an image file it
# finds /STEAMSHELF/<name> in a handful of sector reads. No mount, no root, no
# walk of the whole disc (a game DVD can hold thousands of files). Everything it
# reads is bounded: the disc is untrusted.

SECTOR = 2048
_MAX_DIR = 256 * 1024          # bytes of one directory we are willing to read


class _Image:
    def __init__(self, fp, block: int = SECTOR):
        self.fp, self.block = fp, block

    def read(self, lba: int, size: int) -> bytes:
        if lba < 0 or size < 0:
            return b""
        self.fp.seek(lba * self.block)
        return self.fp.read(size)


def _both32(b: bytes, off: int) -> int:
    return int.from_bytes(b[off:off + 4], "little")


def _records(buf: bytes, block: int):
    """Directory records of one directory extent: (name, is_dir, lba, size)."""
    i = 0
    while i < len(buf):
        n = buf[i]
        if n == 0:                                   # padding up to the next sector
            i = (i // block + 1) * block
            continue
        rec = buf[i:i + n]
        i += n
        if len(rec) < 34:
            break
        name_len = rec[32]
        raw = rec[33:33 + name_len]
        if raw in (b"\x00", b"\x01"):              # "." and ".."
            continue
        yield raw, bool(rec[25] & 0x02), _both32(rec, 2), _both32(rec, 10)


def _volume(img: _Image) -> Optional[tuple[int, int, bool]]:
    """(root lba, root size, joliet) of the best volume descriptor; None if this is not ISO 9660."""
    primary = joliet = None
    for n in range(16, 32):                          # descriptors start at sector 16, end with type 255
        d = img.read(n, SECTOR)
        if len(d) < SECTOR or d[1:6] != b"CD001":
            break
        kind = d[0]
        if kind == 255:
            break
        root = d[156:190]
        entry = (_both32(root, 2), _both32(root, 10), int.from_bytes(d[128:130], "little") or SECTOR)
        if kind == 1 and primary is None:
            primary = entry
        elif kind == 2 and d[88:90] == b"%/" and joliet is None:      # Joliet: UCS-2 names
            joliet = entry
    best, is_joliet = (primary, False) if primary else (joliet, True)
    if best is None:
        return None
    lba, size, block = best
    if block not in (512, 1024, 2048):
        return None
    img.block = block
    return lba, size, is_joliet


def _name(raw: bytes, joliet: bool) -> str:
    try:
        s = raw.decode("utf-16-be") if joliet else raw.decode("ascii", "replace")
    except UnicodeDecodeError:
        return ""
    return s.split(";")[0].rstrip(".").upper()


def image_file(fp, path: str, limit: int) -> tuple[Optional[bytes], bool]:
    """(content of `path` or None, whether the medium is a readable ISO 9660 volume).
    `path` like "STEAMSHELF/DISC.JSON"; at most `limit` + 1 bytes are read."""
    img = _Image(fp)
    try:
        vol = _volume(img)
        if vol is None:
            return None, False
        lba, size, joliet = vol
        parts = [p.upper() for p in path.split("/") if p]
        for i, part in enumerate(parts):
            listing = img.read(lba, min(size, _MAX_DIR))
            last = i == len(parts) - 1
            hit = next(((l, s) for raw, is_dir, l, s in _records(listing, img.block)
                        if _name(raw, joliet) == part and is_dir != last), None)
            if hit is None:
                return None, True
            lba, size = hit
        return img.read(lba, min(size, limit + 1)), True
    except (OSError, ValueError, OverflowError):
        return None, False


def read_tag_from_image(fp) -> tuple[Optional[DiscTag], bool]:
    """(tag, readable) from a raw drive or an image file. Raises TagError like read_tag."""
    raw, readable = image_file(fp, f"{TAG_DIR}/{TAG_FILE}", MAX_TAG_BYTES)
    return (parse_tag(raw) if raw is not None else None), readable


def read_tag_from_iso(path: Path) -> Optional[DiscTag]:
    """Same check as read_tag, straight from an image file."""
    try:
        with open(path, "rb") as fp:
            return read_tag_from_image(fp)[0]
    except OSError:
        return None
