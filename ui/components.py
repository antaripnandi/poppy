"""
Poppy UI Minimalist Components
Stripped of visual noise, garish emoji, and AI border lines.
Faithfully recreating NotchX's design system (home-v2, now-playing-v2, pill-v2).
"""

import os
from PySide6.QtCore import (
    Qt, QRectF, QTimer, QPoint, QUrl, QMimeData, Signal, QPropertyAnimation, QEasingCurve, QEvent
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPainterPath, QDrag, QPixmap
)
from PySide6.QtWidgets import (
    QWidget, QPushButton, QLabel, QFrame, QApplication, QSlider, QScrollArea,
    QVBoxLayout, QHBoxLayout
)

from poppy.ui.icons import Icons


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
            border_color = _accent_to_rgba(self._accent, 0.55)
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {bg_color};
                    border: 1px solid {border_color};
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
            bg_color = _accent_to_rgba(self._accent, 0.22)
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {bg_color};
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
    """Individual lyric row with smooth opacity and highlight."""
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
                    background-color: rgba(255, 255, 255, 0.12);
                    border: none;
                    border-radius: 8px;
                    color: #ffffff;
                    font-size: 14px;
                    font-weight: 700;
                    text-align: left;
                    padding: 8px 12px;
                    margin: 2px 0px;
                }
            """)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: none;
                    border-radius: 6px;
                    color: rgba(255, 255, 255, 0.38);
                    font-size: 12.5px;
                    font-weight: 500;
                    text-align: left;
                    padding: 5px 12px;
                    margin: 1px 0px;
                }
                QPushButton:hover {
                    color: #f1f5f9;
                    background-color: rgba(255, 255, 255, 0.05);
                }
            """)


class SpotifyLyricsWidget(QFrame):
    """
    Spotify-grade interactive animated lyrics view.
    Smoothly tracks song playback with animated auto-scrolling to center the active line.
    Allows clicking any line to jump to that timestamp.
    """
    seek_requested = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("lyricsWidgetFrame")
        self.setStyleSheet("""
            QFrame#lyricsWidgetFrame {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(255, 255, 255, 0.05), stop:1 rgba(255, 255, 255, 0.02));
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 16px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        # Header bar
        hdr_row = QHBoxLayout()
        lbl_hdr = QLabel("LYRICS")
        lbl_hdr.setStyleSheet("QLabel { font-size: 10px; font-weight: 700; color: #94a3b8; letter-spacing: 0.8px; background: transparent; border: none; }")

        self.badge_sync = QLabel("SYNCED")
        self.badge_sync.setStyleSheet("QLabel { font-size: 9px; font-weight: 700; color: #38bdf8; background: rgba(56, 189, 248, 0.18); border-radius: 4px; padding: 1px 5px; border: 1px solid rgba(56, 189, 248, 0.3); }")
        self.badge_sync.setVisible(False)

        hdr_row.addWidget(lbl_hdr)
        hdr_row.addWidget(self.badge_sync)
        hdr_row.addStretch()
        layout.addLayout(hdr_row)

        # Scroll Area for Lyrics
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                border: none;
                background: transparent;
                width: 3px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.2);
                border-radius: 1px;
                min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

        self.lines_container = QWidget()
        self.lines_layout = QVBoxLayout(self.lines_container)
        self.lines_layout.setContentsMargins(0, 4, 0, 8)
        self.lines_layout.setSpacing(2)
        self.scroll_area.setWidget(self.lines_container)
        layout.addWidget(self.scroll_area, stretch=1)

        # Status / Placeholder Label
        self.lbl_status = QLabel("Play music to view synchronized lyrics")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("QLabel { font-size: 11px; color: #64748b; background: transparent; border: none; padding: 20px; }")
        self.lines_layout.addWidget(self.lbl_status)

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
        self.badge_sync.setVisible(False)
        self.lbl_status.setText(f"Searching lyrics for\n\"{title}\"...")
        self.lbl_status.setVisible(True)

    def set_not_found(self, title: str, artist: str):
        self._clear_lines()
        self.badge_sync.setVisible(False)
        self.lbl_status.setText(f"No lyrics available for\n\"{title}\"")
        self.lbl_status.setVisible(True)

    def set_synced_lyrics(self, synced_lines: list[tuple[float, str]]):
        self._clear_lines()
        self.lbl_status.setVisible(False)
        self.badge_sync.setVisible(True)
        self._synced_lines = synced_lines
        self._current_line_idx = -1

        for time_sec, text in synced_lines:
            btn = LyricLineWidget(time_sec, text, self.lines_container)
            btn.clicked.connect(lambda checked=False, t=time_sec: self.seek_requested.emit(t))
            self.lines_layout.addWidget(btn)
            self._line_buttons.append(btn)

        self.lines_layout.addStretch()

    def set_plain_lyrics(self, plain_text: str):
        self._clear_lines()
        self.lbl_status.setVisible(False)
        self.badge_sync.setVisible(False)
        self._synced_lines = []
        self._current_line_idx = -1

        for line in plain_text.splitlines():
            clean = line.strip()
            if not clean:
                continue
            lbl = QLabel(clean, self.lines_container)
            lbl.setStyleSheet("QLabel { font-size: 13px; font-weight: 500; color: #cbd5e1; background: transparent; padding: 4px 6px; }")
            lbl.setWordWrap(True)
            self.lines_layout.addWidget(lbl)

        self.lines_layout.addStretch()

    def update_playback_time(self, pos_sec: float):
        if not self._synced_lines or not self._line_buttons:
            return

        # Find active line
        active_idx = -1
        for i, (t_sec, _) in enumerate(self._synced_lines):
            if pos_sec >= (t_sec - 0.2):
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
            if item.widget() and item.widget() != self.lbl_status:
                item.widget().deleteLater()


