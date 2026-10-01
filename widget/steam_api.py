"""Thin client for the two Steam Web API endpoints we need.

You need a free key (https://steamcommunity.com/dev/apikey) and your SteamID64.
Your profile's "Game details" must be Public or Steam returns nothing.
"""

from __future__ import annotations

import requests

BASE = "https://api.steampowered.com/IPlayerService"


class SteamError(Exception):
    pass


def _get(endpoint: str, params: dict) -> dict:
    try:
        resp = requests.get(f"{BASE}/{endpoint}/v1/", params=params, timeout=15)
    except requests.RequestException as exc:
        raise SteamError(f"Steam API unreachable: {exc}") from exc
    if resp.status_code in (401, 403):
        raise SteamError("Steam rejected the API key - check steam_api_key.")
    if resp.status_code != 200:
        raise SteamError(f"Steam API returned HTTP {resp.status_code}.")
    return resp.json().get("response", {})


def owned_games(key: str, steam_id: str) -> list[dict]:
    """All owned games: appid, name, playtime_forever (minutes), rtime_last_played (unix)."""
    data = _get(
        "GetOwnedGames",
        {
            "key": key,
            "steamid": steam_id,
            "include_appinfo": 1,
            "include_played_free_games": 1,
            "format": "json",
        },
    )
    if "games" not in data:
        raise SteamError("Steam returned no games - is 'Game details' set to Public on your profile?")
    return data["games"]


def recently_played(key: str, steam_id: str) -> list[dict]:
    """Games played in the last 2 weeks, with playtime_2weeks (minutes)."""
    data = _get("GetRecentlyPlayedGames", {"key": key, "steamid": steam_id, "format": "json"})
    return data.get("games", [])


def genres(appid: int) -> list[str]:
    """Store genres for one app (the store API ignores filters when asked for several at once)."""
    try:
        resp = requests.get(
            "https://store.steampowered.com/api/appdetails",
            params={"appids": appid, "filters": "genres", "l": "english"},
            timeout=10,
        )
    except requests.RequestException as exc:
        raise SteamError(f"Steam store unreachable: {exc}") from exc
    if resp.status_code != 200:
        raise SteamError(f"Steam store returned HTTP {resp.status_code}.")
    entry = (resp.json() or {}).get(str(appid)) or {}
    data = entry.get("data") if entry.get("success") else None
    return [g["description"] for g in (data or {}).get("genres", []) if g.get("description")]
