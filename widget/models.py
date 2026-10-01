from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
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
    launch: str | None = None  # URI or exe from the launcher's data (Steam's is derived from the id)
    uninstall: str | None = None  # uninstall command from the launcher's data, when it has one
    genres: list[str] = field(default_factory=list)
    avg_session_minutes: int | None = None  # from tracked sessions; None until we've seen some
    vr: bool = False  # set from config: needs the headset and a longer session

    @property
    def hours(self) -> float:
        return self.playtime_minutes / 60

    def to_dict(self) -> dict:
        data = asdict(self)
        data["last_played"] = self.last_played.isoformat() if self.last_played else None
        return data

    @classmethod
    def from_dict(cls, data: dict) -> Game:
        known = {f.name for f in fields(cls)}
        data = {k: v for k, v in data.items() if k in known}
        if data.get("last_played"):
            data["last_played"] = datetime.fromisoformat(data["last_played"])
        return cls(**data)
