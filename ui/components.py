"""
Poppy UI Minimalist Components
Stripped of visual noise, garish emoji, and AI border lines.
Faithfully recreating NotchX's design system (home-v2, now-playing-v2, pill-v2).
"""

import os
from PySide6.QtCore import Qt, Signal, QRectF, QTimer, QSize, QPoint, QUrl, QMimeData
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPainterPath, QDrag, QPixmap
from PySide6.QtWidgets import QWidget, QPushButton, QLabel, QHBoxLayout, QFrame, QApplication

from poppy.ui.icons import Icons


class IconButton(QPushButton):
    """Minimal, borderless button with subtle hover highlight."""
    def __init__(self, text: str = "", tooltip: str = "", parent=None, size=24, font_size=11, is_fluent: bool = False):
        super().__init__(text, parent)
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)
        family = "'Segoe Fluent Icons', 'Segoe MDL2 Assets', 'Segoe UI'" if is_fluent else "'Segoe UI Variable Text', 'Segoe UI', -apple-system, sans-serif"
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: {size // 4}px;
                color: #94a3b8;
                font-family: {family};
                font-size: {font_size}px;
                font-weight: 500;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 0.08);
                color: #f8fafc;
            }}
            QPushButton:pressed {{
                background-color: rgba(255, 255, 255, 0.15);
                color: #ffffff;
            }}
        """)


class TabButton(QPushButton):
    """NotchX-style top navigation pill tab button with clean typography and active lighting."""
    def __init__(self, name: str, index: int, parent=None, accent="#6e9bff", icon: str = ""):
        label = f"{icon} {name}" if icon else name
        super().__init__(label, parent)
        self.index = index
        self._name = name
        self._accent = accent
        self._is_active = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(30)
        self.update_style()

    def set_active(self, active: bool, accent: str = None):
        self._is_active = active
        if accent:
            self._accent = accent
        self.update_style()

    def set_accent(self, accent: str):
        self._accent = accent
        self.update_style()

    def update_style(self):
        if self._is_active:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: rgba(30, 48, 80, 0.95);
                    border: 1px solid rgba(79, 124, 247, 0.5);
                    border-radius: 12px;
                    color: {self._accent};
                    font-size: 11px;
                    font-weight: 600;
                    padding: 4px 14px;
                }}
            """)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: 1px solid transparent;
                    border-radius: 12px;
                    color: #94a3b8;
                    font-size: 11px;
                    font-weight: 500;
                    padding: 4px 12px;
                }
                QPushButton:hover {
                    background-color: rgba(255, 255, 255, 0.05);
                    color: #f1f5f9;
                }
            """)


class SourcePill(QPushButton):
    """Clean capsule pill for switching active media sessions (Spotify, YouTube, etc.)."""
    def __init__(self, text: str, session_index: int, is_active: bool = False, accent: str = "#6e9bff", parent=None):
        super().__init__(text, parent)
        self.session_index = session_index
        self._is_active = is_active
        self._accent = accent
        self.setFixedHeight(22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_style()

    def set_active(self, is_active: bool, accent: str = None):
        self._is_active = is_active
        if accent:
            self._accent = accent
        self.update_style()

    def update_style(self):
        if self._is_active:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: rgba(30, 48, 80, 0.95);
                    border: 1px solid {self._accent};
                    border-radius: 11px;
                    color: {self._accent};
                    font-size: 10px;
                    font-weight: 600;
                    padding: 1px 10px;
                }}
            """)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background-color: rgba(255, 255, 255, 0.04);
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-radius: 11px;
                    color: #94a3b8;
                    font-size: 10px;
                    font-weight: 500;
                    padding: 1px 10px;
                }
                QPushButton:hover {
                    background-color: rgba(255, 255, 255, 0.08);
                    color: #f8fafc;
                    border: 1px solid rgba(255, 255, 255, 0.15);
                }
            """)


class CardFrame(QFrame):
    """NotchX frosted card with top lighting and 16px radius, cleanly scoped."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("cardFrame")
        self.setStyleSheet("""
            CardFrame#cardFrame {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(255, 255, 255, 0.05), stop:1 rgba(255, 255, 255, 0.02));
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 16px;
            }
            QLabel {
                background: transparent;
                border: none;
            }
        """)


class CircularProgressRing(QWidget):
    """Anti-aliased circular progress ring for Pomodoro and focus tracking."""
    def __init__(self, size=40, track_width=3, parent=None, accent="#6e9bff"):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.track_width = track_width
        self._progress = 0.0
        self._color = QColor(accent)
        self._track_color = QColor(255, 255, 255, 18)

    def set_progress(self, val: float):
        self._progress = max(0.0, min(1.0, val))
        self.update()

    def set_color(self, hex_or_color):
        self._color = QColor(hex_or_color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        margin = self.track_width / 2.0 + 1.0
        draw_rect = QRectF(margin, margin, rect.width() - 2 * margin, rect.height() - 2 * margin)

        # Track Background
        pen_track = QPen(self._track_color, self.track_width)
        pen_track.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen_track)
        painter.drawEllipse(draw_rect)

        # Active Progress Arc
        if self._progress > 0:
            pen_active = QPen(self._color, self.track_width)
            pen_active.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen_active)
            start_angle = 90 * 16
            span_angle = -int(self._progress * 360 * 16)
            painter.drawArc(draw_rect, start_angle, span_angle)


