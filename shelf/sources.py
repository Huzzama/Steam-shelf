"""
Reading a disc, whatever holds it:

  "D:"        a Windows drive letter: the disc's files, as Windows mounted them
  "/dev/sr0"  a Linux drive: read raw (shelf.disc's ISO 9660 reader), no mount needed
  "VIRTUAL"   the virtual drive of "Test with a virtual disc": an image file

The agent and the countdown card both read through here.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional

import config
from shelf import virtual
from shelf.disc import DiscTag, TAG_DIR, find_tag_file, image_file, read_tag, read_tag_from_image

COVER_LIMIT = 4 * 1024 * 1024
_VALID = re.compile(r"^(?:[A-Za-z]:|/dev/sr[0-9]{1,3}|VIRTUAL)$")


def valid(drive: str) -> bool:
    """A drive name the agent can hand over (the card gets it on its command line)."""
    return bool(_VALID.match(drive or ""))


def kind(drive: str) -> str:
    if drive.upper() == virtual.VIRTUAL:
        return "virtual"
    if drive.startswith("/dev/"):
        return "device"
    return "letter"


def drive_root(drive: str) -> Path:
    return Path(drive + "\\")


def _open(drive: str):
    return open(virtual.IMAGE if kind(drive) == "virtual" else drive, "rb")


def read(drive: str, volume_info: Optional[Callable] = None) -> tuple[Optional[DiscTag], bool]:
    """(tag, readable). readable: waiting longer will not bring a tag, because the disc was read
    (with or without one) or because the drive is ready with a disc that holds no data (a music CD).
    Raises TagError for a Steam Shelf disc whose tag is bad."""
    k = kind(drive)
    if k == "letter":
        tag = read_tag(drive_root(drive))
        readable = tag is not None or (volume_info is not None and volume_info(drive) is not None)
        return tag, readable
    try:
        with _open(drive) as fp:
            tag, readable = read_tag_from_image(fp)
    except OSError:                  # no disc yet, spinning up, ejected, no permission
        tag, readable = None, False
    if not readable:                 # a ready disc that is not a data disc (music CD), a junk image
        readable = virtual.inserted() if k == "virtual" else \
            volume_info is not None and volume_info(drive) is not None
    return tag, readable


def cover(drive: str, disc_id: str) -> Optional[Path]:
    """The cover burned on the disc (COVER.JPG), as a file this PC can show."""
    if kind(drive) == "letter":
        f = find_tag_file(drive_root(drive))
        c = f.with_name("COVER.JPG") if f is not None else None
        return c if c is not None and c.is_file() else None
    try:
        with _open(drive) as fp:
            data, _ = image_file(fp, f"{TAG_DIR}/COVER.JPG", COVER_LIMIT)
    except OSError:
        return None
    if not data or len(data) > COVER_LIMIT or data[:3] != b"\xff\xd8\xff":
        return None
    out = config.COVERS_DIR / f"disc_{disc_id}.jpg"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
    except OSError:
        return None
    return out
