import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from widget import fmt, library, rainmeter, scanners, steam_api
from widget.config import Config
from widget.dusty import find_dusty
from widget.models import Game
from widget.prompt import build_inspiration, build_prompt
from widget.store import Store
from widget.tracker import Tracker

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def days_ago(n):
    return NOW - timedelta(days=n)


class VdfTests(unittest.TestCase):
    def test_libraryfolders_and_acf(self):
        vdf = '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"C:\\\\Program Files (x86)\\\\Steam"\n\t}\n\t"1"\n\t{\n\t\t"path"\t\t"D:\\\\SteamLibrary"\n\t}\n}'
        data = scanners.parse_vdf(vdf)
        self.assertEqual(data["libraryfolders"]["1"]["path"], "D:\\SteamLibrary")
        acf = '"AppState"\n{\n"appid"\t"620"\n"name"\t"Portal 2"\n"installdir"\t"Portal 2"\n"SizeOnDisk"\t"12000000000"\n"LastPlayed"\t"1700000000"\n}'
        state = scanners.parse_vdf(acf)["AppState"]
        self.assertEqual(state["name"], "Portal 2")
        self.assertEqual(state["LastPlayed"], "1700000000")

    def test_tools_are_filtered(self):
        self.assertTrue(scanners.is_steam_tool(228980, "Steamworks Common Redistributables"))
        self.assertTrue(scanners.is_steam_tool(1, "Proton 9.0"))
        self.assertFalse(scanners.is_steam_tool(620, "Portal 2"))


class DustyTests(unittest.TestCase):
    def test_ranking_and_thresholds(self):
        games = [
            Game("steam:1", "Long ago, big", "steam", installed=True, playtime_minutes=40 * 60, last_played=days_ago(95)),
            Game("steam:2", "Long ago, tiny", "steam", installed=True, playtime_minutes=30, last_played=days_ago(95)),
            Game("steam:3", "Played yesterday", "steam", installed=True, playtime_minutes=600, last_played=days_ago(1)),
            Game("steam:4", "Never launched", "steam", installed=True, size_bytes=50_000_000_000),
            Game("steam:5", "Not installed", "steam", installed=False, last_played=days_ago(400)),
        ]
        result = find_dusty(games, 30, NOW)
        self.assertEqual([d.game.id for d in result], ["steam:1", "steam:2", "steam:4"])
        self.assertEqual(result[2].note, "never launched")

    def test_tracked_games_wait_for_tracking_history(self):
        game = Game("epic:a", "Epic game", "epic", installed=True, tracked=True)
        self.assertEqual(find_dusty([game], 30, NOW, tracking_started=days_ago(3)), [])
        listed = find_dusty([game], 30, NOW, tracking_started=days_ago(45))
        self.assertEqual(len(listed), 1)


