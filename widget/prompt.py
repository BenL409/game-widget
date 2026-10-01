"""Builds the 'inspire me' prompt and the claude.ai link that opens with it prefilled."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

from . import fmt
from .dusty import DustyGame
from .models import Game

CLAUDE_NEW_CHAT = "https://claude.ai/new"
MAX_URL_LEN = 1800  # Windows shell-opens longer URLs unreliably; we fall back to clipboard-only
_VAGUE_GENRES = {"indie", "free to play", "early access", "massively multiplayer"}


def _name(game: Game) -> str:
    return game.name if len(game.name) <= 40 else game.name[:37] + "..."


def _session(minutes: int) -> str:
    return f"~{minutes}m" if minutes < 60 else f"~{fmt.hours(minutes)}"


def when(now: datetime) -> str:
    h = now.hour
    part = "night" if h < 5 or h >= 22 else "morning" if h < 12 else "afternoon" if h < 17 else "evening"
    return f"It's {now:%A} {part}, {now:%H:%M}."


def candidates(games: list[Game], dusty: list[DustyGame], n: int = 6) -> tuple[list[Game], list[Game], list[DustyGame]]:
    recent = sorted((g for g in games if g.recent_minutes > 0), key=lambda g: -g.recent_minutes)[:n]
    top = sorted((g for g in games if g.playtime_minutes > 0), key=lambda g: -g.playtime_minutes)[:n]
    return recent, top, dusty[:n]


def vr_games(games: list[Game], n: int = 6) -> list[Game]:
    """Installed VR games, most played first."""
    return sorted((g for g in games if g.vr and g.installed), key=lambda g: -g.playtime_minutes)[:n]


def build_prompt(games: list[Game], dusty: list[DustyGame], max_items: int = 6, now: datetime | None = None) -> str:
    recent, top, neglected = candidates(games, dusty, max_items)
    described: set[str] = set()  # genres + session length only on a game's first mention, to save URL space

    def describe(game: Game, stats: str) -> str:
        extras = []
        if game.id not in described:
            described.add(game.id)
            genres = [g for g in game.genres if g.lower() not in _VAGUE_GENRES][:2]
            if genres:
                extras.append("/".join(genres))
            if game.avg_session_minutes:
                stats += f", usual session {_session(game.avg_session_minutes)}"
        tag = f" [{extras[0]}]" if extras else ""
        return f"{_name(game)}{tag} ({stats})"

    now = now or datetime.now()
    now_utc = now.astimezone(timezone.utc)
    lines = ["I can't decide what to play. " + when(now), "", "My library:"]
    if recent:
        lines.append("Played in the last 2 weeks: "
                     + ", ".join(describe(g, fmt.hours(g.recent_minutes)) for g in recent))
    if top:
        lines.append("Most played overall: " + ", ".join(describe(g, fmt.hours(g.playtime_minutes)) for g in top))
    if neglected:
        parts = []
        for d in neglected:
            stats = d.note if d.idle_days is None else f"{fmt.hours(d.game.playtime_minutes)} played, idle {fmt.idle(d.idle_days)}"
            parts.append(describe(d.game, stats))
        lines.append("Installed but untouched for a while: " + ", ".join(parts))
    vr = vr_games(games, max_items)
    if vr:
        parts = [describe(g, f"{fmt.hours(g.playtime_minutes)} total, last played {fmt.ago(g.last_played, now_utc)}"
                          if g.last_played else f"{fmt.hours(g.playtime_minutes)} total")
                 for g in vr]
        lines.append("VR games (headset on, longer and more committed sessions): " + ", ".join(parts))
    lines += [
        "",
        "Start by asking me one or two quick questions (mood, how long I've got), then suggest "
        "three options from my own list, including at least one neglected game. Use the genres, my usual "
        "session lengths and the time of day to fit tonight. Only suggest a VR game if my answers say I've "
        "got the time and energy for it. If something that isn't a game would suit me better, say so.",
    ]
    return "\n".join(lines)


def build_inspiration(games: list[Game], dusty: list[DustyGame], now: datetime | None = None) -> tuple[str, str, bool]:
    """Returns (prompt, url, prefilled). Shrinks the lists until the URL fits."""
    for items in (6, 5, 4, 3, 2):
        prompt = build_prompt(games, dusty, items, now)
        url = f"{CLAUDE_NEW_CHAT}?q={quote(prompt)}"
        if len(url) <= MAX_URL_LEN:
            return prompt, url, True
    return build_prompt(games, dusty, 6, now), CLAUDE_NEW_CHAT, False
