"""Shelf sync: what the app sends and how it marks the answer."""
from shelf import account, family, history, sync
from shelf.disc import DiscTag
from ui import prompt


def test_sync_sends_pending_and_marks_synced(monkeypatch):
    for f in (history._FILE, family._FILE):
        try:
            f.unlink()
        except OSError:
            pass
    account._write(account._CREDS, {"app_token": "x" * 24, "username": "ryu", "steam_id64": "1" * 17})
    family._write(family._FILE, [{"id": "2" * 17, "name": "Ana", "url": "x", "added": 0}])
    history.record("steam", "10", "Mine")
    history.record("nonsteam", "99", "Dolphin")
    sent = {}

    def fake_api(path, **k):
        sent.update(path=path, **k)
        return {"accepted": [{"store": "steam", "game_id": "10", "verified": "owned"}],
                "unverified": [], "steam_linked": True}
    monkeypatch.setattr(account, "api", fake_api)
    res = sync.sync()
    assert sent["path"] == "/shelf/sync" and sent["method"] == "POST"
    assert sent["body"]["family"] == ["2" * 17] and len(sent["body"]["items"]) == 2
    assert res["accepted"][0]["verified"] == "owned"
    h = {x["game_id"]: x for x in history.load()}
    assert h["10"]["synced"] is True and h["10"]["verified"] == "owned"
    assert h["99"]["synced"] is False                      # the server did not answer for it: sent again later
    assert [x["game_id"] for x in sync.pending()] == ["99"]


def test_prompt_image_reads_the_iso(tmp_path):
    from shelf.disc import build_iso
    p = build_iso(DiscTag("steam", "1259420", "Days Gone"), tmp_path / "x.iso")
    tag, _cover = prompt.load_image(str(p))
    assert tag and tag.title == "Days Gone"
    assert prompt.load_image(str(tmp_path / "nope.iso")) == (None, None)


def test_covers_upload_only_own_art_and_only_once(tmp_path, monkeypatch):
    from PIL import Image
    import config
    import shelf.media as media
    from shelf import artwork
    from shelf.stores import Steam
    from tests.test_nonsteam import _steam
    for f in (history._FILE, sync._STATE):
        try:
            f.unlink()
        except OSError:
            pass
    root = _steam(tmp_path)
    (root / "userdata" / "123" / "config" / "grid").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (600, 900), "blue").save(root / "userdata" / "123" / "config" / "grid" / "1259420p.png")
    monkeypatch.setattr(media, "Steam", lambda: Steam(root))
    monkeypatch.setattr(config, "COVERS_DIR", tmp_path / "covers")
    monkeypatch.setattr(media, "_get", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr(artwork, "has_key", lambda: False)
    account._write(account._CREDS, {"app_token": "x" * 24, "username": "ryu"})
    history.record("steam", "1259420", "Days Gone")          # own cover → uploaded
    history.record("steam", "620", "Portal 2")               # Steam's art only → not uploaded
    ups = []
    monkeypatch.setattr(account, "api_upload", lambda path, fn, data, mime, fields=None, **k: ups.append((path, len(data), mime)) or {})
    accepted = [{"store": "steam", "game_id": "1259420"}, {"store": "steam", "game_id": "620"}]
    r = sync.upload_covers(accepted)
    assert r == {"sent": 1, "skipped": 0, "cap": False}
    assert ups[0][0] == "/shelf/cover/steam/1259420" and ups[0][2] == "image/webp" and ups[0][1] <= sync.THUMB_MAX
    assert sync.upload_covers(accepted) == {"sent": 0, "skipped": 1, "cap": False}     # same hash: not again

    def capped(*a, **k):
        raise account.AccountError("cover_cap")
    monkeypatch.setattr(account, "api_upload", capped)
    assert sync.upload_covers(accepted, force=True)["cap"] is True
    assert sync.upload_covers(accepted)["cap"] is True                               # remembered for a day
