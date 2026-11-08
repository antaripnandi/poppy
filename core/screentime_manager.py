"""
Poppy Screen Time & Digital Wellbeing Engine
Monitors user active/idle status and foreground application usage.
Features AFK idle pauses, daily goals, healthy break reminders, and local persistence.
Pure Python standard library + Win32 ctypes (zero external dependencies).
"""

import os
import sys
import json
import time
import datetime
from pathlib import Path
import ctypes
from ctypes import wintypes
from PySide6.QtCore import QObject, Signal, QTimer
from poppy.core.storage import data_path, write_json


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD)
    ]


def _get_idle_seconds() -> float:
    """Return number of seconds since last user keyboard or mouse input."""
    try:
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            millis = (ctypes.windll.kernel32.GetTickCount() - lii.dwTime) & 0xFFFFFFFF
            return max(0.0, millis / 1000.0)
    except Exception:
        pass
    return 0.0


def _get_active_app_name() -> str:
    """Return the friendly name of the active foreground application."""
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.GetForegroundWindow.restype = wintypes.HWND
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return "System"

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return "System"

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        hProcess = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not hProcess:
            return "System"

        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        exe_name = ""
        if kernel32.QueryFullProcessImageNameW(hProcess, 0, buf, ctypes.byref(size)):
            exe_name = os.path.basename(buf.value)
        kernel32.CloseHandle(hProcess)

        if exe_name:
            base, _ = os.path.splitext(exe_name)
            mapping = {
                "code": "Visual Studio Code",
                "brave": "Brave",
                "chrome": "Chrome",
                "msedge": "Edge",
                "firefox": "Firefox",
                "spotify": "Spotify",
                "discord": "Discord",
                "telegram": "Telegram",
                "slack": "Slack",
                "notion": "Notion",
                "windowsterminal": "Terminal",
                "powershell": "PowerShell",
                "cmd": "Command Prompt",
                "explorer": "File Explorer",
                "poppy": "Poppy Notch",
                "devenv": "Visual Studio"
            }
            return mapping.get(base.lower(), base.capitalize())
    except Exception:
        pass
    return "Desktop"


def format_duration(seconds: int) -> str:
    """Format seconds into '2h 15m' or '45m' string."""
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h > 0:
        return f"{h}h {m:02d}m"
    return f"{m}m"


