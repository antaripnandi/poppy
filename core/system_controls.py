"""
Poppy System Hardware Controls
Zero-bloat native Windows hardware integration for Master Volume and Screen Brightness.
Uses Windows Core Audio COM API (IAudioEndpointVolume) via ctypes and WMI / DXVA2 for brightness.
"""

import ctypes
from ctypes import wintypes, HRESULT, POINTER, c_void_p, c_float, byref
import threading
import time


class SystemAudioController:
    """
    Direct Windows Core Audio master volume and mute controller.
    Uses pure ctypes and COM to interact with IAudioEndpointVolume at sub-millisecond latency.
    Strictly releases all COM interface pointers (IUnknown::Release) to eliminate handle leaks.
    """
    def __init__(self):
        self._ole32 = ctypes.oledll.ole32
        self._ole32.CoInitialize(None)

        class GUID(ctypes.Structure):
            _fields_ = [
                ('Data1', wintypes.DWORD),
                ('Data2', wintypes.WORD),
                ('Data3', wintypes.WORD),
                ('Data4', wintypes.BYTE * 8)
            ]
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

    def get_volume(self) -> int:
        """Returns the current master volume as an integer percent (0-100)."""
        pVolume = self._get_volume_interface()
        if not pVolume:
            return 50
        try:
            vtable_vol = ctypes.cast(pVolume, POINTER(POINTER(c_void_p))).contents
            GetVol = ctypes.WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_float))(vtable_vol[9])
            val = c_float()
            GetVol(pVolume, byref(val))
            return int(round(val.value * 100))
        except Exception:
            return 50
        finally:
            self._release(pVolume)

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


class SystemBrightnessController:
    """
    Hardware screen brightness controller.
    Uses in-process WMI COM for laptop panels with an asynchronous throttle worker so
    scrubbing the slider at 144Hz remains completely stutter-free.
    """
    def __init__(self):
        self._target_brightness = None
        self._lock = threading.Lock()
        self._worker_thread = None
        self._cached_brightness = 75

    def get_brightness(self) -> int:
        """Queries and returns the current screen brightness (0-100)."""
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            wmi = win32com.client.GetObject('winmgmts:\\\\.\\root\\wmi')
            bright_objs = wmi.InstancesOf('WmiMonitorBrightness')
            for b in bright_objs:
                val = int(b.CurrentBrightness)
                self._cached_brightness = val
                return val
        except Exception:
            pass
        return self._cached_brightness

    def set_brightness(self, level: int):
        """Asynchronously updates screen brightness with hardware command coalescing."""
        level = max(0, min(100, int(level)))
        self._cached_brightness = level
        with self._lock:
            self._target_brightness = level
            if self._worker_thread is None or not self._worker_thread.is_alive():
                self._worker_thread = threading.Thread(target=self._apply_worker, daemon=True)
                self._worker_thread.start()

    def _apply_worker(self):
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            wmi = win32com.client.GetObject('winmgmts:\\\\.\\root\\wmi')
        except Exception:
            return

        while True:
            target = None
            with self._lock:
                target = self._target_brightness
                self._target_brightness = None
            if target is None:
                break
            try:
                methods = wmi.InstancesOf('WmiMonitorBrightnessMethods')
                for m in methods:
                    in_params = m.Methods_('WmiSetBrightness').InParameters.SpawnInstance_()
                    in_params.Properties_.Item('Timeout').Value = 1
                    in_params.Properties_.Item('Brightness').Value = int(target)
                    m.ExecMethod_('WmiSetBrightness', in_params)
            except Exception:
                pass
            time.sleep(0.04)  # 25 updates/sec throttle to prevent DDC/CI bus flooding

    def cycle_brightness(self) -> int:
        """Cycles brightness between 25% -> 50% -> 75% -> 100%."""
        curr = self.get_brightness()
        presets = [25, 50, 75, 100]
        # find closest preset
        next_val = presets[0]
        for p in presets:
            if p > curr + 5:
                next_val = p
                break
        self.set_brightness(next_val)
        return next_val
