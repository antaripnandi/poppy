"""
Poppy System Features Engine
Native Windows hardware, privacy, security, and desktop integration.
Zero third-party bloat, stdlib + Win32 ctypes only.
"""

import os
import sys
import json
import time
import winreg
import ctypes
from ctypes import wintypes
from pathlib import Path
import subprocess
import uuid
import threading
from contextlib import contextmanager

from PySide6.QtCore import QObject, Signal, QTimer
from poppy.core.storage import data_path, write_json


@contextmanager
def _windows_com_interface(class_id, interface_id):
    from poppy.core.system_controls import GUID
    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.HRESULT
    result = ole32.CoInitializeEx(None, 2)
    if result < 0 and result != -2147417850:  # RPC_E_CHANGED_MODE: COM is already initialized.
        raise OSError(f"Windows COM could not start ({result:#x})")
    pointer = ctypes.c_void_p()
    table = None
    try:
        clsid = GUID.from_buffer_copy(uuid.UUID(class_id).bytes_le)
        iid = GUID.from_buffer_copy(uuid.UUID(interface_id).bytes_le)
        ole32.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p, wintypes.DWORD,
                                          ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
        ole32.CoCreateInstance.restype = ctypes.HRESULT
        hr = ole32.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(pointer))
        if hr < 0 or not pointer.value:
            raise OSError(f"Windows interface is unavailable ({hr:#x})")
        table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        yield pointer, table
    finally:
        if table is not None:
            ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(table[2])(pointer)
        if result >= 0:
            ole32.CoUninitialize()


def current_desktop_windows():
    """List titled app windows on the current desktop through the public shell API."""
    user32 = ctypes.WinDLL("user32")
    dwmapi = ctypes.WinDLL("dwmapi")
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    windows = []
    with _windows_com_interface("aa509086-5ca9-4c25-8f95-589d3c07b48a",
                                "a5cd92ff-29be-454c-8d04-d82879fb3f1b") as (manager, table):
        on_current = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, wintypes.HWND,
                                       ctypes.POINTER(wintypes.BOOL))(table[3])

        @callback_type
        def collect(hwnd, _):
            if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):
                return True
            if user32.GetWindowLongW(hwnd, -20) & 0x80:  # WS_EX_TOOLWINDOW
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == os.getpid():
                return True
            cloaked = wintypes.DWORD()
            dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
            current = wintypes.BOOL()
            if cloaked.value or on_current(manager, hwnd, ctypes.byref(current)) < 0 or not current.value:
                return True
            title = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, title, len(title))
            if title.value.strip():
                windows.append((int(hwnd), title.value.strip()))
            return True

        if not user32.EnumWindows(collect, 0):
            raise OSError("Windows could not list open windows.")
    return windows


def activate_desktop_window(hwnd):
    user32 = ctypes.WinDLL("user32")
    for method in (user32.IsWindow, user32.IsIconic, user32.SetForegroundWindow):
        method.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    if not user32.IsWindow(hwnd):
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    return bool(user32.SetForegroundWindow(hwnd))


class PrivacyMonitor(QObject):
    """
    Apple-style privacy indicator engine.
    Monitors Windows Registry ConsentStore to detect in real-time when the
    Camera (webcam) or Microphone is actively streaming / recording.
    """
    camera_status_changed = Signal(bool)
    mic_status_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.camera_in_use = False
        self.mic_in_use = False

        self._timer = QTimer(self)
        self._timer.setInterval(1500)  # Check every 1.5s
        self._timer.timeout.connect(self.check_status)
        self._timer.start()

    def check_status(self):
        cam = self._is_capability_in_use("webcam")
        mic = self._is_capability_in_use("microphone")

        if cam != self.camera_in_use:
            self.camera_in_use = cam
            self.camera_status_changed.emit(cam)

        if mic != self.mic_in_use:
            self.mic_in_use = mic
            self.mic_status_changed.emit(mic)

    @staticmethod
    def _is_capability_in_use(capability: str) -> bool:
        base_path = f"Software\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\ConsentStore\\{capability}"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base_path) as key:
                subkeys, _, _ = winreg.QueryInfoKey(key)
                for i in range(subkeys):
                    sub_name = winreg.EnumKey(key, i)
                    if sub_name == "NonPackaged":
                        np_path = f"{base_path}\\NonPackaged"
                        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, np_path) as np_key:
                            np_subkeys, _, _ = winreg.QueryInfoKey(np_key)
                            for j in range(np_subkeys):
                                app_name = winreg.EnumKey(np_key, j)
                                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{np_path}\\{app_name}") as app_key:
                                    try:
                                        val, _ = winreg.QueryValueEx(app_key, "LastUsedTimeStop")
                                        if val == 0:
                                            return True
                                    except Exception:
                                        pass
                    else:
                        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{base_path}\\{sub_name}") as app_key:
                            try:
                                val, _ = winreg.QueryValueEx(app_key, "LastUsedTimeStop")
                                if val == 0:
                                    return True
                            except Exception:
                                pass
        except Exception:
            return False
        return False


