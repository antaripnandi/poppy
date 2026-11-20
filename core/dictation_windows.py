"""Windows microphone capture, hotkeys and guarded text insertion."""

import ctypes as ct
from collections import deque
from ctypes import wintypes as wt
from functools import lru_cache
import io
import wave


HOTKEY = 0x5041
CANCEL_HOTKEY = 0x5042
_RATE = 16000
_CLIPBOARD_FLAGS = ("ExcludeClipboardContentFromMonitorProcessing", "CanIncludeInClipboardHistory",
                    "CanUploadToCloudClipboard")


class _WaveFormat(ct.Structure):
    _pack_ = 1
    _fields_ = [("tag", wt.WORD), ("channels", wt.WORD), ("rate", wt.DWORD),
                ("bytes_per_second", wt.DWORD), ("align", wt.WORD), ("bits", wt.WORD), ("extra", wt.WORD)]


class _WaveHeader(ct.Structure):
    _fields_ = [("data", ct.c_void_p), ("size", wt.DWORD), ("recorded", wt.DWORD), ("user", ct.c_size_t),
                ("flags", wt.DWORD), ("loops", wt.DWORD), ("next", ct.c_void_p), ("reserved", ct.c_size_t)]


@lru_cache(maxsize=1)
def _winmm():
    api = ct.WinDLL("winmm")
    api.waveInOpen.argtypes = (ct.POINTER(wt.HANDLE), wt.UINT, ct.POINTER(_WaveFormat),
                               ct.c_size_t, ct.c_size_t, wt.DWORD)
    for name in ("waveInPrepareHeader", "waveInUnprepareHeader", "waveInAddBuffer"):
        getattr(api, name).argtypes = (wt.HANDLE, ct.POINTER(_WaveHeader), wt.UINT)
    for name in ("waveInStart", "waveInReset", "waveInClose"):
        getattr(api, name).argtypes = (wt.HANDLE,)
    return api


