"""Background process watcher: logs play sessions for non-Steam games.

Matches running executables against each game's install folder. Steam is skipped
because the Steam API already provides accurate totals and last-played dates.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Iterable

from .config import Config
from .models import Game
from .store import Store


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


class Tracker(threading.Thread):
    def __init__(self, cfg: Config, store: Store):
        super().__init__(daemon=True, name="game-tracker")
        self.cfg, self.store = cfg, store
        self._targets: list[tuple[str, str]] = []  # (game_id, normalised install path)
        self._active: dict[str, int] = {}  # game_id -> open session row id
        self._lock = threading.Lock()
        self._stop_evt = threading.Event()

    def set_games(self, games: Iterable[Game]) -> None:
        targets = [
            (g.id, _norm(g.install_path))
            for g in games
            if g.source != "steam" and g.installed and g.install_path
        ]
        with self._lock:
            self._targets = targets

    def match(self, exe_path: str) -> str | None:
        exe = _norm(exe_path)
        best: tuple[int, str] | None = None
        with self._lock:
            targets = list(self._targets)
        for game_id, root in targets:
            if exe.startswith(root + os.sep) and (best is None or len(root) > best[0]):
                best = (len(root), game_id)
        return best[1] if best else None

    def poll(self, exe_paths: Iterable[str], now: float) -> None:
        running = {gid for exe in exe_paths if (gid := self.match(exe))}
        for gid in running:
            if gid in self._active:
                self.store.heartbeat(self._active[gid], now)
            else:
                self._active[gid] = self.store.start_session(gid, now)
        for gid in [g for g in self._active if g not in running]:
            del self._active[gid]  # session already holds its last heartbeat as end_ts

    @staticmethod
    def _running_exes() -> Iterable[str]:
        import psutil

        for proc in psutil.process_iter(["exe"]):
            exe = proc.info.get("exe")
            if exe:
                yield exe

    def run(self) -> None:
        while not self._stop_evt.is_set():
            try:
                self.poll(self._running_exes(), time.time())
            except Exception:  # never let the tracker thread die
                pass
            self._stop_evt.wait(self.cfg.poll_seconds)

    def stop(self) -> None:
        self._stop_evt.set()
