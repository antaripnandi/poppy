"""Spotify account connection and playback-volume controls."""

from PySide6.QtCore import QEasingCurve, QObject, QPropertyAnimation, QSignalBlocker, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from poppy.core.spotify_playback import REDIRECT_URI
from poppy.core.system_controls import system_animations_enabled
from poppy.ui.theme import set_widget_style


class SpotifyAccountControls(QWidget):
    def __init__(self, playback, parent=None):
        super().__init__(parent)
        self.playback = playback
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 8)
        title = QLabel("Spotify playback volume")
        set_widget_style(title, "font-size: 14px; font-weight: 600;")
        layout.addWidget(title)
        hint = QLabel("Requires Spotify Premium. Add this redirect URI to your Spotify Developer app.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        redirect = QLabel(REDIRECT_URI)
        redirect.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(redirect)
        row = QHBoxLayout()
        self.client = QLineEdit(playback.client_id)
        self.client.setPlaceholderText("Spotify Developer Client ID")
        self.client.setAccessibleName("Spotify Developer Client ID")
        self.client.setMaxLength(32)
        self.connect_button = QPushButton("Connect Spotify")
        self.connect_button.clicked.connect(lambda: playback.connect_account(self.client.text()))
        row.addWidget(self.client, 1)
        row.addWidget(self.connect_button)
        layout.addLayout(row)
        actions = QHBoxLayout()
        dashboard = QPushButton("Developer dashboard")
        dashboard.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://developer.spotify.com/dashboard")))
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.clicked.connect(playback.disconnect_account)
        self.cancel_button = QPushButton("Cancel connection")
        self.cancel_button.clicked.connect(lambda: playback.cancel_connect())
        actions.addWidget(dashboard)
        actions.addStretch()
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.disconnect_button)
        layout.addLayout(actions)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        note = QLabel("Connecting and disconnecting take effect immediately. Windows protects the saved connection.")
        note.setWordWrap(True)
        set_widget_style(note, "color: #9ca3a5; font-size: 11px;")
        layout.addWidget(note)
        playback.changed.connect(self._update)
        self._update()

    def _update(self):
        self.status.setText(self.playback.status)
        self.connect_button.setEnabled(not self.playback.connecting)
        self.client.setEnabled(not self.playback.connecting)
        self.cancel_button.setVisible(self.playback.connecting)
        self.disconnect_button.setVisible(self.playback.connected)


class SpotifyVolumeBinding(QObject):
    """Bind the existing Spotify mixer row to its playback device."""

    def __init__(self, playback, slider, readout, mute, parent, restore_volumes):
        super().__init__(parent)
        self.playback = playback
        self.slider, self.readout, self.mute = slider, readout, mute
        self._device_id = None
        self._pending = None
        self._in_flight = None
        self._restore_volumes = restore_volumes
        self._animation = QPropertyAnimation(slider, b"value", self)
        self._animation.setDuration(120)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        slider.sliderPressed.connect(self._animation.stop)
        slider.valueChanged.connect(self._display_level)
        self._write_timer = QTimer(self, interval=150, singleShot=True)
        self._write_timer.timeout.connect(self._write_volume)
        playback.changed.connect(self._update)
        self._update()

    @property
    def active(self):
        return self.playback.connected

    def close(self):
        self._write_timer.stop()
        self._pending = None
        self._in_flight = None
        self._animation.stop()

    def _display_level(self, level):
        if self.active:
            self.readout.setText(f"{level}%")
            self.mute.setText("Unmute" if level == 0 else "Mute")
            self.mute.setAccessibleName(f"{self.mute.text()} Spotify playback")

    def _show_level(self, level, *, animate=False):
        if (animate and self.slider.isVisible() and system_animations_enabled()
                and self.slider.value() != level):
            if self._animation.state() == QPropertyAnimation.State.Running and self._animation.endValue() == level:
                return
            self._animation.stop()
            self._animation.setStartValue(self.slider.value())
            self._animation.setEndValue(level)
            self._animation.start()
        else:
            self._animation.stop()
            with QSignalBlocker(self.slider):
                self.slider.setValue(level)
            self._display_level(level)

    def _update(self):
        playback = self.playback
        device = playback.device
        device_id = device.get("id")
        device_changed = self._device_id != device_id
        if device_changed:
            self.close()
            self.slider.setSliderDown(False)
        self._device_id = device_id
        if not self.active:
            self.close()
            return
        available = playback.can_set_volume
        if not available:
            self.close()
        elif self._in_flight is not None and not playback.busy:
            completed, self._in_flight = self._in_flight, None
            if self._pending == completed or device.get("volume_percent") != completed[1]:
                self._pending = None
            elif self._pending is not None and not self._write_timer.isActive():
                self._write_timer.start()
        self.slider.setEnabled(available)
        self.mute.setEnabled(available)
        self.slider.setAccessibleName("Spotify playback volume")
        text = playback.status
        if device_id and (not device.get("supports_volume", True) or device.get("is_restricted")):
            text = "This Spotify device does not support volume control."
        self.parent().setToolTip(f"Spotify playback volume · {text}")
        if not self.slider.isSliderDown() and self._pending is None and self._in_flight is None:
            level = device.get("volume_percent")
            if type(level) is int and level > 0:
                self._restore_volumes[device_id] = level
            if type(level) is int:
                self._show_level(level, animate=available and not device_changed)
            else:
                self.readout.setText("—")

    def volume_gesture(self):
        if not self.active or not self.slider.isEnabled() or not self.slider.isVisible() or self._device_id is None:
            return
        self._animation.stop()
        self._pending = (self._device_id, self.slider.sliderPosition())
        self._display_level(self.slider.sliderPosition())
        if not self._write_timer.isActive():
            self._write_timer.start()  # Throttle continuous dragging instead of waiting for it to stop.

    def toggle_mute(self):
        if self.playback.can_set_volume:
            level = self._pending[1] if self._pending is not None else self.playback.device["volume_percent"]
            if level > 0:
                self._restore_volumes[self._device_id] = level
            self._pending = (self._device_id, 0 if level else self._restore_volumes.get(self._device_id, 50))
            self._show_level(self._pending[1])
            self._write_volume()

    def _write_volume(self):
        self._write_timer.stop()
        if self._pending is None:
            return
        if not self.slider.isVisible() or not self.active:
            self._pending = None
            return
        if self.playback.busy or self._in_flight is not None:
            self._write_timer.start()
            return
        device_id, level = self._pending
        self._in_flight = self._pending
        if not self.playback.set_volume(device_id, level):
            self._pending = self._in_flight = None
            self._update()
