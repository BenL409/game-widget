"""Background process watcher: logs play sessions and reports when a game starts.

Matches running executables against each game's install folder. Steam games are watched too: their
totals still come from the Steam API, but sessions give us typical session length and trigger companions.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Callable, Iterable

from .config import Config
from .launch import norm_path, running_exes
from .models import Game
from .store import Store

OnStart = Callable[[str, str, set[str]], None]  # (game_id, game name, normalised running exes)


class Tracker(threading.Thread):
    def __init__(self, cfg: Config, store: Store, on_start: OnStart | None = None):
        super().__init__(daemon=True, name="game-tracker")
        self.cfg, self.store, self.on_start = cfg, store, on_start
        self._targets: list[tuple[str, str]] = []  # (game_id, normalised install path)
        self._names: dict[str, str] = {}
        self._active: dict[str, int] = {}  # game_id -> open session row id
        self._lock = threading.Lock()
        self._stop_evt = threading.Event()

    def set_games(self, games: Iterable[Game]) -> None:
        games = [g for g in games if g.installed and g.install_path]
        with self._lock:
            self._targets = [(g.id, norm_path(g.install_path)) for g in games]
            self._names = {g.id: g.name for g in games}

    def match(self, exe_path: str) -> str | None:
        exe = norm_path(exe_path)
        best: tuple[int, str] | None = None
        with self._lock:
            targets = list(self._targets)
        for game_id, root in targets:
            if exe.startswith(root + os.sep) and (best is None or len(root) > best[0]):
                best = (len(root), game_id)
        return best[1] if best else None

    def poll(self, exe_paths: Iterable[str], now: float) -> None:
        exes = {norm_path(e) for e in exe_paths}
        running = {gid for exe in exes if (gid := self.match(exe))}
        started = []
        for gid in running:
            if gid in self._active:
                self.store.heartbeat(self._active[gid], now)
            else:
                self._active[gid] = self.store.start_session(gid, now)
                started.append(gid)
        for gid in [g for g in self._active if g not in running]:
            del self._active[gid]  # session already holds its last heartbeat as end_ts
        if self.on_start:
            for gid in started:
                self.on_start(gid, self._names.get(gid, gid), exes)

    def run(self) -> None:
        while not self._stop_evt.is_set():
            try:
                self.poll(running_exes(), time.time())
            except Exception:  # never let the tracker thread die
                pass
            self._stop_evt.wait(self.cfg.poll_seconds)

    def stop(self) -> None:
        self._stop_evt.set()
