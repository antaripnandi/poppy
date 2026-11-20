"""Windows microphone capture, hotkeys and guarded text insertion."""

import ctypes as ct
from collections import deque
from contextlib import contextmanager
from ctypes import wintypes as wt
from functools import lru_cache
import io
import os
from typing import NamedTuple
from uuid import UUID
import wave


HOTKEY = 0x5041
CANCEL_HOTKEY = 0x5042
HOLD_HOTKEY = 0x5043
EDIT_HOTKEY = 0x5044
CONTEXT_LIMIT = 200
SELECTION_LIMIT = 4000
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


@lru_cache(maxsize=1)
def _transliteration_api():
    for name in ("icu.dll", "icuin.dll"):
        try:
            api = ct.CDLL(name, winmode=0x00000800)  # LOAD_LIBRARY_SEARCH_SYSTEM32
            status_ptr = ct.POINTER(ct.c_int32)
            api.utrans_openU.argtypes = (ct.c_wchar_p, ct.c_int32, ct.c_int32, ct.c_wchar_p,
                                         ct.c_int32, ct.c_void_p, status_ptr)
            api.utrans_openU.restype = ct.c_void_p
            api.utrans_transUChars.argtypes = (ct.c_void_p, ct.c_wchar_p, status_ptr, ct.c_int32,
                                              ct.c_int32, status_ptr, status_ptr)
            api.utrans_transUChars.restype = None
            api.utrans_close.argtypes = (ct.c_void_p,)
            api.utrans_close.restype = None
            return api
        except (AttributeError, OSError):
            continue
    return None


def romanize_text(text):
    """Use Windows' transliterator when the provider returns native script."""
    api = _transliteration_api()
    if api is None:
        return text
    status = ct.c_int32()
    rules = "[:^Latin:]; Any-Latin; Latin-ASCII"
    handle = api.utrans_openU(rules, -1, 0, None, 0, None, ct.byref(status))
    if not handle:
        return text
    try:
        code_units = len(text.encode("utf-16-le", errors="surrogatepass")) // 2
        length = ct.c_int32(code_units)
        limit = ct.c_int32(code_units)
        buffer = ct.create_unicode_buffer(text, code_units * 8 + 1)
        api.utrans_transUChars(handle, buffer, ct.byref(length), len(buffer), 0, ct.byref(limit), ct.byref(status))
        return buffer.value if status.value <= 0 else text
    finally:
        api.utrans_close(handle)


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
    api.SendMessageTimeoutW.argtypes = (wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, wt.UINT, wt.UINT,
                                       ct.POINTER(ct.c_size_t))
    api.SendMessageTimeoutW.restype = wt.LPARAM
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


def register_extra_shortcut(hwnd, shortcut):
    modifiers, key = {HOLD_HOTKEY: (0x4003, 0x20), EDIT_HOTKEY: (0x4007, ord("E"))}[shortcut]
    return bool(_user32().RegisterHotKey(hwnd, shortcut, modifiers, key))


def unregister_extra_shortcut(hwnd, shortcut):
    _user32().UnregisterHotKey(hwnd, shortcut)


def hold_shortcut_down():
    return all(_user32().GetAsyncKeyState(key) < 0 for key in (0x11, 0x12, 0x20))


def _focused_window():
    info = _GuiThreadInfo()
    info.size = ct.sizeof(info)
    if not _user32().GetGUIThreadInfo(0, ct.byref(info)) or not info.active or not info.focus:
        return None
    return info.active, info.focus


class _Variant(ct.Structure):
    _fields_ = [("type", wt.WORD), ("reserved", wt.WORD * 3), ("data", ct.c_void_p * 2)]


@lru_cache(maxsize=1)
def _oleaut():
    api = ct.WinDLL("oleaut32")
    api.VariantClear.argtypes = (ct.POINTER(_Variant),)
    api.SafeArrayDestroy.argtypes = (ct.c_void_p,)
    api.SafeArrayGetDim.argtypes = (ct.c_void_p,)
    for name in ("SafeArrayGetLBound", "SafeArrayGetUBound"):
        getattr(api, name).argtypes = (ct.c_void_p, wt.UINT, ct.POINTER(wt.LONG))
    api.SafeArrayGetElement.argtypes = (ct.c_void_p, ct.POINTER(wt.LONG), ct.c_void_p)
    api.SysStringLen.argtypes = (ct.c_void_p,)
    api.SysStringLen.restype = wt.UINT
    api.SysFreeString.argtypes = (ct.c_void_p,)
    api.SysFreeString.restype = None
    return api


