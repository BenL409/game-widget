"""Builds the 'inspire me' prompt and the claude.ai link that opens with it prefilled."""

from __future__ import annotations

from urllib.parse import quote

from . import fmt
from .dusty import DustyGame
from .models import Game

CLAUDE_NEW_CHAT = "https://claude.ai/new"
MAX_URL_LEN = 1800  # Windows shell-opens longer URLs unreliably; we fall back to clipboard-only


def _name(game: Game) -> str:
    return game.name if len(game.name) <= 40 else game.name[:37] + "..."


def build_prompt(games: list[Game], dusty: list[DustyGame], max_items: int = 6) -> str:
    recent = sorted((g for g in games if g.recent_minutes > 0), key=lambda g: -g.recent_minutes)[:max_items]
    top = sorted((g for g in games if g.playtime_minutes > 0), key=lambda g: -g.playtime_minutes)[:max_items]

    lines = ["I can't decide what to play tonight. My library snapshot:", ""]
    if recent:
        lines.append(
            "Played in the last 2 weeks: "
            + ", ".join(f"{_name(g)} ({fmt.hours(g.recent_minutes)})" for g in recent)
        )
    if top:
        lines.append(
            "Most played overall: " + ", ".join(f"{_name(g)} ({fmt.hours(g.playtime_minutes)})" for g in top)
        )
    if dusty:
        parts = []
        for d in dusty[:max_items]:
            if d.idle_days is None:
                parts.append(f"{_name(d.game)} ({d.note})")
            else:
                parts.append(f"{_name(d.game)} ({fmt.hours(d.game.playtime_minutes)} played, idle {fmt.idle(d.idle_days)})")
        lines.append("Installed but untouched for a while: " + ", ".join(parts))
    lines += [
        "",
        "Start by asking me one or two quick questions (mood, time available), then suggest "
        "three options from my own list, including at least one neglected game. "
        "If something that isn't a game would suit me better tonight, say so.",
    ]
    return "\n".join(lines)


def build_inspiration(games: list[Game], dusty: list[DustyGame]) -> tuple[str, str, bool]:
    """Returns (prompt, url, prefilled). Shrinks the lists until the URL fits."""
    for items in (6, 4, 3):
        prompt = build_prompt(games, dusty, items)
        url = f"{CLAUDE_NEW_CHAT}?q={quote(prompt)}"
        if len(url) <= MAX_URL_LEN:
            return prompt, url, True
    return build_prompt(games, dusty, 6), CLAUDE_NEW_CHAT, False
