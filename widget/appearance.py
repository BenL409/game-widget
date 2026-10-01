"""Skin appearance settings: the list of options, and reading/writing the user's Settings.inc."""

from __future__ import annotations

from pathlib import Path

# (name, default, description). Colors are "R,G,B" or "R,G,B,Alpha" (0-255).
APPEARANCE = [
    ("Font", "Segoe UI", "Any installed font family"),
    ("TitleFont", "Segoe UI", "Font for the 'Games' title"),
    ("BackgroundColor", "17,18,23", "Panel background, R,G,B"),
    ("BackgroundOpacity", "232", "0 = invisible, 255 = solid"),
    ("BorderColor", "255,255,255,20", "Panel outline"),
    ("TextColor", "234,236,242", "Game names, hours, title"),
    ("MutedTextColor", "140,146,162", "Section labels, 'total' / 'ago' notes, update time"),
    ("WarningColor", "238,180,90", "Warning line under the title"),
    ("BarTrackColor", "255,255,255,14", "Empty part of each bar"),
    ("RecentBarColor", "122,162,247", "Bars under 'Last 2 weeks'"),
    ("MostPlayedBarColor", "122,162,247,150", "Bars under 'Most played'"),
    ("DustBarColor", "222,172,92", "Bars under 'Gathering dust'"),
    ("RowHoverColor", "255,255,255,14", "Highlight on the row under the mouse"),
    ("ButtonColor", "217,119,87", "'What should I play?' button"),
    ("ButtonHoverColor", "231,141,110", "Button under the mouse"),
    ("ButtonTextColor", "255,255,255", "Button label"),
]

# How the appearance window groups them: (heading, [(name, label)])
GROUPS = [
    ("Fonts", [("Font", "Text"), ("TitleFont", "Title")]),
    ("Panel", [("BackgroundColor", "Background"), ("BackgroundOpacity", "Background opacity"),
               ("BorderColor", "Border")]),
    ("Text", [("TextColor", "Main text"), ("MutedTextColor", "Secondary text"), ("WarningColor", "Warnings")]),
    ("Lines", [("RecentBarColor", "Last 2 weeks bars"), ("MostPlayedBarColor", "Most played bars"),
               ("DustBarColor", "Gathering dust bars"), ("BarTrackColor", "Bar track"),
               ("RowHoverColor", "Row hover")]),
    ("Button", [("ButtonColor", "Button"), ("ButtonHoverColor", "Button hover"), ("ButtonTextColor", "Button text")]),
]

SETTINGS_HEADER = """; Game Widget appearance. Easiest to change from the cog next to the panel's title.
; Colors are R,G,B or R,G,B,Alpha (each 0-255). Delete a line to go back to its default.
; This file is yours: it isn't overwritten by updates (the defaults live in Settings.default.inc).
[Variables]
"""


def defaults() -> dict[str, str]:
    return {name: value for name, value, _ in APPEARANCE}


def render_settings(values: dict[str, str] | None = None, with_comments: bool = True) -> str:
    values = {**defaults(), **(values or {})}
    if with_comments:
        return SETTINGS_HEADER + "\n".join(f"; {desc}\n{name}={values[name]}\n" for name, _, desc in APPEARANCE)
    return "\n".join(f"{name}={values[name]}" for name, _, _ in APPEARANCE)


def read_settings(path: Path) -> dict[str, str]:
    values = defaults()
    if not path.exists():
        return values
    raw = path.read_bytes()
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", "replace")
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() in values:
            values[key.strip()] = value.strip()
    return values


def write_settings(path: Path, values: dict[str, str]) -> None:
    """UTF-16 with BOM so any font name survives (Rainmeter reads ANSI or UTF-16 only)."""
    path.write_text(render_settings(values), encoding="utf-16", newline="\r\n")


def parse_color(value: str) -> tuple[tuple[int, int, int], int | None]:
    """'R,G,B' or 'R,G,B,A' -> ((r, g, b), alpha or None). Bad input falls back to white."""
    try:
        parts = [max(0, min(255, int(p))) for p in value.split(",")]
    except ValueError:
        parts = []
    if len(parts) not in (3, 4):
        return (255, 255, 255), None
    return (parts[0], parts[1], parts[2]), (parts[3] if len(parts) == 4 else None)


def format_color(rgb: tuple[int, int, int], alpha: int | None) -> str:
    return ",".join(str(c) for c in (*rgb, alpha) if c is not None)


def is_color(name: str) -> bool:
    return name.endswith("Color")
