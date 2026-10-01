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

from . import rainmeter
from .config import Config, app_data_dir
from .dusty import find_dusty
from .library import build_library
from .prompt import build_inspiration
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
    return app_data_dir() / "inspire.json"


def refresh_once(cfg: Config, store: Store, tracker: Tracker | None = None) -> int:
    """Build the library, write the skin data + inspire snapshot, and reload the skins. Returns game count."""
    games, warnings = build_library(cfg, store)
    dusty = find_dusty(games, cfg.dusty_days, datetime.now(timezone.utc), store.tracking_started())
    if tracker:
        tracker.set_games(games)

    rainmeter.write(rainmeter.render(games, dusty, warnings), rainmeter.data_path(cfg.rainmeter_skin_dir))
    prompt, url, prefilled = build_inspiration(games, dusty)
    _snapshot_path().write_text(json.dumps({"prompt": prompt, "url": url, "prefilled": prefilled}), encoding="utf-8")
    rainmeter.refresh_skins()
    for warning in warnings:
        log.warning(warning)
    return len(games)


def inspire(cfg: Config, store: Store) -> None:
    """Copy the prompt and open Claude. Uses the last refresh's snapshot so the click feels instant."""
    path = _snapshot_path()
    if not path.exists():
        refresh_once(cfg, store)
    snap = json.loads(path.read_text(encoding="utf-8"))
    if sys.platform == "win32":
        from .clipboard import copy

        copy(snap["prompt"])
    webbrowser.open(snap["url"])


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
    tracker = Tracker(cfg, store)
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
