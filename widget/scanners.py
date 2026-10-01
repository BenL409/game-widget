"""Find what's installed, per launcher. Windows-first; everything degrades to [] elsewhere."""

from __future__ import annotations

import json
import os
import re
import string
import sys
from datetime import datetime, timezone
from pathlib import Path

from .models import Game

# --------------------------------------------------------------------------- VDF

_TOKEN = re.compile(r'"((?:\\.|[^"\\])*)"|([{}])')


def parse_vdf(text: str) -> dict:
    """Minimal Valve KeyValues parser (enough for appmanifest_*.acf and libraryfolders.vdf)."""
    stack: list[dict] = [{}]
    key: str | None = None
    for match in _TOKEN.finditer(text):
        string_val, brace = match.group(1), match.group(2)
        if brace == "{":
            child: dict = {}
            stack[-1][key if key is not None else ""] = child
            stack.append(child)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        else:
            value = re.sub(r"\\(.)", r"\1", string_val)
            if key is None:
                key = value
            else:
                stack[-1][key] = value
                key = None
    return stack[0]


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _from_ts(ts: int) -> datetime | None:
    return datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None


# --------------------------------------------------------------------------- Steam

STEAM_TOOL_APPIDS = {228980, 250820, 1493710}  # Redistributables, SteamVR, Proton Experimental
_TOOL_NAME = re.compile(r"^(Proton\b|Steam Linux Runtime|Steamworks Common|SteamVR\b)", re.I)


def is_steam_tool(appid: int, name: str) -> bool:
    return appid in STEAM_TOOL_APPIDS or bool(_TOOL_NAME.match(name))


def _steam_root() -> Path | None:
    if sys.platform == "win32":
        import winreg

        for hive, sub, value in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        ):
            try:
                with winreg.OpenKey(hive, sub) as key:
                    path, _ = winreg.QueryValueEx(key, value)
                if path and Path(path).exists():
                    return Path(path)
            except OSError:
                continue
    for guess in (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"):
        if Path(guess).exists():
            return Path(guess)
    return None


def steam_libraries(extra=()) -> list[Path]:
    libs: list[Path] = []

    def add(path) -> None:
        p = Path(path)
        if p.exists() and p not in libs:
            libs.append(p)

    root = _steam_root()
    if root:
        add(root)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            data = parse_vdf(vdf.read_text(encoding="utf-8", errors="replace"))
            for entry in data.get("libraryfolders", {}).values():
                path = entry.get("path") if isinstance(entry, dict) else entry
                if path:
                    add(path)
    for path in extra:
        add(path)
    return libs


def scan_steam(extra=()) -> list[Game]:
    games: list[Game] = []
    for lib in steam_libraries(extra):
        apps = lib / "steamapps"
        if not apps.is_dir():
            continue
        for acf in apps.glob("appmanifest_*.acf"):
            try:
                state = parse_vdf(acf.read_text(encoding="utf-8", errors="replace")).get("AppState", {})
            except OSError:
                continue
            appid, name = _int(state.get("appid")), state.get("name")
            if not appid or not name or is_steam_tool(appid, name):
                continue
            games.append(
                Game(
                    id=f"steam:{appid}",
                    name=name,
                    source="steam",
                    installed=True,
                    install_path=str(apps / "common" / state.get("installdir", "")),
                    size_bytes=_int(state.get("SizeOnDisk")) or None,
                    last_played=_from_ts(_int(state.get("LastPlayed"))),
                )
            )
    return games


# --------------------------------------------------------------------------- Epic


def scan_epic() -> list[Game]:
    manifests = (
        Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    )
    games: list[Game] = []
    if not manifests.is_dir():
        return games
    for item in manifests.glob("*.item"):
        try:
            data = json.loads(item.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        name, location = data.get("DisplayName"), data.get("InstallLocation")
        app = data.get("AppName") or data.get("CatalogItemId")
        main = data.get("MainGameAppName")
        if not (name and location and app) or (main and main != app):  # skip DLC entries
            continue
        if not Path(location).exists():
            continue
        games.append(
            Game(
                id=f"epic:{app}",
                name=name,
                source="epic",
                installed=True,
                install_path=location,
                size_bytes=_int(data.get("InstallSize")) or None,
            )
        )
    return games


# --------------------------------------------------------------------------- GOG


def scan_gog() -> list[Game]:
    """Installed GOG games from the registry. (Galaxy's own playtime DB is a later step.)"""
    if sys.platform != "win32":
        return []
    import winreg

    games: list[Game] = []
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\GOG.com\Games")
    except OSError:
        return games
    with root:
        index = 0
        while True:
            try:
                sub = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            try:
                with winreg.OpenKey(root, sub) as key:
                    name = winreg.QueryValueEx(key, "gameName")[0]
                    path = winreg.QueryValueEx(key, "path")[0]
            except OSError:
                continue
            if Path(path).exists():
                games.append(Game(id=f"gog:{sub}", name=name, source="gog", installed=True, install_path=path))
    return games


# --------------------------------------------------------------------------- Xbox / Game Pass PC


def _xbox_roots(extra=()) -> list[Path]:
    candidates = [Path(p) for p in extra]
    if sys.platform == "win32":
        candidates += [Path(f"{letter}:\\XboxGames") for letter in string.ascii_uppercase]
    roots: list[Path] = []
    for path in candidates:
        try:
            if path.is_dir() and path not in roots:
                roots.append(path)
        except OSError:  # empty card-reader drives etc.
            continue
    return roots


def _xbox_name(game_dir: Path) -> str:
    config = game_dir / "Content" / "MicrosoftGame.config"
    try:
        match = re.search(r'DefaultDisplayName="([^"]+)"', config.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        match = None
    if match and not match.group(1).startswith("ms-resource:"):
        return match.group(1)
    return game_dir.name


def scan_xbox(extra=()) -> list[Game]:
    games: list[Game] = []
    for root in _xbox_roots(extra):
        for game_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            if game_dir.name.startswith(("GameSave", ".")):
                continue
            games.append(
                Game(
                    id=f"xbox:{game_dir.name}",
                    name=_xbox_name(game_dir),
                    source="xbox",
                    installed=True,
                    install_path=str(game_dir),
                )
            )
    return games


# --------------------------------------------------------------------------- Anything else


def scan_folders(folders=()) -> list[Game]:
    """Standalone installs: every sub-folder of each configured folder counts as one game."""
    games: list[Game] = []
    for folder in folders:
        root = Path(folder)
        if not root.is_dir():
            continue
        for game_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            games.append(
                Game(
                    id=f"other:{game_dir.name}",
                    name=game_dir.name,
                    source="other",
                    installed=True,
                    install_path=str(game_dir),
                )
            )
    return games


def dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total
