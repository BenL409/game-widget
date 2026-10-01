"""SQLite storage for the process tracker's play sessions (used for non-Steam games)."""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    game_id TEXT NOT NULL,
    start_ts REAL NOT NULL,
    end_ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_game ON sessions(game_id);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS size_cache (game_id TEXT PRIMARY KEY, size INTEGER, checked_ts REAL);
CREATE TABLE IF NOT EXISTS genre_cache (game_id TEXT PRIMARY KEY, genres TEXT, checked_ts REAL);
"""


class Store:
    def __init__(self, path: Path | str):
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.executescript(_SCHEMA)
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ---- sessions (crash-safe: a row is written at start and its end_ts bumped each poll)
    def start_session(self, game_id: str, ts: float) -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO sessions (game_id, start_ts, end_ts) VALUES (?, ?, ?)", (game_id, ts, ts)
            )
            self._db.commit()
            return int(cur.lastrowid)

    def heartbeat(self, session_id: int, ts: float) -> None:
        with self._lock:
            self._db.execute("UPDATE sessions SET end_ts = ? WHERE id = ?", (ts, session_id))
            self._db.commit()

    def playtime_all(self, min_seconds: int) -> dict[str, tuple[int, float]]:
        """game_id -> (total minutes, last end timestamp), ignoring blips under min_seconds."""
        with self._lock:
            rows = self._db.execute(
                "SELECT game_id, SUM(end_ts - start_ts), MAX(end_ts) FROM sessions "
                "WHERE end_ts - start_ts >= ? GROUP BY game_id",
                (min_seconds,),
            ).fetchall()
        return {gid: (int(total // 60), last) for gid, total, last in rows}

    def recent_all(self, min_seconds: int, days: int = 14) -> dict[str, int]:
        since = time.time() - days * 86400
        with self._lock:
            rows = self._db.execute(
                "SELECT game_id, SUM(end_ts - start_ts) FROM sessions "
                "WHERE end_ts - start_ts >= ? AND end_ts >= ? GROUP BY game_id",
                (min_seconds, since),
            ).fetchall()
        return {gid: int(total // 60) for gid, total in rows}

    def session_stats(self, min_seconds: int, days: int = 120) -> dict[str, tuple[int, int]]:
        """game_id -> (session count, average minutes) over the last `days`."""
        since = time.time() - days * 86400
        with self._lock:
            rows = self._db.execute(
                "SELECT game_id, COUNT(*), AVG(end_ts - start_ts) FROM sessions "
                "WHERE end_ts - start_ts >= ? AND end_ts >= ? GROUP BY game_id",
                (min_seconds, since),
            ).fetchall()
        return {gid: (count, int(avg // 60)) for gid, count, avg in rows}

    # ---- meta
    def tracking_started(self) -> datetime:
        """When tracking first ran. Non-Steam games can't be called 'dusty' before this is old enough."""
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key = 'tracking_started'").fetchone()
            if row:
                return datetime.fromtimestamp(float(row[0]), tz=timezone.utc)
            now = time.time()
            self._db.execute("INSERT INTO meta (key, value) VALUES ('tracking_started', ?)", (str(now),))
            self._db.commit()
            return datetime.fromtimestamp(now, tz=timezone.utc)

    # ---- folder size cache
    def get_size(self, game_id: str, max_age_days: int = 7) -> int | None:
        with self._lock:
            row = self._db.execute(
                "SELECT size, checked_ts FROM size_cache WHERE game_id = ?", (game_id,)
            ).fetchone()
        if row and time.time() - row[1] < max_age_days * 86400:
            return int(row[0])
        return None

    def set_size(self, game_id: str, size: int) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO size_cache (game_id, size, checked_ts) VALUES (?, ?, ?)",
                (game_id, size, time.time()),
            )
            self._db.commit()

    # ---- genre cache (genres never change, so no expiry; '' = looked up, none found)
    def get_genres(self, game_id: str) -> list[str] | None:
        with self._lock:
            row = self._db.execute("SELECT genres FROM genre_cache WHERE game_id = ?", (game_id,)).fetchone()
        if row is None:
            return None
        return [g for g in row[0].split("|") if g]

    def set_genres(self, game_id: str, genres: list[str]) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO genre_cache (game_id, genres, checked_ts) VALUES (?, ?, ?)",
                (game_id, "|".join(genres), time.time()),
            )
            self._db.commit()
