from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from widget import fmt
from widget.config import app_data_dir, load_config
from widget.dusty import find_dusty
from widget.library import build_library
from widget.store import Store


def print_report(cfg, store) -> None:
    games, warnings = build_library(cfg, store)
    now = datetime.now(timezone.utc)
    dusty = find_dusty(games, cfg.dusty_days, now, store.tracking_started())

    for warning in warnings:
        print(f"! {warning}")
    print(f"\n{len(games)} games found\n")

    print("RECENT (2 weeks)")
    for g in sorted((g for g in games if g.recent_minutes > 0), key=lambda g: -g.recent_minutes)[: cfg.recent_count]:
        print(f"  {g.name:<40} {fmt.hours(g.recent_minutes):>7}  ({fmt.hours(g.playtime_minutes)} total)")

    print("\nMOST PLAYED")
    for g in sorted((g for g in games if g.playtime_minutes > 0), key=lambda g: -g.playtime_minutes)[: cfg.most_played_count]:
        print(f"  {g.name:<40} {fmt.hours(g.playtime_minutes):>7}  last {fmt.ago(g.last_played, now)}")

    print(f"\nDUSTY (installed, idle {cfg.dusty_days}+ days)")
    for d in dusty[: cfg.dusty_count]:
        detail = fmt.idle(d.idle_days) if d.idle_days is not None else d.note
        print(f"  {d.game.name:<40} {detail:>10}  {fmt.size(d.game.size_bytes)}")


def install_skin(cfg) -> None:
    """Link the repo's skin folder into Rainmeter's Skins folder, so edits here show up live."""
    import subprocess

    from widget import rainmeter

    source = Path(__file__).resolve().parent / "rainmeter" / rainmeter.SKIN_NAME
    target = Path(cfg.rainmeter_skin_dir) if cfg.rainmeter_skin_dir else rainmeter.skins_dir() / rainmeter.SKIN_NAME
    if target.exists() or target.is_junction():
        if target.resolve() != source.resolve():
            raise SystemExit(f"{target} already exists and isn't linked to this repo - move it away first.")
        print(f"Already linked: {target}")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["cmd", "/c", "mklink", "/J", str(target), str(source)], check=True,
                       stdout=subprocess.DEVNULL)
        print(f"Linked {target} -> {source}")
    print("Now in Rainmeter: Manage > Refresh all, then load a GameWidget skin.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Game widget: Steam + standalone + Xbox playtime")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--cli", action="store_true", help="print a text report")
    mode.add_argument("--window", action="store_true", help="open the standalone tkinter widget")
    mode.add_argument("--refresh", action="store_true", help="update the Rainmeter skin data once and exit")
    mode.add_argument("--inspire", action="store_true", help="copy the 'what should I play?' prompt and open Claude")
    mode.add_argument("--launch", metavar="GAME_ID", help="start a game (and its companions) unless it's running")
    mode.add_argument("--uninstall", metavar="GAME_ID", help="open the game's uninstaller")
    mode.add_argument("--install-skin", action="store_true", help="link the Rainmeter skins into your Skins folder")
    mode.add_argument("--startup", choices=["on", "off"], help="run the background service at login")
    args = parser.parse_args()

    cfg = load_config()
    if args.install_skin:
        install_skin(cfg)
        return
    store = Store(app_data_dir() / "data.db")

    if args.cli:
        print_report(cfg, store)
        return

    from widget import service

    service.setup_logging()
    if args.refresh:
        print(f"Wrote skin data for {service.refresh_once(cfg, store)} games.")
    elif args.inspire:
        service.inspire(cfg, store)
    elif args.launch:
        print(service.launch(cfg, store, args.launch))
    elif args.uninstall:
        print(service.uninstall(cfg, store, args.uninstall))
    elif args.startup:
        print(service.set_startup(args.startup == "on"))
    elif args.window:
        from widget.ui import WidgetApp

        tracker = service.make_tracker(cfg, store)
        tracker.start()
        try:
            WidgetApp(cfg, store, tracker).run()
        finally:
            tracker.stop()
    else:
        service.run_service(cfg, store)


if __name__ == "__main__":
    main()
