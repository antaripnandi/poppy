"""Windows application icons for desktop and usage lists."""

import ctypes
from ctypes import wintypes
from functools import lru_cache
import os
import sys

from PySide6.QtCore import QFileInfo
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import QApplication, QFileIconProvider, QStyle


@lru_cache(maxsize=128)
def _shell_icon(path: str) -> QIcon:
    info = QFileInfo(path)
    return QFileIconProvider().icon(info) if info.isFile() else QIcon()


@lru_cache(maxsize=1)
def _window_icon_functions():
    user32 = ctypes.WinDLL("user32")
    send = user32.SendMessageTimeoutW
    send.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t),
    ]
    send.restype = wintypes.LPARAM
    class_icon = getattr(user32, "GetClassLongPtrW", user32.GetClassLongW)
    class_icon.argtypes = [wintypes.HWND, ctypes.c_int]
    class_icon.restype = ctypes.c_size_t
    return send, class_icon


def app_icon(exe_path: str = "", hwnd: int | None = None) -> QIcon:
    if hwnd and sys.platform == "win32":
        send, class_icon = _window_icon_functions()
        handle = ctypes.c_size_t()
        # WM_GETICON / ICON_SMALL2, with a bounded wait for hung windows.
        send(hwnd, 0x007F, 2, 0, 0x0023, 15, ctypes.byref(handle))
        native_icon = handle.value or class_icon(hwnd, -34) or class_icon(hwnd, -14)
        if native_icon:
            image = QImage.fromHICON(native_icon)
            if not image.isNull():
                return QIcon(QPixmap.fromImage(image))
    if exe_path:
        icon = _shell_icon(os.path.normcase(exe_path))
        if not icon.isNull():
            return icon
    return QApplication.style().standardIcon(QStyle.StandardPixmap.SP_DesktopIcon)
