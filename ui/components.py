"""
Poppy UI Minimalist Components
Stripped of visual noise, garish emoji, and AI border lines.
Faithfully recreating NotchX's design system (home-v2, now-playing-v2, pill-v2).
"""

import os
from functools import lru_cache
from PySide6.QtCore import (
    Qt, QRect, QRectF, QSize, QTimer, QPoint, QUrl, QMimeData, Signal, QPropertyAnimation, QVariantAnimation, QEasingCurve, QEvent, Property
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPainterPath, QDrag, QPixmap, QFont, QIcon
)
from PySide6.QtWidgets import (
    QWidget, QPushButton, QLabel, QFrame, QApplication, QSlider, QScrollArea,
    QVBoxLayout, QHBoxLayout, QStackedWidget, QGraphicsOpacityEffect, QSizePolicy, QLayout, QStyle, QStyleOptionSlider
)

from poppy.ui.theme import set_widget_style, LAYOUT_THEMES, TRACK_LAYOUTS, is_light_theme, current_layout, surface_colors
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
            self.setAccessibleName(tooltip)
        family = "'Segoe Fluent Icons', 'Segoe MDL2 Assets', 'Segoe UI'" if is_fluent else "'Segoe UI Variable Text', 'Segoe UI', -apple-system, sans-serif"
        set_widget_style(self, f"""
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
            QPushButton:focus {{ border: 1px solid #b7c5bc; }}
            QPushButton:disabled {{ color: #59615d; }}
            QPushButton:pressed {{
                background-color: rgba(255, 255, 255, 0.15);
                color: #ffffff;
            }}
        """)


class ToggleSwitch(QWidget):
    """
    Modern iOS / macOS / Fluent style animated toggle switch.
    Replaces bulky Qt checkboxes with a clean, minimalist 36x20 pill.
    """
    toggled = Signal(bool)

    def __init__(self, checked: bool = False, accent: str = "#0a84ff", parent=None):
        super().__init__(parent)
        self.setFixedSize(36, 20)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._checked = bool(checked)
        self._accent = accent
        self._thumb_pos = 18.0 if checked else 2.0

        self._anim = QPropertyAnimation(self, b"thumb_position", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool, animate: bool = True):
        checked = bool(checked)
        if self._checked == checked:
            return
        self._checked = checked
        target = 18.0 if checked else 2.0
        if animate and self.isVisible():
            self._anim.stop()
            self._anim.setStartValue(self._thumb_pos)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self._thumb_pos = target
            self.update()
        self.toggled.emit(self._checked)
        self.setAccessibleDescription("On" if self._checked else "Off")

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.setChecked(not self._checked)
            event.accept()
            return
        super().keyPressEvent(event)

    def set_accent(self, accent: str):
        self._accent = accent
        self.update()

    def _get_thumb_position(self) -> float:
        return self._thumb_pos

    def _set_thumb_position(self, pos: float):
        self._thumb_pos = pos
        self.update()

    thumb_position = Property(float, _get_thumb_position, _set_thumb_position)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = float(self.width()), float(self.height())
        r = h / 2.0
        track_color = QColor(self._accent) if self._checked else (QColor(0, 0, 0, 35) if is_light_theme() else QColor(255, 255, 255, 30))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(track_color))
        painter.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        thumb_d = h - 4.0
        thumb_color = QColor(255, 255, 255)
        painter.setBrush(QBrush(thumb_color))
        painter.drawEllipse(QRectF(self._thumb_pos, 2.0, thumb_d, thumb_d))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#ffffff"), 1))
            painter.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), r, r)


class SettingRow(QWidget):
    """
    Minimalist setting row: Title + optional subtitle on the left, control on the right.
    """
    def __init__(self, title: str, subtitle: str = "", control: QWidget = None, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 10)
        layout.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)

        lbl_title = QLabel(title)
        lbl_title.setWordWrap(True)
        set_widget_style(lbl_title, "font-size: 12px; font-weight: 500; color: #f1f5f9; background: transparent; border: none;")
        text_col.addWidget(lbl_title)

        if subtitle:
            lbl_sub = QLabel(subtitle)
            lbl_sub.setWordWrap(True)
            set_widget_style(lbl_sub, "font-size: 11px; color: #919899; background: transparent; border: none;")
            text_col.addWidget(lbl_sub)

        layout.addLayout(text_col, 1)

        if control:
            control.setAccessibleName(title)
            layout.addWidget(control)


class ScrollArea(QScrollArea):
    """Handle pixel wheel input consistently, with native wheel-notch behavior."""
    def wheelEvent(self, event):
        delta = event.pixelDelta().y()
        if delta:
            bar = self.verticalScrollBar()
            previous = bar.value()
            bar.setValue(previous - delta)
            if bar.value() != previous:
                event.accept()
            else:
                event.ignore()
            return
        super().wheelEvent(event)


