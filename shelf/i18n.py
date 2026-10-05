"""
Translations: the 26 languages of Steam Curator, one flat JSON per language in
locales/ (en.json is the source of truth; a missing key falls back to English).

    from shelf.i18n import t
    t("disc.starting_in", n=5)
"""
from __future__ import annotations

import json
import locale as _locale

import config

LANGUAGES = {
    "en": "English", "es": "Español", "de": "Deutsch", "fr": "Français", "pt": "Português",
    "ru": "Русский", "zh_CN": "中文 (简体)", "zh_TW": "中文 (繁體)", "ja": "日本語", "ko": "한국어",
    "tr": "Türkçe", "hi": "हिन्दी", "it": "Italiano", "nl": "Nederlands", "uk": "Українська",
    "pl": "Polski", "cs": "Čeština", "sv": "Svenska", "da": "Dansk", "fi": "Suomi", "no": "Norsk",
    "ro": "Română", "hu": "Magyar", "th": "ไทย", "vi": "Tiếng Việt", "id": "Bahasa Indonesia",
}

_DIR = config.BUNDLE_DIR / "locales"
_en: dict = {}
_cur: dict = {}
_lang = "en"


def _load(code: str) -> dict:
    try:
        return json.loads((_DIR / f"{code}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def system_language() -> str:
    """Best match for the OS language among ours."""
    try:
        from PySide6.QtCore import QLocale
        name = QLocale.system().name()            # es_MX, zh_CN, pt_BR…
    except Exception:                             # noqa: BLE001 — the agent has no Qt
        name = (_locale.getlocale()[0] or "en")
    name = name.replace("-", "_")
    if name in LANGUAGES:
        return name
    if name.startswith("zh"):
        return "zh_TW" if any(x in name for x in ("TW", "HK", "MO", "Hant")) else "zh_CN"
    if name.startswith(("nb", "nn")):
        return "no"
    base = name.split("_")[0]
    return base if base in LANGUAGES else "en"


def set_language(code: str) -> str:
    global _en, _cur, _lang
    if code in ("", "auto"):
        code = system_language()
    if code not in LANGUAGES:
        code = "en"
    _en = _load("en")
    _cur = _en if code == "en" else _load(code)
    _lang = code
    return code


def language() -> str:
    return _lang


def t(key: str, **kw) -> str:
    if not _en:
        set_language("auto")
    s = _cur.get(key) or _en.get(key) or key
    if kw:
        try:
            return s.format(**kw)
        except (KeyError, IndexError, ValueError):
            return s
    return s
