"""
Poppy System Tools Engine
Native Windows desktop tools: Keep Awake (Caffeine), Screen Color Eyedropper, Screen Snip, and Workstation Lock.
"""

import ctypes
import subprocess

from PySide6.QtCore import QObject, Qt, QPoint, QRectF, QTimer, Signal
from PySide6.QtGui import (
    QColor, QCursor, QFont, QGuiApplication, QPainter,
    QPainterPath, QPen
)
from PySide6.QtWidgets import QApplication, QWidget


class CaffeineManager(QObject):
    """Keeps the system and display awake using native SetThreadExecutionState."""
    changed = Signal(bool)
    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001
    ES_DISPLAY_REQUIRED = 0x00000002

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_active = False
        self.minutes = None
        self._timer = QTimer(self, singleShot=True)
        self._timer.timeout.connect(self._expire)

    def start(self, minutes=None):
        if not ctypes.windll.kernel32.SetThreadExecutionState(
            self.ES_CONTINUOUS | self.ES_SYSTEM_REQUIRED | self.ES_DISPLAY_REQUIRED
        ):
            return False
        self._timer.stop()
        if minutes is not None:
            self._timer.start(minutes * 60_000)
        self.is_active = True
        self.minutes = minutes
        self.changed.emit(True)
        return True

    def stop(self):
        if not self.is_active:
            return True
        if not ctypes.windll.kernel32.SetThreadExecutionState(self.ES_CONTINUOUS):
            return False
        self._timer.stop()
        self.is_active = False
        self.minutes = None
        self.changed.emit(False)
        return True

    def _expire(self):
        if not self.stop():
            self._timer.start(5000)


class ColorEyedropperOverlay(QWidget):
    """
    Interactive full-screen screen color eyedropper with a magnifying loupe,
    pixel grid, crosshairs, and instant click-to-copy HEX color.
    """
    color_picked = Signal(str)

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

        screen = QGuiApplication.primaryScreen()
        self._pixmap = screen.grabWindow(0)
        self._image = self._pixmap.toImage()
        self.setGeometry(screen.geometry())

        self._pos = QCursor.pos()
        self._current_color = QColor(0, 0, 0)

    def mouseMoveEvent(self, event):
        self._pos = event.position().toPoint()
        dpr = self.devicePixelRatio()
        px = int(round(self._pos.x() * dpr))
        py = int(round(self._pos.y() * dpr))
        x = max(0, min(self._image.width() - 1, px))
        y = max(0, min(self._image.height() - 1, py))
        self._current_color = self._image.pixelColor(x, y)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            hex_val = self._current_color.name().upper()
            QApplication.clipboard().setText(hex_val)
            self.color_picked.emit(hex_val)
            self.close()
        elif event.button() == Qt.MouseButton.RightButton:
            self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw slight dark tint across screen to focus on loupe
        painter.fillRect(self.rect(), QColor(0, 0, 0, 40))

        cx = self._pos.x()
        cy = self._pos.y()

        # Loupe dimensions
        loupe_radius = 56
        loupe_x = cx + 24
        loupe_y = cy + 24

        # Flip loupe position if near bottom or right screen edge
        if loupe_x + loupe_radius * 2 + 10 > self.width():
            loupe_x = cx - loupe_radius * 2 - 24
        if loupe_y + loupe_radius * 2 + 36 > self.height():
            loupe_y = cy - loupe_radius * 2 - 36

        # Clip circle for loupe
        path = QPainterPath()
        path.addEllipse(loupe_x, loupe_y, loupe_radius * 2, loupe_radius * 2)

        painter.save()
        painter.setClipPath(path)

        # Draw magnified 11x11 pixel region
        grid_cells = 11
        cell_size = (loupe_radius * 2.0) / grid_cells
        half_grid = grid_cells // 2

        dpr = self.devicePixelRatio()
        px = int(round(cx * dpr))
        py = int(round(cy * dpr))

        for row in range(grid_cells):
            for col in range(grid_cells):
                src_x = px - half_grid + col
                src_y = py - half_grid + row
                if 0 <= src_x < self._image.width() and 0 <= src_y < self._image.height():
                    c = self._image.pixelColor(src_x, src_y)
                else:
                    c = QColor(0, 0, 0)

                rx = loupe_x + col * cell_size
                ry = loupe_y + row * cell_size
                painter.fillRect(QRectF(rx, ry, cell_size + 0.5, cell_size + 0.5), c)

        # Center targeted pixel highlight
        center_cell_x = loupe_x + half_grid * cell_size
        center_cell_y = loupe_y + half_grid * cell_size
        painter.setPen(QPen(QColor(255, 255, 255, 220), 1.5))
        painter.drawRect(QRectF(center_cell_x, center_cell_y, cell_size, cell_size))

        painter.restore()

        # Loupe border
        painter.setPen(QPen(QColor(255, 255, 255, 180), 2.5))
        painter.drawEllipse(loupe_x, loupe_y, loupe_radius * 2, loupe_radius * 2)

        # Color Pill Info box below loupe
        pill_rect = QRectF(loupe_x - 10, loupe_y + loupe_radius * 2 + 8, loupe_radius * 2 + 20, 26)
        pill_path = QPainterPath()
        pill_path.addRoundedRect(pill_rect, 13, 13)
        painter.fillPath(pill_path, QColor(18, 21, 28, 235))
        painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
        painter.drawPath(pill_path)

        # Color swatch dot
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._current_color)
        painter.drawEllipse(QRectF(pill_rect.x() + 8, pill_rect.y() + 6, 14, 14))

        # Hex text
        painter.setPen(QColor(241, 245, 249))
        painter.setFont(QFont("Segoe UI Variable Text", 9, QFont.Weight.DemiBold))
        painter.drawText(
            QRectF(pill_rect.x() + 28, pill_rect.y(), pill_rect.width() - 32, pill_rect.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self._current_color.name().upper()
        )


def launch_screen_snip():
    """Triggers the native Windows Snipping Tool (Win + Shift + S)."""
    try:
        subprocess.Popen(["cmd.exe", "/c", "start", "ms-screenclip:"], shell=False)
    except Exception:
        pass


def lock_workstation():
    """Locks the Windows workstation immediately (Win + L)."""
    try:
        ctypes.windll.user32.LockWorkStation()
    except Exception:
        pass


def launch_windows_search():
    """Opens native Windows Search or Run prompt."""
    try:
        subprocess.Popen(["cmd.exe", "/c", "start", "ms-search:"], shell=False)
    except Exception:
        pass