class TrackerTests(unittest.TestCase):
    def test_sessions_are_recorded_and_blips_ignored(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        root = os.path.join(tmp, "games", "a")
        store = Store(os.path.join(tmp, "t.db"))
        self.addCleanup(store.close)
        tracker = Tracker(Config(), store)
        tracker.set_games([Game("epic:a", "A", "epic", installed=True, install_path=root)])
        exe = os.path.join(root, "bin", "game.exe")

        self.assertIsNone(tracker.match(os.path.join(tmp, "other", "x.exe")))
        tracker.poll([exe], 1000)
        tracker.poll([exe], 1600)  # 10 minutes in
        tracker.poll([], 1700)  # closed
        tracker.poll([exe], 5000)  # launcher blip: 0s session
        tracker.poll([], 5100)

        totals = store.playtime_all(60)
        self.assertEqual(totals["epic:a"], (10, 1600))

    def test_longest_install_path_wins(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        store = Store(os.path.join(tmp, "t.db"))
        self.addCleanup(store.close)
        tracker = Tracker(Config(), store)
        outer, inner = os.path.join(tmp, "Games"), os.path.join(tmp, "Games", "Inner")
        tracker.set_games([
            Game("other:Games", "Outer", "other", installed=True, install_path=outer),
            Game("other:Inner", "Inner", "other", installed=True, install_path=inner),
        ])
        self.assertEqual(tracker.match(os.path.join(inner, "x.exe")), "other:Inner")


class LibraryTests(unittest.TestCase):
    def test_merge_steam_api_with_installed_scan(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        apps = Path(tmp, "lib", "steamapps")
        apps.mkdir(parents=True)
        (apps / "appmanifest_620.acf").write_text(
            '"AppState"\n{\n"appid"\t"620"\n"name"\t"Portal 2"\n"installdir"\t"Portal 2"\n"SizeOnDisk"\t"1000"\n}'
        )
        cfg = Config(steam_api_key="k", steam_id="1", steam_library_paths=[str(apps.parent)])
        store = Store(os.path.join(tmp, "t.db"))
        self.addCleanup(store.close)
        owned = [
            {"appid": 620, "name": "Portal 2", "playtime_forever": 300, "rtime_last_played": int(days_ago(100).timestamp())},
            {"appid": 730, "name": "Counter-Strike 2", "playtime_forever": 6000, "rtime_last_played": int(days_ago(2).timestamp())},
        ]
        with mock.patch.object(steam_api, "owned_games", return_value=owned), \
             mock.patch.object(steam_api, "recently_played", return_value=[{"appid": 730, "playtime_2weeks": 120}]), \
             mock.patch.object(scanners, "_steam_root", return_value=None), \
             mock.patch.object(scanners, "scan_epic", return_value=[]), \
             mock.patch.object(scanners, "scan_gog", return_value=[]), \
             mock.patch.object(scanners, "scan_xbox", return_value=[]):
            games, warnings = library.build_library(cfg, store)

        by_id = {g.id: g for g in games}
        self.assertEqual(warnings, [])
        self.assertTrue(by_id["steam:620"].installed)
        self.assertEqual(by_id["steam:620"].playtime_minutes, 300)
        self.assertFalse(by_id["steam:730"].installed)
        self.assertEqual(by_id["steam:730"].recent_minutes, 120)
        dusty = find_dusty(games, 30, NOW)
        self.assertEqual([d.game.id for d in dusty], ["steam:620"])


class PromptTests(unittest.TestCase):
    def test_prompt_and_url_length(self):
        games = [Game(f"steam:{i}", f"Game number {i} with a fairly long title", "steam", installed=True,
                      playtime_minutes=600 + i, recent_minutes=60 + i, last_played=days_ago(50)) for i in range(40)]
        dusty = find_dusty(games, 30, NOW)
        prompt = build_prompt(games, dusty)
        self.assertIn("Most played overall", prompt)
        self.assertIn("Installed but untouched", prompt)
        _, url, prefilled = build_inspiration(games, dusty)
        self.assertLessEqual(len(url), 1800)
        self.assertTrue(prefilled)


class RainmeterTests(unittest.TestCase):
    def test_render_rows_and_escaping(self):
        games = [
            Game("steam:1", "Big #1 Game", "steam", installed=True, playtime_minutes=6000, recent_minutes=120,
                 last_played=days_ago(1)),
            Game("steam:2", "Old", "steam", installed=True, playtime_minutes=60, last_played=days_ago(90)),
        ]
        text = rainmeter.render(games, find_dusty(games, 30, NOW), ["Steam says no"], NOW)
        values = dict(line.split("=", 1) for line in text.splitlines() if "=" in line and not line.startswith(";"))
        self.assertEqual(values["R1Name"], "Big ＃1 Game")
        self.assertEqual(values["R1Pct"], "1.000")
        self.assertEqual(values["R2Hidden"], "1")
        self.assertEqual((values["RCount"], values["MCount"], values["DCount"]), ("1", "2", "1"))
        self.assertEqual(values["RNone"], "0")
        self.assertEqual(values["M2Name"], "Old")
        self.assertEqual(values["D1Value"], "3mo")
        self.assertEqual(values[f"D{rainmeter.MAX_ROWS}Name"], "")
        self.assertEqual((values["Status"], values["StatusHidden"]), ("Steam says no", "0"))

    def test_write_is_utf16(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        path = Path(tmp, "@Resources", "data.inc")
        rainmeter.write("[Variables]\r\nR1Name=F1® Manager\r\n", path)
        self.assertEqual(path.read_bytes()[:2], b"\xff\xfe")
        self.assertIn("F1® Manager", path.read_text(encoding="utf-16"))
    def test_idle_formats(self):
        self.assertEqual([fmt.idle(d) for d in (5, 90, 1900)], ["5d", "3mo", "5y"])


if __name__ == "__main__":
    unittest.main()
