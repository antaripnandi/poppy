"""On-demand dictation indicator and the Windows recording lifecycle."""

import math
import time
from pywintypes import error as WindowsError

from PySide6.QtCore import QObject, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from poppy.core import dictation_windows as native
from poppy.core.dictation_api import DictationApi, read_keys
from poppy.ui.theme import surface_colors


class DictationIndicator(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus
                         | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(340, 64)
        self.setAccessibleName("Voice typing")
        self.title = QLabel()
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        for label in (self.title, self.detail):
            label.setTextFormat(Qt.TextFormat.PlainText)
        labels = QVBoxLayout()
        labels.setSpacing(2)
        labels.addWidget(self.title)
        labels.addWidget(self.detail)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(53, 8, 12, 8)
        layout.addLayout(labels)
        self.level = 0.0
        self.listening = False

    def set_status(self, title, detail):
        colors = surface_colors()
        self.title.setStyleSheet(f"color: {colors['text']}; background: transparent; font: 600 13px 'Segoe UI';")
        self.detail.setStyleSheet(f"color: {colors['muted']}; background: transparent; font: 11px 'Segoe UI';")
        self.title.setText(title)
        self.detail.setText(detail)
        self.listening = title == "Listening"
        self.update()

    def set_level(self, level):
        self.level = self.level * 0.4 + level * 0.6
        self.update()

    def paintEvent(self, event):
        colors = surface_colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colors["root"]))
        painter.drawRoundedRect(QRectF(self.rect()), 13, 13)
        painter.setBrush(QColor(colors["text"] if self.listening else colors["muted"]))
        level = self.level if self.listening else 0
        for index, weight in enumerate((0.43, 0.78, 1.0, 0.67, 0.47)):
            height = 3 + level * 21 * weight
            painter.drawRoundedRect(QRectF(16 + index * 5, 32 - height / 2, 3, height), 1.5, 1.5)


class DictationController(QObject):
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
        if self._phase or not self._keys:
            return
        focus = native.focused_target()
        self._target = focus[0] if focus else None
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
        self._status("Listening", "Ctrl+Alt+D to finish")
        self._indicator.level = 0
        self._sample_timer.start()

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

    def _add_audio(self, data):
        self._pcm.extend(data)
        if data:
            samples = memoryview(data).cast("h")[::4]
            rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples))
            if rms >= 80:
                self._speech_seconds += len(data) / 32000
            self._indicator.set_level(min(1.0, rms / 1800))

    def _stop_recording(self):
        self._sample_timer.stop()
        mic, self._mic = self._mic, None
        self._add_audio(mic.close(keep_audio=True))
        pcm, self._pcm = self._pcm, bytearray()
        if self._speech_seconds < 0.12:
            self._phase = ""
            self._status("No speech heard", "Ctrl+Alt+D to try again", auto_hide=2100)
            return
        if self._api is None:
            self._api = DictationApi(self)
            self._api.set_keys(self._keys)
            self._api.phase_changed.connect(self._processing)
            self._api.finished.connect(self._finished)
        style = self._config.get("style", "auto")
        if style == "auto":
            style = native.target_style(self._target[0]) if self._target else "natural"
        self._api.start(native.wav_data(pcm), cleanup=self._config.get("cleanup", True),
                        vocabulary=self._config.get("vocabulary", []), snippets=self._config.get("snippets", {}),
                        style=style)

    def _processing(self, phase):
        self._phase = "processing"
        self._status(phase, "Ctrl+Alt+Shift+D to cancel")

    def _finished(self, text, message):
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
        pasted = None
        if self._target and self._config.get("auto_paste", True) and self._restore is None:
            try:
                pasted = native.paste_text(int(self._notch.winId()), self._target, text)
            except (OSError, WindowsError):
                pass
        if pasted:
            self._restore = pasted
            self._restore_attempts = 0
            self._restore_timer.start(2500)
            self._status("Text sent", self._cleanup_message or "Copy it again from Poppy’s menu", auto_hide=1700)
        else:
            self._status("Dictation ready", "Right-click Poppy and choose Copy last dictation.", auto_hide=4800)

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
            native.copy_text(int(self._notch.winId()), self.last_text)
        except (OSError, WindowsError):
            self._status("Clipboard is busy", "Choose Copy last dictation again.", auto_hide=2800)
            return
        self._status("Copied", "Paste the dictation where you want it.", auto_hide=1600)

    def _status(self, title, detail, *, auto_hide=0):
        self._hide_timer.stop()
        if self._indicator is None:
            self._indicator = DictationIndicator()
        self._indicator.set_status(title, detail)
        if not self._indicator.isVisible():
            screen = getattr(self, "_screen", None)
            if screen not in QGuiApplication.screens():
                screen = self._notch.screen()
            bounds = screen.availableGeometry()
            notch = self._notch.geometry()
            y = bounds.top() + 44
            if self._notch.isVisible() and bounds.intersects(notch):
                y = notch.bottom() + 8
            y = max(bounds.top() + 8, min(y, bounds.bottom() - self._indicator.height() - 7))
            self._indicator.move(bounds.center().x() - self._indicator.width() // 2, y)
        self._indicator.show()
        if auto_hide:
            self._hide_timer.start(auto_hide)

    def _hide(self):
        if self._indicator is not None:
            self._indicator.hide()

    def cancel(self):
        self._phase = ""
        self._sample_timer.stop()
        self._hide_timer.stop()
        self._paste_timer.stop()
        self._pending_insert = ""
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
