"""On-demand dictation indicator and the Windows recording lifecycle."""

import json
import logging
import math
import time
from pywintypes import error as WindowsError

from PySide6.QtCore import QEasingCurve, QLineF, QObject, QPoint, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, Signal, QVariantAnimation
from PySide6.QtGui import QColor, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient, QTextCursor
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QLineEdit, QMenu, QPlainTextEdit, QTextEdit, QVBoxLayout, QWidget

from poppy.core import dictation_windows as native
from poppy.core.dictation_api import DictationApi, REVIEW_TRANSCRIPT, SPEECH_LANGUAGES, read_keys
from poppy.core.dictation_live import GeminiLiveDictation
from poppy.core.storage import data_path, write_json
from poppy.core.system_controls import system_animations_enabled
from poppy.ui.drawer_tools import DrawerToolButton
from poppy.ui.theme import is_light_theme, surface_colors


_LOG = logging.getLogger(__name__)


class DictationIndicator(QWidget):
    clicked = Signal()
    copy_requested = Signal()
    dismissed = Signal()
    drag_started = Signal()
    moved = Signal()
    reset_position = Signal()

    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(324, 54)
        self.setAccessibleName("Voice typing")
        self.setToolTip("Drag the pill to move it. Right-click while idle to reset its position.")
        header = QWidget(self)
        header.setGeometry(1, 7, self.width() - 9, 40)
        self.title = QLabel()
        self.detail = QLabel()
        self.preview = QLabel(self)
        self.preview.setGeometry(0, 51, self.width(), 36)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.preview.setAccessibleName("Live transcript preview")
        for label in (self.title, self.detail, self.preview):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        labels = QVBoxLayout()
        labels.setSpacing(1)
        labels.addWidget(self.title)
        labels.addWidget(self.detail)
        self.action = DrawerToolButton("mic", "Start recording")
        self.action.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.action.clicked.connect(self._activate)
        close = DrawerToolButton("close", "Dismiss voice typing")
        close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close.clicked.connect(self.dismissed)
        row = QHBoxLayout(header)
        row.setContentsMargins(51, 0, 0, 0)
        row.setSpacing(3)
        row.addLayout(labels, 1)
        row.addWidget(self.action)
        row.addWidget(close)
        self.preview.hide()
        self.levels = [0.0] * 5
        self._press = None
        self._dragging = False
        self._bottom_anchor = None
        self._show_preview = False
        self._preview_text = ""
        self.listening = False
        self._ready = False
        self._copy_ready = False
        self._done = False
        self._glow_amount = 0.45
        self._check_amount = 1.0
        self._arrival = QPropertyAnimation(self, b"windowOpacity", self)
        self._arrival.setDuration(165)
        self._arrival.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._height_motion = QVariantAnimation(self, duration=180)
        self._height_motion.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._height_motion.valueChanged.connect(self._set_height)
        self._glow = QVariantAnimation(self, duration=1800, loopCount=-1, startValue=0.0, endValue=0.0)
        self._glow.setKeyValueAt(0.5, 1.0)
        self._glow.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._glow.valueChanged.connect(self._set_glow)
        self._check = QVariantAnimation(self, duration=200, startValue=0.0, endValue=1.0)
        self._check.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._check.valueChanged.connect(self._set_check)

    def _activate(self):
        if self._copy_ready:
            self.copy_requested.emit()
        else:
            self.clicked.emit()

    def _set_glow(self, value):
        self._glow_amount = value
        self.update()

    def _set_check(self, value):
        self._check_amount = value
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if system_animations_enabled() and QApplication.platformName() == "windows":
            self._arrival.setStartValue(0.55)
            self._arrival.setEndValue(1.0)
            self._arrival.start()

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
                self._height_motion.stop()
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
            self._resize_for_state()
        elif self._ready and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        event.accept()

    def contextMenuEvent(self, event):
        if not self._ready:
            return
        menu = QMenu(self)
        menu.addAction("Reset pill position", self.reset_position)
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(event.globalPos())

    def hideEvent(self, event):
        self._height_motion.stop()
        self._glow.stop()
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
            self._bottom_anchor = y + self.height()

    def _set_height(self, height):
        bottom = self._bottom_anchor if self._bottom_anchor is not None else self.y() + self.height()
        self.setFixedHeight(height)
        if self.isVisible() and not self._dragging:
            self._bottom_anchor = bottom
            self.place(QPoint(self.x(), bottom - height), self.screen(), set_anchor=False)
        self.preview.setVisible(self._show_preview and height >= 87)
        self.update()

    def _resize_for_state(self):
        target = 94 if self._show_preview else 54
        self._height_motion.stop()
        if not self.isVisible() or not system_animations_enabled() or self.height() == target:
            self._set_height(target)
        elif not self._dragging:
            self._height_motion.setStartValue(self.height())
            self._height_motion.setEndValue(target)
            self._height_motion.start()

    def set_status(self, title, detail, *, offer_copy=False):
        colors = surface_colors()
        self.title.setStyleSheet(f"color: {colors['text']}; background: transparent; font: 600 13px 'Segoe UI';")
        self.detail.setStyleSheet(f"color: {colors['muted']}; background: transparent; font: 11px 'Segoe UI';")
        self.title.setText(title)
        self.detail.setText(self.detail.fontMetrics().elidedText(detail, Qt.TextElideMode.ElideRight, 198))
        self.detail.setToolTip(detail)
        was_listening = self.listening
        was_done = self._done
        self.listening = title == "Listening"
        self._done = title in ("Text sent", "Copied to clipboard")
        self._ready = title == "Ready to dictate"
        self._copy_ready = offer_copy
        if not self._dragging:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.action.setVisible(self._ready or self.listening or offer_copy)
        glyph, name = "mic", "Start recording"
        if self.listening:
            glyph, name = "stop", "Finish dictation"
        elif offer_copy:
            glyph, name = "copy", "Copy dictation"
        self.action.set_glyph(glyph)
        self.action.setAccessibleName(name)
        self.action.setToolTip(name)
        if self.listening != was_listening:
            self._glow.stop()
            self._glow_amount = 0.45
            if self.listening and system_animations_enabled():
                self._glow.start()
        if self._done != was_done:
            self._check.stop()
            self._check_amount = 1.0
            if self._done and system_animations_enabled():
                self._check_amount = 0.0
                self._check.start()
        if self.listening and not was_listening:
            self.preview.setStyleSheet(
                f"color: {colors['text']}; background: transparent; padding: 0 12px 0 29px; font: 12px 'Segoe UI';")
            self.set_preview("")
            self.levels = [0.0] * 5
        self._show_preview = self.listening or (
            title in ("Transcribing", "Checking languages", "Checking transcript", "Cleaning up", REVIEW_TRANSCRIPT)
            and bool(self._preview_text))
        self._resize_for_state()
        self.update()

    def set_preview(self, text):
        self._preview_text = text
        metrics = self.preview.fontMetrics()
        width = self.width() - 44
        recent = " ".join(text.split())[-400:] or "Waiting for speech…"
        if metrics.horizontalAdvance(recent) <= width:
            self.preview.setText(recent)
            return
        words = recent.split()
        last = words.pop()
        while words and metrics.horizontalAdvance(f"{words[-1]} {last}") <= width:
            last = f"{words.pop()} {last}"
        first = metrics.elidedText(" ".join(words), Qt.TextElideMode.ElideLeft, width)
        last = metrics.elidedText(last, Qt.TextElideMode.ElideLeft, width)
        self.preview.setText(f"{first}\n{last}" if first else last)

    def set_elapsed(self, seconds, *, hold=False, editing=False):
        minutes, seconds = divmod(seconds, 60)
        hint = "Release the keys to finish" if hold else "Speak an edit, then click Stop" if editing else "Click stop to finish"
        self.detail.setText(f"{minutes}:{seconds:02d}  ·  {hint}")

    def set_level(self, level):
        previous = self.levels
        self.levels = [old * 0.38 + new * 0.62 for old, new in zip(previous, [*previous[1:], level])]
        self.update()

    def paintEvent(self, event):
        colors = surface_colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        bounds = QRectF(self.rect()).adjusted(6, 3, -6, -7)
        for spread, opacity in ((5, 9), (4, 10), (3, 12), (2, 15), (1, 17)):
            painter.setBrush(QColor(0, 0, 0, opacity))
            shadow = bounds.adjusted(-spread, 2 - spread, spread, 2 + spread)
            painter.drawRoundedRect(shadow, 18 + spread, 18 + spread)
        surface = QLinearGradient(0, 0, 0, bounds.height())
        surface.setColorAt(0, QColor(colors["card"]))
        surface.setColorAt(1, QColor(colors["root"]))
        painter.setBrush(surface)
        painter.drawRoundedRect(bounds, 18, 18)
        shine = QColor("#ffffff")
        shine.setAlpha(75 if is_light_theme() else 23)
        painter.setBrush(shine)
        painter.drawRoundedRect(QRectF(19, 4, self.width() - 38, 1), 0.5, 0.5)
        accent = QColor("#235945" if is_light_theme() else "#b5e3cc")
        if self._done:
            painter.setPen(QPen(accent, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            start, elbow, end = QPointF(17, 27), QPointF(23, 32), QPointF(33, 21)
            first, second = QLineF(start, elbow), QLineF(elbow, end)
            distance = self._check_amount * (first.length() + second.length())
            path = QPainterPath(start)
            path.lineTo(first.pointAt(min(1.0, distance / first.length())))
            if distance > first.length():
                path.lineTo(second.pointAt((distance - first.length()) / second.length()))
            painter.drawPath(path)
            painter.setPen(Qt.PenStyle.NoPen)
        else:
            if self.listening:
                halo = QRadialGradient(25, 27, 18)
                glow = QColor(accent)
                glow.setAlpha(int(13 + 21 * self._glow_amount))
                halo.setColorAt(0, glow)
                glow.setAlpha(0)
                halo.setColorAt(1, glow)
                painter.setBrush(halo)
                painter.drawEllipse(QRectF(7, 9, 36, 36))
            painter.setBrush(accent if self.listening else QColor(colors["muted"]))
            for index, level in enumerate(self.levels if self.listening else (0.07, 0.21, 0.36, 0.21, 0.07)):
                height = 3 + level * (19 if index in (1, 2, 3) else 14)
                painter.drawRoundedRect(QRectF(15 + index * 5, 27 - height / 2, 2.5, height), 1.25, 1.25)
        if self.preview.isVisible():
            painter.setBrush(QColor(colors["muted"]))
            for x, y, width, height in ((15, 60, 8, 1), (15, 63, 5, 1), (23, 63, 1, 7), (15, 66, 5, 1)):
                painter.drawRoundedRect(QRectF(x, y, width, height), 0.5, 0.5)


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
        self._previewing = False
        self._phase = ""
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
        self._hide_timer.timeout.connect(self._hide)
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
        if self._phase or not self.available:
            return
        self.last_text = ""
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
        self._phase = "recording"
        self._pcm = bytearray()
        self._speech_seconds = 0.0
        self._preview_offset = 0
        self._preview_attempts = 0
        self._preview_speech_seconds = 0.0
        self._preview_text = ""
        self._previewing = False
        self._retried_live_key = False
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
        elif not self._phase:
            if self._indicator is not None and self._indicator.isVisible() and self._indicator._ready:
                self._hide()
            else:
                self._screen = self._notch.screen()
                self._status("Ready to dictate", "Click to start  ·  Drag to move", auto_hide=18000)

    def _read_mic(self):
        if self._mic is None:
            return
        try:
            self._add_audio(self._mic.read())
        except OSError:
            self.cancel()
            self._status("Microphone disconnected", "Reconnect it and try again.", auto_hide=4200)
            return
        elapsed = int(time.monotonic() - self._started)
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
            if self._live is not None:
                self._live.feed(data)

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
                               vocabulary=self._config.get("vocabulary", []), snippets={}, style="natural", preview=True)

    def _start_live(self):
        if not self._config.get("streaming", True) or time.monotonic() < self._live_retry_at:
            return
        if not self._keys.get("gemini"):
            return
        key = self._pipeline().live_key()
        if key:
            self._live_credential = key
            self._live = GeminiLiveDictation(self)
            self._live.preview.connect(self._remember_live_draft)
            self._live.finalized.connect(self._live_result)
            self._live.failed.connect(self._live_failed)
            self._live.start(key, self._config.get("vocabulary", []),
                             language_codes=SPEECH_LANGUAGES[self._language_mode][1])

    def _close_live(self):
        if self._live is not None:
            live, self._live = self._live, None
            self._live_credential = None
            live.cancel()
            live.deleteLater()

    def _remember_live_draft(self, text):
        self._live_draft = text[:12000]
        self._indicator.set_preview(text)

    def _live_result(self, text, preview_reference):
        self._close_live()
        if self._phase == "finishing":
            _LOG.debug("Dictation Live finished recovery=%s stop_ms=%d", bool(preview_reference or not text.strip()),
                       int((time.monotonic() - self._stopped_at) * 1000))
            if preview_reference or not text.strip():
                self._transcribe_recording(live_text=text, preview_reference=preview_reference)
            else:
                short_take = len(self._pcm) <= 640000  # 20 seconds of PCM.
                self._pcm.clear()
                self._indicator.set_preview(text)
                self._pipeline().finish_transcript(text, short_take=short_take, **self._output_options())

    def _live_failed(self, status):
        _LOG.debug("Dictation Live failed status=%s", status)
        key = self._live_credential
        self._close_live()
        if status in (401, 403) and key:
            self._pipeline().reject_live_key(key, invalid=status == 401)
            if self._mic is not None and not self._retried_live_key and len(self._pcm) <= 64000:
                self._retried_live_key = True
                self._start_live()
                if self._live is not None:
                    self._live.feed(self._pcm)
                    return
        else:
            self._live_retry_at = time.monotonic() + 60
        if self._phase == "finishing":
            self._transcribe_recording()

    def _stop_recording(self):
        self._stopped_at = time.monotonic()
        self._sample_timer.stop()
        self._holding = False
        mic, self._mic = self._mic, None
        # A socket failure during the last read must not start a second finalization.
        self._previewing = False
        if self._api is not None:
            self._api.cancel()
        self._add_audio(mic.close(keep_audio=True))
        pcm, self._pcm = self._pcm, bytearray()
        if self._speech_seconds < 0.12:
            self._close_live()
            self._phase = ""
            self._text_scope = None
            self._live_draft = ""
            self._status("No speech heard", "No new text copied", auto_hide=4800)
            return
        self._pcm = pcm
        if self._live is not None:
            self._phase = "finishing"
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

    def _transcribe_recording(self, *, live_text="", preview_reference=""):
        pcm, self._pcm = self._pcm, bytearray()
        self._pipeline().start(native.wav_data(pcm), **self._output_options(), live_text=live_text,
                               preview_reference=preview_reference,
                               recovery_draft=self._live_draft if not live_text and not self._editing else "")

    def _processing(self, phase):
        if self._previewing:
            return
        self._phase = "processing"
        self._status(phase, "Ctrl+Alt+Shift+D to cancel")

    def _finished(self, text, message):
        if self._previewing:
            self._previewing = False
            if text and self._mic is not None:
                self._preview_text = (self._preview_text + " " + text)[-480:]
                self._indicator.set_preview(self._preview_text)
            return
        self._phase = ""
        self._live_draft = ""
        if not text:
            self.last_text = ""
            self._text_scope = None
            if self._indicator is not None:
                self._indicator.set_preview("")
            self._status(message.partition(".")[0] or "Dictation failed", "No new text copied", auto_hide=6800)
            return
        self.last_text = text
        if message == REVIEW_TRANSCRIPT:
            self._text_scope = None
            self._indicator.set_preview(text)
            self._status(REVIEW_TRANSCRIPT, "May be incomplete · Copy to review", offer_copy=True)
            return
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
            self._status("Text sent", "Selection replaced" if editing else self._cleanup_message or "Copy it again from Poppy’s menu",
                         auto_hide=1700)
        elif editing:
            self._status("Edit ready", "Copy the revised text", auto_hide=10000, offer_copy=True)
        else:
            self._copy_result(output, explicit=False)

    def copy_last(self):
        self._copy_result(self.last_text, explicit=True)

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
            detail = "Ctrl+V to paste" if explicit else self._cleanup_message or "Ctrl+V to paste"
            self._status("Copied to clipboard", detail, auto_hide=2100)
        else:
            self._status("Dictation ready", "Copy replaces clipboard contents", auto_hide=10000, offer_copy=True)

    def _status(self, title, detail, *, auto_hide=0, offer_copy=False):
        self._hide_timer.stop()
        if self._indicator is None:
            self._indicator = DictationIndicator()
            self._indicator.clicked.connect(self.toggle)
            self._indicator.copy_requested.connect(self.copy_last)
            self._indicator.dismissed.connect(self.cancel)
            self._indicator.drag_started.connect(self._hide_timer.stop)
            self._indicator.moved.connect(self._remember_position)
            self._indicator.reset_position.connect(self._reset_position)
        was_visible = self._indicator.isVisible()
        self._indicator.set_status(title, detail, offer_copy=offer_copy)
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
        if not self._phase:
            self._hide_timer.start(10000)

    def _reset_position(self):
        self._position = None
        try:
            write_json(self._position_file, {})
        except OSError:
            pass
        self._place_indicator()

    def _hide(self):
        if self._indicator is not None and self._indicator.isVisible():
            self._indicator.hide()
            self.panel_visible.emit(False)

    def cancel(self):
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