class Microphone:
    def __init__(self):
        self._api = _winmm()
        self._handle = wt.HANDLE()
        self._prepared = []
        self._queued = deque()
        self._check(self._api.waveInOpen(ct.byref(self._handle), 0xffffffff,
                                        ct.byref(_WaveFormat(1, 1, _RATE, _RATE * 2, 2, 16, 0)), 0, 0, 0))
        try:
            for _ in range(8):
                buffer = ct.create_string_buffer(_RATE * 2 // 20)
                header = _WaveHeader(ct.addressof(buffer), len(buffer))
                self._header_call(self._api.waveInPrepareHeader, header)
                self._prepared.append((header, buffer))
                self._header_call(self._api.waveInAddBuffer, header)
                self._queued.append((header, buffer))
            self._check(self._api.waveInStart(self._handle))
        except OSError:
            self.close()
            raise

    @staticmethod
    def _check(code):
        if code:
            raise OSError(f"Windows microphone error {code}")

    def _header_call(self, function, header):
        self._check(function(self._handle, ct.byref(header), ct.sizeof(header)))

    def read(self):
        return self._drain(requeue=True)

    def _drain(self, *, requeue):
        data = bytearray()
        while self._queued and self._queued[0][0].flags & 1:  # WHDR_DONE
            header, buffer = self._queued.popleft()
            data.extend(buffer.raw[:min(header.recorded, header.size) & ~1])
            if requeue:
                self._header_call(self._api.waveInAddBuffer, header)
                self._queued.append((header, buffer))
        return data

    def close(self, *, keep_audio=False):
        if not self._handle:
            return b""
        self._api.waveInReset(self._handle)
        data = self._drain(requeue=False) if keep_audio else b""
        for header, _ in self._prepared:
            self._api.waveInUnprepareHeader(self._handle, ct.byref(header), ct.sizeof(header))
        self._api.waveInClose(self._handle)
        self._handle = None
        self._queued.clear()
        self._prepared.clear()
        return data


def wav_data(pcm):
    with io.BytesIO() as output:
        with wave.open(output, "wb") as wav:
            wav.setparams((1, 2, _RATE, 0, "NONE", "not compressed"))
            wav.writeframes(pcm)
        return output.getvalue()


class _GuiThreadInfo(ct.Structure):
    _fields_ = [("size", wt.DWORD), ("flags", wt.DWORD), ("active", wt.HWND), ("focus", wt.HWND),
                ("capture", wt.HWND), ("menu", wt.HWND), ("move_size", wt.HWND), ("caret", wt.HWND),
                ("caret_rect", wt.RECT)]


class _KeyInput(ct.Structure):
    _fields_ = [("key", wt.WORD), ("scan", wt.WORD), ("flags", wt.DWORD),
                ("time", wt.DWORD), ("extra", ct.c_size_t)]


class _MouseInput(ct.Structure):
    _fields_ = [("x", wt.LONG), ("y", wt.LONG), ("data", wt.DWORD), ("flags", wt.DWORD),
                ("time", wt.DWORD), ("extra", ct.c_size_t)]


class _InputData(ct.Union):
    _fields_ = [("key", _KeyInput), ("mouse", _MouseInput)]


class _Input(ct.Structure):
    _fields_ = [("type", wt.DWORD), ("data", _InputData)]


@lru_cache(maxsize=1)
def _user32():
    api = ct.WinDLL("user32")
    api.RegisterHotKey.argtypes = (wt.HWND, ct.c_int, wt.UINT, wt.UINT)
    api.UnregisterHotKey.argtypes = (wt.HWND, ct.c_int)
    api.GetGUIThreadInfo.argtypes = (wt.DWORD, ct.POINTER(_GuiThreadInfo))
    api.GetClipboardSequenceNumber.restype = wt.DWORD
    api.SendInput.argtypes = (wt.UINT, ct.POINTER(_Input), ct.c_int)
    api.SendInput.restype = wt.UINT
    api.GetAsyncKeyState.argtypes = (ct.c_int,)
    api.GetAsyncKeyState.restype = ct.c_short
    return api


def register_shortcuts(hwnd):
    api = _user32()
    if not api.RegisterHotKey(hwnd, HOTKEY, 0x4003, ord("D")):  # Ctrl+Alt, no auto-repeat
        return False
    if not api.RegisterHotKey(hwnd, CANCEL_HOTKEY, 0x4007, ord("D")):
        api.UnregisterHotKey(hwnd, HOTKEY)
        return False
    return True


def unregister_shortcuts(hwnd):
    for shortcut in (HOTKEY, CANCEL_HOTKEY):
        _user32().UnregisterHotKey(hwnd, shortcut)


def focused_target():
    info = _GuiThreadInfo()
    info.size = ct.sizeof(info)
    if not _user32().GetGUIThreadInfo(0, ct.byref(info)) or not info.active or not info.focus:
        return None
    import win32gui

    try:
        if win32gui.GetClassName(info.focus).lower().endswith("edit") and win32gui.GetWindowLong(info.focus, -16) & 0x20:
            return None  # Native Windows password edit.
        rect = win32gui.GetWindowRect(info.active)
    except (OSError, win32gui.error):
        return None
    return (info.active, info.focus), (rect[0], rect[1])


def target_style(hwnd):
    import psutil
    import win32process

    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        app = psutil.Process(pid).name().casefold()
    except (OSError, psutil.Error, win32process.error):
        return "natural"
    if app in {"code.exe", "cursor.exe", "windsurf.exe", "devenv.exe", "windowsterminal.exe"}:
        return "technical"
    if app in {"whatsapp.exe", "discord.exe", "telegram.exe", "signal.exe"}:
        return "casual"
    if app in {"outlook.exe", "olk.exe", "winword.exe"}:
        return "professional"
    return "natural"


def modifiers_down():
    return any(_user32().GetAsyncKeyState(key) < 0 for key in (0x10, 0x11, 0x12, 0x5b, 0x5c, ord("D")))


def _clip_formats(clipboard):
    return [clipboard.RegisterClipboardFormat(name) for name in _CLIPBOARD_FLAGS]


def _put_private_text(clipboard, text, formats):
    clipboard.EmptyClipboard()
    for fmt in formats:
        clipboard.SetClipboardData(fmt, b"\0" * 4)
    clipboard.SetClipboardText(text, clipboard.CF_UNICODETEXT)


def copy_text(hwnd, text):
    import win32clipboard as cb

    cb.OpenClipboard(hwnd)
    try:
        _put_private_text(cb, text, _clip_formats(cb))
    finally:
        cb.CloseClipboard()


def paste_text(hwnd, target, text):
    """Paste into the original field; leave complex clipboard content alone."""
    import win32clipboard as cb

    current = focused_target()
    if not current or current[0] != target or modifiers_down():
        return None
    saved = {}
    cb.OpenClipboard(hwnd)
    try:
        privacy = _clip_formats(cb)
        allowed = {cb.CF_TEXT, cb.CF_UNICODETEXT, cb.CF_OEMTEXT, cb.CF_LOCALE, *privacy}
        fmt = cb.EnumClipboardFormats(0)
        while fmt:
            if fmt not in allowed:
                return None
            if fmt in (cb.CF_UNICODETEXT, *privacy):
                saved[fmt] = cb.GetClipboardData(fmt)
            fmt = cb.EnumClipboardFormats(fmt)
        if saved and cb.CF_UNICODETEXT not in saved:
            return None
        _put_private_text(cb, text, privacy)
        sequence = _user32().GetClipboardSequenceNumber()
    finally:
        cb.CloseClipboard()
    keys = (_Input * 4)(*(_Input(1, _InputData(key=_KeyInput(key, 0, flags, 0, 0)))
                          for key, flags in ((0x11, 0), (ord("V"), 0), (ord("V"), 2), (0x11, 2))))
    current = focused_target()
    if current and current[0] == target and not modifiers_down():
        sent = _user32().SendInput(4, keys, ct.sizeof(_Input))
        if sent == 4:
            return sequence, saved
        if sent:
            releases = (_Input * 2)(keys[2], keys[3])
            _user32().SendInput(2, releases, ct.sizeof(_Input))
    restore_clipboard(hwnd, sequence, saved)
    return None


def restore_clipboard(hwnd, sequence, saved):
    import win32clipboard as cb

    cb.OpenClipboard(hwnd)
    try:
        if _user32().GetClipboardSequenceNumber() == sequence:
            cb.EmptyClipboard()
            for fmt, data in saved.items():
                cb.SetClipboardData(fmt, data)
    finally:
        cb.CloseClipboard()
