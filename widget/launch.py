"""Launching games (and the programs that go with them) and opening their uninstallers."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

from .config import Config
from .models import Game

log = logging.getLogger("gamewidget")
_JUNK_EXE = re.compile(r"unins|setup|crash|report|redist|dxsetup|helper|easyanticheat|launcherpatcher", re.I)
_DETACHED = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if sys.platform == "win32" else 0


def norm_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _is_uri(target: str) -> bool:
    return "://" in target or target.startswith(("shell:", "ms-settings:"))


def guess_exe(folder: str) -> str | None:
    """Best guess for a loose install: the biggest non-installer exe within two folders of the root."""
    root = Path(folder)
    candidates = [p for pattern in ("*.exe", "*/*.exe", "*/*/*.exe") for p in root.glob(pattern)
                  if not _JUNK_EXE.search(p.name)]
    return str(max(candidates, key=lambda p: p.stat().st_size)) if candidates else None


def launch_target(game: Game, cfg: Config) -> str | None:
    override = cfg.game_settings(game.name).get("launch")
    if override:
        return os.path.expandvars(override)
    if game.source == "steam":
        return f"steam://rungameid/{game.id.split(':', 1)[1]}"
    if game.launch:
        return game.launch
    return guess_exe(game.install_path) if game.install_path else None


def uninstall_target(game: Game) -> str | None:
    """Every target here goes through the launcher's (or Windows') own confirmation, or just opens a folder."""
    if game.source == "steam":
        return f"steam://uninstall/{game.id.split(':', 1)[1]}"
    if game.uninstall:
        return game.uninstall
    if game.source == "epic":
        return "com.epicgames.launcher://"  # no uninstall link; opens the launcher's library
    if game.source == "xbox":
        return "ms-settings:appsfeatures"
    return game.install_path  # loose installs: open the folder


def open_target(target: str) -> None:
    if _is_uri(target) or Path(target).is_dir():
        os.startfile(target)
    elif Path(target).is_file():
        subprocess.Popen([target], cwd=str(Path(target).parent), creationflags=_DETACHED)
    else:  # a full command line, e.g. a registry UninstallString with arguments
        subprocess.Popen(target, creationflags=_DETACHED)


def companions(cfg: Config, name: str) -> list[tuple[str, int | None]]:
    """(path, monitor number or None) for each program configured to run alongside a game."""
    out = []
    for entry in cfg.game_settings(name).get("companions", []):
        path, monitor = (entry, None) if isinstance(entry, str) else (entry.get("path", ""), entry.get("monitor"))
        if path:
            out.append((os.path.expandvars(path), monitor))
    return out


def running_exes() -> set[str]:
    import psutil

    exes = set()
    for proc in psutil.process_iter(["exe"]):
        if proc.info.get("exe"):
            exes.add(norm_path(proc.info["exe"]))
    return exes


def launch_game(game: Game, cfg: Config, running: set[str] | None = None) -> str:
    """Start the game (or its configured launcher) and any companions, never a second copy of anything.
    If the game is already up, its window is brought forward instead. Returns what happened."""
    running = running_exes() if running is None else running
    root = norm_path(game.install_path) + os.sep if game.install_path else None
    target = launch_target(game, cfg)
    target_exe = norm_path(target) if target and not _is_uri(target) else None

    def is_ours(exe: str) -> bool:
        return bool((root and exe.startswith(root)) or exe == target_exe)

    if any(is_ours(exe) for exe in running):
        if sys.platform == "win32":
            from .windows import focus_first

            focus_first(lambda exe: is_ours(norm_path(exe)))
        result = "already running"
    elif target:
        open_target(target)
        result = f"launched {target}"
    else:
        result = "no way to launch it found"
    start_companions(cfg, game.name, running, wait=True)
    log.info("%s: %s", game.name, result)
    return result


def start_companions(cfg: Config, name: str, running: set[str], wait: bool = False) -> list[str]:
    """Start the game's companions that aren't already running (`running` = normalised exe paths).
    wait=True keeps the process alive until window placement finishes (for one-shot commands)."""
    started = []
    for path, monitor in companions(cfg, name):
        if norm_path(path) in running:
            continue
        if not Path(path).is_file():
            log.warning("companion for %s not found: %s", name, path)
            continue
        open_target(path)
        started.append(path)
        log.info("started %s for %s", path, name)
        if monitor and sys.platform == "win32":
            from .windows import place_on_monitor

            threading.Thread(target=place_on_monitor, args=(path, int(monitor)), daemon=not wait).start()
    return started
