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
Right-click a skin for *Refresh game data* / *Ask Claude*. Service log: `%APPDATA%\GameWidget\service.log`.

In VS Code: open the folder, pick the `.venv` interpreter, press F5 (launch configs: *Widget* and *CLI report*).
Tests: `python -m unittest discover -s tests -t .`

## How each source works

| Source | Installed detection | Hours / last played |
|---|---|---|
| Steam | `libraryfolders.vdf` + `appmanifest_*.acf` | Steam Web API (accurate, complete history) |
| Epic | `ProgramData\Epic\...\Manifests\*.item` | Process tracker |
| GOG | Registry (`HKLM\...\GOG.com\Games`) | Process tracker |
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
