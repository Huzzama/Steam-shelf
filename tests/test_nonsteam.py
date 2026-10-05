"""Non-Steam games added to Steam: shortcuts.vdf, ids, launch."""
import zlib

from shelf import launch, library, settings, vdf
from shelf.disc import DiscTag, parse_tag
from shelf.stores import NonSteam, Steam, shortcut_app_id, shortcut_game_id


def _bin(shortcuts: list[dict]) -> bytes:
    def s(k, v): return b"\x01" + k.encode() + b"\x00" + v.encode("utf-8") + b"\x00"
    def i(k, v): return b"\x02" + k.encode() + b"\x00" + v.to_bytes(4, "little", signed=True)
    body = b""
    for n, sc in enumerate(shortcuts):
        entry = b""
        for k, v in sc.items():
            entry += i(k, v) if isinstance(v, int) else s(k, v)
        entry += b"\x00tags\x00\x08" + b"\x08"
        body += b"\x00" + str(n).encode() + b"\x00" + entry
    return b"\x00shortcuts\x00" + body + b"\x08\x08"


def test_binary_vdf_roundtrip():
    data = _bin([{"appid": -1234, "AppName": "Dolphin", "Exe": '"C:\\Dolphin\\Dolphin.exe"'}])
    d = vdf.loads_binary(data)
    sc = d["shortcuts"]["0"]
    assert sc["appname"] == "Dolphin" and sc["appid"] == -1234 and sc["tags"] == {}


def test_shortcut_ids():
    exe, name = '"C:\\Games\\Pikmin.exe"', "Pikmin 2"
    aid = shortcut_app_id(exe, name)
    assert int(aid) == (zlib.crc32((exe + name).encode()) | 0x80000000)
    assert shortcut_game_id(aid) == (int(aid) << 32) | 0x02000000


def _steam(tmp_path):
    root = tmp_path / "Steam"
    (root / "steamapps").mkdir(parents=True)
    cfg = root / "userdata" / "123" / "config"
    cfg.mkdir(parents=True)
    (cfg / "shortcuts.vdf").write_bytes(_bin([
        {"appid": -559038737, "AppName": "Pikmin 2", "Exe": '"C:\\Games\\Pikmin.exe"'},
        {"AppName": "Chrono Trigger (GOG)", "Exe": '"D:\\GOG\\ct.exe"'},          # old format: no appid
    ]))
    (cfg / "grid").mkdir()
    return root


def test_shortcuts_listed_and_launched(tmp_path, monkeypatch):
    import shelf.stores as stores
    st = Steam(_steam(tmp_path))
    ns = NonSteam(st)
    games = ns.installed_games()
    assert [g.title for g in games] == ["Chrono Trigger (GOG)", "Pikmin 2"]
    pik = next(g for g in games if g.title == "Pikmin 2")
    assert pik.game_id == str(-559038737 & 0xFFFFFFFF) and ns.is_installed(pik.game_id)
    assert ns.launch_uri(pik.game_id) == f"steam://rungameid/{shortcut_game_id(pik.game_id)}"
    assert ns.web_page(pik.game_id) == ""
    monkeypatch.setitem(stores.STORE_IMPLS, "nonsteam", ns)
    prefs = settings.load()
    assert launch.plan(DiscTag("nonsteam", pik.game_id, "Pikmin 2"), prefs).kind == "play"
    # disc from another PC: other id, same title
    other = launch.plan(DiscTag("nonsteam", "2222222222", "pikmin 2"), prefs)
    assert other.kind == "play" and other.uri == ns.launch_uri(pik.game_id)
    assert launch.plan(DiscTag("nonsteam", "2222222222", "Nope"), prefs).kind == "missing"


def test_nonsteam_tag_and_library():
    tag = DiscTag("nonsteam", "4294967295", "Dolphin")
    assert parse_tag(tag.to_json().encode()).store == "nonsteam"
    from shelf.stores import Game
    games = library.build([], [Game("nonsteam", "99", "Dolphin", True), Game("steam", "99", "Other", True)], [])
    assert len(games) == 2 and all(g.burnable for g in games)


def test_own_steam_cover_wins(tmp_path, monkeypatch):
    from PIL import Image
    import shelf.media as media
    import config
    root = _steam(tmp_path)
    grid = root / "userdata" / "123" / "config" / "grid"
    Image.new("RGB", (600, 900), "red").save(grid / "1259420p.png")
    monkeypatch.setattr(media, "Steam", lambda: Steam(root))
    monkeypatch.setattr(config, "COVERS_DIR", tmp_path / "covers")
    monkeypatch.setattr(media, "_get", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    p = media.fetch_cover("steam", "1259420")
    assert p and p.is_file() and Image.open(p).getpixel((10, 10))[0] > 200