class ScreenTimeManager(QObject):
    """
    Background Screen Time tracker and health advisor.
    Emits periodic updates for UI chips and notifies when goals/breaks are triggered.
    """
    stats_updated = Signal(int, int, list, str)  # total_seconds, streak_seconds, top_apps [(name, sec, fmt)], active_app
    break_reminder_triggered = Signal(int)       # streak_minutes
    daily_goal_reached = Signal(float)          # goal_hours

    def __init__(self, config: dict = None, parent=None):
        super().__init__(parent)
        self.config = config or {}
        self._cache_file = data_path("screentime.json")

        self._today_str = datetime.date.today().isoformat()
        self._today_seconds = 0
        self._continuous_seconds = 0
        self._today_apps: dict[str, int] = {}
        self._current_app = "Desktop"

        self._goal_alerted_today = False
        self._last_break_alert_minute = 0
        self._save_counter = 0

        self._load_data()

        # 1-second pulse timer
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_tick)
        if self.is_enabled():
            self._timer.start()

    def update_config(self, config: dict):
        self._save_data()
        self.config = config or {}
        if self.is_enabled():
            self._timer.start()
        else:
            self._timer.stop()

    def _cfg(self) -> dict:
        return self.config.get("screentime", {})

    def is_enabled(self) -> bool:
        return self._cfg().get("enabled", True)

    def get_today_seconds(self) -> int:
        return self._today_seconds

    def get_formatted_today(self) -> str:
        return format_duration(self._today_seconds)

    def get_goal_hours(self) -> float:
        return float(self._cfg().get("daily_goal_hours", 6.0))

    def get_goal_progress(self) -> float:
        goal_sec = self.get_goal_hours() * 3600.0
        if goal_sec <= 0:
            return 0.0
        return min(1.0, max(0.0, self._today_seconds / goal_sec))

    def get_top_apps(self, limit: int = 4) -> list[tuple[str, int, str]]:
        """Return [(app_name, seconds, formatted_str)] sorted by duration desc."""
        sorted_apps = sorted(self._today_apps.items(), key=lambda x: x[1], reverse=True)
        return [(name, sec, format_duration(sec)) for name, sec in sorted_apps[:limit]]

    def reset_today(self):
        """Reset today's recorded screen time and streak."""
        self._today_seconds = 0
        self._continuous_seconds = 0
        self._today_apps.clear()
        self._goal_alerted_today = False
        self._last_break_alert_minute = 0
        self._save_data()
        self.stats_updated.emit(0, 0, [], self._current_app)

    def _on_tick(self):
        if not self.is_enabled():
            return

        # Check date rollover at midnight
        today = datetime.date.today().isoformat()
        if today != self._today_str:
            self._save_data()
            self._today_str = today
            self._today_seconds = 0
            self._continuous_seconds = 0
            self._today_apps.clear()
            self._goal_alerted_today = False
            self._last_break_alert_minute = 0

        # Check if user is active or AFK/idle
        idle_threshold = int(self._cfg().get("idle_threshold_seconds", 120))
        idle_sec = _get_idle_seconds()
        self._current_app = ""

        if idle_sec < idle_threshold:
            # User is active
            self._today_seconds += 1
            self._continuous_seconds += 1

            # Track foreground app
            if self._cfg().get("track_apps", True):
                app_name = _get_active_app_name()
                excluded = [x.strip().lower() for x in self._cfg().get("excluded_apps", []) if x.strip()]
                if app_name.lower() not in excluded:
                    self._current_app = app_name
                    self._today_apps[app_name] = self._today_apps.get(app_name, 0) + 1

            # Check healthy break reminder
            if self._cfg().get("break_reminders_enabled", True):
                interval_min = int(self._cfg().get("break_interval_minutes", 60))
                if interval_min > 0:
                    streak_min = self._continuous_seconds // 60
                    if streak_min >= self._last_break_alert_minute + interval_min:
                        self._last_break_alert_minute = streak_min
                        self.break_reminder_triggered.emit(streak_min)

            # Check daily goal
            if self._cfg().get("goal_alert_enabled", True) and not self._goal_alerted_today:
                goal_sec = int(self.get_goal_hours() * 3600)
                if goal_sec > 0 and self._today_seconds >= goal_sec:
                    self._goal_alerted_today = True
                    self.daily_goal_reached.emit(self.get_goal_hours())

        else:
            # User is idle / AFK: pause active time and reset streak
            self._continuous_seconds = 0
            self._last_break_alert_minute = 0

        # Periodic disk save every 30s
        self._save_counter += 1
        if self._save_counter >= 30:
            self._save_counter = 0
            self._save_data()

        # Emit stats update every 2 seconds
        if self._save_counter % 2 == 0:
            top_apps = self.get_top_apps(5) if self._cfg().get("track_apps", True) else []
            self.stats_updated.emit(self._today_seconds, self._continuous_seconds, top_apps, self._current_app)

    def _load_data(self):
        try:
            if self._cache_file.exists():
                with open(self._cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    day_data = data.get(self._today_str, {})
                    self._today_seconds = day_data.get("seconds", 0)
                    self._today_apps = day_data.get("apps", {})
                    self._goal_alerted_today = day_data.get("goal_alerted", False)
        except Exception:
            pass

    def _save_data(self):
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            if self._cache_file.exists():
                try:
                    with open(self._cache_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    data = {}

            data[self._today_str] = {
                "seconds": self._today_seconds,
                "apps": self._today_apps,
                "goal_alerted": self._goal_alerted_today,
                "updated_at": datetime.datetime.now().isoformat()
            }

            # Keep only last 14 days of history to avoid growth
            if len(data) > 14:
                sorted_keys = sorted(data.keys())
                for k in sorted_keys[:-14]:
                    del data[k]

            write_json(self._cache_file, data)
        except Exception:
            pass

    def close(self):
        self._timer.stop()
        self._save_data()

