"""Minimal reader for Valve's text KeyValues (libraryfolders.vdf, appmanifest_*.acf)."""
from __future__ import annotations

import re

_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])|//[^\n]*|(\S+)')


def loads(text: str) -> dict:
    root: dict = {}
    stack = [root]
    key = None
    for m in _TOKEN.finditer(text):
        quoted, brace, bare = m.groups()
        if brace == "{":
            new: dict = {}
            if key is not None:
                stack[-1][key] = new
                key = None
            stack.append(new)
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        elif quoted is not None or bare is not None:
            if m.group(0).startswith("//"):
                continue
            val = (quoted if quoted is not None else bare)
            if quoted is not None:
                val = val.replace('\\\\', '\\').replace('\\"', '"')
            if key is None:
                key = val
            else:
                stack[-1][key] = val
                key = None
    return root


def lower_keys(d):
    """Valve is not consistent about key case (AppState vs appstate)."""
    if isinstance(d, dict):
        return {k.lower(): lower_keys(v) for k, v in d.items()}
    return d


# ── binary KeyValues (userdata/<id>/config/shortcuts.vdf) ─────────────────────
_T_MAP, _T_STR, _T_INT, _T_END = 0x00, 0x01, 0x02, 0x08


def loads_binary(data: bytes) -> dict:
    """Valve's binary KeyValues: maps of strings / int32 (what shortcuts.vdf uses).
    Keys are lower-cased. Unknown value types stop the parse (what was read is kept)."""
    pos = 0
    root: dict = {}
    stack = [root]

    def cstr() -> str:
        nonlocal pos
        end = data.find(b"\x00", pos)
        if end < 0:
            raise ValueError("unterminated string")
        s = data[pos:end].decode("utf-8", "replace")
        pos = end + 1
        return s

    try:
        while pos < len(data) and stack:
            t = data[pos]
            pos += 1
            if t == _T_END:
                stack.pop()
                continue
            key = cstr().lower()
            if t == _T_MAP:
                new: dict = {}
                stack[-1][key] = new
                stack.append(new)
            elif t == _T_STR:
                stack[-1][key] = cstr()
            elif t == _T_INT:
                stack[-1][key] = int.from_bytes(data[pos:pos + 4], "little", signed=True)
                pos += 4
            else:
                break
    except (ValueError, IndexError):
        pass
    return root