def _automation_edit_id(inspect=None):
    from poppy.core.system_features import _windows_com_interface

    # IUIAutomation2 and IUIAutomationElement vtables follow the Windows SDK.
    def method(table, slot, *args):
        return ct.WINFUNCTYPE(ct.HRESULT, ct.c_void_p, *args)(table[slot])

    element = ct.c_void_p()
    with _windows_com_interface("e22ad333-b25f-460c-83d0-0581107395c9",
                                "34723aff-0c9d-49d0-9896-7ab52df8cd8a") as (client, table):
        method(table, 61, wt.DWORD)(client, 300)  # ConnectionTimeout
        method(table, 63, wt.DWORD)(client, 300)  # TransactionTimeout
        if method(table, 8, ct.POINTER(ct.c_void_p))(client, ct.byref(element)) < 0 or not element:
            return None
        vtable = ct.cast(element, ct.POINTER(ct.POINTER(ct.c_void_p))).contents
        try:
            control = ct.c_int()
            password = wt.BOOL()
            if (method(vtable, 21, ct.POINTER(ct.c_int))(element, ct.byref(control)) < 0
                    or control.value not in (50004, 50030)  # Edit, Document
                    or method(vtable, 35, ct.POINTER(wt.BOOL))(element, ct.byref(password)) < 0 or password.value):
                return None

            def bool_property(identifier):
                value = _Variant()
                try:
                    get = method(vtable, 11, ct.c_int, wt.BOOL, ct.POINTER(_Variant))
                    if get(element, identifier, True, ct.byref(value)) >= 0 and value.type == 11:  # VT_BOOL
                        return bool(ct.c_short.from_address(ct.addressof(value) + _Variant.data.offset).value)
                    return None
                finally:
                    _oleaut().VariantClear(ct.byref(value))

            read_only = bool_property(30046)  # Value.IsReadOnly
            if read_only is True or (control.value == 50030 and read_only is None and not bool_property(30149)):
                return None
            array = ct.c_void_p()
            if method(vtable, 4, ct.POINTER(ct.c_void_p))(element, ct.byref(array)) < 0 or not array:
                return None
            api = _oleaut()
            try:
                lower, upper = wt.LONG(), wt.LONG()
                if (api.SafeArrayGetDim(array) != 1 or api.SafeArrayGetLBound(array, 1, ct.byref(lower)) < 0
                        or api.SafeArrayGetUBound(array, 1, ct.byref(upper)) < 0
                        or not 0 <= upper.value - lower.value < 64):
                    return None
                identity = []
                for index in range(lower.value, upper.value + 1):
                    item = wt.LONG()
                    if api.SafeArrayGetElement(array, ct.byref(wt.LONG(index)), ct.byref(item)) < 0:
                        return None
                    identity.append(item.value)
                identity = tuple(identity)
                return (identity, inspect(element)) if inspect else identity
            finally:
                api.SafeArrayDestroy(array)
        finally:
            ct.WINFUNCTYPE(wt.ULONG, ct.c_void_p)(vtable[2])(element)


class TextScope(NamedTuple):
    text: str
    location: tuple = ()


def _uia_method(obj, slot, *args):
    table = ct.cast(obj, ct.POINTER(ct.POINTER(ct.c_void_p))).contents
    return ct.WINFUNCTYPE(ct.HRESULT, ct.c_void_p, *args)(table[slot])


@contextmanager
def _uia_object(obj, slot, *parameters):
    result = ct.c_void_p()
    method = _uia_method(obj, slot, *(kind for kind, _ in parameters), ct.POINTER(ct.c_void_p))
    success = method(obj, *(value for _, value in parameters), ct.byref(result)) >= 0 and result.value
    try:
        yield result if success else None
    finally:
        if result:
            _uia_method(result, 2)(result)


def _range_text(text_range, limit):
    text = ct.c_void_p()
    api = _oleaut()
    try:
        if _uia_method(text_range, 12, ct.c_int, ct.POINTER(ct.c_void_p))(text_range, limit, ct.byref(text)) < 0:
            return None
        if not text:
            return ""
        size = min(limit, api.SysStringLen(text)) * 2
        return ct.string_at(text, size).decode("utf-16-le", errors="ignore")
    finally:
        if text:
            api.SysFreeString(text)


