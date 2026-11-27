"""Windows application icons for desktop and usage lists."""

import ctypes
from ctypes import wintypes
from functools import lru_cache
import os
import sys

from PySide6.QtCore import QFileInfo, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QFileIconProvider

from poppy.core.storage import resource_path


@lru_cache(maxsize=128)
def _registered_executable(name: str) -> str:
    if sys.platform != "win32":
        return ""
    import winreg

    if name == "file explorer":
        return os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "explorer.exe")
    stem = "".join(char for char in name if char.isascii() and char.isalnum())
    if not stem:
        return ""
    key = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{stem}.exe"
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, key) as app:
                path, _ = winreg.QueryValueEx(app, "")
            return os.path.expandvars(path.strip('"')) if isinstance(path, str) else ""
        except OSError:
            continue
    return ""


@lru_cache(maxsize=48)
def _fallback_icon(initial: str) -> QIcon:
    tile = QPixmap(32, 32)
    tile.fill(Qt.GlobalColor.transparent)
    painter = QPainter(tile)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#41454a"))
    painter.drawRoundedRect(1, 1, 30, 30, 7, 7)
    font = QFont()
    font.setPixelSize(17)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#f2f3f4"))
    painter.drawText(tile.rect(), Qt.AlignmentFlag.AlignCenter, initial)
    painter.end()
    return QIcon(tile)


@lru_cache(maxsize=128)
def _shell_icon(path: str) -> QIcon:
    info = QFileInfo(path)
    if not info.isFile():
        return QIcon()
    if sys.platform != "win32":
        return QFileIconProvider().icon(info)

    extract, destroy = _executable_icon_functions()
    handle = wintypes.HICON()
    if extract(path, 0, ctypes.byref(handle), None, 1) == 1 and handle.value:
        try:
            image = QImage.fromHICON(handle.value)
            if not image.isNull():
                return QIcon(QPixmap.fromImage(image))
        finally:
            destroy(handle)
    return QIcon()


@lru_cache(maxsize=1)
def _executable_icon_functions():
    extract = ctypes.WinDLL("shell32").ExtractIconExW
    icon_pointer = ctypes.POINTER(wintypes.HICON)
    extract.argtypes = [wintypes.LPCWSTR, ctypes.c_int, icon_pointer, icon_pointer, wintypes.UINT]
    extract.restype = wintypes.UINT
    destroy = ctypes.WinDLL("user32").DestroyIcon
    destroy.argtypes = [wintypes.HICON]
    destroy.restype = wintypes.BOOL
    return extract, destroy


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


def app_icon(exe_path: str = "", hwnd: int | None = None, *, name: str = "") -> QIcon:
    if name.casefold() in ("poppy", "poppy notch"):
        return QIcon(str(resource_path("assets/branding/poppy-avatar.png")))
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
    registered = _registered_executable(name.casefold())
    if registered:
        icon = _shell_icon(os.path.normcase(registered))
        if not icon.isNull():
            return icon
    initial = next((char.upper() for char in name if char.isalnum()), "?")
    return _fallback_icon(initial)