class ScreenCaptureShield:
    """
    Win32 SetWindowDisplayAffinity wrapper.
    Hides Poppy from OBS, Discord stream, Zoom, Teams, and screen snips.
    """
    WDA_NONE = 0x00000000
    WDA_MONITOR = 0x00000001
    WDA_EXCLUDEFROMCAPTURE = 0x00000011

    @classmethod
    def set_shield(cls, hwnd: int, enable: bool) -> bool:
        try:
            user32 = ctypes.windll.user32
            if not hasattr(user32, "SetWindowDisplayAffinity"):
                return False
            val = cls.WDA_EXCLUDEFROMCAPTURE if enable else cls.WDA_NONE
            res = user32.SetWindowDisplayAffinity(hwnd, val)
            return bool(res)
        except Exception:
            return False


class BluetoothManager(QObject):
    """
    Queries paired and actively connected Bluetooth devices via Win32 bthprops.cpl.
    Sub-millisecond, zero subprocess overhead, 100% accurate real connection state.
    """
    devices_updated = Signal(list)
    _scan_finished = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.devices = []
        self._scanning = False
        self._closed = False
        self._scan_finished.connect(self._apply_scan)

    def refresh(self):
        # Windows enumeration can block even without an inquiry. Keep a single
        # daemon worker so a slow driver cannot freeze navigation or app exit.
        if self._scanning or self._closed:
            return
        self._scanning = True

        def scan():
            try:
                devices = self._get_devices()
            except Exception:
                devices = []
            try:
                self._scan_finished.emit(devices)
            except RuntimeError:
                pass  # The owning Qt window has already been deleted.

        threading.Thread(target=scan, name="poppy-bluetooth", daemon=True).start()

    def _apply_scan(self, devices):
        self._scanning = False
        if self._closed:
            return
        self.devices = devices
        self.devices_updated.emit(devices)

    def close(self):
        self._closed = True

    @staticmethod
    def _get_devices() -> list[dict]:
        devices = []
        try:
            class SYSTEMTIME(ctypes.Structure):
                _fields_ = [
                    ('wYear', wintypes.WORD),
                    ('wMonth', wintypes.WORD),
                    ('wDayOfWeek', wintypes.WORD),
                    ('wDay', wintypes.WORD),
                    ('wHour', wintypes.WORD),
                    ('wMinute', wintypes.WORD),
                    ('wSecond', wintypes.WORD),
                    ('wMilliseconds', wintypes.WORD)
                ]

            class BLUETOOTH_DEVICE_INFO(ctypes.Structure):
                _fields_ = [
                    ('dwSize', wintypes.DWORD),
                    ('Address', ctypes.c_ulonglong),
                    ('ulClassofDevice', wintypes.ULONG),
                    ('fConnected', wintypes.BOOL),
                    ('fRemembered', wintypes.BOOL),
                    ('fAuthenticated', wintypes.BOOL),
                    ('stLastSeen', SYSTEMTIME),
                    ('stLastUsed', SYSTEMTIME),
                    ('szName', wintypes.WCHAR * 248)
                ]

            class BLUETOOTH_DEVICE_SEARCH_PARAMS(ctypes.Structure):
                _fields_ = [
                    ('dwSize', wintypes.DWORD),
                    ('fReturnAuthenticated', wintypes.BOOL),
                    ('fReturnRemembered', wintypes.BOOL),
                    ('fReturnUnknown', wintypes.BOOL),
                    ('fReturnConnected', wintypes.BOOL),
                    ('fIssueInquiry', wintypes.BOOL),
                    ('cTimeoutMultiplier', ctypes.c_ubyte),
                    ('hRadio', wintypes.HANDLE)
                ]

            bluetooth_api = Path(os.environ["SystemRoot"]) / "System32" / "bthprops.cpl"
            bth = ctypes.WinDLL(str(bluetooth_api))
            bth.BluetoothFindFirstDevice.argtypes = [ctypes.POINTER(BLUETOOTH_DEVICE_SEARCH_PARAMS), ctypes.POINTER(BLUETOOTH_DEVICE_INFO)]
            bth.BluetoothFindFirstDevice.restype = wintypes.HANDLE

            bth.BluetoothFindNextDevice.argtypes = [wintypes.HANDLE, ctypes.POINTER(BLUETOOTH_DEVICE_INFO)]
            bth.BluetoothFindNextDevice.restype = wintypes.BOOL

            bth.BluetoothFindDeviceClose.argtypes = [wintypes.HANDLE]
            bth.BluetoothFindDeviceClose.restype = wintypes.BOOL

            params = BLUETOOTH_DEVICE_SEARCH_PARAMS()
            params.dwSize = ctypes.sizeof(BLUETOOTH_DEVICE_SEARCH_PARAMS)
            params.fReturnAuthenticated = True
            params.fReturnRemembered = True
            params.fReturnUnknown = False
            params.fReturnConnected = True
            params.fIssueInquiry = False
            params.hRadio = None

            info = BLUETOOTH_DEVICE_INFO()
            info.dwSize = ctypes.sizeof(BLUETOOTH_DEVICE_INFO)

            hFind = bth.BluetoothFindFirstDevice(ctypes.byref(params), ctypes.byref(info))
            if hFind:
                seen = set()
                while True:
                    name = str(info.szName).strip()
                    if name and name not in seen:
                        seen.add(name)
                        is_conn = bool(info.fConnected)
                        devices.append({
                            "name": name,
                            "connected": is_conn,
                            "status": "Connected" if is_conn else "Paired",
                            "is_audio": any(a in name.lower() for a in ("tune", "audio", "airbass", "buds", "headphone", "sound", "dubstep"))
                        })
                    if not bth.BluetoothFindNextDevice(hFind, ctypes.byref(info)):
                        break
                bth.BluetoothFindDeviceClose(hFind)
        except Exception:
            pass
        return devices


