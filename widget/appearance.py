"""Skin appearance settings: the list of options, and reading/writing the user's Settings.inc.

The settings themselves are edited in Rainmeter (the GameWidget\\Settings skin, opened from the panel's cog).
Colors are "R,G,B"; translucent ones have a separate 0-255 "...Opacity" setting so the skin can set each alone.
"""

from __future__ import annotations

from pathlib import Path

# (name, default, description)
APPEARANCE = [
    ("Font", "Segoe UI", "Any installed font family"),
    ("TitleFont", "Segoe UI", "Font for the 'Games' title"),
    ("BackgroundColor", "17,18,23", "Panel background"),
    ("BackgroundOpacity", "232", "0 = invisible, 255 = solid"),
    ("BorderColor", "255,255,255", "Panel outline"),
    ("BorderOpacity", "20", ""),
    ("TextColor", "234,236,242", "Game names, hours, title"),
    ("MutedTextColor", "140,146,162", "Section labels, 'total' / 'ago' notes, update time"),
    ("WarningColor", "238,180,90", "Warning line under the title"),
    ("RecentBarColor", "122,162,247", "Bars under 'Last 2 weeks'"),
    ("MostPlayedBarColor", "122,162,247", "Bars under 'Most played'"),
    ("MostPlayedBarOpacity", "150", ""),
    ("DustBarColor", "222,172,92", "Bars under 'Gathering dust'"),
    ("BarTrackColor", "255,255,255", "Empty part of each bar"),
    ("BarTrackOpacity", "14", ""),
    ("RowHoverColor", "255,255,255", "Highlight on the row under the mouse"),
    ("RowHoverOpacity", "14", ""),
    ("ButtonColor", "217,119,87", "'What should I play?' button"),
    ("ButtonHoverColor", "231,141,110", "Button under the mouse"),
    ("ButtonTextColor", "255,255,255", "Button label"),
]

# Rows of the settings skin: (heading, [(setting, label, opacity setting or None)])
GROUPS = [
    ("Fonts", [("Font", "Text", None), ("TitleFont", "Title", None)]),
    ("Panel", [("BackgroundColor", "Background", None), ("BackgroundOpacity", "Background opacity", None),
               ("BorderColor", "Border", "BorderOpacity")]),
    ("Text", [("TextColor", "Main text", None), ("MutedTextColor", "Secondary text", None),
              ("WarningColor", "Warnings", None)]),
    ("Lines", [("RecentBarColor", "Last 2 weeks bars", None), ("MostPlayedBarColor", "Most played bars", "MostPlayedBarOpacity"),
               ("DustBarColor", "Gathering dust bars", None), ("BarTrackColor", "Bar track", "BarTrackOpacity"),
               ("RowHoverColor", "Row hover", "RowHoverOpacity")]),
    ("Button", [("ButtonColor", "Button", None), ("ButtonHoverColor", "Button hover", None),
                ("ButtonTextColor", "Button text", None)]),
]

# Preset colours in the settings skin's palette
PALETTE = [
    "255,255,255", "234,236,242", "190,195,208", "140,146,162", "90,95,110", "45,48,58", "17,18,23", "0,0,0",
    "122,162,247", "86,182,194", "126,201,140", "222,172,92", "238,180,90", "217,119,87", "231,111,111",
    "199,146,234", "245,169,184", "250,214,120",
]

SETTINGS_HEADER = """; Game Widget appearance. Easiest to change from the cog next to the panel's title.
; Colors are R,G,B (each 0-255); opacities are 0 (invisible) to 255 (solid). Delete a line for its default.
; This file is yours: it isn't overwritten by updates (the defaults live in Settings.default.inc).
[Variables]
"""


def defaults() -> dict[str, str]:
    return {name: value for name, value, _ in APPEARANCE}


def render_settings(values: dict[str, str] | None = None, with_comments: bool = True) -> str:
    values = {**defaults(), **(values or {})}
    if with_comments:
        return SETTINGS_HEADER + "\n".join(f"; {desc}\n{name}={values[name]}\n" if desc else f"{name}={values[name]}\n"
                                           for name, _, desc in APPEARANCE)
    return "\n".join(f"{name}={values[name]}" for name, _, _ in APPEARANCE)


def _decode(raw: bytes) -> str:
    return raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", "replace")


def read_settings(path: Path) -> dict[str, str]:
    """User settings over defaults. Older files had 'R,G,B,A' colours; the alpha moves to the ...Opacity setting."""
    values = defaults()
    if not path.exists():
        return values
    found: dict[str, str] = {}
    for line in _decode(path.read_bytes()).splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() in values:
            found[key.strip()] = value.strip()
    for key, value in list(found.items()):
        parts = value.split(",")
        opacity = key.removesuffix("Color") + "Opacity"
        if key.endswith("Color") and len(parts) == 4:
            found[key] = ",".join(p.strip() for p in parts[:3])
            if opacity in values:
                found.setdefault(opacity, parts[3].strip())
    values.update(found)
    return values


def write_settings(path: Path, values: dict[str, str]) -> None:
    """UTF-16 with BOM so any font name survives (Rainmeter reads ANSI or UTF-16 only)."""
    path.write_text(render_settings(values), encoding="utf-16", newline="\r\n")


def migrate(path: Path) -> bool:
    """Bring an older Settings.inc up to the current format. Returns True if it was rewritten."""
    if not path.exists():
        return False
    lines = (line.partition("=") for line in _decode(path.read_bytes()).splitlines())
    if not any(key.strip().endswith("Color") and len(value.split(",")) == 4 for key, _, value in lines):
        return False
    write_settings(path, read_settings(path))
    return True


def parse_color(value: str) -> tuple[int, int, int] | None:
    """'R,G,B' (or '#RRGGBB') -> (r, g, b); None if it isn't a colour."""
    value = value.strip()
    if value.startswith("#") and len(value) == 7:
        try:
            return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
        except ValueError:
            return None
    try:
        parts = [int(p) for p in value.split(",")]
    except ValueError:
        return None
    if len(parts) != 3 or not all(0 <= p <= 255 for p in parts):
        return None
    return parts[0], parts[1], parts[2]
