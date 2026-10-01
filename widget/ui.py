from __future__ import annotations

import queue
import threading
import tkinter as tk
import webbrowser
from datetime import datetime, timezone
from tkinter import ttk

from . import fmt
from .config import Config
from .dusty import DustyGame, find_dusty
from .library import build_library
from .models import Game
from .prompt import build_inspiration
from .store import Store
from .tracker import Tracker

BG, PANEL, FG, MUTED, ACCENT = "#1b1d23", "#23262e", "#e6e6e6", "#8b90a0", "#4f8cff"


class WidgetApp:
    def __init__(self, cfg: Config, store: Store, tracker: Tracker):
        self.cfg, self.store, self.tracker = cfg, store, tracker
        self.games: list[Game] = []
        self.dusty: list[DustyGame] = []
        self._busy = False
        self._results: queue.Queue = queue.Queue()

        self.root = tk.Tk()
        self.root.title("Game Widget")
        self.root.geometry("400x580")
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", cfg.always_on_top)
        self.status = tk.StringVar(value="Loading...")
        self._style()
        self._build()
        self.root.after(200, self._drain_results)
        self.refresh()
        self._schedule_auto_refresh()

    # ------------------------------------------------------------------ layout
    def _style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG,
                        rowheight=26, borderwidth=0)
        style.configure("Treeview.Heading", background=BG, foreground=MUTED, borderwidth=0)
        style.map("Treeview", background=[("selected", "#2f3a52")])
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=BG, foreground=MUTED, padding=(14, 6))
        style.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", FG)])
        style.configure("Accent.TButton", background=ACCENT, foreground="white", padding=8)
        style.map("Accent.TButton", background=[("active", "#6aa0ff")])
        style.configure("TButton", padding=8)

    def _build(self) -> None:
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(header, text="Your games", bg=BG, fg=FG, font=("Segoe UI", 13, "bold")).pack(side="left")
        self.pin = tk.BooleanVar(value=self.cfg.always_on_top)
        tk.Checkbutton(header, text="pin", variable=self.pin, command=self._toggle_pin, bg=BG, fg=MUTED,
                       selectcolor=BG, activebackground=BG, activeforeground=FG).pack(side="right")

        tk.Label(self.root, textvariable=self.status, bg=BG, fg=MUTED, anchor="w",
                 wraplength=370, justify="left").pack(fill="x", padx=12)

        tabs = ttk.Notebook(self.root)
        tabs.pack(fill="both", expand=True, padx=8, pady=8)
        self.recent_tree = self._tree(tabs, "Recent", (("name", "Game", 190), ("recent", "2 weeks", 80), ("total", "Total", 70)))
        self.top_tree = self._tree(tabs, "Most played", (("name", "Game", 190), ("total", "Total", 70), ("last", "Last played", 80)))
        self.dusty_tree = self._tree(tabs, "Dusty", (("name", "Game", 190), ("idle", "Idle", 70), ("size", "Size", 80)))

        buttons = tk.Frame(self.root, bg=BG)
        buttons.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(buttons, text="What should I play?", style="Accent.TButton",
                   command=self.inspire).pack(side="left", expand=True, fill="x", padx=(0, 6))
        ttk.Button(buttons, text="Refresh", command=self.refresh).pack(side="left")

    def _tree(self, notebook: ttk.Notebook, title: str, columns) -> ttk.Treeview:
        frame = tk.Frame(notebook, bg=PANEL)
        notebook.add(frame, text=title)
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", selectmode="browse")
        for ident, heading, width in columns:
            tree.heading(ident, text=heading)
            tree.column(ident, width=width, anchor="w" if ident == "name" else "e")
        tree.pack(fill="both", expand=True)
        return tree

    def _toggle_pin(self) -> None:
        self.root.attributes("-topmost", self.pin.get())

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.status.set("Refreshing...")
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self) -> None:
        try:
            games, warnings = build_library(self.cfg, self.store)
            dusty = find_dusty(games, self.cfg.dusty_days, datetime.now(timezone.utc),
                               self.store.tracking_started())
            self._results.put(("ok", games, dusty, warnings))
        except Exception as exc:  # surface in the status line instead of dying silently
            self._results.put(("err", str(exc)))

    def _drain_results(self) -> None:
        try:
            while True:
                kind, *payload = self._results.get_nowait()
                self._busy = False
                if kind == "ok":
                    self.games, self.dusty, warnings = payload
                    self.tracker.set_games(self.games)
                    self._populate()
                    stamp = datetime.now().strftime("%H:%M")
                    note = f"  |  {warnings[0]}" if warnings else ""
                    self.status.set(f"{len(self.games)} games, updated {stamp}{note}")
                else:
                    self.status.set(f"Refresh failed: {payload[0]}")
        except queue.Empty:
            pass
        self.root.after(200, self._drain_results)

    def _populate(self) -> None:
        for tree in (self.recent_tree, self.top_tree, self.dusty_tree):
            tree.delete(*tree.get_children())

        recent = sorted((g for g in self.games if g.recent_minutes > 0), key=lambda g: -g.recent_minutes)
        for g in recent[: self.cfg.recent_count]:
            self.recent_tree.insert("", "end", values=(g.name, fmt.hours(g.recent_minutes), fmt.hours(g.playtime_minutes)))

        top = sorted((g for g in self.games if g.playtime_minutes > 0), key=lambda g: -g.playtime_minutes)
        for g in top[: self.cfg.most_played_count]:
            self.top_tree.insert("", "end", values=(g.name, fmt.hours(g.playtime_minutes), fmt.ago(g.last_played)))

        for d in self.dusty[: self.cfg.dusty_count]:
            self.dusty_tree.insert("", "end", values=(d.game.name, fmt.idle(d.idle_days), fmt.size(d.game.size_bytes)))

    def _schedule_auto_refresh(self) -> None:
        self.root.after(self.cfg.refresh_minutes * 60_000, self._auto_refresh)

    def _auto_refresh(self) -> None:
        self.refresh()
        self._schedule_auto_refresh()

    # ------------------------------------------------------------------ Claude button
    def inspire(self) -> None:
        if not self.games:
            self.status.set("Nothing loaded yet - hit Refresh first.")
            return
        prompt, url, prefilled = build_inspiration(self.games, self.dusty)
        self.root.clipboard_clear()
        self.root.clipboard_append(prompt)
        webbrowser.open(url)
        self.status.set(
            "Opened Claude with your prompt prefilled." if prefilled
            else "Opened Claude - paste (Ctrl+V): the prompt is on your clipboard."
        )

    def run(self) -> None:
        self.root.mainloop()
