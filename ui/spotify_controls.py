"""Spotify account connection and playback-volume controls."""

from PySide6.QtCore import QEvent, QSignalBlocker, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from poppy.core.spotify_playback import REDIRECT_URI
from poppy.ui.components import ClickableSlider
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


class SpotifyVolumeControls(QWidget):
    def __init__(self, playback, open_settings, parent=None):
        super().__init__(parent)
        self.playback = playback
        self._device_id = None
        self._pending = None
        self._timer = QTimer(self, interval=2000)
        self._timer.timeout.connect(playback.refresh)
        self._write_timer = QTimer(self, interval=150, singleShot=True)
        self._write_timer.timeout.connect(self._write_volume)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(5)
        header = QHBoxLayout()
        header.addWidget(QLabel("Spotify playback volume"))
        header.addStretch()
        self.account = QPushButton("Connect")
        self.account.clicked.connect(open_settings)
        header.addWidget(self.account)
        layout.addLayout(header)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.slider.setAccessibleName("Spotify playback volume")
        self.slider.setRange(0, 100)
        self.slider.installEventFilter(self)
        self.slider.setEnabled(False)
        self.slider.actionTriggered.connect(self._volume_gesture)
        self.slider.sliderReleased.connect(self._write_volume)
        self.readout = QLabel("—")
        self.readout.setMinimumWidth(34)
        row.addWidget(self.slider, 1)
        row.addWidget(self.readout)
        layout.addLayout(row)
        playback.changed.connect(self._update)
        self._update()

    def showEvent(self, event):
        super().showEvent(event)
        self._update()
        if self.playback.connected:
            self.playback.refresh()
            self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()
        self._write_timer.stop()
        self._pending = None
        self.slider.setSliderDown(False)
        super().hideEvent(event)

    def _update(self):
        playback = self.playback
        device = playback.device
        device_id = device.get("id")
        if self._device_id != device_id:
            self._pending = None
            self._write_timer.stop()
            self.slider.setSliderDown(False)
        self._device_id = device_id
        self.slider.setEnabled(playback.connected and playback.can_set_volume)
        self.account.setText("Account" if playback.connected else "Connect")
        text = playback.status
        if device_id and not playback.can_set_volume:
            text = "This Spotify device does not support volume control."
        self.status.setText(text)
        if not self.slider.isSliderDown() and self._pending is None:
            level = device.get("volume_percent")
            with QSignalBlocker(self.slider):
                self.slider.setValue(level if type(level) is int else 0)
            self.readout.setText(f"{level}%" if type(level) is int else "—")
        if self.isVisible() and playback.connected and not self._timer.isActive():
            self._timer.start()
        elif not playback.connected:
            self._timer.stop()

    def _volume_gesture(self, action):
        if not self.slider.isEnabled() or not self.isVisible() or self._device_id is None:
            return
        self._pending = (self._device_id, self.slider.sliderPosition())
        self.readout.setText(f"{self.slider.sliderPosition()}%")
        self._write_timer.start()

    def eventFilter(self, watched, event):
        if watched is self.slider and event.type() == QEvent.Type.Wheel:
            event.ignore()
            return True
        return super().eventFilter(watched, event)

    def _write_volume(self):
        self._write_timer.stop()
        if self._pending is None:
            return
        if not self.isVisible() or not self.playback.connected:
            self._pending = None
            return
        if self.playback.busy:
            self._write_timer.start()
            return
        device_id, level = self._pending
        self._pending = None
        if self.playback.set_volume(device_id, level):
            QTimer.singleShot(800, self.playback, self.playback.refresh)
        else:
            self._update()
