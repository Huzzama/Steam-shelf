"""The virtual drive and reading discs through shelf.sources, the way the agent and the card do (any OS)."""
import os

from shelf import sources, virtual
from shelf.disc import DiscTag, build_iso


def test_virtual_drive_reads_like_a_disc(tmp_path):
    tag = DiscTag("steam", "1259420", "Days Gone")
    virtual.insert(build_iso(tag, tmp_path / "t.iso", b"\xff\xd8\xff" + b"0" * 100))
    try:
        got, readable = sources.read(virtual.VIRTUAL)
        assert got.disc_id == tag.disc_id and readable
        c = sources.cover(virtual.VIRTUAL, tag.disc_id)
        assert c is not None and c.read_bytes().startswith(b"\xff\xd8\xff")
        (virtual.DIR / "junk.tmp").write_bytes(b"not an image")
        os.replace(virtual.DIR / "junk.tmp", virtual.IMAGE)
        assert sources.read(virtual.VIRTUAL) == (None, True)       # in, but no Shelf disc: stop waiting
    finally:
        virtual.eject()
    assert sources.read(virtual.VIRTUAL) == (None, False)
    assert sources.valid("/dev/sr0") and sources.valid("VIRTUAL") and sources.valid("D:")
    assert not sources.valid("/etc/passwd") and not sources.valid("/dev/sda")


def test_the_card_reads_the_virtual_drive(tmp_path):
    from ui import prompt
    tag = DiscTag("steam", "1259420", "Days Gone")
    virtual.insert(build_iso(tag, tmp_path / "t.iso", b"\xff\xd8\xff" + b"1" * 100))
    try:
        got, cover = prompt.load("VIRTUAL")
        assert got.game_id == "1259420" and cover is not None and cover.read_bytes().startswith(b"\xff\xd8\xff")
        assert prompt.load("/etc/passwd") == (None, None)
    finally:
        virtual.eject()
    assert prompt.load("VIRTUAL") == (None, None)


def test_discs_of_removed_stores_are_skipped():
    """0.7.0 could make GOG / Epic discs; 0.8.0 dropped those launchers: such entries must not break the shelf."""
    import json
    import config
    from shelf import collection
    old = config.SHELF_FILE.read_text(encoding="utf-8") if config.SHELF_FILE.exists() else None
    try:
        config.SHELF_FILE.write_text(json.dumps([
            {"disc_id": "a", "store": "gog", "game_id": "1207658924", "title": "Beneath a Steel Sky", "created": ""},
            {"disc_id": "b", "store": "steam", "game_id": "620", "title": "Portal 2", "created": ""},
            "junk"]), encoding="utf-8")
        assert [e.game_id for e in collection.load()] == ["620"]
    finally:
        if old is None:
            config.SHELF_FILE.unlink()
        else:
            config.SHELF_FILE.write_text(old, encoding="utf-8")
