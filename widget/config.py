from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path

APP_NAME = "GameWidget"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def app_data_dir() -> Path:
    """Where the SQLite database lives (%APPDATA%\\GameWidget on Windows)."""
    base = os.environ.get("APPDATA") or str(Path.home() / ".local" / "share")
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Config:
    steam_api_key: str = ""
    steam_id: str = ""  # 17-digit SteamID64
    dusty_days: int = 30  # "not played in a while" threshold
    poll_seconds: int = 15  # process tracker interval
    min_session_seconds: int = 60  # ignore launcher blips shorter than this
    refresh_minutes: int = 15  # auto-refresh interval for the widget
    always_on_top: bool = True
    recent_count: int = 8
    most_played_count: int = 8
    dusty_count: int = 12
    # Extra Steam library folders (normally auto-detected)
    steam_library_paths: list[str] = field(default_factory=list)
    # Extra XboxGames roots (all drives are auto-detected on Windows)
    xbox_games_roots: list[str] = field(default_factory=list)
    # Folders where each sub-folder is one standalone game, e.g. ["D:\\Games"]
    extra_game_folders: list[str] = field(default_factory=list)
    # Games to hide completely (case-insensitive exact names)
    ignore_names: list[str] = field(default_factory=list)
    # Rainmeter skin root (normally <Rainmeter SkinPath>\GameWidget, auto-detected)
    rainmeter_skin_dir: str = ""
    # Per-game tweaks, keyed by game name (case-insensitive). See config.example.json.
    #   "launch": exe/URI the panel opens instead of the launcher (e.g. a mod manager)
    #   "companions": programs started whenever the game starts: "path" or {"path": ..., "monitor": 3}
    #   "extra_hours": hours played before tracking began (added to the total)
    #   "vr": true for VR games; the Claude prompt lists them separately as a bigger commitment
    games: dict[str, dict] = field(default_factory=dict)

    def game_settings(self, name: str) -> dict:
        wanted = name.lower()
        return next((v for k, v in self.games.items() if k.lower() == wanted), {})


def load_config(path: Path | None = None) -> Config:
    candidates = [path] if path else [PROJECT_ROOT / "config.json", app_data_dir() / "config.json"]
    data: dict = {}
    for candidate in candidates:
        if candidate and candidate.exists():
            data = json.loads(candidate.read_text(encoding="utf-8"))
            break
    known = {f.name for f in fields(Config)}
    cfg = Config(**{k: v for k, v in data.items() if k in known})
    cfg.steam_api_key = os.environ.get("STEAM_API_KEY", cfg.steam_api_key)
    cfg.steam_id = os.environ.get("STEAM_ID", cfg.steam_id)
    return cfg
