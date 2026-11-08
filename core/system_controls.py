"""
Poppy System Hardware Controls
Zero-bloat native Windows hardware integration for Master Volume and Screen Brightness.
Uses Windows Core Audio COM API (IAudioEndpointVolume) via ctypes and WMI for brightness.
"""

import ctypes
from ctypes import wintypes, HRESULT, POINTER, c_void_p, c_float, byref
import threading
import time


from PySide6.QtCore import QObject, Signal


def system_animations_enabled() -> bool:
    """Read the Windows accessibility preference for app animations."""
    user32 = getattr(getattr(ctypes, "windll", None), "user32", None)
    enabled = wintypes.BOOL(True)
    if user32 and user32.SystemParametersInfoW(0x1042, 0, byref(enabled), 0):
        return bool(enabled.value)
    return True


class GUID(ctypes.Structure):
    _fields_ = [
        ('Data1', wintypes.DWORD),
        ('Data2', wintypes.WORD),
        ('Data3', wintypes.WORD),
        ('Data4', wintypes.BYTE * 8)
    ]


class SystemAudioController:
    """
    Direct Windows Core Audio master volume and mute controller.
    Uses pure ctypes and COM to interact with IAudioEndpointVolume at sub-millisecond latency.
    Strictly releases all COM interface pointers (IUnknown::Release) to eliminate handle leaks.
    """
    def __init__(self):
        self._ole32 = ctypes.oledll.ole32
        self._ole32.CoInitialize(None)
        self._GUID = GUID
        self._ole32.CLSIDFromString.argtypes = [wintypes.LPCWSTR, POINTER(GUID)]

        self._clsid_enum = GUID()
        self._iid_enum = GUID()
        self._iid_vol = GUID()
        self._ole32.CLSIDFromString('{BCDE0395-E52F-467C-8E3D-C4579291692E}', byref(self._clsid_enum))
        self._ole32.CLSIDFromString('{A95664D2-9614-4F35-A746-DE8DB63617E6}', byref(self._iid_enum))
        self._ole32.CLSIDFromString('{5CDF2C82-841E-4546-9722-0CF74078229A}', byref(self._iid_vol))

    def _release(self, ptr):
        """Release COM interface pointer to prevent handle leakage."""
        if ptr and ptr.value:
            try:
                vtable = ctypes.cast(ptr, POINTER(POINTER(c_void_p))).contents
                Release = ctypes.WINFUNCTYPE(wintypes.ULONG, c_void_p)(vtable[2])
                Release(ptr)
            except Exception:
                pass

    def _get_volume_interface(self):
        try:
            pEnumerator = c_void_p()
            hr = self._ole32.CoCreateInstance(byref(self._clsid_enum), None, 1, byref(self._iid_enum), byref(pEnumerator))
            if hr != 0 or not pEnumerator.value:
                return None

            vtable_enum = ctypes.cast(pEnumerator, POINTER(POINTER(c_void_p))).contents
            GetDefaultEndpoint = ctypes.WINFUNCTYPE(HRESULT, c_void_p, wintypes.DWORD, wintypes.DWORD, POINTER(c_void_p))(vtable_enum[4])

            pDevice = c_void_p()
            hr = GetDefaultEndpoint(pEnumerator, 0, 1, byref(pDevice))  # eRender=0, eMultimedia=1
            self._release(pEnumerator)
            if hr != 0 or not pDevice.value:
                return None

            vtable_dev = ctypes.cast(pDevice, POINTER(POINTER(c_void_p))).contents
            Activate = ctypes.WINFUNCTYPE(HRESULT, c_void_p, POINTER(self._GUID), wintypes.DWORD, c_void_p, POINTER(c_void_p))(vtable_dev[3])

            pVolume = c_void_p()
            hr = Activate(pDevice, byref(self._iid_vol), 23, None, byref(pVolume))
            self._release(pDevice)
            if hr != 0 or not pVolume.value:
                return None
            return pVolume
        except Exception:
            return None

    def read_volume(self) -> tuple[int, bool] | None:
        """Read master level and mute from the same playback endpoint."""
        pVolume = self._get_volume_interface()
        if not pVolume:
            return None
        try:
            table = ctypes.cast(pVolume, POINTER(POINTER(c_void_p))).contents
            get_level = ctypes.WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_float))(table[9])
            get_mute = ctypes.WINFUNCTYPE(HRESULT, c_void_p, POINTER(wintypes.BOOL))(table[15])
            level, muted = c_float(), wintypes.BOOL()
            if get_level(pVolume, byref(level)) < 0 or get_mute(pVolume, byref(muted)) < 0:
                return None
            if not 0 <= level.value <= 1:
                return None
            return round(level.value * 100), bool(muted.value)
        except Exception:
            return None
        finally:
            self._release(pVolume)

    def get_volume(self) -> int | None:
        reading = self.read_volume()
        return reading[0] if reading is not None else None

    def set_volume(self, level: int):
        """Sets the system master volume (0-100)."""
        level = max(0, min(100, int(level)))
        pVolume = self._get_volume_interface()
        if not pVolume:
            return
        try:
            vtable_vol = ctypes.cast(pVolume, POINTER(POINTER(c_void_p))).contents
            SetVol = ctypes.WINFUNCTYPE(HRESULT, c_void_p, c_float, c_void_p)(vtable_vol[7])
            SetVol(pVolume, float(level) / 100.0, None)
        except Exception:
            pass
        finally:
            self._release(pVolume)

    def get_mute(self) -> bool:
        """Returns True if the system audio is muted."""
        pVolume = self._get_volume_interface()
        if not pVolume:
            return False
        try:
            vtable_vol = ctypes.cast(pVolume, POINTER(POINTER(c_void_p))).contents
            GetMute = ctypes.WINFUNCTYPE(HRESULT, c_void_p, POINTER(wintypes.BOOL))(vtable_vol[15])
            val = wintypes.BOOL()
            GetMute(pVolume, byref(val))
            return bool(val.value)
        except Exception:
            return False
        finally:
            self._release(pVolume)

    def set_mute(self, mute: bool):
        """Mutes or unmutes the system audio."""
        pVolume = self._get_volume_interface()
        if not pVolume:
            return
        try:
            vtable_vol = ctypes.cast(pVolume, POINTER(POINTER(c_void_p))).contents
            SetMute = ctypes.WINFUNCTYPE(HRESULT, c_void_p, wintypes.BOOL, c_void_p)(vtable_vol[14])
            SetMute(pVolume, wintypes.BOOL(mute), None)
        except Exception:
            pass
        finally:
            self._release(pVolume)

    def toggle_mute(self) -> bool:
        """Toggles audio mute state and returns the new muted status."""
        curr = self.get_mute()
        self.set_mute(not curr)
        return not curr

    def _get_mic_interface(self):
        try:
            pEnumerator = c_void_p()
            hr = self._ole32.CoCreateInstance(byref(self._clsid_enum), None, 1, byref(self._iid_enum), byref(pEnumerator))
            if hr != 0 or not pEnumerator.value:
                return None

            vtable_enum = ctypes.cast(pEnumerator, POINTER(POINTER(c_void_p))).contents
            GetDefaultEndpoint = ctypes.WINFUNCTYPE(HRESULT, c_void_p, wintypes.DWORD, wintypes.DWORD, POINTER(c_void_p))(vtable_enum[4])

            pDevice = c_void_p()
            # eCapture = 1, eMultimedia = 1
            hr = GetDefaultEndpoint(pEnumerator, 1, 1, byref(pDevice))
            self._release(pEnumerator)
            if hr != 0 or not pDevice.value:
                return None

            vtable_dev = ctypes.cast(pDevice, POINTER(POINTER(c_void_p))).contents
            Activate = ctypes.WINFUNCTYPE(HRESULT, c_void_p, POINTER(self._GUID), wintypes.DWORD, c_void_p, POINTER(c_void_p))(vtable_dev[3])

            pVolume = c_void_p()
            hr = Activate(pDevice, byref(self._iid_vol), 23, None, byref(pVolume))
            self._release(pDevice)
            if hr != 0 or not pVolume.value:
                return None
            return pVolume
        except Exception:
            return None

    def get_mic_mute(self) -> bool:
        """Returns True if the default microphone is muted."""
        pVolume = self._get_mic_interface()
        if not pVolume:
            return False
        try:
            vtable_vol = ctypes.cast(pVolume, POINTER(POINTER(c_void_p))).contents
            GetMute = ctypes.WINFUNCTYPE(HRESULT, c_void_p, POINTER(wintypes.BOOL))(vtable_vol[15])
            val = wintypes.BOOL()
            GetMute(pVolume, byref(val))
            return bool(val.value)
        except Exception:
            return False
        finally:
            self._release(pVolume)

    def set_mic_mute(self, mute: bool):
        """Mutes or unmutes the default microphone."""
        pVolume = self._get_mic_interface()
        if not pVolume:
            return
        try:
            vtable_vol = ctypes.cast(pVolume, POINTER(POINTER(c_void_p))).contents
            SetMute = ctypes.WINFUNCTYPE(HRESULT, c_void_p, wintypes.BOOL, c_void_p)(vtable_vol[14])
            SetMute(pVolume, wintypes.BOOL(mute), None)
        except Exception:
            pass
        finally:
            self._release(pVolume)

    def toggle_mic_mute(self) -> bool:
        """Toggles microphone mute state and returns the new muted status."""
        curr = self.get_mic_mute()
        self.set_mic_mute(not curr)
        return not curr


