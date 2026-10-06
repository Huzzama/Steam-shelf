from pathlib import Path

from shelf import vdf
from shelf.stores import Steam

LIBS = '''"libraryfolders"
{
\t"0"
\t{
\t\t"path"\t\t"%s"
\t\t"apps" { "1259420" "1" }
\t}
\t"1"
\t{
\t\t"path"\t\t"%s"
\t}
}
'''

ACF = '''"AppState"
{
\t"appid"\t\t"%s"
\t"name"\t\t"%s"
\t"StateFlags"\t\t"%s"
\t"installdir"\t\t"x"
}
'''


def fake_steam(tmp: Path) -> Steam:
    root, lib2 = tmp / "Steam", tmp / "Games"
    (root / "steamapps").mkdir(parents=True)
    (lib2 / "steamapps").mkdir(parents=True)
    (root / "steamapps" / "libraryfolders.vdf").write_text(
        LIBS % (str(root).replace("\\", "\\\\"), str(lib2).replace("\\", "\\\\")), encoding="utf-8")
    (root / "steamapps" / "appmanifest_1259420.acf").write_text(ACF % ("1259420", "Days Gone", "4"), encoding="utf-8")
    (lib2 / "steamapps" / "appmanifest_1593500.acf").write_text(ACF % ("1593500", "God of War", "6"), encoding="utf-8")
    (lib2 / "steamapps" / "appmanifest_1222140.acf").write_text(ACF % ("1222140", "Detroit: Become Human", "1026"), encoding="utf-8")
    (lib2 / "steamapps" / "appmanifest_228980.acf").write_text(ACF % ("228980", "Steamworks Common Redistributables", "4"), encoding="utf-8")
    return Steam(root)


def test_vdf_nested_and_escapes():
    d = vdf.loads('"a" { "b" "c\\\\d" "e" { "f" "1" } } // comment\n')
    assert d == {"a": {"b": "c\\d", "e": {"f": "1"}}}


def test_installed_across_libraries(tmp_path):
    s = fake_steam(tmp_path)
    assert len(s.libraries()) == 2
    assert s.is_installed("1259420")
    assert s.is_installed("1593500")          # flags 6 = installed + update queued
    assert not s.is_installed("1222140")      # 1026 = update required, not fully installed
    assert not s.is_installed("999")


def test_installed_games_skips_tools(tmp_path):
    names = [g.title for g in fake_steam(tmp_path).installed_games()]
    assert "Days Gone" in names and "Steamworks Common Redistributables" not in names


def test_uris_only_from_valid_ids(tmp_path):
    s = fake_steam(tmp_path)
    assert s.launch_uri("1259420") == "steam://rungameid/1259420"
    assert s.page_uri("1259420") == "steam://store/1259420"
    import pytest
    with pytest.raises(ValueError):
        s.launch_uri("1259420/../../x")


def test_plan(tmp_path, monkeypatch):
    from shelf import launch, stores
    from shelf.disc import DiscTag
    monkeypatch.setitem(stores.STORE_IMPLS, "steam", fake_steam(tmp_path))
    play = launch.plan(DiscTag("steam", "1259420", "Days Gone"), {"not_installed": "store"})
    assert (play.kind, play.uri) == ("play", "steam://rungameid/1259420")
    shop = launch.plan(DiscTag("steam", "1222140", "Detroit"), {"not_installed": "store"})
    assert (shop.kind, shop.uri) == ("store", "steam://store/1222140")
    inst = launch.plan(DiscTag("steam", "1222140", "Detroit"), {"not_installed": "install"})
    assert inst.kind == "install"


def test_big_picture_mode_opens_it_before_the_game(monkeypatch, tmp_path):
    from shelf import launch, settings
    from shelf.disc import DiscTag
    opened = []
    monkeypatch.setattr(launch, "open_uri", lambda uri: opened.append(uri) or True)
    st = fake_steam(tmp_path)
    monkeypatch.setattr(launch, "store_for", lambda key: st)
    monkeypatch.setattr(st, "client_running", lambda: True)
    monkeypatch.setattr(launch, "BP_SETTLE", 0.0)
    prefs = dict(settings.DEFAULTS, launch_mode="bigpicture")
    launch.run(DiscTag("steam", "1259420", "Days Gone"), prefs)
    assert opened == ["steam://open/bigpicture", "steam://rungameid/1259420"]
    opened.clear()
    launch.run(DiscTag("steam", "1259420", "Days Gone"), dict(settings.DEFAULTS))
    assert opened == ["steam://rungameid/1259420"]
    assert settings.load()["launch_mode"] == "desktop"


def test_steam_client_detected_in_proc(tmp_path):
    from shelf import stores
    (tmp_path / "123").mkdir(); (tmp_path / "123" / "comm").write_text("bash\n")
    assert not stores._linux_steam_running(tmp_path)
    (tmp_path / "124").mkdir(); (tmp_path / "124" / "comm").write_text("steam\n")
    assert stores._linux_steam_running(tmp_path)


def test_cover_from_steam_library_cache(tmp_path):
    from PIL import Image
    st = fake_steam(tmp_path)
    cache = st.root() / "appcache" / "librarycache"
    (cache / "1259420").mkdir(parents=True)
    Image.new("RGB", (920, 430)).save(cache / "1259420" / "aaaa.jpg")       # the wide header, by hash
    Image.new("RGB", (600, 900)).save(cache / "1259420" / "bbbb.jpg")       # the portrait, by hash
    assert st.cached_cover("1259420") == cache / "1259420" / "bbbb.jpg"
    Image.new("RGB", (600, 900)).save(cache / "1593500_library_600x900.jpg")  # the old layout
    assert st.cached_cover("1593500") == cache / "1593500_library_600x900.jpg"
    assert st.cached_cover("620") is None