def _range_location(text_range):
    rectangles = ct.c_void_p()
    api = _oleaut()
    try:
        if _uia_method(text_range, 10, ct.POINTER(ct.c_void_p))(text_range, ct.byref(rectangles)) < 0 or not rectangles:
            return ()
        lower, upper = wt.LONG(), wt.LONG()
        if (api.SafeArrayGetDim(rectangles) != 1 or api.SafeArrayGetLBound(rectangles, 1, ct.byref(lower)) < 0
                or api.SafeArrayGetUBound(rectangles, 1, ct.byref(upper)) < 0):
            return ()
        count = upper.value - lower.value + 1
        if not 4 <= count <= 1024 or count % 4:
            return ()
        values = []
        for index in range(lower.value, upper.value + 1):
            value = ct.c_double()
            if api.SafeArrayGetElement(rectangles, ct.byref(wt.LONG(index)), ct.byref(value)) < 0:
                return ()
            values.append(round(value.value, 2))
        return tuple(values)
    finally:
        if rectangles:
            api.SafeArrayDestroy(rectangles)


def _read_text_range(element, selection):
    from poppy.core.system_controls import GUID

    # IUIAutomationTextPattern, TextRangeArray, and TextRange slots from UIAutomationClient.h.
    iid = GUID.from_buffer_copy(UUID("32eba289-3583-42c9-9c59-3b6d9a1e9b6a").bytes_le)
    with _uia_object(element, 14, (ct.c_int, 10014), (ct.POINTER(GUID), ct.byref(iid))) as pattern:
        if not pattern:
            return None
        with _uia_object(pattern, 5) as ranges:
            length = ct.c_int()
            if not ranges or _uia_method(ranges, 3, ct.POINTER(ct.c_int))(ranges, ct.byref(length)) < 0 or length.value != 1:
                return None
            with _uia_object(ranges, 4, (ct.c_int, 0)) as text_range:
                if not text_range:
                    return None
                if selection:
                    text = _range_text(text_range, SELECTION_LIMIT + 1)
                    location = _range_location(text_range) if text and len(text) <= SELECTION_LIMIT else ()
                    return TextScope(text, location) if location else None
                if _range_text(text_range, 1) != "":
                    return None
                moved = ct.c_int()
                move = _uia_method(text_range, 14, ct.c_int, ct.c_int, ct.c_int, ct.POINTER(ct.c_int))
                if move(text_range, 0, 0, -CONTEXT_LIMIT, ct.byref(moved)) < 0:
                    return None
                text = _range_text(text_range, CONTEXT_LIMIT)
                return TextScope(text) if text else None


def _read_win32_edit(hwnd, selection):
    import win32gui

    if not _is_win32_edit(win32gui.GetClassName(hwnd)):
        return None
    if win32gui.GetWindowLong(hwnd, -16) & 0x820:  # ES_PASSWORD or ES_READONLY.
        return None
    send = _user32().SendMessageTimeoutW

    def read(message, wparam=0, lparam=0):
        result = ct.c_size_t()
        return result.value if send(hwnd, message, wparam, lparam, 3, 150, ct.byref(result)) else None

    start, end = wt.DWORD(), wt.DWORD()
    if read(0x00B0, ct.addressof(start), ct.addressof(end)) is None:  # EM_GETSEL.
        return None
    left, right = start.value, end.value
    if (selection and not 0 < right - left <= SELECTION_LIMIT) or (not selection and left != right):
        return None
    length = read(0x000E)  # WM_GETTEXTLENGTH.
    if length is None or not right <= length <= 32768:
        return None
    buffer = ct.create_unicode_buffer(length + 1)
    received = read(0x000D, len(buffer), ct.addressof(buffer))  # WM_GETTEXT.
    if received is None or received < right:
        return None
    # Windows offsets count UTF-16 code units, including supplementary characters.
    begin, finish = (left, right) if selection else (max(0, left - CONTEXT_LIMIT), left)
    data = ct.string_at(ct.addressof(buffer) + begin * 2, (finish - begin) * 2)
    text = data.decode("utf-16-le", errors="ignore")
    if read(0x00B0, ct.addressof(start), ct.addressof(end)) is None or (start.value, end.value) != (left, right):
        return None
    return TextScope(text, (left, right) if selection else ()) if text.strip() else None


def read_text_scope(target, *, selection):
    """Read a bounded selection or the text leading up to a collapsed caret."""
    if _focused_window() != target[:2]:
        return None
    try:
        if not target[2]:
            from pywintypes import error as WindowsError

            try:
                scope = _read_win32_edit(target[1], selection)
            except WindowsError:
                return None
            return scope if _focused_window() == target[:2] else None
        inspected = _automation_edit_id(lambda element: _read_text_range(element, selection))
    except OSError:
        return None
    if not inspected or (target[2] and inspected[0] != target[2]) or _focused_window() != target[:2]:
        return None
    return inspected[1]


def _is_win32_edit(class_name):
    name = class_name.casefold()
    return name == "edit" or name.startswith(("richedit", "windowsforms10.edit."))