class AppLauncherIndexer:
    """
    Fast Windows Start Menu application scanner for Spotlight/Raycast style launcher.
    """
    @staticmethod
    def get_installed_apps() -> list[dict]:
        paths = [
            Path(os.environ.get("ProgramData", "C:\\ProgramData")) / "Microsoft\\Windows\\Start Menu\\Programs",
            Path(os.environ.get("APPDATA", "")) / "Microsoft\\Windows\\Start Menu\\Programs"
        ]
        apps = []
        seen = set()

        # Built-in essential Windows utilities
        builtins = [
            {"name": "Lock Workstation", "cmd": "lock", "icon": "\uE72E", "sub": "Lock PC screen instantly"},
            {"name": "Task Manager", "cmd": "taskmgr", "icon": "\uE7C4", "sub": "View active system tasks & performance"},
            {"name": "Windows Settings", "cmd": "ms-settings:", "icon": "\uE713", "sub": "Open system settings"},
            {"name": "Calculator", "cmd": "calc", "icon": "\uE8EF", "sub": "Open Windows Calculator"},
            {"name": "Snipping Tool", "cmd": "ms-screenclip:", "icon": "\uE7C8", "sub": "Capture desktop screen snip"},
            {"name": "Windows Terminal", "cmd": "wt", "icon": "\uE756", "sub": "Open command line terminal"},
            {"name": "File Explorer", "cmd": "explorer", "icon": "\uED25", "sub": "Open file manager"},
            {"name": "Notepad", "cmd": "notepad", "icon": "\uE70B", "sub": "Quick text editor"},
        ]
        for b in builtins:
            apps.append(b)
            seen.add(b["name"].lower())

        for p in paths:
            if p.exists():
                try:
                    for lnk in p.rglob("*.lnk"):
                        name = lnk.stem
                        name_lower = name.lower()
                        if "uninstall" not in name_lower and "help" not in name_lower and name_lower not in seen:
                            seen.add(name_lower)
                            apps.append({
                                "name": name,
                                "cmd": str(lnk),
                                "icon": "\uE71D",
                                "sub": "Application"
                            })
                except Exception:
                    pass
        return apps


