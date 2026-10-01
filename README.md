# Game Widget

A Rainmeter desktop widget (with a fallback standalone window) that shows:

- **Recent**: games played in the last 2 weeks
- **Most played**: total hours, last played
- **Dusty**: installed games you haven't touched in a while (default 30 days), ranked by hours invested x idle time, with disk size
- **"What should I play?"** button: builds a prompt from your library and opens claude.ai with it prefilled (also copied to your clipboard)

## Setup (Windows)

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy config.example.json config.json
```

Then edit `config.json`:

1. **steam_api_key**: free at https://steamcommunity.com/dev/apikey
2. **steam_id**: your 17-digit SteamID64 (look yours up at steamid.io)
3. Steam profile > Edit Profile > Privacy Settings > **Game details = Public** (otherwise Steam returns nothing)
4. Optional: `extra_game_folders` for standalone installs, e.g. `["D:\\Games"]` (each sub-folder = one game)

Run it:

```powershell
python main.py --install-skin   # once: links rainmeter\GameWidget into your Rainmeter Skins folder
python main.py                  # background service: tracks play sessions, refreshes skin data every 15 min
python main.py --startup on     # optional: start the service (windowless) at login
python main.py --cli            # text report, handy for debugging
python main.py --window         # standalone tkinter window instead of Rainmeter
```

Then in Rainmeter: Manage > Refresh all, and load a `GameWidget` skin (Panel, Tabs or Minimal).
Right-click a skin for *Refresh game data* / *Ask Claude* / *Edit appearance*. Service log: `%APPDATA%\GameWidget\service.log`.

**In the panel:** click a game to play it (if it's already running, its window comes forward instead).
Right-click a dusty game to open its launcher's uninstaller.

**Appearance:** click the cog next to the *Games* title (or right-click > *Edit appearance*) to open the
*Appearance* skin beside the panel. Click a colour row, then a palette dot (or *Custom colour* for R,G,B / #hex);
click or scroll the sliders for opacity; use the arrows (or click the name) for fonts. The panel updates as you go;
*Cancel* puts everything back. Settings are saved in `@Resources\Settings.inc` (not in git).

**Per-game settings** in `config.json` (names are case-insensitive):

```json
"games": {
  "Path of Exile": {"companions": [
    "%LOCALAPPDATA%\\Programs\\Awakened PoE Trade\\Awakened PoE Trade.exe",
    {"path": "%APPDATA%\\Path of Building Community\\Path of Building.exe", "monitor": 3}
  ]},
  "Cities: Skylines II": {"launch": "C:\\Program Files (x86)\\Skyve CS-II\\Skyve.exe"}
}
```

- `launch`: what the panel opens instead of the game's launcher (e.g. a mod manager).
- `companions`: started whenever the service sees the game start, however it was launched, and skipped if
  already running. `monitor` is the display number from Settings > Display.
- `extra_hours`: hours played before tracking began, added to the total (e.g. `"DCS World": {"extra_hours": 56}`).
- `vr`: `true` for VR games. The Claude prompt lists them on their own line as needing a longer, committed session.

In VS Code: open the folder, pick the `.venv` interpreter, press F5 (launch configs: *Widget* and *CLI report*).
Tests: `python -m unittest discover -s tests -t .`

## How each source works

| Source | Installed detection | Hours / last played |
|---|---|---|
| Steam | `libraryfolders.vdf` + `appmanifest_*.acf` | Steam Web API (accurate, complete history) |
| Epic | `ProgramData\Epic\...\Manifests\*.item` | Process tracker |
| GOG | Registry (`HKLM\...\GOG.com\Games`) | Process tracker |
| DCS World (standalone) | Registry (`HKCU\Software\Eagle Dynamics`) | Process tracker |
| Xbox / Game Pass PC | `X:\XboxGames\*` on every drive | Process tracker |
| Anything else | `extra_game_folders` | Process tracker |

**The tracker** (`widget/tracker.py`) polls running processes every 15s and logs a session when an
executable lives inside a game's install folder. Sessions are stored in SQLite at
`%APPDATA%\GameWidget\data.db`. It only runs while the service (or `--window`) is running.

## Known limits (honest list)

- Non-Steam hours are only counted **from the day you first run this**. There's no API for earlier history.
- Until tracking has run for `dusty_days`, non-Steam games with no sessions are *not* listed as dusty
  (we can't know yet). Steam games are judged immediately from Steam's last-played date.
- Xbox: Microsoft exposes no playtime API for third parties, so it's tracking-only. Games installed under
  `WindowsApps` (rather than `XboxGames`) may be unreadable to the tracker. Display names come from
  `MicrosoftGame.config` where possible, otherwise the folder name.
- GOG: Galaxy's own playtime database isn't read yet (next step below).
- The Claude button prefills `claude.ai/new?q=...`. If a URL would be too long it opens a blank chat and
  you paste from the clipboard.

## Next steps

- Read GOG Galaxy's playtime DB (`ProgramData\GOG.com\Galaxy\storage\galaxy-2.0.db`) to backfill hours.
- In-widget chat via the Claude API (needs an API key; billed separately from a Claude subscription).
- Click a dusty game to launch or uninstall it.
