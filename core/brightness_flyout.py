"""Replace the Windows 11 brightness flyout after a verified brightness notification."""

import ctypes
from ctypes import wintypes
from time import monotonic
from uuid import UUID


_BRIGHTNESS_GUID = UUID("8ffee2c6-2d01-46be-adb9-398addc5b4ff").bytes_le
_SHOW = 0x8002  # EVENT_OBJECT_SHOW
_WIN_EVENT = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
                                wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)


class BrightnessFlyout:
    def __init__(self, can_show, show):
        self._can_show = can_show
        self._show = show
        self._user32 = ctypes.windll.user32
        self._hook = None
        self._notification = None
        self._level = None
        self._window = None
        self._change = None
        self._last_shown = float("-inf")
        self._callback = _WIN_EVENT(self._window_shown)

    def start(self, hwnd):
        if not hasattr(self._user32, "GetWindowBand"):
            return
        self._user32.GetShellWindow.restype = wintypes.HWND
        self._user32.SetWinEventHook.restype = wintypes.HANDLE
        self._user32.RegisterPowerSettingNotification.restype = wintypes.HANDLE
        self._hook = self._user32.SetWinEventHook(_SHOW, _SHOW, None, self._callback, 0, 0, 2)
        if self._hook:
            self._notification = self._user32.RegisterPowerSettingNotification(
                hwnd, ctypes.create_string_buffer(_BRIGHTNESS_GUID), 0)
            if not self._notification:
                self.close()

    def close(self):
        if self._hook:
            self._user32.UnhookWinEvent(wintypes.HANDLE(self._hook))
            self._hook = None
        if self._notification:
            self._user32.UnregisterPowerSettingNotification(wintypes.HANDLE(self._notification))
            self._notification = None

    def power_setting_changed(self, address):
        if not self._notification or not address:
            return False
        header = ctypes.string_at(address, 20)
        if header[:16] != _BRIGHTNESS_GUID or int.from_bytes(header[16:], "little") != 4:
            return False
        value = wintypes.DWORD.from_address(address + 20).value
        if value <= 100:
            self._record_level(value)
        return True

    def _record_level(self, value):
        previous, self._level = self._level, value
        if previous is None:
            return  # Registration immediately sends the current value.
        now = monotonic()
        self._change = (now, previous, value)
        if not self._pair() and previous != value and now - self._last_shown < 1 and self._can_show():
            # The shell can update the same hidden flyout during a held key.
            self._last_shown = now
            self._show(previous, value)

    def _window_shown(self, hook, event, hwnd, object_id, child_id, thread, timestamp):
        if hwnd and object_id == 0 and child_id == 0 and self._is_shell_indicator(hwnd):
            self._window = (hwnd, monotonic())
            self._pair()

    def _pair(self):
        if self._window is None or self._change is None:
            return False
        hwnd, shown_at = self._window
        changed_at, previous, value = self._change
        if abs(shown_at - changed_at) > 0.45 or not self._can_show():
            return False
        self._window = None
        if not self._hide_indicator(hwnd):
            return False
        if changed_at > self._last_shown:
            self._last_shown = changed_at
            self._show(previous, value)
        return True

    def _is_shell_indicator(self, hwnd):
        user32 = self._user32
        hwnd = wintypes.HWND(hwnd)
        name = ctypes.create_unicode_buffer(64)
        if (not user32.GetClassNameW(hwnd, name, len(name))
                or name.value != "XamlExplorerHostIslandWindow" or user32.GetWindowTextLengthW(hwnd)):
            return False
        pid, shell_pid, band = wintypes.DWORD(), wintypes.DWORD(), wintypes.DWORD()
        shell = user32.GetShellWindow()
        if not shell:
            return False
        user32.GetWindowThreadProcessId(wintypes.HWND(shell), ctypes.byref(shell_pid))
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value or pid.value != shell_pid.value:
            return False
        # Explorer shares the XAML class with Task Switching and other surfaces.
        if not user32.GetWindowBand(hwnd, ctypes.byref(band)) or band.value != 18:
            return False
        rect = wintypes.RECT()
        dpi = user32.GetDpiForWindow(hwnd) or 96
        return (bool(user32.GetWindowRect(hwnd, ctypes.byref(rect)))
                and 0 < rect.right - rect.left <= 4 * dpi and 0 < rect.bottom - rect.top <= 2 * dpi)

    def _hide_indicator(self, hwnd):
        return (self._is_shell_indicator(hwnd) and self._user32.IsWindowVisible(wintypes.HWND(hwnd))
                and self._user32.ShowWindowAsync(wintypes.HWND(hwnd), 0))  # SW_HIDE
