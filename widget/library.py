"""Merge every source into one list of Game objects."""

from __future__ import annotations

from datetime import datetime, timezone

from . import scanners, steam_api
from .config import Config
from .models import Game
from .store import Store


def _from_ts(ts: int | None) -> datetime | None:
    return datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None


def build_library(cfg: Config, store: Store) -> tuple[list[Game], list[str]]:
    games: dict[str, Game] = {}
    warnings: list[str] = []

    # 1. Steam: accurate totals + last-played straight from the API
    if cfg.steam_api_key and cfg.steam_id:
        try:
            for item in steam_api.owned_games(cfg.steam_api_key, cfg.steam_id):
                gid = f"steam:{item['appid']}"
                games[gid] = Game(
                    id=gid,
                    name=item.get("name", f"App {item['appid']}"),
                    source="steam",
                    playtime_minutes=item.get("playtime_forever", 0),
                    last_played=_from_ts(item.get("rtime_last_played")),
                )
            for item in steam_api.recently_played(cfg.steam_api_key, cfg.steam_id):
                game = games.get(f"steam:{item['appid']}")
                if game:
                    game.recent_minutes = item.get("playtime_2weeks", 0)
        except steam_api.SteamError as exc:
            warnings.append(str(exc))
    else:
        warnings.append("Steam key / SteamID not set - Steam playtime unavailable (see config.example.json).")

    # 2. Steam installs (adds install path + size; fills gaps if the API was unavailable)
    for inst in scanners.scan_steam(cfg.steam_library_paths):
        game = games.get(inst.id)
        if game is None:
            games[inst.id] = inst
            continue
        game.installed, game.install_path, game.size_bytes = True, inst.install_path, inst.size_bytes
        game.last_played = game.last_played or inst.last_played

    # 3. Everything else: installs from launcher data, playtime from our own tracker
    others = (
        scanners.scan_epic()
        + scanners.scan_gog()
        + scanners.scan_xbox(cfg.xbox_games_roots)
        + scanners.scan_folders(cfg.extra_game_folders)
    )
    totals = store.playtime_all(cfg.min_session_seconds)
    recent = store.recent_all(cfg.min_session_seconds)
    for game in others:
        if game.id in games:
            continue
        game.tracked = True
        if game.size_bytes is None and game.install_path:
            cached = store.get_size(game.id)
            if cached is None:
                cached = scanners.dir_size(game.install_path)
                store.set_size(game.id, cached)
            game.size_bytes = cached or None
        if game.id in totals:
            minutes, last_ts = totals[game.id]
            game.playtime_minutes = minutes
            game.last_played = datetime.fromtimestamp(last_ts, tz=timezone.utc)
        game.recent_minutes = recent.get(game.id, 0)
        games[game.id] = game

    hidden = {n.lower() for n in cfg.ignore_names}
    return [g for g in games.values() if g.name.lower() not in hidden], warnings
