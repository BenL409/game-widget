"""Appearance window for the Rainmeter panel (opened from the cog next to its title).

Every change is written to Settings.inc and the skin is refreshed, so the panel previews live.
Done keeps the changes; Cancel (or Esc) puts the file back exactly as it was.
"""

from __future__ import annotations

import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import colorchooser, ttk

from . import appearance, rainmeter
from .config import Config

TITLE = "Game Widget Appearance"
BG, PANEL, FG, MUTED, ACCENT = "#1b1d23", "#23262e", "#e6e6e6", "#8b90a0", "#d97757"


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def _focus_existing() -> bool:
    """One window only: if it's already open, bring it forward instead."""
    import ctypes

    hwnd = ctypes.windll.user32.FindWindowW(None, TITLE)
    if not hwnd:
        return False
    ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    ctypes.windll.user32.SetForegroundWindow(hwnd)
    return True


class AppearanceWindow:
    def __init__(self, path: Path):
        self.path = path
        self.original = path.read_bytes() if path.exists() else None
        self.values = appearance.read_settings(path)
        self._pending: str | None = None

        self.root = tk.Tk()
        self.root.title(TITLE)
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.done)
        self.root.bind("<Escape>", lambda _e: self.cancel())
        self._style()
        self.families = sorted({f for f in tkfont.families(self.root) if not f.startswith("@")}, key=str.lower)
        self.body = tk.Frame(self.root, bg=BG)
        self.body.pack(fill="both", expand=True, padx=16, pady=(12, 4))
        self._build_body()
        self._build_buttons()

    # ------------------------------------------------------------------ layout
    def _style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=PANEL, background=PANEL, foreground=FG, arrowcolor=MUTED,
                        bordercolor=PANEL, lightcolor=PANEL, darkcolor=PANEL)
        style.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", FG)])
        style.configure("Horizontal.TScale", background=BG, troughcolor=PANEL, bordercolor=BG,
                        lightcolor=MUTED, darkcolor=MUTED)
        style.configure("TButton", padding=(14, 6), background=PANEL, foreground=FG, bordercolor=PANEL)
        style.map("TButton", background=[("active", "#2f3340")])
        style.configure("Accent.TButton", background=ACCENT, foreground="white", bordercolor=ACCENT)
        style.map("Accent.TButton", background=[("active", "#e78d6e")])
        self.root.option_add("*TCombobox*Listbox.background", PANEL)
        self.root.option_add("*TCombobox*Listbox.foreground", FG)

    def _build_body(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        row = 0
        for heading, items in appearance.GROUPS:
            tk.Label(self.body, text=heading.upper(), bg=BG, fg=MUTED, font=("Segoe UI", 8, "bold"),
                     anchor="w").grid(row=row, column=0, columnspan=3, sticky="w", pady=(10 if row else 0, 4))
            row += 1
            for name, label in items:
                tk.Label(self.body, text=label, bg=BG, fg=FG, font=("Segoe UI", 10), anchor="w", width=18
                         ).grid(row=row, column=0, sticky="w", pady=3)
                if name.endswith("Font"):
                    self._font_row(name, row)
                elif appearance.is_color(name):
                    self._color_row(name, row)
                else:
                    self._alpha_slider(name, row, column=1, columnspan=2, get=lambda n=name: int(self.values[n]),
                                       put=lambda v, n=name: self.set(n, str(v)))
                row += 1

    def _font_row(self, name: str, row: int) -> None:
        var = tk.StringVar(value=self.values[name])
        box = ttk.Combobox(self.body, textvariable=var, values=self.families, width=26, state="readonly")
        box.grid(row=row, column=1, columnspan=2, sticky="we")
        box.bind("<<ComboboxSelected>>", lambda _e: self.set(name, var.get()))

    def _color_row(self, name: str, row: int) -> None:
        rgb, alpha = appearance.parse_color(self.values[name])
        swatch = tk.Label(self.body, bg=_hex(rgb), width=4, relief="flat", cursor="hand2",
                          highlightthickness=1, highlightbackground=MUTED)
        swatch.grid(row=row, column=1, sticky="w")

        def pick(_event=None):
            current, current_alpha = appearance.parse_color(self.values[name])
            chosen, _ = colorchooser.askcolor(color=_hex(current), parent=self.root, title=f"{TITLE}: colour")
            if chosen:
                new_rgb = tuple(int(c) for c in chosen)
                swatch.configure(bg=_hex(new_rgb))
                self.set(name, appearance.format_color(new_rgb, current_alpha))

        swatch.bind("<Button-1>", pick)
        if alpha is not None:  # colours that carry their own transparency get an opacity slider too
            def put(value: int) -> None:
                current, _ = appearance.parse_color(self.values[name])
                self.set(name, appearance.format_color(current, value))

            self._alpha_slider(name, row, column=2, columnspan=1,
                               get=lambda: appearance.parse_color(self.values[name])[1] or 0, put=put)

    def _alpha_slider(self, name: str, row: int, column: int, columnspan: int, get, put) -> None:
        frame = tk.Frame(self.body, bg=BG)
        frame.grid(row=row, column=column, columnspan=columnspan, sticky="we", padx=(8 if column == 2 else 0, 0))
        readout = tk.Label(frame, bg=BG, fg=MUTED, font=("Segoe UI", 9), width=5, anchor="e")
        var = tk.IntVar(value=get())

        def changed(_value=None):
            value = int(float(var.get()))
            readout.configure(text=f"{round(value / 2.55)}%")
            put(value)

        scale = ttk.Scale(frame, from_=0, to=255, variable=var, command=changed, length=140)
        scale.pack(side="left", fill="x", expand=True)
        readout.pack(side="left")
        readout.configure(text=f"{round(get() / 2.55)}%")

    def _build_buttons(self) -> None:
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=16, pady=(8, 14))
        ttk.Button(bar, text="Reset to defaults", command=self.reset).pack(side="left")
        ttk.Button(bar, text="Done", style="Accent.TButton", command=self.done).pack(side="right")
        ttk.Button(bar, text="Cancel", command=self.cancel).pack(side="right", padx=(0, 8))

    # ------------------------------------------------------------------ changes
    def set(self, name: str, value: str) -> None:
        if self.values.get(name) == value:
            return
        self.values[name] = value
        if self._pending:
            self.root.after_cancel(self._pending)
        self._pending = self.root.after(200, self._apply)  # debounce slider drags

    def _apply(self) -> None:
        self._pending = None
        appearance.write_settings(self.path, self.values)
        threading.Thread(target=rainmeter.refresh_skins, daemon=True).start()

    def reset(self) -> None:
        self.values = appearance.defaults()
        self._build_body()
        self._apply()

    def done(self) -> None:
        if self._pending:
            self.root.after_cancel(self._pending)
            self._apply()
        self.root.destroy()

    def cancel(self) -> None:
        if self._pending:
            self.root.after_cancel(self._pending)
        if self.original is None:
            self.path.unlink(missing_ok=True)
        else:
            self.path.write_bytes(self.original)
        rainmeter.refresh_skins()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def open_window(cfg: Config) -> None:
    if sys.platform == "win32":
        if _focus_existing():
            return
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp text on scaled displays
        except (AttributeError, OSError):
            pass
    path = rainmeter.data_path(cfg.rainmeter_skin_dir).with_name("Settings.inc")
    AppearanceWindow(path).run()
