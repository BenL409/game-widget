from __future__ import annotations

from datetime import datetime, timezone


def hours(minutes: int) -> str:
    h = minutes / 60
    return f"{h:.1f}h" if h < 10 else f"{h:.0f}h"


def size(num_bytes: int | None) -> str:
    if not num_bytes:
        return "-"
    gb = num_bytes / 1e9
    return f"{gb:.1f} GB" if gb >= 1 else f"{num_bytes / 1e6:.0f} MB"


def idle(days: int | None) -> str:
    if days is None:
        return "never"
    if days < 60:
        return f"{days}d"
    if days < 730:
        return f"{days // 30}mo"
    return f"{days // 365}y"


def ago(when: datetime | None, now: datetime | None = None) -> str:
    if when is None:
        return "-"
    now = now or datetime.now(timezone.utc)
    days = (now - when).days
    if days <= 0:
        return "today"
    return f"{idle(days)} ago"
