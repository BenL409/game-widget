"""Headless mode for the Rainmeter skins: tracker + periodic refresh, plus the one-shot commands the skins run."""

from __future__ import annotations

import json
import logging
import sys
import time
import webbrowser
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import launch as launcher
from . import rainmeter
from .config import Config, app_data_dir
from .dusty import DustyGame, find_dusty
from .library import add_genres, build_library
from .models import Game
from .prompt import build_inspiration, candidates, vr_games
from .store import Store
from .tracker import Tracker

log = logging.getLogger("gamewidget")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def setup_logging() -> None:
    handler = RotatingFileHandler(app_data_dir() / "service.log", maxBytes=500_000, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


def _snapshot_path() -> Path:
    return app_data_dir() / "snapshot.json"


def refresh_once(cfg: Config, store: Store, tracker: Tracker | None = None) -> int:
    """Build the library, write the skin data + snapshot, and reload the skins. Returns game count."""
    games, warnings = build_library(cfg, store)
    dusty = find_dusty(games, cfg.dusty_days, datetime.now(timezone.utc), store.tracking_started())
    recent, top, neglected = candidates(games, dusty)
    add_genres(recent + top + [d.game for d in neglected] + vr_games(games), store)
    if tracker:
        tracker.set_games(games)

    rainmeter.write(rainmeter.render(games, dusty, warnings), rainmeter.data_path(cfg.rainmeter_skin_dir))
    snapshot = {
        "games": [g.to_dict() for g in games],
        "dusty": [[d.game.id, d.idle_days, d.score, d.note] for d in dusty],
    }
    _snapshot_path().write_text(json.dumps(snapshot), encoding="utf-8")
    rainmeter.refresh_skins()
    for warning in warnings:
        log.warning(warning)
    return len(games)


def load_snapshot(cfg: Config, store: Store) -> tuple[dict[str, Game], list[DustyGame]]:
    """The last refresh's library, so the skins' clicks respond instantly (refreshes first if there is none)."""
    path = _snapshot_path()
    if not path.exists():
        refresh_once(cfg, store)
    data = json.loads(path.read_text(encoding="utf-8"))
    games = {g["id"]: Game.from_dict(g) for g in data["games"]}
    dusty = [DustyGame(games[gid], idle, score, note) for gid, idle, score, note in data["dusty"] if gid in games]
    return games, dusty


def inspire(cfg: Config, store: Store) -> None:
    """Copy the prompt and open Claude. The prompt is built now so the time of day is current."""
    games, dusty = load_snapshot(cfg, store)
    prompt, url, _ = build_inspiration(list(games.values()), dusty)
    if sys.platform == "win32":
        from .clipboard import copy

        copy(prompt)
    webbrowser.open(url)


def launch(cfg: Config, store: Store, game_id: str) -> str:
    games, _ = load_snapshot(cfg, store)
    if game_id not in games:
        return f"unknown game {game_id}"
    return launcher.launch_game(games[game_id], cfg)


def uninstall(cfg: Config, store: Store, game_id: str) -> str:
    games, _ = load_snapshot(cfg, store)
    game = games.get(game_id)
    target = launcher.uninstall_target(game) if game else None
    if not target:
        return f"no uninstaller for {game_id}"
    launcher.open_target(target)
    log.info("%s: opened uninstaller %s", game.name, target)
    return f"opened {target}"


def make_tracker(cfg: Config, store: Store) -> Tracker:
    """Tracker that starts each game's companions when it sees the game start, however it was launched."""

    def on_start(game_id: str, name: str, running: set[str]) -> None:
        try:
            launcher.start_companions(cfg, name, running)
        except Exception:
            log.exception("starting companions for %s failed", name)

    return Tracker(cfg, store, on_start)


def _single_instance():
    """Hold an exclusive lock for the life of the process; None if another service already has it."""
    if sys.platform != "win32":
        return object()
    import msvcrt

    handle = open(app_data_dir() / "service.lock", "a+")
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        return None
    return handle


def run_service(cfg: Config, store: Store) -> None:
    lock = _single_instance()
    if lock is None:
        log.info("service already running; exiting")
        print("Game widget service is already running.")
        return
    tracker = make_tracker(cfg, store)
    tracker.start()
    log.info("service started")
    print("Game widget service running (Ctrl+C to stop). Log:", app_data_dir() / "service.log")
    try:
        while True:
            try:
                count = refresh_once(cfg, store, tracker)
                log.info("refreshed: %d games", count)
            except Exception:  # keep tracking even if a refresh fails
                log.exception("refresh failed")
            time.sleep(cfg.refresh_minutes * 60)
    except KeyboardInterrupt:
        pass
    finally:
        tracker.stop()
        log.info("service stopped")


def set_startup(enabled: bool) -> str:
    """Add/remove the service from HKCU Run so it starts (windowless) at login."""
    import winreg

    pythonw = Path(sys.executable).with_name("pythonw.exe")
    command = f'"{pythonw}" "{Path(__file__).resolve().parent.parent / "main.py"}"'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, "GameWidget", 0, winreg.REG_SZ, command)
            return f"Starts at login: {command}"
        try:
            winreg.DeleteValue(key, "GameWidget")
        except FileNotFoundError:
            pass
        return "Removed from login startup."
