"""Route wheel input under the annotation canvas while interacting on Windows."""

import ctypes
from ctypes import wintypes


_WHEEL = 0x020A
_HORIZONTAL_WHEEL = 0x020E
_MOUSE_HOOK = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
_WHEEL_KEYS = ((0x01, 0x01), (0x02, 0x02), (0x10, 0x04), (0x11, 0x08),
               (0x04, 0x10), (0x05, 0x20), (0x06, 0x40))


class _MouseEvent(ctypes.Structure):
    _fields_ = [("point", wintypes.POINT), ("data", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("extra", ctypes.c_size_t)]


class AnnotationWheel:
    def __init__(self, canvas, toolbar):
        self._canvas = canvas
        self._toolbar = toolbar
        self._hook = None
        self._callback = _MOUSE_HOOK(self._on_mouse)
        user32 = ctypes.WinDLL("user32")
        user32.SetWindowsHookExW.argtypes = (ctypes.c_int, _MOUSE_HOOK, wintypes.HMODULE, wintypes.DWORD)
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
        user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        user32.WindowFromPoint.argtypes = (wintypes.POINT,)
        user32.WindowFromPoint.restype = wintypes.HWND
        user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        user32.GetAncestor.restype = wintypes.HWND
        user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        self._win = user32

    def start(self):
        if not self._hook:
            kernel32 = ctypes.WinDLL("kernel32")
            kernel32.GetModuleHandleW.restype = wintypes.HMODULE
            self._hook = self._win.SetWindowsHookExW(14, self._callback, kernel32.GetModuleHandleW(None), 0)

    def close(self):
        if self._hook:
            self._win.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def _on_mouse(self, code, message, address):
        if code == 0 and message in (_WHEEL, _HORIZONTAL_WHEEL) and address:
            event = _MouseEvent.from_address(address)
            if self._post_wheel(event.point, message, event.data & 0xffff0000):
                return 1
        return self._win.CallNextHookEx(None, code, message, address)

    def forward(self, horizontal, delta):
        point = wintypes.POINT()
        if not delta or not self._win.GetCursorPos(ctypes.byref(point)):
            return False
        return self._post_wheel(point, _HORIZONTAL_WHEEL if horizontal else _WHEEL, (delta & 0xffff) << 16)

    def _post_wheel(self, point, message, distance):
        bounds = wintypes.RECT()
        if not self._win.GetWindowRect(self._canvas, ctypes.byref(bounds)):
            return False
        if not (bounds.left <= point.x < bounds.right and bounds.top <= point.y < bounds.bottom):
            return False
        target = self._win.WindowFromPoint(point)
        if not target or self._win.GetAncestor(target, 2) in (self._canvas, self._toolbar):
            return False
        flags = 0
        for key, mask in _WHEEL_KEYS:
            if self._win.GetAsyncKeyState(key) & 0x8000:
                flags |= mask
        position = (point.x & 0xffff) | ((point.y & 0xffff) << 16)
        # Leave native routing intact if Windows rejects posting to this target.
        return bool(self._win.PostMessageW(target, message, distance | flags, position))
