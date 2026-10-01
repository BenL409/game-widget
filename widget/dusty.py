"""'Installed but neglected' logic."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from .models import Game


@dataclass
class DustyGame:
    game: Game
    idle_days: int | None  # None = no last-played date at all
    score: float
    note: str = ""


def find_dusty(
    games: list[Game],
    days: int,
    now: datetime,
    tracking_started: datetime | None = None,
) -> list[DustyGame]:
    """Installed games not played for `days`+.

    Ranked by idle_days * (1 + ln(1 + hours)), so '40h in, untouched for 3 months'
    outranks a game you only poked at once. Games with no play date come last.
    Tracked (non-Steam) games with no sessions are only listed once tracking has been
    running for `days`, because before that we can't know they're neglected.
    """
    idle: list[DustyGame] = []
    never: list[DustyGame] = []
    for game in games:
        if not game.installed:
            continue
        if game.last_played:
            idle_days = (now - game.last_played).days
            if idle_days >= days:
                idle.append(DustyGame(game, idle_days, idle_days * (1 + math.log1p(game.hours))))
        elif game.tracked:
            if tracking_started and (now - tracking_started).days < days:
                continue
            never.append(DustyGame(game, None, 0.0, "no plays seen since tracking began"))
        else:
            never.append(DustyGame(game, None, 0.0, "never launched"))
    idle.sort(key=lambda d: d.score, reverse=True)
    never.sort(key=lambda d: d.game.size_bytes or 0, reverse=True)
    return idle + never
