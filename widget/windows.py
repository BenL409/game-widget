"""Win32 window placement: move a program's windows onto a given monitor once they appear."""

from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes

import psutil

log = logging.getLogger("gamewidget")

user32 = ctypes.WinDLL("user32", use_last_error=True)

SW_RESTORE, SW_MAXIMIZE = 9, 3
SWP_NOZORDER, SWP_NOACTIVATE = 0x0004, 0x0010
GW_OWNER = 4
MONITOR_DEFAULTTONEAREST = 2


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]


_MonitorEnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                      ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
_WndEnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p, _MonitorEnumProc, wintypes.LPARAM]
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HMONITOR
user32.EnumWindows.argtypes = [_WndEnumProc, wintypes.LPARAM]
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, wintypes.UINT]
for _name in ("IsWindowVisible", "IsZoomed", "IsIconic", "GetWindowTextLengthW", "SetForegroundWindow"):
    getattr(user32, _name).argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]


def _device(monitor) -> tuple[str, wintypes.RECT]:
    info = MONITORINFOEXW()
    info.cbSize = ctypes.sizeof(info)
    user32.GetMonitorInfoW(monitor, ctypes.byref(info))
    return info.szDevice, info.rcWork


def monitor_work_area(number: int) -> wintypes.RECT | None:
    """Work area of \\\\.\\DISPLAY<number> (the number Windows shows in Settings > Display)."""
    wanted = f"\\\\.\\DISPLAY{number}"
    found: list[wintypes.RECT] = []

    def callback(monitor, _hdc, _rect, _lparam):
        device, work = _device(monitor)
        if device.upper() == wanted:
            found.append(work)
        return True

    user32.EnumDisplayMonitors(None, None, _MonitorEnumProc(callback), 0)
    return found[0] if found else None


def _windows_of(exe: str) -> list[int]:
    target = exe.lower()
    hwnds: list[int] = []

    def callback(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd) and not user32.GetWindow(hwnd, GW_OWNER) and user32.GetWindowTextLengthW(hwnd):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            try:
                if psutil.Process(pid.value).exe().lower() == target:
                    hwnds.append(hwnd)
            except psutil.Error:
                pass
        return True

    user32.EnumWindows(_WndEnumProc(callback), 0)
    return hwnds


def focus_first(match) -> bool:
    """Bring forward the first top-level window whose process exe satisfies `match(exe)`."""
    found: list[int] = []

    def callback(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd) and not user32.GetWindow(hwnd, GW_OWNER) and user32.GetWindowTextLengthW(hwnd):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            try:
                if match(psutil.Process(pid.value).exe()):
                    found.append(hwnd)
                    return False
            except psutil.Error:
                pass
        return True

    user32.EnumWindows(_WndEnumProc(callback), 0)
    if not found:
        return False
    if user32.IsIconic(found[0]):
        user32.ShowWindow(found[0], SW_RESTORE)
    return bool(user32.SetForegroundWindow(found[0]))


def _move(hwnd: int, work: wintypes.RECT) -> None:
    maximized = user32.IsZoomed(hwnd)
    if maximized:
        user32.ShowWindow(hwnd, SW_RESTORE)
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    work_w, work_h = work.right - work.left, work.bottom - work.top
    w, h = min(rect.right - rect.left, work_w), min(rect.bottom - rect.top, work_h)
    x, y = work.left + (work_w - w) // 2, work.top + (work_h - h) // 2
    user32.SetWindowPos(hwnd, None, x, y, w, h, SWP_NOZORDER | SWP_NOACTIVATE)
    if maximized:
        user32.ShowWindow(hwnd, SW_MAXIMIZE)


def place_on_monitor(exe: str, number: int, timeout: float = 60.0, settle: float = 10.0) -> None:
    """Wait for `exe`'s windows, centre them on monitor `number` (keeping maximised windows maximised),
    and keep correcting for `settle` seconds in case the app restores its own saved position."""
    user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2: real pixel coordinates
    work = monitor_work_area(number)
    if work is None:
        log.warning("monitor %d not found; leaving %s where it opens", number, exe)
        return
    wanted = f"\\\\.\\DISPLAY{number}"
    deadline, seen_at = time.time() + timeout, None
    while time.time() < deadline:
        hwnds = _windows_of(exe)
        if hwnds:
            seen_at = seen_at or time.time()
            for hwnd in hwnds:
                if _device(user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST))[0].upper() != wanted:
                    _move(hwnd, work)
            if time.time() - seen_at > settle:
                return
        time.sleep(0.5)
