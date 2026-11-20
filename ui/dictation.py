"""On-demand dictation indicator and the Windows recording lifecycle."""

import math
import time
from pywintypes import error as WindowsError

from PySide6.QtCore import QEasingCurve, QObject, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QLinearGradient, QPainter
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QTextEdit, QVBoxLayout, QWidget

from poppy.core import dictation_windows as native
from poppy.core.dictation_api import DictationApi, read_keys
from poppy.core.system_controls import system_animations_enabled
from poppy.ui.drawer_tools import DrawerToolButton
from poppy.ui.theme import is_light_theme, surface_colors


class DictationIndicator(QWidget):
    clicked = Signal()
    dismissed = Signal()

    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(324, 54)
        self.setAccessibleName("Voice typing")
        self.title = QLabel()
        self.detail = QLabel()
        self.preview = QLabel()
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
        self.action.clicked.connect(self.clicked)
        close = DrawerToolButton("close", "Dismiss voice typing")
        close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close.clicked.connect(self.dismissed)
        row = QHBoxLayout()
        row.setContentsMargins(51, 0, 0, 0)
        row.setSpacing(3)
        row.addLayout(labels, 1)
        row.addWidget(self.action)
        row.addWidget(close)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 7, 9, 7)
        layout.setSpacing(4)
        layout.addLayout(row, 1)
        layout.addWidget(self.preview)
        self.preview.hide()
        self.levels = [0.0] * 5
        self.listening = False
        self._ready = False
        self._arrival = QPropertyAnimation(self, b"windowOpacity", self)
        self._arrival.setDuration(165)
        self._arrival.setEasingCurve(QEasingCurve.Type.OutCubic)

    def showEvent(self, event):
        super().showEvent(event)
        if system_animations_enabled() and QApplication.platformName() == "windows":
            self._arrival.setStartValue(0.55)
            self._arrival.setEndValue(1.0)
            self._arrival.start()

    def mouseReleaseEvent(self, event):
        if self._ready and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def set_status(self, title, detail):
        colors = surface_colors()
        self.title.setStyleSheet(f"color: {colors['text']}; background: transparent; font: 600 13px 'Segoe UI';")
        self.detail.setStyleSheet(f"color: {colors['muted']}; background: transparent; font: 11px 'Segoe UI';")
        self.title.setText(title)
        self.detail.setText(self.detail.fontMetrics().elidedText(detail, Qt.TextElideMode.ElideRight, 198))
        self.detail.setToolTip(detail)
        self.listening = title == "Listening"
        self._ready = title == "Ready to dictate"
        self.setCursor(Qt.CursorShape.PointingHandCursor if self._ready else Qt.CursorShape.ArrowCursor)
        self.action.setVisible(self._ready or self.listening)
        self.action.set_glyph("stop" if self.listening else "mic")
        name = "Finish dictation" if self.listening else "Start recording"
        self.action.setAccessibleName(name)
        self.action.setToolTip(name)
        self.preview.setVisible(self.listening)
        self.setFixedHeight(80 if self.listening else 54)
        if self.listening:
            self.preview.setStyleSheet(
                f"color: {colors['muted']}; background: transparent; padding: 2px 10px 2px 28px; font: 12px 'Segoe UI';")
            self.set_preview("")
            self.levels = [0.0] * 5
        self.update()

    def set_preview(self, text):
        line = " ".join(text.split())
        self.preview.setText(self.preview.fontMetrics().elidedText(
            line or "Waiting for speech…", Qt.TextElideMode.ElideLeft, 270))

    def set_level(self, level):
        previous = self.levels
        self.levels = [old * 0.38 + new * 0.62 for old, new in zip(previous, [*previous[1:], level])]
        self.update()

    def paintEvent(self, event):
        colors = surface_colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        bounds = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        surface = QLinearGradient(0, 0, 0, bounds.height())
        surface.setColorAt(0, QColor(colors["card"]))
        surface.setColorAt(1, QColor(colors["root"]))
        painter.setBrush(surface)
        painter.drawRoundedRect(bounds, 18, 18)
        shine = QColor("#ffffff")
        shine.setAlpha(75 if is_light_theme() else 23)
        painter.setBrush(shine)
        painter.drawRoundedRect(QRectF(16, 2, self.width() - 32, 1), 0.5, 0.5)
        painter.setBrush(QColor(("#235945" if is_light_theme() else "#b5e3cc") if self.listening else colors["muted"]))
        for index, level in enumerate(self.levels if self.listening else (0.07, 0.21, 0.36, 0.21, 0.07)):
            height = 3 + level * (19 if index in (1, 2, 3) else 14)
            painter.drawRoundedRect(QRectF(15 + index * 5, 27 - height / 2, 2.5, height), 1.25, 1.25)
        if self.listening:
            painter.setBrush(QColor(colors["muted"]))
            for x, y, width, height in ((15, 60, 8, 1), (15, 63, 5, 1), (23, 63, 1, 7), (15, 66, 5, 1)):
                painter.drawRoundedRect(QRectF(x, y, width, height), 0.5, 0.5)


