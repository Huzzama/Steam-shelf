import json

import pytest

from shelf.disc import DiscTag, TagError, build_iso, parse_tag, read_tag, read_tag_from_iso, volume_label


def tag(**kw):
    return DiscTag(store=kw.get("store", "steam"), game_id=kw.get("game_id", "1259420"), title=kw.get("title", "Days Gone"))


def test_roundtrip():
    t = tag()
    assert parse_tag(t.to_json().encode()) == t


@pytest.mark.parametrize("change", [
    {"format": "other"}, {"version": 2}, {"store": "uplay"}, {"game_id": "123; calc.exe"},
    {"game_id": "../../x"}, {"game_id": ""}, {"disc_id": "nope"},
])
def test_rejects(change):
    d = json.loads(tag().to_json())
    d.update(change)
    with pytest.raises(TagError):
        parse_tag(json.dumps(d).encode())


def test_rejects_garbage_and_size():
    with pytest.raises(TagError):
        parse_tag(b"\x00\xff not json")
    with pytest.raises(TagError):
        parse_tag(b" " * (70 * 1024))


def test_title_is_cleaned():
    d = json.loads(tag().to_json())
    d["title"] = "Days\x00 Gone\n" + "x" * 500
    t = parse_tag(json.dumps(d).encode())
    assert "\x00" not in t.title and "\n" not in t.title and len(t.title) <= 120


def test_read_from_folder_any_case(tmp_path):
    (tmp_path / "SteamShelf").mkdir()
    (tmp_path / "SteamShelf" / "disc.json").write_text(tag().to_json(), encoding="utf-8")
    assert read_tag(tmp_path).game_id == "1259420"
    assert read_tag(tmp_path / "SteamShelf") is None      # no tag dir inside


def test_iso_roundtrip(tmp_path):
    t = tag(title="Detroit: Become Human")
    p = build_iso(t, tmp_path / "x.iso", cover_jpg=b"\xff\xd8\xff" + b"0" * 100, icon_ico=b"ico")
    assert p.stat().st_size > 2 * 1024 * 1024 and p.stat().st_size % 2048 == 0   # hidden filler + padding
    assert read_tag_from_iso(p) == t


def test_volume_label():
    assert volume_label("Detroit: Become Human") == "DETROIT_BECOME_H"
    assert volume_label("Days Gone") == "DAYS_GONE"
    assert volume_label("") == "STEAM_SHELF"
    assert len(volume_label("x" * 99)) == 16


def test_image_reader_without_mounting(tmp_path):
    """The mini ISO 9660 reader (Linux drives, virtual drive) reads what pycdlib wrote."""
    import io
    from shelf.disc import image_file, read_tag_from_image
    t = tag(title="SIGNALIS")
    p = build_iso(t, tmp_path / "s.iso", cover_jpg=b"\xff\xd8\xff" + b"1" * 3000, icon_ico=b"ico")
    with open(p, "rb") as fp:
        got, readable = read_tag_from_image(fp)
        assert readable and got == t
        cover, _ = image_file(fp, "steamshelf/cover.jpg", 1 << 20)          # names are case-insensitive
        assert cover == b"\xff\xd8\xff" + b"1" * 3000
        assert image_file(fp, "STEAMSHELF/NOPE.TXT", 100) == (None, True)
        assert image_file(fp, "README.TXT/DISC.JSON", 100) == (None, True)  # a file is not a directory
    assert read_tag_from_image(io.BytesIO(b"\0" * 80_000)) == (None, False)  # not ISO 9660 (an audio CD…)
    assert read_tag_from_image(io.BytesIO(b"")) == (None, False)


def test_image_reader_is_bounded(tmp_path):
    """A hostile disc cannot make the reader allocate or loop much."""
    import io
    from shelf import disc as d
    raw = bytearray(build_iso(tag(), tmp_path / "x.iso").read_bytes())
    pvd = 16 * 2048
    root = pvd + 156
    raw[root + 10:root + 14] = (2 ** 31).to_bytes(4, "little")              # root dir claims 2 GB
    raw[root + 2:root + 6] = (10 ** 6).to_bytes(4, "little")                # …at a sector past the end
    assert d.read_tag_from_image(io.BytesIO(bytes(raw))) == (None, True)
