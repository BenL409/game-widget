from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Game:
    """One game from any source (steam, epic, gog, xbox, other)."""

    id: str  # e.g. "steam:620", "epic:Fortnite", "xbox:Halo Infinite"
    name: str
    source: str
    installed: bool = False
    install_path: str | None = None
    size_bytes: int | None = None
    playtime_minutes: int = 0
    recent_minutes: int = 0  # last 2 weeks
    last_played: datetime | None = None  # timezone-aware UTC
    tracked: bool = False  # True when playtime comes from our own process tracker

    @property
    def hours(self) -> float:
        return self.playtime_minutes / 60
