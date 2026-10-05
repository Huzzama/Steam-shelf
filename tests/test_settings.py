import json

import config
from shelf import settings


def test_defaults_and_bad_values():
    config.SETTINGS_FILE.write_text(json.dumps({"countdown": 99, "startup_disc": "launch", "enabled": "yes", "x": 1}))
    s = settings.load()
    assert s["countdown"] == 30 and s["startup_disc"] == "ask" and s["enabled"] is True and "x" not in s


def test_save_roundtrip():
    s = settings.load(); s["countdown"] = 0; s["not_installed"] = "install"
    settings.save(s)
    assert settings.load()["countdown"] == 0 and settings.load()["not_installed"] == "install"