class DictationController(QObject):
    panel_visible = Signal(bool)

    def __init__(self, notch):
        super().__init__(notch)
        self._notch = notch
        self._api = None
        self._indicator = None
        self._mic = None
        self._keys = {}
        self._config = {}
        self._registered_hwnd = None
        self._target = None
        self._local_target = None
        self._pending_insert = ""
        self._restore = None
        self._phase = ""
        self.last_text = ""
        self.shortcut_status = ""
        self._sample_timer = QTimer(self, interval=40)
        self._sample_timer.timeout.connect(self._read_mic)
        self._hide_timer = QTimer(self, singleShot=True)
        self._hide_timer.timeout.connect(self._hide)
        self._paste_timer = QTimer(self, singleShot=True)
        self._paste_timer.timeout.connect(self._deliver)
        self._restore_timer = QTimer(self, singleShot=True)
        self._restore_timer.timeout.connect(self._restore_clipboard)

    def configure(self, config):
        config = config if isinstance(config, dict) else {}
        if config != self._config:
            self.cancel()
            self._config = config
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
        self.shortcut_status = (
            "Ctrl+Alt+D is active." if self._registered_hwnd else
            "The shortcut is unavailable. It may be in use by another app." if enabled else
            "Add a Groq or Gemini key to enable voice typing." if config.get("enabled") else
            "Voice typing is off."
        )

    def _unregister(self):
        if self._registered_hwnd is not None:
            native.unregister_shortcuts(self._registered_hwnd)
            self._registered_hwnd = None

    def handle_shortcut(self, shortcut):
        if self._registered_hwnd is None:
            return False
        if shortcut == native.HOTKEY:
            self.toggle()
        elif shortcut == native.CANCEL_HOTKEY:
            self.cancel()
        else:
            return False
        return True

    def toggle(self):
        if self._mic is not None:
            self._stop_recording()
            return
        if self._phase or not self.available:
            return
        focus = native.focused_target()
        self._target = focus[0] if focus else None
        self._local_target = self._local_editor() if not self._target else None
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
        self._status("Listening", "Click stop or press Ctrl+Alt+D")
        self._sample_timer.start()

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

    def open_panel(self):
        if not self.available:
            self._notch.open_settings("Voice typing")
        elif not self._phase:
            if self._indicator is not None and self._indicator.isVisible() and self._indicator._ready:
                self._hide()
            else:
                self._screen = self._notch.screen()
                self._status("Ready to dictate", "Click to start", auto_hide=18000)

    def _read_mic(self):
        if self._mic is None:
            return
        try:
            self._add_audio(self._mic.read())
        except OSError:
            self.cancel()
            self._status("Microphone disconnected", "Reconnect it and try again.", auto_hide=4200)
            return
        if time.monotonic() - self._started >= 90:
            self._stop_recording()
        else:
            self._maybe_preview()

    def _add_audio(self, data):
        self._pcm.extend(data)
        if data:
            samples = memoryview(data).cast("h")[::4]
            rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples))
            if rms >= 80:
                self._speech_seconds += len(data) / 32000
            self._indicator.set_level(min(1.0, math.sqrt(rms / 3300)))

    def _pipeline(self):
        if self._api is None:
            self._api = DictationApi(self)
            self._api.set_keys(self._keys)
            self._api.phase_changed.connect(self._processing)
            self._api.finished.connect(self._finished)
        return self._api

    def _maybe_preview(self):
        interval = 112000 if self._preview_attempts < 3 else 192000
        if (self._previewing or len(self._pcm) - self._preview_offset < interval
                or self._speech_seconds - self._preview_speech_seconds < 0.3):
            return
        self._previewing = True
        self._preview_attempts += 1
        offset = max(self._preview_offset, len(self._pcm) - 192000)
        self._preview_offset = len(self._pcm)
        self._preview_speech_seconds = self._speech_seconds
        self._pipeline().start(native.wav_data(self._pcm[offset:]), cleanup=False,
                               vocabulary=self._config.get("vocabulary", []), snippets={}, style="natural", preview=True)

    def _stop_recording(self):
        self._sample_timer.stop()
        mic, self._mic = self._mic, None
        self._previewing = False
        if self._api is not None:
            self._api.cancel()
        self._add_audio(mic.close(keep_audio=True))
        pcm, self._pcm = self._pcm, bytearray()
        if self._speech_seconds < 0.12:
            self._phase = ""
            self._status("No speech heard", "Ctrl+Alt+D to try again", auto_hide=2100)
            return
        style = self._config.get("style", "auto")
        if style == "auto":
            style = native.target_style(self._target[0]) if self._target else "natural"
        self._pipeline().start(native.wav_data(pcm), cleanup=self._config.get("cleanup", True),
                               vocabulary=self._config.get("vocabulary", []), snippets=self._config.get("snippets", {}),
                               style=style)

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
        if not text:
            self._status("Dictation", message, auto_hide=4800)
            return
        self.last_text = text
        self._pending_insert = text
        self._insertion_deadline = time.monotonic() + 0.8
        self._cleanup_message = message
        self._phase = "inserting"
        self._deliver()

    def _deliver(self):
        if native.modifiers_down() and time.monotonic() < self._insertion_deadline:
            self._paste_timer.start(40)
            return
        text, self._pending_insert = self._pending_insert, ""
        self._phase = ""
        pasted = False
        if self._config.get("auto_paste", True):
            editor = self._local_editor()
            if editor is not None and editor is self._local_target:
                if isinstance(editor, QLineEdit):
                    editor.insert(text)
                else:
                    editor.insertPlainText(text)
                pasted = True
            elif self._target and self._restore is None:
                try:
                    restored = native.paste_text(int(self._notch.winId()), self._target, text)
                except (OSError, WindowsError):
                    restored = None
                if restored:
                    pasted = True
                    self._restore = restored
                    self._restore_attempts = 0
                    self._restore_timer.start(2500)
        if pasted:
            self._status("Text sent", self._cleanup_message or "Copy it again from Poppy’s menu", auto_hide=1700)
        else:
            self.copy_last()

    def _restore_clipboard(self):
        if self._restore is None:
            return
        try:
            native.restore_clipboard(int(self._notch.winId()), *self._restore)
        except (OSError, WindowsError):
            self._restore_attempts += 1
            if self._restore_attempts < 5:
                self._restore_timer.start(120)
                return
        self._restore = None

    def copy_last(self):
        if not self.last_text:
            return
        try:
            native.copy_text(int(self._notch.winId()), self.last_text, history=True)
        except (OSError, WindowsError):
            self._status("Clipboard is busy", "Choose Copy last dictation again.", auto_hide=2800)
            return
        self._status("Copied to clipboard", "Ctrl+V to paste", auto_hide=2100)

    def _status(self, title, detail, *, auto_hide=0):
        self._hide_timer.stop()
        if self._indicator is None:
            self._indicator = DictationIndicator()
            self._indicator.clicked.connect(self.toggle)
            self._indicator.dismissed.connect(self.cancel)
        was_visible = self._indicator.isVisible()
        self._indicator.set_status(title, detail)
        screen = getattr(self, "_screen", None)
        if screen not in QGuiApplication.screens():
            screen = self._notch.screen()
        bounds = screen.availableGeometry()
        self._indicator.move(bounds.center().x() - self._indicator.width() // 2,
                             bounds.bottom() - self._indicator.height() - 22)
        if not was_visible:
            self._indicator.show()
            self.panel_visible.emit(True)
        if auto_hide:
            self._hide_timer.start(auto_hide)

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
        self._previewing = False
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
        self._restore_timer.stop()
        self._restore_clipboard()
        self._restore_timer.stop()
        if self._indicator is not None:
            self._indicator.close()
            self._indicator.deleteLater()
            self._indicator = None