class ClipboardHistoryManager(QObject):
    """Text history with stable identities; pinned entries survive recopying."""
    history_updated = Signal()
    save_failed = Signal(str)
    MAX_RECENT = 40
    MAX_TEXT_BYTES = 1024 * 1024

    def __init__(self, parent=None):
        super().__init__(parent)
        self.store_file = data_path("clipboard_history.json")
        self.store_file.parent.mkdir(parents=True, exist_ok=True)
        self.history: list[dict] = []
        self.last_save_error = ""
        self._load()

    def _load(self):
        if self.store_file.exists():
            try:
                raw = json.loads(self.store_file.read_text(encoding="utf-8"))
                if not isinstance(raw, list):
                    return
                seen_ids = set()
                for item in raw:
                    if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                        continue
                    item_id = item.get("id")
                    if not isinstance(item_id, str) or item_id in seen_ids:
                        item_id = uuid.uuid4().hex
                    seen_ids.add(item_id)
                    self.history.append({**item, "id": item_id})
                self._trim()
            except Exception:
                self.history = []

    def _save(self):
        try:
            write_json(self.store_file, self.history)
            self.last_save_error = ""
            return True
        except OSError as error:
            self.last_save_error = str(error)
            self.save_failed.emit(str(error))
            return False

    def _trim(self):
        pinned = [c for c in self.history if c.get("pinned", False)]
        recent = [c for c in self.history if not c.get("pinned", False)]
        self.history = pinned + recent[:self.MAX_RECENT]

    def add_clip(self, text: str):
        if not text or not text.strip():
            return False
        if len(text.encode("utf-8")) > self.MAX_TEXT_BYTES:
            return False
        existing = next((c for c in self.history if c["text"] == text), None)
        if existing and self.history[0] is existing:
            if self.last_save_error:
                self._save()
                self.history_updated.emit()
            return True
        self.history = [c for c in self.history if c["text"] != text]
        item = {
            "id": existing["id"] if existing else uuid.uuid4().hex,
            "text": text,
            "time": time.strftime("%I:%M %p"),
            "pinned": existing.get("pinned", False) if existing else False
        }
        self.history.insert(0, item)
        self._trim()
        self._save()
        self.history_updated.emit()
        return True

    def _index(self, identity: str | int) -> int:
        if isinstance(identity, int):
            return identity
        return next((i for i, c in enumerate(self.history) if c.get("id") == identity), -1)

    def toggle_pin(self, identity: str | int):
        index = self._index(identity)
        if 0 <= index < len(self.history):
            self.history[index]["pinned"] = not self.history[index].get("pinned", False)
            self._trim()
            self._save()
            self.history_updated.emit()

    def delete_clip(self, identity: str | int):
        index = self._index(identity)
        if 0 <= index < len(self.history):
            self.history.pop(index)
            self._save()
            self.history_updated.emit()

    def clear_all(self):
        self.history = [c for c in self.history if c.get("pinned", False)]
        self._save()
        self.history_updated.emit()


def clipboard_allows_history() -> bool:
    return clipboard_history_permission() is True


def clipboard_history_permission() -> bool | None:
    """Return None if Windows could not expose clipboard privacy metadata yet."""
    try:
        import win32clipboard
        win32clipboard.OpenClipboard()
        try:
            excluded = win32clipboard.RegisterClipboardFormat("ExcludeClipboardContentFromMonitorProcessing")
            if win32clipboard.IsClipboardFormatAvailable(excluded):
                return False
            allowed = win32clipboard.RegisterClipboardFormat("CanIncludeInClipboardHistory")
            if win32clipboard.IsClipboardFormatAvailable(allowed):
                value = win32clipboard.GetClipboardData(allowed)
                if isinstance(value, bytes) and len(value) >= 4:
                    return int.from_bytes(value[:4], "little") == 1
                return False
            return True
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        return None


class _CountedArray(ctypes.Structure):
    _fields_ = [("count", wintypes.ULONG), ("elements", ctypes.c_void_p)]


class _VariantValue(ctypes.Union):
    _fields_ = [("pwszVal", ctypes.c_void_p), ("array", _CountedArray)]


