"""
Poppy UI Minimalist Components
Stripped of visual noise, garish emoji, and AI border lines.
Faithfully recreating NotchX's design system (home-v2, now-playing-v2, pill-v2).
"""

import os
import math
import time
from PySide6.QtCore import (
    Qt, QRectF, QTimer, QPoint, QUrl, QMimeData, Signal, QPropertyAnimation, QEasingCurve, QEvent
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPainterPath, QDrag, QPixmap
)
from PySide6.QtWidgets import (
    QWidget, QPushButton, QLabel, QFrame, QApplication, QSlider, QScrollArea,
    QVBoxLayout, QHBoxLayout, QStackedWidget, QGraphicsOpacityEffect
)

from poppy.ui.icons import Icons, get_fluent_font_family
from poppy.core.system_controls import AudioPeakMeter


def _accent_to_rgba(hex_color: str, alpha: float) -> str:
    """Helper to convert hex accent to rgba string with custom alpha."""
    c = (hex_color or "#6e9bff").lstrip('#')
    if len(c) == 6:
        r = int(c[0:2], 16)
        g = int(c[2:4], 16)
        b = int(c[4:6], 16)
        return f"rgba({r}, {g}, {b}, {alpha})"
    return hex_color


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


class AnimatedTabStrip(QWidget):
    """
    Fluid segmented tab bar with a gliding active indicator pill.
    Smoothly animates its geometry between tab buttons with cubic spring physics.
    Zero AI borders, pure solid/translucent modern glass styling.
    """
    tab_changed = Signal(int)

    def __init__(self, tab_items: list[tuple[str, str]], accent="#6e9bff", parent=None):
        super().__init__(parent)
        self._accent = accent
        self._current_index = 0
        self.buttons: list[QPushButton] = []

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Sliding indicator pill behind buttons
        self.indicator = QWidget(self)
        self.indicator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._update_indicator_style()

        self._anim = QPropertyAnimation(self.indicator, b"geometry", self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        fluent_font = get_fluent_font_family()
        for idx, (name, icon) in enumerate(tab_items):
            label = f"{icon}  {name}" if icon else name
            btn = QPushButton(label, self)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(28)
            btn.clicked.connect(lambda checked=False, i=idx: self.set_current_index(i, animate=True))
            self.buttons.append(btn)
            self._layout.addWidget(btn)

        self._update_buttons_style()

    def set_tabs(self, tab_items: list[tuple[str, str]]):
        """Dynamically replace tabs in the strip without recreating the widget."""
        for btn in self.buttons:
            self._layout.removeWidget(btn)
            btn.deleteLater()
        self.buttons.clear()

        fluent_font = get_fluent_font_family()
        for idx, (name, icon) in enumerate(tab_items):
            label = f"{icon}  {name}" if icon else name
            btn = QPushButton(label, self)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(28)
            btn.clicked.connect(lambda checked=False, i=idx: self.set_current_index(i, animate=True))
            self.buttons.append(btn)
            self._layout.addWidget(btn)

        self._current_index = 0
        self._update_buttons_style()
        if self.buttons:
            self.indicator.setGeometry(self.buttons[0].geometry())

    def set_accent(self, accent: str):
        self._accent = accent
        self._update_indicator_style()
        self._update_buttons_style()

    def _update_indicator_style(self):
        bg = _accent_to_rgba(self._accent, 0.22)
        self.indicator.setStyleSheet(f"""
            background-color: {bg};
            border: none;
            border-radius: 12px;
        """)

    def _update_buttons_style(self):
        fluent_font = get_fluent_font_family()
        for i, btn in enumerate(self.buttons):
            is_active = (i == self._current_index)
            color = self._accent if is_active else "#94a3b8"
            font_weight = "600" if is_active else "500"
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    border: none;
                    border-radius: 12px;
                    color: {color};
                    font-family: '{fluent_font}', -apple-system, 'Segoe UI', Roboto, sans-serif;
                    font-size: 11px;
                    font-weight: {font_weight};
                    padding: 3px 8px;
                }}
                QPushButton:hover {{
                    color: #ffffff;
                }}
            """)

    def set_current_index(self, index: int, animate: bool = True, emit_signal: bool = True):
        if not (0 <= index < len(self.buttons)):
            return
        old_idx = self._current_index
        self._current_index = index
        self._update_buttons_style()

        target_btn = self.buttons[index]
        target_geom = target_btn.geometry()

        if animate and old_idx != index and self.isVisible():
            self._anim.stop()
            self._anim.setStartValue(self.indicator.geometry())
            self._anim.setEndValue(target_geom)
            self._anim.start()
        else:
            self.indicator.setGeometry(target_geom)

        if emit_signal:
            self.tab_changed.emit(index)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if 0 <= self._current_index < len(self.buttons):
            self.indicator.setGeometry(self.buttons[self._current_index].geometry())

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(20, self._sync_indicator)

    def _sync_indicator(self):
        if 0 <= self._current_index < len(self.buttons):
            self.indicator.setGeometry(self.buttons[self._current_index].geometry())
            self.indicator.lower()


class AnimatedStackedWidget(QStackedWidget):
    """
    Fluid, artifact-free stacked container for tabs.
    Directly switches indices to prevent DWM alpha-channel punch-through glitches
    where desktop / code behind the translucent window becomes visible during transitions.
    """
    def __init__(self, parent=None):
        super().__init__(parent)

    def slide_to_index(self, target_idx: int):
        if not (0 <= target_idx < self.count()):
            return
        if target_idx != self.currentIndex():
            self.setCurrentIndex(target_idx)


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
            bg_color = _accent_to_rgba(self._accent, 0.22)
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {bg_color};
                    border: none;
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
                    border: none;
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
            bg_color = _accent_to_rgba(self._accent, 0.22)
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {bg_color};
                    border: none;
                    border-radius: 11px;
                    color: {self._accent};
                    font-size: 10px;
                    font-weight: 600;
                    padding: 2px 10px;
                }}
            """)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background-color: rgba(255, 255, 255, 0.05);
                    border: none;
                    border-radius: 11px;
                    color: #94a3b8;
                    font-size: 10px;
                    font-weight: 500;
                    padding: 2px 10px;
                }
                QPushButton:hover {
                    background-color: rgba(255, 255, 255, 0.10);
                    color: #f8fafc;
                }
            """)


class CardFrame(QFrame):
    """NotchX frosted card with clean borderless styling."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("cardFrame")
        self.setStyleSheet("""
            CardFrame#cardFrame {
                background: rgba(255, 255, 255, 0.035);
                border: none;
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
    """
    NotchX pill-v2 style 4-bar sound wave equalizer with fluid physics.
    Reacts dynamically to real Windows Core Audio peak levels and musical harmonics.
    Butter-smooth 33 FPS subpixel rendering with fast attack and natural decay.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(18, 14)
        self._is_playing = False
        self._heights = [2.5, 2.5, 2.5, 2.5]
        self._meter = None
        self._timer = QTimer(self)
        self._timer.setInterval(30)  # ~33 FPS fluid motion
        self._timer.timeout.connect(self._animate_bars)

    def set_playing(self, playing: bool):
        if self._is_playing != playing:
            self._is_playing = playing
            if playing:
                if not self._meter:
                    try:
                        self._meter = AudioPeakMeter.get_instance()
                    except Exception:
                        self._meter = None
                self._timer.start()
            else:
                # Keep timer running briefly for smooth analog decay towards resting height
                if not self._timer.isActive():
                    self._timer.start()
            self.update()

    def _animate_bars(self):
        # If widget is not visible on screen, suspend animation updates to save CPU
        if not self.isVisible():
            if not self._is_playing:
                self._timer.stop()
            return

        if not self._is_playing:
            # Smoothly decay towards idle resting height (2.5px)
            all_at_rest = True
            for i in range(4):
                if self._heights[i] > 2.55:
                    self._heights[i] += (2.5 - self._heights[i]) * 0.22
                    all_at_rest = False
                else:
                    self._heights[i] = 2.5
            self.update()
            if all_at_rest:
                self._timer.stop()
            return

        # Query live system audio peak levels (master, left, right)
        master, left, right = 0.0, 0.0, 0.0
        if self._meter:
            try:
                master, left, right = self._meter.get_peaks()
            except Exception:
                pass

        # Perceptual logarithmic energy (human hearing curve)
        m_energy = pow(max(0.0, min(1.0, master)), 0.45) if master > 0.001 else 0.0
        l_energy = pow(max(0.0, min(1.0, left)), 0.45) if left > 0.001 else 0.0
        r_energy = pow(max(0.0, min(1.0, right)), 0.45) if right > 0.001 else 0.0

        t = time.time()
        # Multi-frequency musical harmonics for each of the 4 capsules
        w0 = max(0.0, min(1.0, math.sin(t * 7.5) * 0.35 + math.sin(t * 3.8 + 0.4) * 0.35 + 0.5))
        w1 = max(0.0, min(1.0, math.sin(t * 9.2 + 1.2) * 0.35 + math.cos(t * 4.6 + 0.8) * 0.35 + 0.5))
        w2 = max(0.0, min(1.0, math.sin(t * 8.4 + 2.5) * 0.35 + math.sin(t * 5.7 + 1.6) * 0.35 + 0.5))
        w3 = max(0.0, min(1.0, math.sin(t * 10.1 + 3.8) * 0.35 + math.cos(t * 6.9 + 2.2) * 0.35 + 0.5))

        if master > 0.004:
            # Active audio playback: bars pulse dynamically to the beat and loudness
            t0 = 2.5 + 10.5 * (l_energy * 0.72 + w0 * 0.28)
            t1 = 2.5 + 10.5 * (m_energy * 0.76 + w1 * 0.24)
            t2 = 2.5 + 10.5 * (m_energy * 0.76 + w2 * 0.24)
            t3 = 2.5 + 10.5 * (r_energy * 0.70 + w3 * 0.30)
        else:
            # Subtle rhythmic flow when playing soft/acoustic passages or muted output
            t0 = 2.5 + 8.5 * (w0 * 0.80 + 0.10)
            t1 = 2.5 + 10.5 * (w1 * 0.88 + 0.10)
            t2 = 2.5 + 9.8 * (w2 * 0.85 + 0.10)
            t3 = 2.5 + 8.0 * (w3 * 0.75 + 0.10)

        targets = [t0, t1, t2, t3]
        for i in range(4):
            tgt = targets[i]
            # Fast attack (0.45) for rhythmic snap, gentle decay (0.22) for analog fluidity
            rate = 0.45 if tgt > self._heights[i] else 0.22
            self._heights[i] += (tgt - self._heights[i]) * rate

        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(241, 245, 249, 235) if self._is_playing else QColor(148, 163, 184, 80)
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)

        w = 2.5
        spacing = 4.2
        h_max = self.height()
        for i, h in enumerate(self._heights):
            h_clamped = max(2.5, min(h_max, h))
            x = i * spacing + 1.0
            y = (h_max - h_clamped) / 2.0  # Symmetrically centered vertically
            painter.drawRoundedRect(QRectF(x, y, w, h_clamped), 1.25, 1.25)


