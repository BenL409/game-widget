# Game Widget

Rainmeter skins (plus a fallback tkinter window) showing recent / most-played / "dusty" games across Steam, Epic, GOG, Xbox and
loose folders. See README.md for user-facing setup and known limits.

## Commands (Windows, from this folder)

- Tests: `.venv\Scripts\python -m unittest discover -s tests -t .`
- Text report (fast end-to-end check, no GUI): `.venv\Scripts\python main.py --cli`
- Background service (tracker + skin data every 15 min): `.venv\Scripts\python main.py`
- One-shot skin data refresh: `main.py --refresh`; other modes: `--inspire`, `--window`, `--install-skin`, `--startup on|off`
- Rebuild skins after editing the generator: `.venv\Scripts\python rainmeter\build_skins.py`

## Layout

- `widget/scanners.py`: per-launcher install detection; must degrade to `[]` off-Windows or when a launcher is missing
- `widget/steam_api.py`: Steam Web API (only source with real historical playtime)
- `widget/tracker.py` + `widget/store.py`: process poller that logs sessions to SQLite (`%APPDATA%\GameWidget\data.db`) for non-Steam games
- `widget/library.py`: merges everything into `models.Game`; `widget/dusty.py`: ranking; `widget/prompt.py`: claude.ai prompt/URL
- `widget/service.py`: headless service + the commands the skins run; `widget/rainmeter.py`: renders `data.inc` (UTF-16) and refreshes the `GameWidget` skin group
- `rainmeter/build_skins.py` generates `rainmeter/GameWidget/**` (never hand-edit the .ini output); `--install-skin` junctions that folder into Rainmeter's Skins dir
- `widget/launch.py`: launch/uninstall targets, single-instance checks, companions; `widget/windows.py`: Win32 window focus + monitor placement
- Skin clicks run one-shot commands that read `%APPDATA%\GameWidget\snapshot.json` (written each refresh), so they never wait on Steam
- Appearance variables live in `APPEARANCE` in `widget/appearance.py` (build_skins.py imports it) → `Style.inc` defaults + `Settings.default.inc`; the user's `Settings.inc` (gitignored) is copied from it once, then edited by the `GameWidget\Settings` skin (toggled by the cog; `@Resources/Settings.lua` writes values and refreshes the panel), never overwritten by builds. Colours are `R,G,B` with separate `...Opacity` settings so the skin can change each alone
- `widget/ui.py`: fallback tkinter window; library builds run on a worker thread and results come back via a queue

## Conventions

- Dependencies are kept minimal (`requests`, `psutil`); stdlib otherwise.
- Datetimes are timezone-aware UTC.
- Tests must pass on Windows: close every `Store` before its temp dir is removed (use `self.enterContext(tempfile.TemporaryDirectory())` then `self.addCleanup(store.close)`).
- Skin .ini files must be ASCII (Rainmeter reads them via the Windows ini API); non-ASCII goes in `data.inc` or as `[\xHHHH]` character references.
