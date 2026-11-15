"""Read Windows mouse-button presses while the drawer is open."""

import ctypes
from ctypes import wintypes


WM_INPUT = 0x00FF


class _RawInputDevice(ctypes.Structure):
    _fields_ = [("page", wintypes.USHORT), ("usage", wintypes.USHORT),
                ("flags", wintypes.DWORD), ("window", wintypes.HWND)]


class _RawInputHeader(ctypes.Structure):
    _fields_ = [("kind", wintypes.DWORD), ("size", wintypes.DWORD),
                ("device", wintypes.HANDLE), ("param", wintypes.WPARAM)]


class _RawMouse(ctypes.Structure):
    _fields_ = [("flags", wintypes.USHORT), ("buttons", wintypes.ULONG),
                ("raw_buttons", wintypes.ULONG), ("x", wintypes.LONG),
                ("y", wintypes.LONG), ("extra", wintypes.ULONG)]


class _MouseInput(ctypes.Structure):
    _fields_ = [("header", _RawInputHeader), ("mouse", _RawMouse)]


def register_mouse_input(hwnd):
    # Keep ordinary Windows messages enabled. A null target removes the subscription.
    device = _RawInputDevice(1, 2, 0x100 if hwnd else 0x01, hwnd)
    return bool(ctypes.windll.user32.RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(device)))


def is_mouse_press(handle):
    packet = _MouseInput()
    size = wintypes.UINT(ctypes.sizeof(packet))
    read = ctypes.windll.user32.GetRawInputData(
        wintypes.HANDLE(handle), 0x10000003, ctypes.byref(packet), ctypes.byref(size),
        ctypes.sizeof(_RawInputHeader),
    )
    # The low word contains RI_MOUSE_LEFT_BUTTON_DOWN and RI_MOUSE_RIGHT_BUTTON_DOWN.
    return read == ctypes.sizeof(packet) and packet.header.kind == 0 and bool(packet.mouse.buttons & 0x05)