class MetricLabel(QLabel):
    """Clean hardware telemetry label."""
    def __init__(self, tag: str, val: str = "--%", parent=None):
        super().__init__(parent)
        self.tag = tag
        self.setText(f"{tag} {val}")
        self.setStyleSheet("""
            QLabel {
                background: rgba(255, 255, 255, 0.05);
                border: none;
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
                background-color: rgba(255, 255, 255, 0.06);
                border: none;
                border-radius: {border_radius}px;
            }}
            QLabel:hover {{
                background-color: rgba(255, 255, 255, 0.12);
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


class ClickableSlider(QSlider):
    """Horizontal scrubber that jumps to exact click position and emits seeking values."""
    seek_clicked = Signal(int)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            val_range = self.maximum() - self.minimum()
            if val_range > 0 and self.width() > 0:
                pos = event.position().x()
                pct = max(0.0, min(1.0, pos / float(self.width())))
                val = int(round(self.minimum() + pct * val_range))
                self.setValue(val)
                self.seek_clicked.emit(val)
                event.accept()
                return
        super().mousePressEvent(event)


class LyricLineWidget(QPushButton):
    """Clean, modern lyric row matching native Spotify desktop typography."""
    def __init__(self, time_sec: float, text: str, parent=None):
        super().__init__(text, parent)
        self.time_sec = time_sec
        self._is_active = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_style()

    def set_active(self, active: bool):
        if self._is_active != active:
            self._is_active = active
            self.update_style()

    def update_style(self):
        if self._is_active:
            self.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    border: none;
                    color: #ffffff;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                    font-size: 15px;
                    font-weight: 700;
                    text-align: left;
                    padding: 6px 4px;
                    margin: 2px 0px;
                }
            """)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    border: none;
                    color: rgba(255, 255, 255, 0.35);
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                    font-size: 13.5px;
                    font-weight: 500;
                    text-align: left;
                    padding: 5px 4px;
                    margin: 1px 0px;
                }
                QPushButton:hover {
                    color: rgba(255, 255, 255, 0.85);
                    background: transparent;
                }
            """)


class SpotifyLyricsWidget(QFrame):
    """
    Clean, modern synchronized lyrics panel.
    Seamlessly integrated with Poppy's design system.
    Smoothly tracks song playback with animated vertical auto-scrolling to center the active line.
    Allows clicking any line to jump to that timestamp.
    """
    seek_requested = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("lyricsWidgetFrame")
        self.setStyleSheet("""
            QFrame#lyricsWidgetFrame {
                background: transparent;
                border: none;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 6)
        layout.setSpacing(6)

        # Header bar
        hdr_row = QHBoxLayout()
        hdr_row.setContentsMargins(4, 0, 4, 4)
        lbl_hdr = QLabel("Lyrics")
        lbl_hdr.setStyleSheet("QLabel { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 11px; font-weight: 600; color: #94a3b8; background: transparent; border: none; }")

        hdr_row.addWidget(lbl_hdr)
        hdr_row.addStretch()
        layout.addLayout(hdr_row)

        # Content stack: Page 0 = Lyrics Scroll Area, Page 1 = Placeholder / Status
        self.content_stack = QStackedWidget(self)
        self.content_stack.setStyleSheet("background: transparent; border: none;")

        # Page 0: Scroll Area for Lyrics
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.viewport().setAutoFillBackground(False)
        self.scroll_area.viewport().setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.scroll_area.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.scroll_area.setStyleSheet("""
            QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical, QScrollBar:horizontal {
                border: none;
                background: transparent;
                width: 0px;
                height: 0px;
                margin: 0px;
            }
            QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
                background: transparent;
                border: none;
            }
            QScrollBar::add-line, QScrollBar::sub-line {
                width: 0px;
                height: 0px;
                border: none;
            }
        """)

        self.lines_container = QWidget()
        self.lines_container.setStyleSheet("background: transparent; border: none;")
        self.lines_layout = QVBoxLayout(self.lines_container)
        self.lines_layout.setContentsMargins(0, 4, 0, 8)
        self.lines_layout.setSpacing(2)
        self.scroll_area.setWidget(self.lines_container)
        self.content_stack.addWidget(self.scroll_area)

        # Page 1: Centered Status / Placeholder
        placeholder_wrap = QWidget()
        placeholder_wrap.setStyleSheet("background: transparent; border: none;")
        p_layout = QVBoxLayout(placeholder_wrap)
        p_layout.setContentsMargins(12, 24, 12, 24)
        p_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_status = QLabel("Play music to view lyrics", placeholder_wrap)
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("QLabel { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 12px; font-weight: 400; color: #64748b; background: transparent; border: none; line-height: 1.5; }")
        p_layout.addWidget(self.lbl_status)
        self.content_stack.addWidget(placeholder_wrap)

        layout.addWidget(self.content_stack, stretch=1)

        # Smooth Scroll Animation
        self._scroll_anim = QPropertyAnimation(self.scroll_area.verticalScrollBar(), b"value")
        self._scroll_anim.setDuration(240)
        self._scroll_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._synced_lines: list[tuple[float, str]] = []
        self._line_buttons: list[LyricLineWidget] = []
        self._current_line_idx = -1
        self._user_scrolling = False

        # Resume auto-scroll timer after user manual scrolling
        self._resume_timer = QTimer(self)
        self._resume_timer.setSingleShot(True)
        self._resume_timer.setInterval(3200)
        self._resume_timer.timeout.connect(self._resume_auto_scroll)

        # Detect user scroll interaction
        self.scroll_area.verticalScrollBar().sliderPressed.connect(self._on_user_scroll)
        self.scroll_area.viewport().installEventFilter(self)

        # Start on placeholder
        self.content_stack.setCurrentIndex(1)

    def eventFilter(self, obj, event):
        if obj == self.scroll_area.viewport() and event.type() == QEvent.Type.Wheel:
            self._on_user_scroll()
        return super().eventFilter(obj, event)

    def set_playback_state(self, is_playing: bool):
        pass

    def _on_user_scroll(self):
        self._user_scrolling = True
        self._resume_timer.start()

    def _resume_auto_scroll(self):
        self._user_scrolling = False
        if self._current_line_idx >= 0 and self._current_line_idx < len(self._line_buttons):
            self._scroll_to_line(self._current_line_idx)

    def set_loading(self, title: str, artist: str):
        self._clear_lines()
        disp = f'"{title}"' if title else "track"
        if artist:
            disp += f"\n{artist}"
        self.lbl_status.setText(f"Searching lyrics for\n{disp}...")
        self.content_stack.setCurrentIndex(1)

    def set_not_found(self, title: str, artist: str):
        self._clear_lines()
        disp = f'"{title}"' if title else "track"
        if artist:
            disp += f"\n{artist}"
        self.lbl_status.setText(f"No lyrics found for\n{disp}")
        self.content_stack.setCurrentIndex(1)

    def set_synced_lyrics(self, synced_lines: list[tuple[float, str]]):
        self._clear_lines()
        self.content_stack.setCurrentIndex(0)
        self._synced_lines = synced_lines
        self._current_line_idx = -1

        self.lines_layout.addSpacing(16)
        for time_sec, text in synced_lines:
            btn = LyricLineWidget(time_sec, text, self.lines_container)
            btn.clicked.connect(lambda checked=False, t=time_sec: self.seek_requested.emit(t))
            self.lines_layout.addWidget(btn)
            self._line_buttons.append(btn)

        self.lines_layout.addSpacing(28)
        self.lines_layout.addStretch()

    def set_plain_lyrics(self, plain_text: str):
        self._clear_lines()
        self.content_stack.setCurrentIndex(0)
        self._synced_lines = []
        self._current_line_idx = -1

        self.lines_layout.addSpacing(16)
        for line in plain_text.splitlines():
            clean = line.strip()
            if not clean:
                continue
            lbl = QLabel(clean, self.lines_container)
            lbl.setStyleSheet("""
                QLabel {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                    font-size: 13.5px;
                    font-weight: 500;
                    color: rgba(255, 255, 255, 0.65);
                    background: transparent;
                    border: none;
                    padding: 5px 4px;
                }
            """)
            lbl.setWordWrap(True)
            self.lines_layout.addWidget(lbl)

        self.lines_layout.addSpacing(28)
        self.lines_layout.addStretch()

    def update_playback_time(self, pos_sec: float):
        if not self._synced_lines or not self._line_buttons:
            return

        # 0.25s vocal anticipation compensation so highlighting lands squarely on the opening syllable
        sync_time = pos_sec + 0.25

        active_idx = -1
        for i, (t_sec, _) in enumerate(self._synced_lines):
            if sync_time >= t_sec:
                active_idx = i
            else:
                break

        if active_idx != self._current_line_idx:
            # Unset old
            if 0 <= self._current_line_idx < len(self._line_buttons):
                self._line_buttons[self._current_line_idx].set_active(False)

            self._current_line_idx = active_idx

            # Set new
            if 0 <= active_idx < len(self._line_buttons):
                self._line_buttons[active_idx].set_active(True)
                if not self._user_scrolling:
                    self._scroll_to_line(active_idx)

    def _scroll_to_line(self, idx: int):
        if 0 <= idx < len(self._line_buttons):
            btn = self._line_buttons[idx]
            viewport_h = self.scroll_area.viewport().height()
            target_y = btn.y() - (viewport_h // 2) + (btn.height() // 2)
            max_y = self.scroll_area.verticalScrollBar().maximum()
            target_y = max(0, min(max_y, target_y))

            self._scroll_anim.stop()
            self._scroll_anim.setStartValue(self.scroll_area.verticalScrollBar().value())
            self._scroll_anim.setEndValue(target_y)
            self._scroll_anim.start()

    def _clear_lines(self):
        self._scroll_anim.stop()
        self._synced_lines.clear()
        self._line_buttons.clear()
        self._current_line_idx = -1
        while self.lines_layout.count() > 0:
            item = self.lines_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()