def focused_target():
    """Identify an editable control without reading the field's contents."""
    window = _focused_window()
    if window is None:
        return None
    import win32gui
    import win32process

    active, focus = window
    try:
        if _is_win32_edit(win32gui.GetClassName(focus)):
            if win32gui.GetWindowLong(focus, -16) & 0x820:  # ES_PASSWORD or ES_READONLY
                return None
            identity = ()
        else:
            _, pid = win32process.GetWindowThreadProcessId(active)
            if pid == os.getpid():  # Avoid synchronous UIA calls into Poppy's own GUI thread.
                return None
            identity = _automation_edit_id()
            if not identity:
                return None
        rect = win32gui.GetWindowRect(active)
    except (OSError, win32gui.error):
        return None
    if _focused_window() != window:
        return None
    return (active, focus, identity), (rect[0], rect[1])


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
    return any(_user32().GetAsyncKeyState(key) < 0 for key in (0x10, 0x11, 0x12, 0x5b, 0x5c, ord("D"), ord("E")))


def _clip_formats(clipboard):
    return [clipboard.RegisterClipboardFormat(name) for name in _CLIPBOARD_FLAGS]


def _text_clipboard_formats(clipboard, privacy):
    allowed = {clipboard.CF_TEXT, clipboard.CF_UNICODETEXT, clipboard.CF_OEMTEXT, clipboard.CF_LOCALE, *privacy}
    found = set()
    fmt = clipboard.EnumClipboardFormats(0)
    while fmt:
        if fmt not in allowed:
            return None
        found.add(fmt)
        fmt = clipboard.EnumClipboardFormats(fmt)
    return found


def _put_private_text(clipboard, text, formats, *, history=False):
    clipboard.EmptyClipboard()
    excluded, allow_history, allow_cloud = formats
    if not history:
        clipboard.SetClipboardData(excluded, b"\0" * 4)
    clipboard.SetClipboardData(allow_history, int(history).to_bytes(4, "little"))
    clipboard.SetClipboardData(allow_cloud, b"\0" * 4)
    clipboard.SetClipboardText(text, clipboard.CF_UNICODETEXT)


def copy_text(hwnd, text, *, history=False, preserve_complex=False):
    import win32clipboard as cb

    cb.OpenClipboard(hwnd)
    try:
        privacy = _clip_formats(cb)
        if preserve_complex and _text_clipboard_formats(cb, privacy) is None:
            return False
        _put_private_text(cb, text, privacy, history=history)
        return True
    finally:
        cb.CloseClipboard()


def paste_text(hwnd, target, text, *, validate=None):
    """Paste into the original field; leave complex clipboard content alone."""
    import win32clipboard as cb

    current = focused_target()
    if not current or current[0] != target or modifiers_down() or (validate and not validate()):
        return None
    cb.OpenClipboard(hwnd)
    try:
        privacy = _clip_formats(cb)
        formats = _text_clipboard_formats(cb, privacy)
        if formats is None or (formats and cb.CF_UNICODETEXT not in formats):
            return None
        saved = {fmt: cb.GetClipboardData(fmt) for fmt in (cb.CF_UNICODETEXT, *privacy) if fmt in formats}
        try:
            _put_private_text(cb, text, privacy)
        except (OSError, cb.error):
            _restore_formats(cb, saved)
            raise
        sequence = _user32().GetClipboardSequenceNumber()
    finally:
        cb.CloseClipboard()
    keys = (_Input * 4)(*(_Input(1, _InputData(key=_KeyInput(key, 0, flags, 0, 0)))
                          for key, flags in ((0x11, 0), (ord("V"), 0), (ord("V"), 2), (0x11, 2))))
    sent = 0
    try:
        current = focused_target()
        if (current and current[0] == target and (not validate or validate())
                and _focused_window() == target[:2] and not modifiers_down()
                and _user32().GetClipboardSequenceNumber() == sequence):
            sent = _user32().SendInput(4, keys, ct.sizeof(_Input))
            if sent == 4:
                return sequence, saved
            if sent:
                releases = (_Input * 2)(keys[2], keys[3])
                _user32().SendInput(2, releases, ct.sizeof(_Input))
    finally:
        if sent != 4:
            restore_clipboard(hwnd, sequence, saved)
    return None


def _restore_formats(clipboard, saved):
    clipboard.EmptyClipboard()
    for fmt, data in saved.items():
        clipboard.SetClipboardData(fmt, data)


def restore_clipboard(hwnd, sequence, saved):
    import win32clipboard as cb

    cb.OpenClipboard(hwnd)
    try:
        if _user32().GetClipboardSequenceNumber() == sequence:
            _restore_formats(cb, saved)
    finally:
        cb.CloseClipboard()
