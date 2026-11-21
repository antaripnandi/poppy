"""On-demand dictation indicator and the Windows recording lifecycle."""

import json
import logging
import math
import time
from pywintypes import error as WindowsError

from PySide6.QtCore import QEasingCurve, QLineF, QObject, QPoint, QPointF, QRectF, Qt, QTimer, Signal, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRegion, QTextCursor
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QLineEdit, QMenu, QPlainTextEdit, QTextEdit, QVBoxLayout, QWidget

from poppy.core import dictation_windows as native
from poppy.core.dictation_api import DictationApi, REVIEW_TRANSCRIPT, SPEECH_LANGUAGES, needs_language_check, read_keys
from poppy.core.dictation_live import GeminiLiveDictation
from poppy.core.storage import data_path, write_json
from poppy.core.system_controls import system_animations_enabled
from poppy.ui.drawer_tools import DrawerToolButton
from poppy.ui.theme import surface_colors


_LOG = logging.getLogger(__name__)


class _TranscriptStrip(QLabel):
    """A visual tail of the caption, independent of the text ultimately delivered."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAccessibleName("Live transcript preview")
        font = QFont("Segoe UI")
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.DemiBold)
        self.setFont(font)
        self.fade = 0.0
        self._offset = 0.0
        self._target_x = 0.0
        self._leaving = ""
        self._leaving_x = 0.0
        self._motion = QVariantAnimation(self, duration=240)
        self._motion.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._motion.valueChanged.connect(self._move_words)

    def _move_words(self, offset):
        self._offset = offset
        self.update()

    def set_caption(self, text):
        metrics = self.fontMetrics()
        words = text.rsplit(None, 6)[-6:]
        width = max(1, self.width() - 30)
        while len(words) > 1 and metrics.horizontalAdvance(" ".join(words)) > width:
            words.pop(0)
        line = metrics.elidedText(" ".join(words), Qt.TextElideMode.ElideLeft, width)
        if line == self.text():
            return
        previous = self.text().split()
        current = line.split()
        old_x = self._target_x + self._offset
        self._motion.stop()
        self.setText(line)
        self._target_x = (self.width() - metrics.horizontalAdvance(line)) / 2
        self._offset = 0.0
        self._leaving = ""
        if previous and current and system_animations_enabled():
            shared = next((n for n in range(min(len(previous), len(current)), 0, -1)
                           if previous[-n:] == current[:n]), 0)
            if shared:
                self._leaving = " ".join(previous[:-shared])
                prefix = self._leaving + " " if self._leaving else ""
                self._offset = old_x + metrics.horizontalAdvance(prefix) - self._target_x
                self._leaving_x = old_x - self._offset
            else:
                self._offset = 5.0
            if abs(self._offset) > 0.5:
                self._motion.setStartValue(self._offset)
                self._motion.setEndValue(0.0)
                self._motion.start()
        self.update()

    def paintEvent(self, event):
        if not self.text() or self.fade <= 0:
            return
        colors = surface_colors()
        painter = QPainter(self)
        painter.setOpacity(self.fade)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colors["card"]))
        painter.drawRoundedRect(QRectF(self.rect()), 10, 10)

        # Fade the two edges and spread the glyphs by a pixel in those bands.
        ratio = self.devicePixelRatioF()
        layer = QPixmap(round(self.width() * ratio), round(self.height() * ratio))
        layer.setDevicePixelRatio(ratio)
        layer.fill(Qt.GlobalColor.transparent)
        text_painter = QPainter(layer)
        text_painter.setFont(self.font())
        text_painter.setPen(QColor(colors["text"]))
        metrics = self.fontMetrics()
        baseline = (self.height() + metrics.ascent() - metrics.descent()) / 2
        edge = 15
        regions = (
            (QRectF(edge, 0, self.width() - 2 * edge, self.height()), (0,)),
            (QRectF(0, 0, edge, self.height()), (-1, 0, 1)),
            (QRectF(self.width() - edge, 0, edge, self.height()), (-1, 0, 1)),
        )
        for clip, shifts in regions:
            text_painter.save()
            text_painter.setClipRect(clip)
            for shift in shifts:
                text_painter.setOpacity(1.0 if len(shifts) == 1 else 0.38)
                text_painter.drawText(QPointF(self._target_x + self._offset + shift, baseline), self.text())
                if self._leaving and self._motion.state() == self._motion.State.Running:
                    text_painter.save()
                    text_painter.setOpacity(text_painter.opacity() * abs(self._offset / self._motion.startValue()))
                    text_painter.drawText(QPointF(self._leaving_x + self._offset + shift, baseline), self._leaving)
                    text_painter.restore()
            text_painter.restore()
        mask = QLinearGradient(0, 0, self.width(), 0)
        mask.setColorAt(0.0, Qt.GlobalColor.transparent)
        mask.setColorAt(edge / self.width(), Qt.GlobalColor.white)
        mask.setColorAt(1 - edge / self.width(), Qt.GlobalColor.white)
        mask.setColorAt(1.0, Qt.GlobalColor.transparent)
        text_painter.setOpacity(1)
        text_painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        text_painter.fillRect(self.rect(), mask)
        text_painter.end()
        painter.drawPixmap(0, 0, layer)


class DictationIndicator(QWidget):
    clicked = Signal()
    copy_requested = Signal()
    retry_requested = Signal()
    dismissed = Signal()
    drag_started = Signal()
    moved = Signal()
    reset_position = Signal()

    _PROCESSING = ("Transcribing", "Checking languages", "Checking transcript", "Cleaning up")
    _COMPACT = ("Ready to dictate", "Listening", "Text sent", "Copied to clipboard", *_PROCESSING)
    _SIDE_ICON_OFFSET = 37

    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAccessibleName("Poppy voice typing")
        self._wordmark_font = QFont("Segoe UI")
        self._wordmark_font.setPixelSize(13)
        self._wordmark_font.setWeight(QFont.Weight.DemiBold)
        self.header = QWidget(self)
        self.title = QLabel(self.header)
        self.detail = QLabel(self.header)
        for label in (self.title, self.detail):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        labels = QVBoxLayout()
        labels.setSpacing(0)
        labels.addWidget(self.title)
        labels.addWidget(self.detail)
        self.action = DrawerToolButton("stop", "Finish dictation")
        self.action.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.action.clicked.connect(self._activate)
        self.retry = DrawerToolButton("retry", "Retry transcription")
        self.retry.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.retry.clicked.connect(self.retry_requested)
        self.dismiss_button = DrawerToolButton("close", "Dismiss voice typing")
        self.dismiss_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.dismiss_button.clicked.connect(self.dismissed)
        self.row = QHBoxLayout(self.header)
        self.row.setSpacing(2)
        self.row.addLayout(labels, 1)
        for button in (self.action, self.retry, self.dismiss_button):
            self.row.addWidget(button)
        self.preview = _TranscriptStrip(self)
        # Give the strip a stable text width before the first caption arrives.
        self.preview.resize(276, 34)
        self.preview.hide()
        self.levels = [0.0] * 5
        self._press = None
        self._dragging = False
        self._anchor = None
        self._preview_text = ""
        self._feedback = ""
        self._hint = ""
        self._status_title = ""
        self._caption_open = False
        self.listening = False
        self._ready = False
        self._copy_ready = False
        self._done = False
        self._check_amount = 1.0
        self._caption_fade = QVariantAnimation(self, duration=180)
        self._caption_fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._caption_fade.valueChanged.connect(self._set_caption_fade)
        self._caption_fade.finished.connect(self._settle_caption)
        self._check = QVariantAnimation(self, duration=200, startValue=0.0, endValue=1.0)
        self._check.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._check.valueChanged.connect(self._set_check)
        self.set_status("Ready to dictate", "Click to start  ·  Drag to move")

    def _activate(self):
        if self._copy_ready:
            self.copy_requested.emit()
        else:
            self.clicked.emit()

    def _set_check(self, value):
        self._check_amount = value
        self.update()

    def _set_caption_fade(self, value):
        self.preview.fade = value
        self.preview.move((self.width() - self.preview.width()) // 2, 4 + round(4 * (1 - value)))
        self.preview.update()

    def _settle_caption(self):
        if not self._caption_open:
            self.preview.hide()
            self._layout_pill()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.globalPosition().toPoint(), self.pos()
            self._dragging = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press is None or not event.buttons() & Qt.MouseButton.LeftButton:
            return super().mouseMoveEvent(event)
        origin, position = self._press
        delta = event.globalPosition().toPoint() - origin
        if self._dragging or delta.manhattanLength() >= QApplication.startDragDistance():
            if not self._dragging:
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.drag_started.emit()
            self._dragging = True
            screen = QGuiApplication.screenAt(event.globalPosition().toPoint()) or self.screen()
            self.place(position + delta, screen)
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self._press is None:
            return super().mouseReleaseEvent(event)
        self._press = None
        if self._dragging:
            self._dragging = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.moved.emit()
        elif (self._ready or self.listening) and self.header.geometry().contains(event.position().toPoint()):
            self.clicked.emit()
        event.accept()

    def contextMenuEvent(self, event):
        if not (self._ready or self.listening):
            return
        menu = QMenu(self)
        if self._ready:
            menu.addAction("Reset pill position", self.reset_position)
        menu.addAction("Cancel recording" if self.listening else "Hide Poppy", self.dismissed)
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(event.globalPos())

    def hideEvent(self, event):
        self._caption_fade.stop()
        self._caption_open = False
        self.preview.fade = 0.0
        self.preview.hide()
        self._check.stop()
        self._check_amount = 1.0
        self._press = None
        self._dragging = False
        super().hideEvent(event)

    def place(self, point, screen, *, set_anchor=True):
        bounds = screen.availableGeometry()
        x = max(bounds.left(), min(point.x(), bounds.right() - self.width() + 1))
        y = max(bounds.top(), min(point.y(), bounds.bottom() - self.height() + 1))
        self.move(x, y)
        if set_anchor:
            self._anchor = QPoint(x + self.width() // 2, y + self.height())

    def _layout_pill(self):
        with_caption = not self.preview.isHidden()
        body_height = 32 if self._compact else 44
        width = max(self._body_width, self.preview.width() if with_caption else 0) + 16
        height = body_height + 16 + (44 if with_caption else 0)
        self.setFixedSize(width, height)
        self.header.setGeometry((width - self._body_width) // 2, height - body_height - 9,
                                self._body_width, body_height)
        self.preview.move((width - self.preview.width()) // 2, 4 + round(4 * (1 - self.preview.fade)))
        if self._anchor is not None and self.isVisible() and not self._dragging:
            screen = QGuiApplication.screenAt(self._anchor - QPoint(0, 1)) or self.screen()
            self.place(self._anchor - QPoint(width // 2, height), screen, set_anchor=False)
        if QApplication.platformName() == "windows":
            mask = QRegion(self.header.geometry().adjusted(-7, -4, 7, 8))
            if with_caption:
                mask |= QRegion(self.preview.geometry().adjusted(-4, -4, 4, 6))
            self.setMask(mask)
        self.update()

    def _sync_caption(self):
        visible = bool(self._preview_text) and (
            self.listening or self._status_title in (*self._PROCESSING, REVIEW_TRANSCRIPT))
        if visible == self._caption_open:
            return
        self._caption_open = visible
        self._caption_fade.stop()
        if visible:
            self.preview.show()
            self._layout_pill()
        target = float(visible)
        if not self.isVisible() or not system_animations_enabled() or self.preview.fade == target:
            self._set_caption_fade(target)
            self._settle_caption()
        else:
            self._caption_fade.setStartValue(self.preview.fade)
            self._caption_fade.setEndValue(target)
            self._caption_fade.start()

    def set_status(self, title, detail, *, offer_copy=False, offer_retry=False):
        was_listening = self.listening
        was_done = self._done
        self._status_title = title
        self._hint = detail
        self.listening = title == "Listening"
        self._feedback = "Checking microphone…" if self.listening else ""
        self._done = title in ("Text sent", "Copied to clipboard")
        self._ready = title == "Ready to dictate"
        self._copy_ready = offer_copy
        self._compact = title in self._COMPACT
        self._body_width = 114 if self._ready or self._done else 124 if self._compact else 300
        colors = surface_colors()
        self.title.setStyleSheet(f"color: {colors['text']}; background: transparent; font: 600 13px 'Segoe UI';")
        self.detail.setStyleSheet(f"color: {colors['muted']}; background: transparent; font: 11px 'Segoe UI';")
        self.title.setText(title)
        self.title.setVisible(not self._compact)
        self.detail.setText(self.detail.fontMetrics().elidedText(detail, Qt.TextElideMode.ElideRight, 200))
        self.detail.setVisible(not self._compact)
        right_padding = self._body_width // 2 - self._SIDE_ICON_OFFSET - 12 if self._compact else 4
        self.row.setContentsMargins(0 if self._compact else 42, 0, right_padding, 0)
        for button in (self.action, self.dismiss_button):
            button.setFixedWidth(24 if self._compact else 28)
        if not self._dragging:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.action.setVisible(self.listening or offer_copy)
        self.retry.setVisible(offer_retry)
        self.dismiss_button.setVisible(not (self._ready or self.listening or self._done))
        dismiss = "Discard recording" if offer_retry else "Dismiss voice typing"
        self.dismiss_button.setToolTip(dismiss)
        self.dismiss_button.setAccessibleName(dismiss)
        glyph, name = ("copy", "Copy dictation") if offer_copy else ("stop", "Finish dictation")
        self.action.set_glyph(glyph)
        self.action.setAccessibleName(name)
        self.action.setToolTip(name)
        if self._done != was_done:
            self._check.stop()
            self._check_amount = 1.0
            if self._done and system_animations_enabled():
                self._check_amount = 0.0
                self._check.start()
        if self.listening and not was_listening:
            self.set_preview("")
            self.levels = [0.0] * 5
        self._update_hint()
        self._sync_caption()
        self._layout_pill()

    def _update_hint(self):
        hint = "\n".join(part for part in (self._status_title, self._hint, self._feedback) if part)
        self.setToolTip(hint)
        self.setAccessibleDescription(hint)

    def set_preview(self, text):
        self._preview_text = text.strip()
        if self._preview_text and self._feedback:
            self._feedback = ""
            self._update_hint()
        self.preview.set_caption(self._preview_text)
        self._sync_caption()

    def set_capture_feedback(self, text):
        if not self._preview_text and self._feedback != text:
            self._feedback = text
            self._update_hint()

    def set_elapsed(self, seconds, *, hold=False, editing=False):
        minutes, seconds = divmod(seconds, 60)
        hint = "Release the keys to finish" if hold else "Speak an edit, then click Stop" if editing else "Click stop to finish"
        self._hint = f"{minutes}:{seconds:02d}  ·  {hint}"
        self._update_hint()

    def set_level(self, level):
        self.levels = [old * 0.38 + new * 0.62 for old, new in zip(self.levels, [*self.levels[1:], level])]
        self.update(self.header.geometry())

    def paintEvent(self, event):
        colors = surface_colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        bounds = QRectF(self.header.geometry())
        radius = bounds.height() / 2
        for spread, opacity in ((5, 7), (4, 9), (3, 11), (2, 15), (1, 19)):
            painter.setBrush(QColor(0, 0, 0, opacity))
            shadow = bounds.adjusted(-spread, 2 - spread, spread, 2 + spread)
            painter.drawRoundedRect(shadow, radius + spread, radius + spread)
        painter.setBrush(QColor(colors["root"]))
        painter.drawRoundedRect(bounds, radius, radius)
        if self._compact:
            # Lower the lowercase wordmark slightly to align it optically with the marks.
            wordmark = "poppy"
            painter.setFont(self._wordmark_font)
            ink = QRectF(painter.fontMetrics().tightBoundingRect(wordmark))
            painter.setPen(QColor(colors["text"]))
            painter.drawText(bounds.center() - ink.center() + QPointF(0, 2), wordmark)
            painter.setPen(Qt.PenStyle.NoPen)
        mark_x = bounds.center().x() - self._SIDE_ICON_OFFSET if self._compact else bounds.left() + 18
        painter.translate(mark_x, bounds.center().y())
        if self._done:
            painter.setPen(QPen(QColor(colors["text"]), 1.6, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            start, elbow, end = QPointF(-6, 0), QPointF(-2, 4), QPointF(6, -4)
            first, second = QLineF(start, elbow), QLineF(elbow, end)
            distance = self._check_amount * (first.length() + second.length())
            path = QPainterPath(start)
            path.lineTo(first.pointAt(min(1.0, distance / first.length())))
            if distance > first.length():
                path.lineTo(second.pointAt((distance - first.length()) / second.length()))
            painter.drawPath(path)
            return
        painter.setBrush(QColor(colors["text"] if self.listening else colors["muted"]))
        if self._status_title in self._PROCESSING:
            for x in (-5, 0, 5):
                painter.drawEllipse(QPointF(x, 0), 1.1, 1.1)
            return
        levels = self.levels if self.listening else (0.10, 0.30, 0.46, 0.30, 0.10)
        for index, level in enumerate(levels):
            height = 3 + level * 14
            painter.drawRoundedRect(QRectF(-8.5 + index * 4, -height / 2, 1.8, height), 0.9, 0.9)


class DictationController(QObject):
    panel_visible = Signal(bool)

    def __init__(self, notch):
        super().__init__(notch)
        self._notch = notch
        self._api = None
        self._live = None
        self._live_credential = None
        self._live_retry_at = 0
        self._language_mode = "auto"
        self._indicator = None
        self._mic = None
        self._keys = {}
        self._config = {}
        self._registered_hwnd = None
        self._extra_shortcuts = set()
        self._target = None
        self._local_target = None
        self._text_scope = None
        self._editing = False
        self._holding = False
        self._pending_insert = ""
        self._live_draft = ""
        self._retry_audio = b""
        self._retry_options = {}
        self._retry_review = False
        self._retry_language_reference = ""
        self._confirmed_text = ""
        self._covered = 0
        self._cut = None
        self._started = None
        self._first_caption = False
        self._capture_interrupted = False
        self._previewing = False
        self._phase = ""
        self._keep_panel = False
        self._stopped_at = None
        self._position_file = data_path("dictation-position.json")
        self._position = None
        try:
            saved = json.loads(self._position_file.read_text(encoding="utf-8"))
            if (isinstance(saved.get("screen"), str)
                    and all(type(saved.get(axis)) in (int, float) and 0 <= saved[axis] <= 1 for axis in ("x", "y"))):
                self._position = saved
        except (OSError, ValueError, AttributeError):
            pass
        QGuiApplication.instance().screenRemoved.connect(self._screen_removed)
        self.last_text = ""
        self.shortcut_status = ""
        self._sample_timer = QTimer(self, interval=40)
        self._sample_timer.timeout.connect(self._read_mic)
        self._hide_timer = QTimer(self, singleShot=True)
        self._hide_timer.timeout.connect(self._expire_status)
        self._paste_timer = QTimer(self, singleShot=True)
        self._paste_timer.timeout.connect(self._deliver)

    def configure(self, config):
        config = config if isinstance(config, dict) else {}
        if config != self._config:
            self.cancel()
            self._live_retry_at = 0
            self._config = config
            mode = config.get("speech_languages")
            self._language_mode = mode if isinstance(mode, str) and mode in SPEECH_LANGUAGES else "auto"
            self._keys = read_keys(config) if config.get("enabled") else {}
            if self._api is not None:
                self._api.set_keys(self._keys)
        enabled = config.get("enabled") and (self._keys.get("groq") or self._keys.get("gemini"))
        if not enabled:
            self._unregister()
        elif self._registered_hwnd is None and QApplication.platformName() == "windows":
            hwnd = int(self._notch.winId())
            if native.register_shortcuts(hwnd):
                self._registered_hwnd = hwnd
        unavailable = []
        if self._registered_hwnd is not None:
            for setting, shortcut, label in (("hold_to_talk", native.HOLD_HOTKEY, "Ctrl+Alt+Space"),
                                             ("voice_editing", native.EDIT_HOTKEY, "Ctrl+Alt+Shift+E")):
                if config.get(setting, True):
                    if shortcut not in self._extra_shortcuts:
                        if native.register_extra_shortcut(self._registered_hwnd, shortcut):
                            self._extra_shortcuts.add(shortcut)
                        else:
                            unavailable.append(label)
                elif shortcut in self._extra_shortcuts:
                    native.unregister_extra_shortcut(self._registered_hwnd, shortcut)
                    self._extra_shortcuts.remove(shortcut)
        self.shortcut_status = (
            "Ctrl+Alt+D is active." if self._registered_hwnd else
            "The shortcut is unavailable. It may be in use by another app." if enabled else
            "Add a Groq or Gemini key to enable voice typing." if config.get("enabled") else
            "Voice typing is off."
        )
        if unavailable:
            self.shortcut_status = f"Shortcut unavailable: {', '.join(unavailable)}."

    def _unregister(self):
        if self._registered_hwnd is not None:
            for shortcut in self._extra_shortcuts:
                native.unregister_extra_shortcut(self._registered_hwnd, shortcut)
            self._extra_shortcuts.clear()
            native.unregister_shortcuts(self._registered_hwnd)
            self._registered_hwnd = None

    def handle_shortcut(self, shortcut):
        if self._registered_hwnd is None:
            return False
        if shortcut == native.HOTKEY:
            self.toggle()
        elif shortcut == native.CANCEL_HOTKEY:
            self.cancel()
        elif shortcut == native.HOLD_HOTKEY and shortcut in self._extra_shortcuts:
            if native.hold_shortcut_down():
                self._start_capture(hold=True)
        elif shortcut == native.EDIT_HOTKEY and shortcut in self._extra_shortcuts:
            if self._mic is not None and self._editing:
                self._stop_recording()
            else:
                self._start_capture(editing=True)
        else:
            return False
        return True

    def toggle(self):
        if self._mic is not None:
            self._stop_recording()
            return
        self._start_capture()

    def _start_capture(self, *, hold=False, editing=False):
        if self._retry_review and self._phase == "processing":
            self.cancel()
        if self._phase or not self.available:
            return
        self.last_text = ""
        self._forget_recording()
        self._live_draft = ""
        focus = native.focused_target()
        self._target = focus[0] if focus else None
        self._local_target = self._local_editor() if not self._target else None
        self._editing = editing
        self._holding = hold
        self._text_scope = None
        if editing or (self._config.get("continuation_context", False) and self._config.get("cleanup", True)):
            self._text_scope = self._read_text_scope(selection=editing)
        if editing and self._text_scope is None:
            self._status("Select text to edit", "Select up to 4,000 characters in an editable field", auto_hide=4800)
            return
        self._screen = None
        if self._target:
            import win32api

            try:
                monitor = win32api.MonitorFromWindow(self._target[0], 2)
                device = win32api.GetMonitorInfo(monitor)["Device"]
                self._screen = next((screen for screen in QGuiApplication.screens() if screen.name() == device), None)
            except (OSError, win32api.error):
                pass
        try:
            self._mic = native.Microphone()
        except OSError:
            self._status("Microphone unavailable", "Check the Windows microphone and privacy settings.", auto_hide=4200)
            return
        self._started = time.monotonic()
        self._last_pcm_at = self._started
        self._capture_interrupted = False
        self._phase = "recording"
        self._pcm = bytearray()
        self._speech_seconds = 0.0
        self._preview_offset = 0
        self._preview_attempts = 0
        self._preview_speech_seconds = 0.0
        self._preview_text = ""
        self._previewing = False
        self._reconnects = 0
        self._quiet_bytes = self._unanswered_voice = 0
        self._confirmed_text = ""
        self._covered = 0
        self._cut = None
        self._first_caption = False
        self._meter_peak = 600.0
        self._elapsed = 0
        self._status("Listening", "0:00  ·  Click stop to finish")
        self._indicator.set_elapsed(0, hold=hold, editing=editing)
        self._sample_timer.start()
        self._start_live()

    @property
    def available(self):
        return bool(self._keys.get("groq") or self._keys.get("gemini"))

    @staticmethod
    def _local_editor():
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit)) and not focus.isReadOnly():
            if not isinstance(focus, QLineEdit) or focus.echoMode() == QLineEdit.EchoMode.Normal:
                return focus
        return None

    def _read_text_scope(self, *, selection):
        if self._target:
            return native.read_text_scope(self._target, selection=selection)
        editor = self._local_editor()
        if editor is None or editor is not self._local_target:
            return None
        if isinstance(editor, QLineEdit):
            start, end = editor.selectionStart(), editor.selectionEnd()
            if selection:
                text = editor.selectedText()
                return native.TextScope(text, (start, end)) if text and len(text) <= native.SELECTION_LIMIT else None
            if start >= 0:
                return None
            position = editor.cursorPosition()
            end = position * 2
            text = editor.text().encode("utf-16-le")[max(0, end - native.CONTEXT_LIMIT * 2):end]
            text = text.decode("utf-16-le", errors="ignore")
        else:
            cursor = editor.textCursor()
            if selection:
                text = cursor.selectedText().replace("\u2029", "\n")
                where = (cursor.selectionStart(), cursor.selectionEnd())
                return native.TextScope(text, where) if text and len(text) <= native.SELECTION_LIMIT else None
            if cursor.hasSelection():
                return None
            position = cursor.position()
            cursor.setPosition(max(0, position - native.CONTEXT_LIMIT), QTextCursor.MoveMode.KeepAnchor)
            text = cursor.selectedText().replace("\u2029", "\n")
        return native.TextScope(text, (position,)) if text.strip() else None

    def open_panel(self):
        if not self.available:
            self._notch.open_settings("Voice typing")
        elif self.can_retry:
            self._show_recovery()
        elif not self._phase:
            if self._indicator is not None and self._indicator.isVisible() and self._indicator._ready:
                self._hide()
            else:
                self._keep_panel = True
                self._screen = self._notch.screen()
                self._show_ready()

    def _show_ready(self):
        self._status("Ready to dictate", "Click to start  ·  Drag to move")

    def _expire_status(self):
        if self._keep_panel and not self._phase:
            self._show_ready()
        else:
            self._hide()

    def _read_mic(self):
        if self._mic is None:
            return
        try:
            data = self._mic.read()
        except OSError:
            self._stop_recording(capture_interrupted=True)
            return
        now = time.monotonic()
        if data:
            self._last_pcm_at = now
            self._add_audio(data)
        elif now - self._last_pcm_at >= 2:
            self._stop_recording(capture_interrupted=True)
            return
        elapsed = int(now - self._started)
        if self._speech_seconds >= 0.12:
            feedback = "Mic signal detected"
            if self._config.get("streaming", True):
                if self._live is not None:
                    feedback += " · Waiting for captions"
                elif self._previewing:
                    feedback = "Getting captions from recorded audio…"
            self._indicator.set_capture_feedback(feedback)
        elif elapsed >= 2:
            self._indicator.set_capture_feedback("Low mic level · Check Windows input")
        if elapsed != self._elapsed:
            self._elapsed = elapsed
            self._indicator.set_elapsed(elapsed, hold=self._holding, editing=self._editing)
        if elapsed >= 90 or (self._holding and not native.hold_shortcut_down()):
            self._stop_recording()
        elif self._live is None:
            self._maybe_preview()

    def _add_audio(self, data):
        self._pcm.extend(data)
        if data:
            samples = memoryview(data).cast("h")[::4]
            rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples))
            if rms >= 80:
                self._speech_seconds += len(data) / 32000
            self._meter_peak = max(600.0, self._meter_peak * 0.99, rms)
            self._indicator.set_level(math.sqrt(rms / self._meter_peak) if rms >= 80 else 0)
            live = self._live
            if live is not None and self._cut is None:
                self._quiet_bytes = self._quiet_bytes + len(data) if rms < 80 else 0
                if rms >= 80:
                    self._unanswered_voice += len(data)
                live.feed(data, voiced=rms >= 80)
                if live is not self._live or self._mic is None:
                    return
                if self._unanswered_voice >= (6 if self._first_caption else 5) * 32000:
                    self._live_failed(0)
                elif (len(self._pcm) - self._covered >= 18 * 32000 and self._quiet_bytes >= 32000
                      and self._live_draft):
                    self._cut = len(self._pcm)
                    live.checkpoint()

    def _pipeline(self):
        if self._api is None:
            self._api = DictationApi(self)
            self._api.set_keys(self._keys)
            self._api.phase_changed.connect(self._processing)
            self._api.finished.connect(self._finished)
        return self._api

    def _maybe_preview(self):
        interval = 80000 if self._preview_attempts < 2 else 192000
        if (not self._config.get("streaming", True) or self._previewing
                or len(self._pcm) - self._preview_offset < interval
                or self._speech_seconds - self._preview_speech_seconds < 0.3):
            return
        self._previewing = True
        self._preview_attempts += 1
        offset = max(self._preview_offset, len(self._pcm) - 192000)
        self._preview_offset = len(self._pcm)
        self._preview_speech_seconds = self._speech_seconds
        self._pipeline().start(native.wav_data(self._pcm[offset:]), cleanup=False,
                               vocabulary=self._config.get("vocabulary", []), snippets={}, style="natural", preview=True,
                               language_mode=self._language_mode)

    def _start_live(self):
        if not self._config.get("streaming", True) or time.monotonic() < self._live_retry_at:
            return
        if not self._keys.get("gemini"):
            return
        key = self._pipeline().live_key()
        if key:
            self._live_credential = key
            live = self._live = GeminiLiveDictation(self)
            live.preview.connect(self._remember_live_draft)
            live.checkpointed.connect(self._checkpointed)
            live.finalized.connect(self._live_result)
            live.failed.connect(self._live_failed)
            live.start(key, self._config.get("vocabulary", []),
                       language_codes=SPEECH_LANGUAGES[self._language_mode][1])

    def _close_live(self):
        if self._live is not None:
            live, self._live = self._live, None
            self._live_credential = None
            live.cancel()
            live.deleteLater()

    def _remember_live_draft(self, text):
        if self.sender() is not None and self.sender() is not self._live:
            return
        if not text.strip():
            return
        self._unanswered_voice = 0
        if not self._first_caption and self._started is not None:
            self._first_caption = True
            _LOG.debug("Dictation first caption ms=%d", int((time.monotonic() - self._started) * 1000))
        self._live_draft = text[:12000]
        self._indicator.set_preview((self._confirmed_text + " " + text).strip())

    def _checkpointed(self, text):
        if self.sender() is not self._live or self._cut is None:
            return
        self._close_live()
        self._covered, self._cut = self._cut, None
        self._confirmed_text = (self._confirmed_text + " " + text).strip()
        self._live_draft = ""
        self._unanswered_voice = self._quiet_bytes = 0
        tail = self._pcm[self._covered:]
        if self._phase == "finishing" and not any(tail):
            self._finish_live_text(self._confirmed_text)
            return
        if self._phase == "finishing":
            self._transcribe_recording()
            return
        self._start_live()
        if self._live is not None:
            self._live.replay(tail)

    def _live_result(self, text, preview_reference):
        if self.sender() is not None and self.sender() is not self._live:
            return
        self._close_live()
        if self._phase == "finishing":
            _LOG.debug("Dictation Live finished recovery=%s stop_ms=%d", bool(preview_reference or not text.strip()),
                       int((time.monotonic() - self._stopped_at) * 1000))
            if preview_reference or not text.strip():
                self._transcribe_recording(live_text=text, preview_reference=preview_reference)
            else:
                self._finish_live_text((self._confirmed_text + " " + text).strip())

    def _finish_live_text(self, text):
        self._close_live()
        if self._needs_language_check(text):
            self._transcribe_recording(language_reference=text)
            return
        short_take = len(self._pcm) <= 640000
        self._pcm.clear()
        self._indicator.set_preview(text)
        self._pipeline().finish_transcript(text, short_take=short_take, **self._output_options())

    def _live_failed(self, status):
        if isinstance(self.sender(), GeminiLiveDictation) and self.sender() is not self._live:
            return
        connected = self._live is not None and self._live.ready
        unconfirmed_ending = self._live is not None and self._live.unconfirmed_ending
        _LOG.debug("Dictation Live failed status=%s ready=%s reconnects=%d unconfirmed_ending=%s",
                   status, connected, self._reconnects, unconfirmed_ending)
        key = self._live_credential
        self._close_live()
        self._cut = None
        if status in (401, 403) and key:
            self._pipeline().reject_live_key(key, invalid=status == 401)
        retryable = status in (401, 403) or (status == 0 and connected and self._first_caption)
        if self._mic is not None and retryable and self._reconnects < 2:
            self._reconnects += 1
            self._unanswered_voice = self._quiet_bytes = 0
            self._start_live()
            if self._live is not None:
                self._live.replay(self._pcm[self._covered:])
                return
        if not unconfirmed_ending:
            self._live_retry_at = time.monotonic() + 60
        if self._phase == "finishing":
            self._transcribe_recording()

    def _stop_recording(self, *, capture_interrupted=False):
        self._stopped_at = time.monotonic()
        self._capture_interrupted = capture_interrupted
        _LOG.debug("Dictation capture ms=%d", int((self._stopped_at - self._started) * 1000))
        self._sample_timer.stop()
        self._holding = False
        mic, self._mic = self._mic, None
        # A socket failure during the last read must not start a second finalization.
        self._previewing = False
        if self._api is not None:
            self._api.cancel()
        try:
            self._add_audio(mic.close(keep_audio=True))
        except OSError:
            self._capture_interrupted = True
            _LOG.debug("Dictation microphone closed before its final buffer was available")
        pcm, self._pcm = self._pcm, bytearray()
        if self._speech_seconds < 0.12:
            self._close_live()
            self._phase = ""
            self._text_scope = None
            self._live_draft = ""
            title = "Microphone stopped" if self._capture_interrupted else "No mic signal" if not any(pcm) else "Mic level too low"
            self._status(title, "Check Windows sound input", auto_hide=6000)
            return
        self._pcm = pcm
        self._retry_audio = bytes(pcm)
        self._retry_options = self._output_options()
        self._phase = "finishing"
        if self._live is not None:
            no_captions = not self._live.has_transcript and self._cut is None
            if (self._capture_interrupted or not self._live.ready
                    or (no_captions and (self._reconnects or self._unanswered_voice >= 4 * 32000))):
                self._close_live()
        if self._covered and self._cut is None and not any(pcm[self._covered:]):
            self._finish_live_text(self._confirmed_text)
            return
        if self._live is not None:
            self._status("Transcribing", "Finishing the live transcript")
            self._live.finish()
        else:
            self._transcribe_recording()

    def _output_options(self):
        style = self._config.get("style", "auto")
        if style == "auto":
            style = native.target_style(self._target[0]) if self._target else "natural"
        text = self._text_scope.text if self._text_scope else ""
        return dict(cleanup=self._config.get("cleanup", True), vocabulary=self._config.get("vocabulary", []),
                    snippets={} if self._editing else self._config.get("snippets", {}), style=style,
                    selection=text if self._editing else "", context="" if self._editing else text,
                    language_mode=self._language_mode, stopped_at=self._stopped_at,
                    romanize=not self._editing and self._config.get("output_script") == "roman")

    def _needs_language_check(self, text):
        return (not self._editing and self._language_mode != "auto" and len(self._pcm) >= 8 * 32000
                and needs_language_check(text))

    def _transcribe_recording(self, *, live_text="", preview_reference="", language_reference=""):
        if not language_reference:
            draft = " ".join([self._confirmed_text, preview_reference or live_text or self._live_draft]).strip()
            if self._needs_language_check(draft):
                language_reference = draft
        pcm, self._pcm = self._pcm, bytearray()
        if language_reference:
            # A locked segment may already be checkpointed. Recheck the whole
            # recording and keep the suspect words out of the provider prompt.
            self._retry_language_reference = language_reference
            self._pipeline().start(native.wav_data(pcm), **self._output_options(),
                                   language_reference=language_reference)
            return
        self._pipeline().start(native.wav_data(pcm[self._covered:]), **self._output_options(), live_text=live_text,
                               confirmed_prefix=self._confirmed_text,
                               preview_reference=preview_reference,
                               recovery_draft=self._live_draft if not live_text and not self._editing else "")

    def _processing(self, phase):
        if self._previewing:
            return
        self._phase = "processing"
        detail = "Mic stopped · Processing captured audio" if self._capture_interrupted else "Ctrl+Alt+Shift+D to cancel"
        self._status(phase, detail)

    def _finished(self, text, message):
        if self._previewing:
            self._previewing = False
            if text and self._mic is not None:
                self._preview_text = (self._preview_text + " " + text)[-480:]
                self._indicator.set_preview(self._preview_text)
            return
        self._phase = ""
        self._live_draft = ""
        self._confirmed_text = ""
        self._covered = 0
        self._cut = None
        if not text:
            self.last_text = ""
            self._text_scope = None
            if self._indicator is not None:
                self._indicator.set_preview("")
            self._failure_title = message.partition(".")[0] or "Dictation failed"
            self._show_recovery()
            return
        self.last_text = text
        if message == REVIEW_TRANSCRIPT or self._retry_review:
            self._text_scope = None
            partial = message == REVIEW_TRANSCRIPT
            if not partial:
                self._forget_recording()
            self._indicator.set_preview(text)
            self._status(REVIEW_TRANSCRIPT, "May be incomplete · Copy to review" if partial else "Recovered · Click to copy",
                         offer_copy=True, offer_retry=self.can_retry)
            return
        self._forget_recording()
        self._pending_insert = text
        self._insertion_deadline = time.monotonic() + 0.8
        self._cleanup_message = message
        self._phase = "inserting"
        self._deliver()

    def _deliver(self):
        if native.modifiers_down() and time.monotonic() < self._insertion_deadline:
            self._paste_timer.start(40)
            return
        output, self._pending_insert = self._pending_insert, ""
        text = output
        self._phase = ""
        pasted = False
        scope = self._text_scope
        editing = self._editing

        def same_text_scope():
            return self._read_text_scope(selection=editing) == scope

        if self._config.get("auto_paste", True):
            editor = self._local_editor()
            if scope and not editing and text and text[0].isalnum() and not scope.text[-1].isspace():
                if scope.text[-1] not in "([{\u201c\u2018":
                    text = " " + text
            if editor is not None and editor is self._local_target and (scope is None or same_text_scope()):
                if isinstance(editor, QLineEdit):
                    editor.insert(text)
                else:
                    editor.insertPlainText(text)
                pasted = True
            elif self._target:
                try:
                    pasted = native.paste_text(int(self._notch.winId()), self._target, text,
                                               validate=same_text_scope if scope else None)
                except (OSError, WindowsError):
                    pasted = False
        self._text_scope = None
        if pasted:
            self._log_delivery("editor" if editor is self._local_target and editor is not None else "paste submitted")
            self._status("Text sent", "Selection replaced" if editing else self._cleanup_message or "Copy it again from Poppy’s menu",
                         auto_hide=1700)
        elif editing:
            self._status("Edit ready", "Copy the revised text", auto_hide=10000, offer_copy=True)
        else:
            self._copy_result(output, explicit=False)

    def copy_last(self):
        self._copy_result(self.last_text, explicit=True)

    def _log_delivery(self, destination):
        if self._stopped_at is not None:
            _LOG.debug("Dictation delivery=%s stop_ms=%d", destination, int((time.monotonic() - self._stopped_at) * 1000))

    @property
    def can_retry(self):
        return not self._phase and bool(self._retry_audio)

    def _forget_recording(self):
        self._retry_audio = b""
        self._retry_options = {}
        self._retry_review = False
        self._retry_language_reference = ""

    def _show_recovery(self):
        if self.last_text:
            self._indicator.set_preview(self.last_text)
            self._status(REVIEW_TRANSCRIPT, "Copy draft or retry recording", offer_copy=True, offer_retry=self.can_retry)
        else:
            self._status(self._failure_title, "Retry recording or discard" if self.can_retry else "No new text copied",
                         auto_hide=0 if self.can_retry else 6800, offer_retry=self.can_retry)

    def retry(self):
        if not self.can_retry:
            return
        self._retry_review = True
        self._capture_interrupted = False
        self._phase = "processing"
        self._stopped_at = time.monotonic()
        self._target = self._local_target = self._text_scope = None
        self._pipeline().start(native.wav_data(self._retry_audio),
                               **dict(self._retry_options, stopped_at=self._stopped_at),
                               recovery_draft=self.last_text, manual_retry=True,
                               language_reference=self._retry_language_reference)

    def _copy_result(self, text, *, explicit):
        if not text:
            return
        try:
            copied = native.copy_text(int(self._notch.winId()), text, history=explicit,
                                      preserve_complex=not explicit)
        except (OSError, WindowsError):
            self._status("Clipboard is busy", "Try copying again", auto_hide=10000, offer_copy=True)
            return
        if copied:
            self._log_delivery("manual copy" if explicit else "clipboard")
            if explicit:
                self._forget_recording()
            detail = "Ctrl+V to paste" if explicit else self._cleanup_message or "Ctrl+V to paste"
            self._status("Copied to clipboard", detail, auto_hide=2100)
        else:
            self._status("Dictation ready", "Copy replaces clipboard contents", auto_hide=10000, offer_copy=True)

    def _status(self, title, detail, *, auto_hide=0, offer_copy=False, offer_retry=False):
        self._hide_timer.stop()
        if self._indicator is None:
            self._indicator = DictationIndicator()
            self._indicator.clicked.connect(self.toggle)
            self._indicator.copy_requested.connect(self.copy_last)
            self._indicator.retry_requested.connect(self.retry)
            self._indicator.dismissed.connect(self.cancel)
            self._indicator.drag_started.connect(self._hide_timer.stop)
            self._indicator.moved.connect(self._remember_position)
            self._indicator.reset_position.connect(self._reset_position)
        was_visible = self._indicator.isVisible()
        self._indicator.set_status(title, detail, offer_copy=offer_copy, offer_retry=offer_retry)
        if not was_visible:
            self._place_indicator()
            self._indicator.show()
            self.panel_visible.emit(True)
        if auto_hide:
            self._hide_timer.start(auto_hide)

    def _place_indicator(self):
        screens = QGuiApplication.screens()
        position = self._position
        saved_screen = next((screen for screen in screens if position and screen.name() == position["screen"]), None)
        screen = saved_screen or getattr(self, "_screen", None)
        if screen not in screens:
            screen = self._notch.screen()
        bounds = screen.availableGeometry()
        if saved_screen is not None:
            x = bounds.left() + round(position["x"] * bounds.width())
            y = bounds.top() + round(position["y"] * bounds.height())
        else:
            x = bounds.center().x()
            y = bounds.bottom() - 22
        self._indicator.place(QPoint(x - self._indicator.width() // 2, y - self._indicator.height()), screen)

    def _screen_removed(self, _screen):
        if self._indicator is not None and self._indicator.isVisible():
            QTimer.singleShot(0, self, self._place_indicator)

    def _remember_position(self):
        pill = self._indicator
        center = pill.geometry().center()
        screen = QGuiApplication.screenAt(center) or pill.screen()
        bounds = screen.availableGeometry()
        self._position = {"screen": screen.name(),
                          "x": (pill.x() + pill.width() // 2 - bounds.left()) / bounds.width(),
                          "y": (pill.y() + pill.height() - bounds.top()) / bounds.height()}
        try:
            write_json(self._position_file, self._position)
        except OSError:
            pass
        if not self._phase and not pill._ready and not self.can_retry:
            self._hide_timer.start(10000)

    def _reset_position(self):
        self._position = None
        try:
            write_json(self._position_file, {})
        except OSError:
            pass
        self._place_indicator()

    def _hide(self):
        self._keep_panel = False
        self._hide_timer.stop()
        if self._indicator is not None and self._indicator.isVisible():
            self._indicator.hide()
            self.panel_visible.emit(False)

    def cancel(self):
        if self._retry_audio or self._retry_review:
            self.last_text = ""
        self._forget_recording()
        self._confirmed_text = ""
        self._covered = 0
        self._cut = None
        self._phase = ""
        self._sample_timer.stop()
        self._hide_timer.stop()
        self._paste_timer.stop()
        self._pending_insert = ""
        self._live_draft = ""
        self._text_scope = None
        self._editing = self._holding = False
        self._previewing = False
        self._close_live()
        if self._mic is not None:
            self._mic.close()
            self._mic = None
        self._pcm = bytearray()
        if self._api is not None:
            self._api.cancel()
        self._hide()

    def close(self):
        self.cancel()
        self._unregister()
        if self._indicator is not None:
            self._indicator.close()
            self._indicator.deleteLater()
            self._indicator = None