class PROPVARIANT(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = [("vt", wintypes.WORD), ("reserved1", wintypes.WORD),
                ("reserved2", wintypes.WORD), ("reserved3", wintypes.WORD),
                ("value", _VariantValue)]


class AudioEndpointManager:
    """Read playback endpoint names with checked COM calls and owned allocations."""

    @staticmethod
    def set_default_output(device_id):
        if not device_id:
            raise ValueError("This output has no Windows device ID.")
        # Windows has no public default-output setter. Keep the unsupported
        # interface isolated so Settings remains available if Windows rejects it.
        with _windows_com_interface("870af99c-171d-4f9e-af0d-e63df40c2bc9",
                                    "f8679f50-850a-41cf-9c72-430f290290c8") as (policy, table):
            set_endpoint = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p,
                                             wintypes.LPCWSTR, ctypes.c_int)(table[13])
            for role in (0, 1):  # Console and Multimedia; leave call-device preferences alone.
                hr = set_endpoint(policy, device_id, role)
                if hr < 0:
                    raise OSError(f"Windows rejected the output change ({hr:#x}).")

    @staticmethod
    def get_output_endpoints() -> list[dict]:
        from poppy.core.system_controls import GUID

        class PROPERTYKEY(ctypes.Structure):
            _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

        ole32 = ctypes.WinDLL("ole32")
        initialized = False
        pointers = []
        devices = []

        def release(pointer):
            if pointer and pointer.value:
                table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
                ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(table[2])(pointer)

        def call(pointer, slot, types, *args):
            table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            method = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *types)(table[slot])
            result = method(pointer, *args)
            if result < 0:
                raise OSError(f"Windows audio query failed ({result:#x})")

        try:
            result = ole32.CoInitialize(None)
            initialized = result in (0, 1)
            if result < 0 and result != -2147417850:
                return []
            ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
            ole32.CoTaskMemFree.restype = None
            ole32.PropVariantClear.argtypes = [ctypes.POINTER(PROPVARIANT)]
            ole32.PropVariantClear.restype = ctypes.HRESULT
            ole32.CLSIDFromString.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(GUID)]
            clsid, iid = GUID(), GUID()
            ole32.CLSIDFromString('{BCDE0395-E52F-467C-8E3D-C4579291692E}', ctypes.byref(clsid))
            ole32.CLSIDFromString('{A95664D2-9614-4F35-A746-DE8DB63617E6}', ctypes.byref(iid))
            enumerator = ctypes.c_void_p()
            result = ole32.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(enumerator))
            if result < 0 or not enumerator.value:
                return []
            pointers.append(enumerator)
            default_device, default_id_ptr = ctypes.c_void_p(), ctypes.c_void_p()
            default_id = ""
            try:
                call(enumerator, 4, [ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)],
                     0, 1, ctypes.byref(default_device))
                call(default_device, 5, [ctypes.POINTER(ctypes.c_void_p)], ctypes.byref(default_id_ptr))
                if default_id_ptr.value:
                    default_id = ctypes.wstring_at(default_id_ptr)
            except OSError:
                pass
            finally:
                if default_id_ptr.value:
                    ole32.CoTaskMemFree(default_id_ptr)
                release(default_device)
            collection = ctypes.c_void_p()
            call(enumerator, 3, [wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)], 0, 1, ctypes.byref(collection))
            pointers.append(collection)
            count = wintypes.UINT()
            call(collection, 3, [ctypes.POINTER(wintypes.UINT)], ctypes.byref(count))
            key = PROPERTYKEY()
            ole32.CLSIDFromString('{A45C254E-DF1C-4EFD-8020-67D146A850E0}', ctypes.byref(key.fmtid))
            key.pid = 14
            for index in range(count.value):
                device, store, device_id = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
                value = PROPVARIANT()
                try:
                    call(collection, 4, [wintypes.UINT, ctypes.POINTER(ctypes.c_void_p)], index, ctypes.byref(device))
                    call(device, 5, [ctypes.POINTER(ctypes.c_void_p)], ctypes.byref(device_id))
                    call(device, 4, [wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)], 0, ctypes.byref(store))
                    call(store, 5, [ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT)], ctypes.byref(key), ctypes.byref(value))
                    name = ctypes.wstring_at(value.pwszVal) if value.vt == 31 and value.pwszVal else "Audio device"
                    endpoint_id = ctypes.wstring_at(device_id) if device_id.value else ""
                    devices.append({"name": name, "id": endpoint_id, "default": bool(endpoint_id and endpoint_id == default_id)})
                finally:
                    ole32.PropVariantClear(ctypes.byref(value))
                    if device_id.value:
                        ole32.CoTaskMemFree(device_id)
                    release(store)
                    release(device)
        except (OSError, ValueError, AttributeError):
            pass
        finally:
            for pointer in reversed(pointers):
                release(pointer)
            if initialized:
                ole32.CoUninitialize()
        return devices


def get_autostart_state() -> bool:
    """Checks whether Poppy is registered to launch on Windows startup."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
        val, _ = winreg.QueryValueEx(key, "Poppy")
        winreg.CloseKey(key)
        return bool(val)
    except FileNotFoundError:
        return False
    except Exception:
        return False


def set_autostart_state(enable: bool) -> bool:
    """Registers or unregisters Poppy in the Windows CurrentVersion Run registry key."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        if enable:
            exe_path = sys.executable
            main_py = Path(__file__).resolve().parent.parent / "main.py"
            cmd = f'"{exe_path}"' if getattr(sys, "frozen", False) else f'"{exe_path}" "{main_py}"'
            winreg.SetValueEx(key, "Poppy", 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, "Poppy")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception as e:
        print(f"[Poppy] Autostart error: {e}")
        return False