class SystemBrightnessController(QObject):
    """Coalesce WMI reads and writes off the Qt event thread."""

    brightness_changed = Signal(object)

    def __init__(self):
        super().__init__()
        self._target_brightness = None
        self._read_pending = False
        self._lock = threading.Lock()
        self._worker_thread = None
        self._closed = False

    def request_brightness(self):
        with self._lock:
            if not self._closed:
                self._read_pending = True
                self._start_worker()

    def set_brightness(self, level):
        with self._lock:
            if not self._closed:
                self._target_brightness = max(0, min(100, int(level)))
                self._start_worker()

    def _start_worker(self):
        if self._worker_thread is None:
            self._worker_thread = threading.Thread(target=self._apply_worker, daemon=True, name="poppy-brightness")
            self._worker_thread.start()

    def _apply_worker(self):
        initialized = False
        try:
            try:
                import pythoncom
                import win32com.client
                pythoncom.CoInitialize()
                initialized = True
                wmi = win32com.client.GetObject(r"winmgmts:\\.\root\wmi")
            except Exception:
                wmi = None
            while True:
                with self._lock:
                    target, read = self._target_brightness, self._read_pending
                    self._target_brightness, self._read_pending = None, False
                    if self._closed or (target is None and not read):
                        self._worker_thread = None
                        return
                value = None
                try:
                    if wmi is not None:
                        if target is not None:
                            for monitor in wmi.InstancesOf("WmiMonitorBrightnessMethods"):
                                params = monitor.Methods_("WmiSetBrightness").InParameters.SpawnInstance_()
                                params.Properties_.Item("Timeout").Value = 1
                                params.Properties_.Item("Brightness").Value = target
                                monitor.ExecMethod_("WmiSetBrightness", params)
                        value = next((int(m.CurrentBrightness) for m in wmi.InstancesOf("WmiMonitorBrightness")), None)
                except Exception:
                    pass
                with self._lock:
                    pending = self._target_brightness is not None
                    closed = self._closed
                if not (pending or closed):
                    try:
                        self.brightness_changed.emit(value)
                    except RuntimeError:
                        return
                if target is not None:
                    time.sleep(0.04)
        finally:
            if initialized:
                wmi = None
                pythoncom.CoUninitialize()

    def close(self):
        with self._lock:
            self._closed = True


