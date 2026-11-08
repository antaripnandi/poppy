"""Mirror Windows brightness and volume feedback in the compact pill."""

import ctypes
from ctypes import wintypes
from time import monotonic
from uuid import UUID

from PySide6.QtCore import QTimer


_BRIGHTNESS_GUID = UUID("8ffee2c6-2d01-46be-adb9-398addc5b4ff").bytes_le
_SHELL_CLASS = "XamlExplorerHostIslandWindow"
_CREATE = 0x8000
_DESTROY = 0x8001
_SHOW = 0x8002  # EVENT_OBJECT_SHOW
_VOLUME_DOWN, _VOLUME_UP = 0xAE, 0xAF
_WIN_EVENT = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
                                wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)
_KEY_EVENT = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class BrightnessFlyout:
    def __init__(self, can_show, show, *, read_volume=None, show_volume=None):
        self._can_show = can_show
        self._show = show
        self._user32 = ctypes.windll.user32
        self._gdi32 = ctypes.windll.gdi32
        self._hook = None
        self._key_hook = None
        self._volume_key = None
        self._notification = None
        self._read_volume = read_volume
        self._show_volume = show_volume
        self._volume = None
        self._volume_window = None
        self._volume_reported = False
        self._volume_timer = QTimer()
        self._volume_timer.setInterval(75)
        self._volume_timer.timeout.connect(self._poll_volume)
        self._clipped = None
        self._level = None
        self._window = None
        self._change = None
        self._last_shown = float("-inf")
        self._callback = _WIN_EVENT(self._window_event)
        self._key_callback = _KEY_EVENT(self._keyboard_event)

    def start(self, hwnd):
        if not hasattr(self._user32, "GetWindowBand"):
            return
        self._user32.GetShellWindow.restype = wintypes.HWND
        self._user32.FindWindowExW.restype = wintypes.HWND
        self._user32.SetWinEventHook.restype = wintypes.HANDLE
        self._user32.RegisterPowerSettingNotification.restype = wintypes.HANDLE
        self._gdi32.CreateRectRgn.restype = wintypes.HRGN
        self._hook = self._user32.SetWinEventHook(_CREATE, _SHOW, None, self._callback, 0, 0, 2)
        if self._hook:
            self._notification = self._user32.RegisterPowerSettingNotification(
                hwnd, ctypes.create_string_buffer(_BRIGHTNESS_GUID), 0)
            self.refresh_volume()
            if self._read_volume:
                self._user32.SetWindowsHookExW.argtypes = (ctypes.c_int, _KEY_EVENT, wintypes.HMODULE, wintypes.DWORD)
                self._user32.SetWindowsHookExW.restype = wintypes.HHOOK
                self._user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
                self._user32.CallNextHookEx.restype = ctypes.c_ssize_t
                kernel = ctypes.windll.kernel32
                kernel.GetModuleHandleW.restype = wintypes.HMODULE
                self._key_hook = self._user32.SetWindowsHookExW(13, self._key_callback, kernel.GetModuleHandleW(None), 0)

    def close(self):
        self._volume_timer.stop()
        self._volume_window = None
        if self._key_hook:
            self._user32.UnhookWindowsHookEx(wintypes.HHOOK(self._key_hook))
            self._key_hook = None
        self._volume_key = None
        if self._hook:
            self._user32.UnhookWinEvent(wintypes.HANDLE(self._hook))
            self._hook = None
        self._restore_indicator()
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
            self.sync()
            return  # Registration immediately sends the current value.
        if previous == value:
            return
        now = monotonic()
        self._change = (now, previous, value)
        if self._clipped and self._can_show() and self._user32.IsWindowVisible(wintypes.HWND(self._clipped[0])):
            self._last_shown = now
            self._show(previous, value)
        elif not self._pair() and now - self._last_shown < 1 and self._can_show():
            # The shell can update the same hidden flyout during a held key.
            self._last_shown = now
            self._show(previous, value)

    def _window_event(self, hook, event, hwnd, object_id, child_id, thread, timestamp):
        if not hwnd or object_id != 0 or child_id != 0:
            return
        if event == _DESTROY:
            if self._volume_window and self._volume_window[0] == hwnd:
                self._volume_window = None
                self._volume_timer.stop()
            if self._clipped and self._clipped[0] == hwnd:
                _, saved = self._clipped
                self._clipped = None
                if saved:
                    self._gdi32.DeleteObject(wintypes.HRGN(saved))
            return
        if not self._is_shell_indicator(hwnd):
            return
        self.sync(hwnd)
        if event == _SHOW:
            now = monotonic()
            self._window = (hwnd, now)
            self._pair()
            if self._read_volume and self._can_show():
                self._volume_window = (hwnd, now)
                self._volume_reported = False
                self._volume_timer.start()
                self._poll_volume()

    def refresh_volume(self):
        if self._hook and self._read_volume and not self._volume_timer.isActive():
            was_available = self._volume is not None
            self._volume = self._read_volume()
            if was_available != (self._volume is not None):
                self.sync()

    def _keyboard_event(self, code, message, address):
        # Observe the volume buttons for unchanged readings at the limits.
        # Windows receives every key and owns the actual volume change.
        if code == 0 and message in (0x100, 0x104) and address:
            key = wintypes.DWORD.from_address(address).value
            if key in (_VOLUME_DOWN, _VOLUME_UP):
                self._volume_key = (key, monotonic())
        return self._user32.CallNextHookEx(None, code, message, address)

    def _poll_volume(self):
        window = self._volume_window
        if window is None or not self._can_show() or monotonic() - window[1] > 2.5:
            self._volume_timer.stop()
            self._volume_window = None
            return
        hwnd, _ = window
        previous, self._volume = self._volume, self._read_volume()
        if self._volume is None:
            self.sync()
            return
        if previous is None:
            return
        if previous == self._volume:
            level, _ = self._volume
            key, pressed_at = self._volume_key or (None, float("-inf"))
            at_limit = (key, level) in ((_VOLUME_DOWN, 0), (_VOLUME_UP, 100))
            if self._volume_reported or not at_limit or abs(window[1] - pressed_at) > 0.45:
                return
        clipped = self._clipped and self._clipped[0] == hwnd
        if clipped or self._volume_reported or self._hide_indicator(hwnd):
            self._volume_key = None
            self._volume_reported = True
            self._volume_window = (hwnd, monotonic())
            self._show_volume(previous, self._volume)

    def sync(self, hwnd=None):
        # Clip the shared host only while both levels can be read and shown.
        if not (self._notification and self._volume is not None and self._level is not None and self._can_show()):
            self._restore_indicator()
            return
        if hwnd is None and self._clipped and self._is_shell_indicator(self._clipped[0]):
            return
        if hwnd is None:
            candidate = None
            while candidate := self._user32.FindWindowExW(
                    None, wintypes.HWND(candidate), ctypes.c_wchar_p(_SHELL_CLASS), ctypes.c_wchar_p("")):
                if self._is_shell_indicator(candidate):
                    hwnd = candidate
                    break
        if hwnd is not None and (not self._clipped or self._clipped[0] != hwnd):
            self._restore_indicator()
            self._clip_indicator(hwnd)

    def _clip_indicator(self, hwnd):
        handle = wintypes.HWND(hwnd)
        saved = self._gdi32.CreateRectRgn(0, 0, 0, 0)
        if not saved:
            return
        kind = self._user32.GetWindowRgn(handle, wintypes.HRGN(saved))
        if kind <= 1:
            self._gdi32.DeleteObject(wintypes.HRGN(saved))
            if kind == 1:  # Another owner already clipped it.
                return
            saved = None
        blank = self._gdi32.CreateRectRgn(0, 0, 0, 0)
        if blank and self._user32.SetWindowRgn(handle, wintypes.HRGN(blank), True):
            self._clipped = (hwnd, saved)
            return
        if blank:
            self._gdi32.DeleteObject(wintypes.HRGN(blank))
        if saved:
            self._gdi32.DeleteObject(wintypes.HRGN(saved))

    def _restore_indicator(self):
        if not self._clipped:
            return
        hwnd, saved = self._clipped
        self._clipped = None
        if self._is_shell_indicator(hwnd, check_size=False):
            region = self._gdi32.CreateRectRgn(0, 0, 0, 0)
            if region:
                kind = self._user32.GetWindowRgn(wintypes.HWND(hwnd), wintypes.HRGN(region))
                self._gdi32.DeleteObject(wintypes.HRGN(region))
                if kind == 1 and self._user32.SetWindowRgn(wintypes.HWND(hwnd), wintypes.HRGN(saved), True):
                    return
        if saved:
            self._gdi32.DeleteObject(wintypes.HRGN(saved))

    def _pair(self):
        if self._window is None or self._change is None:
            return False
        hwnd, shown_at = self._window
        changed_at, previous, value = self._change
        if abs(shown_at - changed_at) > 0.45 or not self._can_show():
            return False
        self._window = None
        if (not self._clipped or self._clipped[0] != hwnd) and not self._hide_indicator(hwnd):
            return False
        if changed_at > self._last_shown:
            self._last_shown = changed_at
            self._show(previous, value)
        return True

    def _is_shell_indicator(self, hwnd, *, check_size=True):
        user32 = self._user32
        hwnd = wintypes.HWND(hwnd)
        name = ctypes.create_unicode_buffer(64)
        if (not user32.GetClassNameW(hwnd, name, len(name))
                or name.value != _SHELL_CLASS or user32.GetWindowTextLengthW(hwnd)):
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
        if not check_size:
            return True
        rect = wintypes.RECT()
        dpi = user32.GetDpiForWindow(hwnd) or 96
        return (bool(user32.GetWindowRect(hwnd, ctypes.byref(rect)))
                and 0 < rect.right - rect.left <= 4 * dpi and 0 < rect.bottom - rect.top <= 2 * dpi)

    def _hide_indicator(self, hwnd):
        return (self._is_shell_indicator(hwnd) and self._user32.IsWindowVisible(wintypes.HWND(hwnd))
                and self._user32.ShowWindowAsync(wintypes.HWND(hwnd), 0))  # SW_HIDE
