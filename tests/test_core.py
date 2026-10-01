import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from widget import appearance, fmt, launch, library, rainmeter, scanners, steam_api
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
             mock.patch.object(scanners, "scan_eagle_dynamics", return_value=[]), \
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


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.cfg = Config(games={"Cities: Skylines II": {"launch": "C:\\Mods\\Skyve.exe"},
                                 "Path of Exile": {"companions": [os.path.join(self.tmp, "trade.exe"),
                                                                  {"path": os.path.join(self.tmp, "pob.exe"), "monitor": 3}]}})

    def test_targets(self):
        steam = Game("steam:620", "Portal 2", "steam", installed=True)
        self.assertEqual(launch.launch_target(steam, self.cfg), "steam://rungameid/620")
        self.assertEqual(launch.uninstall_target(steam), "steam://uninstall/620")
        cities = Game("steam:949230", "cities: skylines ii", "steam", installed=True)
        self.assertEqual(launch.launch_target(cities, self.cfg), "C:\\Mods\\Skyve.exe")
        epic = Game("epic:a", "A", "epic", launch="com.epicgames.launcher://apps/x?action=launch")
        self.assertEqual(launch.launch_target(epic, self.cfg), epic.launch)

    def test_guess_exe_skips_installers(self):
        game_dir = Path(self.tmp, "Loose")
        (game_dir / "bin").mkdir(parents=True)
        (game_dir / "unins000.exe").write_bytes(b"x" * 5000)
        (game_dir / "bin" / "Game.exe").write_bytes(b"x" * 100)
        loose = Game("other:Loose", "Loose", "other", installed=True, install_path=str(game_dir))
        self.assertEqual(launch.launch_target(loose, self.cfg), str(game_dir / "bin" / "Game.exe"))

    def test_no_second_instances(self):
        root = os.path.join(self.tmp, "PoE")
        poe = Game("steam:238960", "Path of Exile", "steam", installed=True, install_path=root)
        for name in ("trade.exe", "pob.exe"):
            Path(self.tmp, name).write_bytes(b"")
        game_exe, trade = launch.norm_path(os.path.join(root, "PoE.exe")), launch.norm_path(os.path.join(self.tmp, "trade.exe"))
        with mock.patch.object(launch, "open_target") as opened, \
             mock.patch("widget.windows.place_on_monitor"), \
             mock.patch("widget.windows.focus_first") as focus:
            self.assertEqual(launch.launch_game(poe, self.cfg, running={game_exe, trade}), "already running")
            focus.assert_called_once()
            self.assertEqual([c.args[0] for c in opened.call_args_list], [os.path.join(self.tmp, "pob.exe")])

            opened.reset_mock()
            launch.launch_game(poe, self.cfg, running=set())
            self.assertEqual([c.args[0] for c in opened.call_args_list],
                             ["steam://rungameid/238960", os.path.join(self.tmp, "trade.exe"), os.path.join(self.tmp, "pob.exe")])

    def test_tracker_reports_each_start_once(self):
        store = Store(os.path.join(self.tmp, "t.db"))
        self.addCleanup(store.close)
        started = []
        tracker = Tracker(self.cfg, store, on_start=lambda gid, name, running: started.append((gid, name)))
        root = os.path.join(self.tmp, "PoE")
        tracker.set_games([Game("steam:238960", "Path of Exile", "steam", installed=True, install_path=root)])
        exe = os.path.join(root, "PoE.exe")
        for ts in (0, 15, 30):
            tracker.poll([exe], ts)
        tracker.poll([], 45)
        tracker.poll([exe], 60)
        self.assertEqual(started, [("steam:238960", "Path of Exile")] * 2)

    def test_publisher_id(self):
        self.assertEqual(scanners.publisher_id("CN=Microsoft Corporation, O=Microsoft Corporation, L=Redmond, S=Washington, C=US"),
                         "8wekyb3d8bbwe")