class AnimatedTabStrip(QWidget):
    """
    Compact text navigation with a short, direct selection transition.
    """
    tab_changed = Signal(int)

    def __init__(self, tab_items: list[tuple[str, str]], accent="#0a84ff", parent=None):
        super().__init__(parent)
        self._accent = accent
        self._current_index = 0
        self.buttons: list[QPushButton] = []

        set_widget_style(self, """
            AnimatedTabStrip {
                background-color: transparent;
                border: none;
                border-radius: 10px;
                padding: 2px 3px;
            }
        """)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(3, 2, 3, 2)
        self._layout.setSpacing(2)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Rubber indicator thumb behind buttons
        self.indicator = QWidget(self)
        self.indicator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._update_indicator_style()

        self._anim = QPropertyAnimation(self.indicator, b"geometry", self)
        self._anim.setDuration(240)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        for idx, (name, icon) in enumerate(tab_items):
            label = f"{icon}  {name}" if icon else name
            btn = QPushButton(label, self)
            btn.setProperty("tabLabel", label)
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

        for idx, (name, icon) in enumerate(tab_items):
            label = f"{icon}  {name}" if icon else name
            btn = QPushButton(label, self)
            btn.setProperty("tabLabel", label)
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
        name = current_layout()
        if name in ("Flat", "Daily"):
            source = "background: transparent; border: none; border-bottom: 2px solid #b5c9bd;"
        elif name == "Paper":
            source = "background: transparent; border: none;"
        elif name in ("Instrument", "Console"):
            source = ("background: rgba(170,211,115,0.24); border: none;"
                      if name == "Console" else "background: #343c3b; border: 1px solid #67766e; border-radius: 2px;")
        elif name == "Deck":
            source = "background: rgba(118,163,245,0.26); border: 1px solid rgba(163,197,255,0.25); border-radius: 10px;"
        else:
            source = "background: #2b2e2f; border: none; border-radius: 8px;"
        set_widget_style(self.indicator, source)

    def apply_design(self):
        self._update_indicator_style()
        self._update_buttons_style()

    def clear_selection(self):
        self._anim.stop()
        self._current_index = -1
        self.indicator.hide()
        self._update_buttons_style()

    def _update_buttons_style(self):
        name = current_layout()
        for i, btn in enumerate(self.buttons):
            is_active = (i == self._current_index)
            color = "#ffffff" if is_active else "rgba(255, 255, 255, 0.65)"
            font_weight = "600" if is_active else "500"
            btn.setFixedHeight(34 if name == "Deck" else 28)
            label = btn.property("tabLabel")
            btn.setText(label.upper() if name == "Console" else label)
            btn.setIcon(self._tab_icon(label, is_light_theme()) if name == "Deck" else QIcon())
            btn.setIconSize(QSize(15, 15))
            family = {"Daily": "Georgia", "Console": "Consolas"}.get(name, "Segoe UI")
            set_widget_style(btn, f"""
                QPushButton {{
                    background-color: transparent;
                    border: none;
                    border-radius: 11px;
                    color: {color};
                    font-family: '{family}';
                    font-size: 12px;
                    font-weight: {font_weight};
                    padding: 3px {6 if name == "Deck" else 9}px;
                }}
                QPushButton:hover {{
                    color: #ffffff;
                }}
                QPushButton:focus {{ border: 1px solid rgba(190,211,242,0.65); }}
            """)

    @staticmethod
    @lru_cache(maxsize=20)
    def _tab_icon(name, light):
        pixmap = QPixmap(30, 30)
        pixmap.setDevicePixelRatio(2)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        font = QFont(get_fluent_font_family())
        font.setPixelSize(13)
        painter.setFont(font)
        painter.setPen(QColor("#354e7a" if light else "#c1d5fa"))
        painter.drawText(QRect(0, 0, 15, 15), Qt.AlignmentFlag.AlignCenter, getattr(Icons, name.upper(), ""))
        painter.end()
        return QIcon(pixmap)

    def set_current_index(self, index: int, animate: bool = True, emit_signal: bool = True):
        if not (0 <= index < len(self.buttons)):
            return
        old_idx = self._current_index
        self._current_index = index
        self._update_buttons_style()

        target_btn = self.buttons[index]
        target_geom = target_btn.geometry()

        self.indicator.show()
        if animate and old_idx != index and self.isVisible() and 0 <= old_idx < len(self.buttons):
            self._anim.stop()
            self._anim.setDuration(150)
            self._anim.setKeyValues([(0.0, self.indicator.geometry()), (1.0, target_geom)])
            self._anim.start()
        else:
            self._anim.stop()
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


# React Bits RubberSegment Component Alias
RubberSegment = AnimatedTabStrip