class AudioVisualizerBars(QWidget):
    """NotchX pill-v2 style 4-bar sound wave equalizer with rounded capsules."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(18, 14)
        self._is_playing = False
        self._heights = [4, 10, 7, 5]
        self._timer = QTimer(self)
        self._timer.setInterval(130)
        self._timer.timeout.connect(self._animate_bars)

    def set_playing(self, playing: bool):
        if self._is_playing != playing:
            self._is_playing = playing
            if playing:
                self._timer.start()
            else:
                self._timer.stop()
                self._heights = [3, 3, 3, 3]
            self.update()

    def _animate_bars(self):
        import random
        self._heights = [random.randint(4, 13) for _ in range(4)]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(241, 245, 249, 230) if self._is_playing else QColor(148, 163, 184, 80)
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)

        w = 2.5
        spacing = 4.2
        h_max = self.height()
        for i, h in enumerate(self._heights):
            x = i * spacing + 1
            y = (h_max - h) / 2.0  # Center aligned vertically like in pill-v2.png
            painter.drawRoundedRect(QRectF(x, y, w, h), 1.25, 1.25)


class MetricLabel(QLabel):
    """Clean hardware telemetry label."""
    def __init__(self, tag: str, val: str = "--%", parent=None):
        super().__init__(parent)
        self.tag = tag
        self.setText(f"{tag} {val}")
        self.setStyleSheet("""
            QLabel {
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.07);
                border-radius: 6px;
                color: #94a3b8;
                font-family: 'Segoe UI Variable Display', -apple-system, sans-serif;
                font-size: 10px;
                font-weight: 600;
                padding: 3px 8px;
            }
        """)

    def set_val(self, val_str: str):
        self.setText(f"{self.tag} {val_str}")


class DraggableThumbnail(QLabel):
    """
    Thumbnail that displays an image and can be dragged directly out
    into any application on screen (Discord, Slack, Photoshop, Explorer, etc.).
    """
    def __init__(self, size: int = 40, border_radius: int = 8, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.border_radius = border_radius
        self.file_path: str | None = None
        self._pixmap: QPixmap | None = None
        self._drag_start_pos: QPoint | None = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(f"""
            QLabel {{
                background-color: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: {border_radius}px;
            }}
            QLabel:hover {{
                border: 1px solid rgba(255, 255, 255, 0.35);
            }}
        """)
        self.setToolTip("Click and drag anywhere onto screen, desktop, or chat")

    def set_image(self, file_path: str, pixmap: QPixmap | None = None):
        self.file_path = file_path
        if pixmap and not pixmap.isNull():
            self._pixmap = pixmap
        elif file_path:
            self._pixmap = QPixmap(file_path)
        else:
            self._pixmap = None

        if self._pixmap and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                self.width() - 4, self.height() - 4,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            rounded = QPixmap(scaled.size())
            rounded.fill(Qt.GlobalColor.transparent)
            painter = QPainter(rounded)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            path = QPainterPath()
            path.addRoundedRect(0, 0, scaled.width(), scaled.height(), self.border_radius, self.border_radius)
            painter.setClipPath(path)
            painter.drawPixmap(0, 0, scaled)
            painter.end()
            self.setPixmap(rounded)
        else:
            self.setStyleSheet(f"font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets'; font-size: 14px; color: #64748b; background: rgba(255, 255, 255, 0.05); border-radius: {self.border_radius}px;")
            self.setText(Icons.IMAGE)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton) or not self._drag_start_pos:
            return
        if (event.position().toPoint() - self._drag_start_pos).manhattanLength() < QApplication.startDragDistance():
            return
        if not self.file_path or not os.path.exists(self.file_path):
            return

        drag = QDrag(self)
        mime = QMimeData()
        abs_path = os.path.abspath(self.file_path)
        mime.setUrls([QUrl.fromLocalFile(abs_path)])
        drag.setMimeData(mime)

        if self._pixmap and not self._pixmap.isNull():
            drag_icon = self._pixmap.scaled(
                52, 52, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            drag.setPixmap(drag_icon)
            drag.setHotSpot(drag_icon.rect().center())

        drag.exec(
            Qt.DropAction.CopyAction | Qt.DropAction.MoveAction | Qt.DropAction.LinkAction,
            Qt.DropAction.CopyAction
        )
        self.setCursor(Qt.CursorShape.OpenHandCursor)