class SmartPromptTests(unittest.TestCase):
    def test_genres_sessions_and_time(self):
        poe = Game("steam:1", "Path of Exile", "steam", installed=True, playtime_minutes=30000, recent_minutes=600,
                   last_played=days_ago(1), genres=["Indie", "Action", "RPG", "Adventure"], avg_session_minutes=95)
        prompt = build_prompt([poe], [], now=datetime(2026, 10, 2, 21, 40))
        self.assertIn("It's Friday evening, 21:40.", prompt)
        self.assertIn("Path of Exile [Action/RPG] (10h, usual session ~1.6h)", prompt)
        self.assertIn("Most played overall: Path of Exile (500h)", prompt)  # described once only

    def test_vr_games_get_their_own_line(self):
        dcs = Game("dcs:DCS World", "DCS World", "dcs", installed=True, playtime_minutes=56 * 60, vr=True)
        pc2 = Game("steam:378860", "Project CARS 2", "steam", installed=True, playtime_minutes=590,
                   last_played=datetime(2026, 6, 1, tzinfo=timezone.utc), vr=True)
        flat = Game("steam:1", "Flat", "steam", installed=True, playtime_minutes=60)
        prompt = build_prompt([dcs, pc2, flat], [], now=datetime(2026, 10, 2, 21, 40))
        vr_line = next(line for line in prompt.splitlines() if line.startswith("VR games"))
        self.assertIn("DCS World (56h total)", vr_line)
        self.assertIn("Project CARS 2 (9.8h total, last played 4mo ago)", vr_line)
        self.assertNotIn("Flat", vr_line)
        self.assertIn("Only suggest a VR game", prompt)

    def test_snapshot_round_trip(self):
        game = Game("steam:1", "A", "steam", last_played=days_ago(3), genres=["RPG"])
        self.assertEqual(Game.from_dict(game.to_dict()), game)

    def test_genres_are_cached_and_lookups_capped(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        store = Store(os.path.join(tmp, "t.db"))
        self.addCleanup(store.close)
        games = [Game(f"steam:{i}", f"G{i}", "steam") for i in range(3)]
        with mock.patch.object(steam_api, "genres", return_value=["RPG"]) as lookup:
            library.add_genres(games, store, max_lookups=2)
            self.assertEqual(lookup.call_count, 2)
            library.add_genres(games, store, max_lookups=2)
            self.assertEqual(lookup.call_count, 3)  # only the one still missing
        self.assertEqual([g.genres for g in games], [["RPG"]] * 3)


class AppearanceTests(unittest.TestCase):
    def test_settings_round_trip_keeps_unknown_out(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        path = Path(tmp, "Settings.inc")
        values = appearance.defaults()
        values["TextColor"] = "1,2,3"
        values["Font"] = "Bahnschrift"
        appearance.write_settings(path, values)
        self.assertEqual(appearance.read_settings(path), values)
        path.write_text("[Variables]\nBackgroundOpacity=100\nNotASetting=1\n", encoding="ascii")
        read = appearance.read_settings(path)
        self.assertEqual(read["BackgroundOpacity"], "100")
        self.assertNotIn("NotASetting", read)
        self.assertEqual(read["TextColor"], appearance.defaults()["TextColor"])

    def test_colors(self):
        self.assertEqual(appearance.parse_color("1,2,3"), ((1, 2, 3), None))
        self.assertEqual(appearance.parse_color("1,2,3,400"), ((1, 2, 3), 255))
        self.assertEqual(appearance.parse_color("junk"), ((255, 255, 255), None))
        self.assertEqual(appearance.format_color((1, 2, 3), 40), "1,2,3,40")

    def test_every_group_item_is_a_setting(self):
        names = {name for _, items in appearance.GROUPS for name, _ in items}
        self.assertEqual(names, set(appearance.defaults()))


class ExtraHoursTests(unittest.TestCase):
    def test_extra_hours_added(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        store = Store(os.path.join(tmp, "t.db"))
        self.addCleanup(store.close)
        dcs = Game("dcs:DCS World", "DCS World", "dcs", installed=True, install_path=tmp)
        cfg = Config(games={"dcs world": {"extra_hours": 56}})
        with mock.patch.object(scanners, "scan_steam", return_value=[]), \
             mock.patch.object(scanners, "scan_epic", return_value=[]), \
             mock.patch.object(scanners, "scan_gog", return_value=[]), \
             mock.patch.object(scanners, "scan_eagle_dynamics", return_value=[dcs]), \
             mock.patch.object(scanners, "scan_xbox", return_value=[]), \
             mock.patch.object(scanners, "dir_size", return_value=0):
            games, _ = library.build_library(cfg, store)
        self.assertEqual(games[0].playtime_minutes, 56 * 60)


if __name__ == "__main__":
    unittest.main()