class AudioPeakMeter:
    """
    Sub-millisecond Windows Core Audio peak level meter using IAudioMeterInformation.
    Provides real-time (master_peak, left_peak, right_peak) audio telemetry directly from hardware.
    Pure ctypes, zero dependencies, safe COM lifecycle management.
    """
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = AudioPeakMeter()
        return cls._instance

    def __init__(self):
        self._ole32 = ctypes.oledll.ole32
        self._ole32.CoInitialize(None)
        self._pMeter = None
        self._GUID = GUID
        self._clsid_enum = GUID()
        self._iid_enum = GUID()
        self._iid_meter = GUID()
        self._ole32.CLSIDFromString('{BCDE0395-E52F-467C-8E3D-C4579291692E}', byref(self._clsid_enum))
        self._ole32.CLSIDFromString('{A95664D2-9614-4F35-A746-DE8DB63617E6}', byref(self._iid_enum))
        self._ole32.CLSIDFromString('{C02216F6-8C67-4B5B-9D00-D008E73E0064}', byref(self._iid_meter))
        self._init_meter()

    def _release(self, ptr):
        if ptr and ptr.value:
            try:
                vtable = ctypes.cast(ptr, POINTER(POINTER(c_void_p))).contents
                Release = ctypes.WINFUNCTYPE(wintypes.ULONG, c_void_p)(vtable[2])
                Release(ptr)
            except Exception:
                pass

    def _init_meter(self):
        try:
            pEnumerator = c_void_p()
            hr = self._ole32.CoCreateInstance(byref(self._clsid_enum), None, 1, byref(self._iid_enum), byref(pEnumerator))
            if hr != 0 or not pEnumerator.value:
                return
            vtable_enum = ctypes.cast(pEnumerator, POINTER(POINTER(c_void_p))).contents
            GetDefaultEndpoint = ctypes.WINFUNCTYPE(HRESULT, c_void_p, wintypes.DWORD, wintypes.DWORD, POINTER(c_void_p))(vtable_enum[4])
            pDevice = c_void_p()
            hr = GetDefaultEndpoint(pEnumerator, 0, 1, byref(pDevice))
            self._release(pEnumerator)
            if hr != 0 or not pDevice.value:
                return
            vtable_dev = ctypes.cast(pDevice, POINTER(POINTER(c_void_p))).contents
            Activate = ctypes.WINFUNCTYPE(HRESULT, c_void_p, POINTER(self._GUID), wintypes.DWORD, c_void_p, POINTER(c_void_p))(vtable_dev[3])
            pMeter = c_void_p()
            hr = Activate(pDevice, byref(self._iid_meter), 23, None, byref(pMeter))
            self._release(pDevice)
            if hr == 0 and pMeter.value:
                self._pMeter = pMeter
        except Exception:
            self._pMeter = None

    def get_peaks(self) -> tuple[float, float, float]:
        """Returns (master_peak, left_peak, right_peak) in range [0.0, 1.0]."""
        if not self._pMeter:
            self._init_meter()
        if not self._pMeter:
            return (0.0, 0.0, 0.0)
        try:
            vtable_meter = ctypes.cast(self._pMeter, POINTER(POINTER(c_void_p))).contents
            GetPeakValue = ctypes.WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_float))(vtable_meter[3])
            val = c_float()
            if GetPeakValue(self._pMeter, byref(val)) != 0:
                self._release(self._pMeter)
                self._pMeter = None
                return (0.0, 0.0, 0.0)
            get_count = ctypes.WINFUNCTYPE(HRESULT, c_void_p, POINTER(wintypes.UINT))(vtable_meter[4])
            count = wintypes.UINT()
            if get_count(self._pMeter, byref(count)) == 0 and count.value:
                get_channels = ctypes.WINFUNCTYPE(HRESULT, c_void_p, wintypes.UINT, POINTER(c_float))(vtable_meter[5])
                peaks = (c_float * count.value)()
                if get_channels(self._pMeter, count.value, peaks) == 0:
                    return val.value, peaks[0], peaks[min(1, count.value - 1)]
            return (val.value,) * 3
        except Exception:
            self._release(self._pMeter)
            self._pMeter = None
            return (0.0, 0.0, 0.0)

    def __del__(self):
        p = getattr(self, "_pMeter", None)
        if p:
            self._release(p)
            self._pMeter = None