class AnimatedStackedWidget(QStackedWidget):
    """
    Fluid, artifact-free stacked container for tabs.
    Directly switches indices to prevent DWM alpha-channel punch-through glitches
    where desktop / code behind the translucent window becomes visible during transitions.
    """
    def __init__(self, parent=None):
        super().__init__(parent)

    def minimumSizeHint(self):
        # Hidden utility pages must not force the compact panel to their own minimum size.
        return QSize(0, 0)

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
            set_widget_style(self, f"""
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
            set_widget_style(self, """
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
            set_widget_style(self, f"""
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
            set_widget_style(self, """
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
    """Shared surface following the selected layout theme."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("cardFrame")
        self.apply_layout(current_layout())

    def apply_layout(self, name, *, outline=True):
        spec = LAYOUT_THEMES.get(name, LAYOUT_THEMES["Classic"])
        self.setProperty("layoutTheme", name)
        border = "1px solid rgba(255,255,255,0.08)" if outline and name != "Minimal" else "none"
        if name == "Flat":
            border = "none; border-top: 1px solid rgba(255,255,255,0.13)"
        elif name == "Paper":
            border = "none"
        elif name == "Daily":
            border = "none; border-top: 1px solid rgba(236,222,194,0.25)"
        elif name in ("Instrument", "Console"):
            border = "1px solid rgba(255,255,255,0.16)"
        elif name == "Deck":
            border = "1px solid rgba(172,199,247,0.22)"
        set_widget_style(self, f"CardFrame#cardFrame {{ background: rgba(255,255,255,{spec['fill']}); border: {border}; border-radius: {spec['radius']}px; }} CardFrame QLabel {{ background: transparent; border: none; }}")


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
        pen_track = QPen(QColor(0, 0, 0, 22) if is_light_theme() else self._track_color, self.track_width)
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


class PillLevel(QWidget):
    """Transient level feedback drawn inside the existing pill."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._value = 0.0
        self._icon = Icons.VOLUME
        self._label = "0%"
        self._ink = QColor("white")
        self._motion = QVariantAnimation(self)
        self._motion.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._motion.valueChanged.connect(self._set_fill)

    def show_level(self, name, icon, previous, value, duration, *, muted=False):
        start = self._value if self.isVisible() and self.accessibleName() == name else previous
        self._motion.stop()
        self._icon = icon
        self._label = "Muted" if muted else f"{value}%"
        self.setAccessibleName(name)
        self.setAccessibleDescription(self._label)
        target = 0 if muted else value
        if duration and start != target:
            self._motion.setDuration(duration)
            self._motion.setStartValue(float(start))
            self._motion.setEndValue(float(target))
            self._motion.start()
        else:
            self._set_fill(float(target))
        self.update()

    def set_ink(self, ink):
        self._ink = QColor(ink)
        self.update()

    def _set_fill(self, value):
        self._value = value
        self.update()

    def hideEvent(self, event):
        self._motion.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        inset = min(18, self.width() // 10)
        height = self.height()
        font = QFont(get_fluent_font_family())
        font.setPixelSize(min(15, max(9, height - 8)))
        painter.setFont(font)
        painter.setPen(self._ink)
        painter.drawText(QRect(inset, 0, 18, height), Qt.AlignmentFlag.AlignCenter, self._icon)

        font = QFont("Segoe UI")
        font.setPixelSize(min(12, max(9, height - 8)))
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        text_width = max(painter.fontMetrics().horizontalAdvance(text) for text in ("100%", "Muted"))
        text_left = self.width() - inset - text_width
        painter.drawText(QRect(text_left, 0, text_width, height), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._label)

        left = inset + 26
        width = max(0, text_left - 10 - left)
        track = QRectF(left, (height - 4) / 2, width, 4)
        painter.setPen(Qt.PenStyle.NoPen)
        rail = QColor(self._ink)
        rail.setAlphaF(0.22)
        painter.setBrush(rail)
        painter.drawRoundedRect(track, 2, 2)
        if self._value > 0 and width:
            track.setWidth(width * self._value / 100)
            painter.setBrush(self._ink)
            painter.drawRoundedRect(track, min(2, track.width() / 2), 2)


class AudioVisualizerBars(QWidget):
    """Four compact bars driven by Windows Core Audio peak levels."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(18, 14)
        self._is_playing = False
        self._muted = False
        self._heights = [2.5, 2.5, 2.5, 2.5]
        self._ink = None
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

    def set_muted(self, muted):
        self._muted = muted

    def _animate_bars(self):
        # If widget is not visible on screen, suspend animation updates to save CPU
        if not self.isVisible():
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
        if self._meter and not self._muted:
            try:
                master, left, right = self._meter.get_peaks()
            except Exception:
                pass

        for i, peak in enumerate((left, master, master, right)):
            energy = max(0.0, min(1.0, peak)) ** 0.45 if peak > 0.001 else 0.0
            tgt = 2.5 + 10.5 * energy
            # Fast attack (0.45) for rhythmic snap, gentle decay (0.22) for analog fluidity
            rate = 0.45 if tgt > self._heights[i] else 0.22
            self._heights[i] += (tgt - self._heights[i]) * rate

        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if self._is_playing:
            self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def set_ink(self, color):
        self._ink = color
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(241, 245, 249, 235) if self._is_playing else QColor(148, 163, 184, 80)
        if is_light_theme():
            color = QColor(32, 40, 51, 235 if self._is_playing else 120)
        if self._ink is not None:
            color = QColor(self._ink)
            color.setAlpha(210 if self._is_playing else 105)
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
        self._default_style = """
            QLabel {
                background: transparent;
                border: none;
                color: #a7adab;
                font-family: 'Segoe UI';
                font-size: 11px;
                padding: 3px 2px;
            }
        """
        self.apply_design(current_layout())

    def apply_design(self, name):
        if name in ("Flat", "Paper", "Instrument"):
            family = "Consolas" if name == "Instrument" else "Segoe UI"
            set_widget_style(self, f"QLabel {{ background: transparent; border: none; color: #a6b5b0; font-family: '{family}'; font-size: 10px; padding: 2px 5px 9px 5px; }}")
        else:
            set_widget_style(self, self._default_style)
        self.update()

    def set_val(self, val_str: str):
        self.setText(f"{self.tag} {val_str}")

    def paintEvent(self, event):
        super().paintEvent(event)
        name = current_layout()
        if name not in ("Flat", "Paper", "Instrument"):
            return
        value = self.text().rsplit(" ", 1)[-1]
        try:
            percentage = max(0.0, min(1.0, float(value.rstrip("%")) / 100)) if value.endswith("%") else None
        except ValueError:
            percentage = None
        painter = QPainter(self)
        track = QColor(0, 0, 0, 28) if is_light_theme() else QColor(255, 255, 255, 28)
        fill = QColor("#526c60" if is_light_theme() else "#a3b9ab")
        painter.setPen(Qt.PenStyle.NoPen)
        width = max(1, self.width() - 10)
        for index in range(10 if name == "Instrument" else 1):
            segments = 10 if name == "Instrument" else 1
            rect = QRectF(5 + index * width / segments, self.height() - 5,
                          width / segments - (2 if segments > 1 else 0), 3)
            painter.fillRect(rect, track)
            if percentage is not None:
                if segments == 1:
                    rect.setWidth(rect.width() * percentage)
                    painter.fillRect(rect, fill)
                elif (index + 1) / segments <= percentage:
                    painter.fillRect(rect, fill)


class ScreenTimeHomeWidget(CardFrame):
    """Today's active time and five ranked apps, updated in place."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        heading = QHBoxLayout()
        title = self.title = QLabel("Screen time today")
        set_widget_style(title, "font-size: 14px; font-weight: 500; color: #edf1f0;")
        heading.addWidget(title)
        self.lbl_time = QLabel("0m")
        set_widget_style(self.lbl_time, "font-size: 14px; font-weight: 500; color: #edf1f0;")
        heading.addWidget(self.lbl_time)
        heading.addStretch()
        settings = QPushButton("Settings")
        settings.setAccessibleName("Open Screen Time settings")
        set_widget_style(settings, """
            QPushButton { background: transparent; border: none; color: #b9bfbd; padding: 4px 6px; }
            QPushButton:hover { color: #edf1f0; }
            QPushButton:focus { border: 1px solid #a7adab; }
        """)
        settings.clicked.connect(self.clicked.emit)
        heading.addWidget(settings)
        layout.addLayout(heading)

        self.empty = QLabel("App usage will appear here.")
        set_widget_style(self.empty, "font-size: 12px; color: #a7adab;")
        layout.addWidget(self.empty)
        self.rows = []
        for rank in range(1, 6):
            row = QWidget(self)
            row.setMinimumHeight(20)
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            rank_label = QLabel(str(rank))
            rank_label.setFixedWidth(20)
            name = QLabel()
            name.setTextFormat(Qt.TextFormat.PlainText)
            name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            duration = QLabel()
            for label in (rank_label, duration):
                set_widget_style(label, "font-size: 12px; color: #a7adab;")
            set_widget_style(name, "font-size: 12px; color: #edf1f0;")
            line.addWidget(rank_label)
            line.addWidget(name, 1)
            line.addWidget(duration)
            layout.addWidget(row)
            row.hide()
            self.rows.append((row, name, duration))
        self._row_count = 0

    def update_stats(self, total_sec, top_apps, track_apps=True):
        hours, minutes = divmod(total_sec // 60, 60)
        self.lbl_time.setText(f"{hours}h {minutes:02d}m" if hours else f"{minutes}m")
        apps = top_apps[:5] if track_apps else []
        for index, (row, name, duration) in enumerate(self.rows):
            row.setVisible(index < len(apps))
            if index < len(apps):
                app, _, formatted = apps[index]
                name.setText(app)
                name.setToolTip(app)
                duration.setText(formatted)
        self.empty.setText("App usage will appear here." if track_apps else "Per-app tracking is off.")
        self.empty.setVisible(not apps)
        changed = self._row_count != len(apps)
        self._row_count = len(apps)
        return changed

    def apply_layout(self, name, *, outline=True):
        super().apply_layout(name, outline=outline)
        if hasattr(self, "title"):
            self.title.setText("Screen time" if name == "Console" else "Screen time today")


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
        set_widget_style(self, f"""
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
            set_widget_style(self, f"font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets'; font-size: 14px; color: #64748b; background: rgba(255, 255, 255, 0.05); border-radius: {self.border_radius}px;")
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


class CapsuleSlider(QSlider):
    """
    Thick tactile capsule slider inspired by macOS Control Center & Option 1 Bento.
    Renders as a 30px rounded pill with fluid fill, embedded icon, and clean numeric readout.
    Fully backwards compatible with standard QSlider APIs.
    """
    def __init__(self, icon: str = "", accent: str = "#0a84ff", orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self._icon = icon
        self._accent = accent
        self._is_down = False
        self.setFixedHeight(30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setRange(0, 100)
        self.setValue(50)

    def set_accent(self, accent: str):
        self._accent = accent
        self.update()

    def isSliderDown(self) -> bool:
        return self._is_down

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_down = True
            self._update_val_from_x(event.position().x())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_down:
            self._update_val_from_x(event.position().x())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_down = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        delta = 5 if event.angleDelta().y() > 0 else -5
        self.setValue(max(self.minimum(), min(self.maximum(), self.value() + delta)))
        event.accept()

    def _update_val_from_x(self, x: float):
        w = max(1.0, float(self.width()))
        if current_layout() in TRACK_LAYOUTS:
            x -= 32
            w = max(1.0, w - 80)
        pct = max(0.0, min(1.0, x / w))
        val = int(round(self.minimum() + pct * (self.maximum() - self.minimum())))
        if val != self.value():
            self.setValue(val)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        if current_layout() in TRACK_LAYOUTS:
            self._paint_track_control(painter, w, h)
            return
        r = h / 2.0

        # 1. Background well / track
        track_rect = QRectF(0, 0, w, h)
        painter.setPen(QColor(0, 0, 0, 30) if is_light_theme() else QColor(255, 255, 255, 18))
        painter.setBrush(QBrush(QColor(0, 0, 0, 14) if is_light_theme() else QColor(255, 255, 255, 14)))
        painter.drawRoundedRect(track_rect, r, r)

        # 2. Filled progress chunk
        val_range = max(1, self.maximum() - self.minimum())
        pct = max(0.0, min(1.0, (self.value() - self.minimum()) / float(val_range)))
        fill_w = max(0.0, w * pct) if self.isEnabled() else 0.0

        if fill_w > 0:
            fill_rect = QRectF(0, 0, fill_w, h)
            path = QPainterPath()
            path.addRoundedRect(track_rect, r, r)
            painter.save()
            painter.setClipPath(path)

            fill_color = QColor(self._accent)
            fill_color.setAlpha(200)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(fill_color))
            painter.drawRect(fill_rect)
            painter.restore()

        # 3. Icon on the left
        if self._icon:
            font = QFont(get_fluent_font_family(), 11)
            painter.setFont(font)
            painter.setPen(QColor("#ffffff"))
            if (pct >= 0.1 and QColor(self._accent).lightness() > 145) or (is_light_theme() and pct < 0.1):
                painter.setPen(QColor("#202833"))
            icon_rect = QRectF(10, 0, 24, h)
            painter.drawText(icon_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._icon)

        # 4. Percentage text on the right
        val_str = f"{self.value()}%" if self.isEnabled() else "N/A"
        font_val = QFont("Segoe UI", 9, QFont.Weight.Bold)
        painter.setFont(font_val)
        painter.setPen(QColor(241, 245, 249, 210))
        if (pct >= 0.9 and QColor(self._accent).lightness() > 145) or (is_light_theme() and pct < 0.9):
            painter.setPen(QColor("#202833"))
        txt_rect = QRectF(w - 44, 0, 36, h)
        painter.drawText(txt_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, val_str)
        if self.hasFocus():
            painter.setPen(QColor("#526c60" if is_light_theme() else "#b7c5bc"))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(track_rect.adjusted(0.5, 0.5, -0.5, -0.5), r, r)

    def _paint_track_control(self, painter, w, h):
        name = current_layout()
        foreground = QColor("#28362f" if is_light_theme() else "#e1e9e5")
        accent = QColor(self._accent)
        if is_light_theme() and accent.lightness() > 145:
            accent = accent.darker(175)
        track = QColor(0, 0, 0, 35) if is_light_theme() else QColor(255, 255, 255, 35)
        left, width = 32.0, max(1.0, w - 80)
        pct = (self.value() - self.minimum()) / max(1, self.maximum() - self.minimum()) if self.isEnabled() else 0
        painter.setPen(Qt.PenStyle.NoPen)
        if name in ("Instrument", "Console"):
            count = max(1, int(width / 10))
            for index in range(count):
                painter.fillRect(QRectF(left + index * width / count, h / 2 - 5, width / count - 2, 10),
                                 accent if (index + 1) / count <= pct else track)
        else:
            thickness = 2 if name in ("Paper", "Daily") else 4 if name == "Deck" else 3
            painter.fillRect(QRectF(left, h / 2, width, thickness), track)
            painter.fillRect(QRectF(left, h / 2, width * pct, thickness), accent)
        if name == "Deck":
            painter.setBrush(foreground)
            painter.drawEllipse(QRectF(left + width * pct - 5, h / 2 - 3, 10, 10))
        else:
            painter.fillRect(QRectF(left + width * pct - 1, h / 2 - 7, 2, 14), foreground)
        painter.setPen(foreground)
        painter.setFont(QFont(get_fluent_font_family(), 10))
        painter.drawText(QRectF(5, 0, 24, h), Qt.AlignmentFlag.AlignVCenter, self._icon)
        painter.setFont(QFont("Consolas" if name in ("Instrument", "Console") else "Segoe UI", 9))
        value = f"{self.value()}%" if self.isEnabled() else "N/A"
        painter.drawText(QRectF(w - 45, 0, 40, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, value)
        if self.hasFocus():
            painter.setPen(QPen(accent, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(1, 1, w - 2, h - 2))


class ClickableSlider(QSlider):
    """Native thumb dragging and track jumps, with committed keyboard/wheel seeks."""
    seek_clicked = Signal(int)

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._track_drag = False

    def _value_at(self, point):
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        style = self.style()
        groove = style.subControlRect(QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderGroove, self)
        handle = style.subControlRect(QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self)
        if self.orientation() == Qt.Orientation.Vertical:
            span = groove.height() - handle.height()
            position = point.y() - groove.y() - handle.height() / 2
        else:
            span = groove.width() - handle.width()
            position = point.x() - groove.x() - handle.width() / 2
        return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), round(position), max(1, span), option.upsideDown)

    def _move_to(self, point):
        self.setValue(self._value_at(point))
        self.sliderMoved.emit(self.value())

    def mousePressEvent(self, event):
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        handle = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self)
        if event.button() == Qt.MouseButton.LeftButton and not handle.contains(event.position().toPoint()):
            self._track_drag = True
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.setSliderDown(True)
            self._move_to(event.position())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._track_drag:
            self._move_to(event.position())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._track_drag and event.button() == Qt.MouseButton.LeftButton:
            self._move_to(event.position())
            self._track_drag = False
            self.setSliderDown(False)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        before = self.value()
        super().keyPressEvent(event)
        if self.value() != before and not self.isSliderDown():
            self.seek_clicked.emit(self.value())

    def wheelEvent(self, event):
        before = self.value()
        super().wheelEvent(event)
        if self.value() != before and not self.isSliderDown():
            self.seek_clicked.emit(self.value())


class PlaybackSlider(ClickableSlider):
    """A time ruler in Console with the same native slider interaction."""

    def paintEvent(self, event):
        if current_layout() != "Console":
            super().paintEvent(event)
            return
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        style = self.style()
        groove = style.subControlRect(QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderGroove, self)
        handle = style.subControlRect(QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self)
        start = groove.x() + handle.width() / 2
        span = max(1, groove.width() - handle.width())
        pct = (self.value() - self.minimum()) / max(1, self.maximum() - self.minimum())
        colors = surface_colors()
        painter = QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        muted = QColor(colors["muted"])
        muted.setAlphaF(0.45)
        count = max(2, int(span // 7))
        for tick in range(count + 1):
            fraction = tick / count
            height = 11 if tick % 5 == 0 else 5
            x = start + span * (1 - fraction if option.upsideDown else fraction)
            painter.fillRect(QRectF(x - 1, (self.height() - height) / 2, 2, height),
                             QColor(colors["accent"]) if fraction <= pct and self.isEnabled() else muted)
        if self.hasFocus():
            painter.setPen(QColor(colors["accent"]))
            painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.end()


class LyricLineWidget(QFrame):
    """Clean, high-craft lyric row matching native Spotify desktop typography."""
    clicked = Signal(float)

    def __init__(self, time_sec: float, text: str, parent=None):
        super().__init__(parent)
        self.time_sec = time_sec
        self._raw_text = text
        self._design = current_layout()
        self._is_active = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(text)

        self._lbl = QLabel(text, self)
        self._lbl.setTextFormat(Qt.TextFormat.PlainText)
        self._lbl.setWordWrap(True)
        self._lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        # Explicit fonts ensure QLabel font metrics, sizeHint and heightForWidth are 100% accurate
        self._font_active = QFont("Segoe UI", 18)
        self._font_active.setWeight(QFont.Weight.ExtraBold)
        self._font_inactive = QFont("Segoe UI", 15)
        self._font_inactive.setWeight(QFont.Weight.DemiBold)
        self._lbl.setFont(self._font_inactive)

        sp = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)
        self.setMinimumHeight(44)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(0)
        layout.addWidget(self._lbl)

        self.apply_design(self._design)

    def apply_design(self, name):
        self._design = name
        seconds = max(0, int(self.time_sec))
        self._lbl.setText(f"{seconds // 60:02d}:{seconds % 60:02d}   {self._raw_text}" if name == "Console" else self._raw_text)
        self.update_style()
        self.updateGeometry()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        inner_w = max(10, width - 28)
        h = self._lbl.heightForWidth(inner_w)
        if h <= 0:
            h = self._lbl.sizeHint().height()
        return max(56 if self._is_active else 44, h + 18)

    def sizeHint(self) -> QSize:
        sh = self._lbl.sizeHint()
        return QSize(sh.width() + 28, max(56 if self._is_active else 44, sh.height() + 18))

    def minimumSizeHint(self) -> QSize:
        return QSize(50, 56 if self._is_active else 44)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.time_sec)
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if not event.isAutoRepeat():
                self.clicked.emit(self.time_sec)
            event.accept()
            return
        super().keyPressEvent(event)

    def set_active(self, active: bool):
        if self._is_active != active:
            self._is_active = active
            self.setMinimumHeight(56 if active else 44)
            self._lbl.setFont(self._font_active if active else self._font_inactive)
            self.updateGeometry()
            self.update_style()

    def update_style(self):
        focus = "QFrame:focus { border: 1px solid rgba(255,255,255,0.65); }"
        if self._design in ("Deck", "Daily", "Console"):
            name = self._design
            family, size = {"Deck": ("Segoe UI", 15), "Daily": ("Georgia", 18), "Console": ("Consolas", 13)}[name]
            color = "#edf1f0" if self._is_active else "#a7adab"
            weight = 800 if self._is_active else 700
            set_widget_style(self._lbl, f"QLabel {{ font-family: '{family}'; font-size: {size}px; font-weight: {weight}; color: {color}; background: transparent; }}")
            border = "border-left: 2px solid #b87557;" if name == "Daily" and self._is_active else ""
            fill = "rgba(171,206,153,0.12)" if self._is_active and name != "Daily" else "transparent"
            set_widget_style(self, f"QFrame {{ background: {fill}; border: 1px solid transparent; {border} }} QFrame:hover {{ background: rgba(255,255,255,0.06); }} {focus}")
            return
        set_widget_style(self, """
            QFrame {
                background: transparent;
                border: 1px solid transparent;
                border-radius: 8px;
            }
            QFrame:hover {
                background: rgba(255, 255, 255, 0.04);
            }
        """ + focus)
        if self._is_active:
            set_widget_style(self._lbl, """
                QLabel {
                    color: #ffffff;
                    font-size: 18px;
                    font-weight: 800;
                    background: transparent;
                    border: none;
                }
            """)
        else:
            set_widget_style(self._lbl, """
                QLabel {
                    color: rgba(255, 255, 255, 0.68);
                    font-size: 15px;
                    font-weight: 700;
                    background: transparent;
                    border: none;
                }
            """)

    def enterEvent(self, event):
        super().enterEvent(event)
        if not self._is_active and self._design not in ("Deck", "Daily", "Console"):
            set_widget_style(self._lbl, """
                QLabel {
                    color: rgba(255, 255, 255, 0.85);
                    font-size: 15px;
                    font-weight: 700;
                    background: transparent;
                    border: none;
                }
            """)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if not self._is_active:
            self.update_style()


class SpotifyLyricsWidget(QFrame):
    """
    Clean, modern synchronized lyrics panel.
    Seamlessly integrated with Poppy's design system.
    Smoothly tracks song playback with animated vertical auto-scrolling to center the active line.
    Allows clicking any line to jump to that timestamp.
    """
    seek_requested = Signal(float)

    def apply_design(self, name):
        background = "rgba(162,191,240,0.09)" if name == "Deck" else "transparent"
        border = ("border-left: 1px solid rgba(200,183,156,0.32);" if name == "Daily"
                  else "border-top: 1px solid rgba(170,192,158,0.24);" if name == "Console" else "")
        set_widget_style(self, f"QFrame#lyricsWidgetFrame {{ background: {background}; border: none; {border} border-radius: 14px; }}")
        margins = (14, 8, 12, 8) if name in ("Deck", "Daily", "Console") else (6, 2, 6, 6)
        self.layout().setContentsMargins(*margins)
        for line in self._line_buttons:
            line.apply_design(name)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("lyricsWidgetFrame")
        set_widget_style(self, """
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
        set_widget_style(lbl_hdr, "QLabel { font-family: 'Segoe UI'; font-size: 11px; font-weight: 600; color: #94a3b8; background: transparent; border: none; }")

        hdr_row.addWidget(lbl_hdr)
        hdr_row.addStretch()
        layout.addLayout(hdr_row)

        # Content stack: Page 0 = Lyrics Scroll Area, Page 1 = Placeholder / Status
        self.content_stack = QStackedWidget(self)
        set_widget_style(self.content_stack, "background: transparent; border: none;")

        # Page 0: Scroll Area for Lyrics
        self.scroll_area = ScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.viewport().setAutoFillBackground(False)
        self.scroll_area.viewport().setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.scroll_area.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        set_widget_style(self.scroll_area, """
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
        set_widget_style(self.lines_container, "background: transparent; border: none;")
        self.lines_layout = QVBoxLayout(self.lines_container)
        self.lines_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.lines_layout.setContentsMargins(0, 4, 0, 8)
        self.lines_layout.setSpacing(2)
        self.scroll_area.setWidget(self.lines_container)
        self.content_stack.addWidget(self.scroll_area)

        # Page 1: Centered Status / Placeholder
        placeholder_wrap = QWidget()
        set_widget_style(placeholder_wrap, "background: transparent; border: none;")
        p_layout = QVBoxLayout(placeholder_wrap)
        p_layout.setContentsMargins(12, 24, 12, 24)
        p_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_status = QLabel("Play music to view lyrics", placeholder_wrap)
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setWordWrap(True)
        set_widget_style(self.lbl_status, "QLabel { font-family: 'Segoe UI'; font-size: 12px; font-weight: 400; color: #a7b2bf; background: transparent; border: none; }")
        p_layout.addWidget(self.lbl_status)
        self.content_stack.addWidget(placeholder_wrap)

        layout.addWidget(self.content_stack, stretch=1)

        # Smooth Scroll Animation
        self._scroll_anim = QPropertyAnimation(self.scroll_area.verticalScrollBar(), b"value")
        self._scroll_anim.setDuration(240)
        self._scroll_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._synced_lines: list[tuple[float, str]] = []
        self._line_buttons: list[LyricLineWidget] = []
        self._lyric_tab_stop = None
        self._keyboard_reading = False
        self._current_line_idx = -1
        self._user_scrolling = False
        self._auto_scroll_enabled = True
        self._layout_scroll_timer = QTimer(self)
        self._layout_scroll_timer.setSingleShot(True)
        self._layout_scroll_timer.timeout.connect(self._scroll_current_line)

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
        elif isinstance(obj, LyricLineWidget):
            if event.type() == QEvent.Type.FocusIn:
                self._set_lyric_tab_stop(obj)
                self._keyboard_reading = event.reason() != Qt.FocusReason.MouseFocusReason
                if self._keyboard_reading:
                    self._scroll_anim.stop()
                    self.scroll_area.ensureWidgetVisible(obj, 0, 12)
            elif event.type() == QEvent.Type.FocusOut:
                if self._keyboard_reading:
                    self._on_user_scroll()
                self._keyboard_reading = False
            elif event.type() == QEvent.Type.MouseButtonPress:
                self._keyboard_reading = False
            elif event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                offset = -1 if event.key() == Qt.Key.Key_Up else 1
                index = self._line_buttons.index(obj) + offset
                if 0 <= index < len(self._line_buttons):
                    self._line_buttons[index].setFocus(Qt.FocusReason.OtherFocusReason)
                return True
        return super().eventFilter(obj, event)

    def _set_lyric_tab_stop(self, row):
        if self._lyric_tab_stop is row:
            return
        if self._lyric_tab_stop is not None:
            self._lyric_tab_stop.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        row.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        QWidget.setTabOrder(self.scroll_area, row)
        self._lyric_tab_stop = row

    def set_playback_state(self, is_playing: bool):
        pass

    def showEvent(self, event):
        super().showEvent(event)
        self._layout_scroll_timer.start(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_layout_scroll_timer"):
            self._layout_scroll_timer.start(0)

    def _on_user_scroll(self):
        self._scroll_anim.stop()
        self._user_scrolling = True
        self._resume_timer.start()

    def set_auto_scroll_enabled(self, enabled):
        self._auto_scroll_enabled = bool(enabled)
        if not enabled:
            self._scroll_anim.stop()
            self._resume_timer.stop()
        else:
            self._resume_auto_scroll()

    def _resume_auto_scroll(self):
        self._user_scrolling = False
        self._scroll_current_line()

    def _scroll_current_line(self):
        if not self._user_scrolling and 0 <= self._current_line_idx < len(self._line_buttons):
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
        self._synced_lines = list(synced_lines)
        self._current_line_idx = -1

        self.lines_layout.addSpacing(60)
        for time_sec, text in synced_lines:
            btn = LyricLineWidget(time_sec, text, self.lines_container)
            btn.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
            btn.installEventFilter(self)
            btn.clicked.connect(lambda *args, t=time_sec: self.seek_requested.emit(t))
            self.lines_layout.addWidget(btn)
            self._line_buttons.append(btn)
        if self._line_buttons:
            self.scroll_area.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._set_lyric_tab_stop(self._line_buttons[0])

        self.lines_layout.addSpacing(100)
        self.lines_layout.addStretch()
        self._layout_scroll_timer.start(0)

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
            set_widget_style(lbl, """
                QLabel {
                    font-family: 'Segoe UI';
                    font-size: 14px;
                    font-weight: 500;
                    color: rgba(255, 255, 255, 0.65);
                    background: transparent;
                    border: none;
                    padding: 5px 4px;
                }
            """)
            lbl.setTextFormat(Qt.TextFormat.PlainText)
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
                active = self._line_buttons[active_idx]
                active.set_active(True)
                if not self._keyboard_reading:
                    self._set_lyric_tab_stop(active)
                if not self._user_scrolling:
                    self._scroll_to_line(active_idx)

    def _scroll_to_line(self, idx: int):
        if not self._auto_scroll_enabled or not self.isVisible() or self._keyboard_reading:
            return
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
        self._layout_scroll_timer.stop()
        self._scroll_anim.stop()
        self._synced_lines = []
        self._lyric_tab_stop = None
        self._keyboard_reading = False
        self.scroll_area.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        for row in self._line_buttons:
            row.removeEventFilter(self)
        self._line_buttons.clear()
        self._current_line_idx = -1
        while self.lines_layout.count() > 0:
            item = self.lines_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()



