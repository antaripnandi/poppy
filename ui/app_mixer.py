"""Compact app-volume controls shared by Home and the hover player."""

import json
import os

from PySide6.QtCore import QFileInfo, QSignalBlocker, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileIconProvider, QHBoxLayout, QLabel, QLayout, QMenu, QPushButton,
    QToolTip, QVBoxLayout, QWidget, QWidgetAction,
)

from poppy.core.app_mixer import AppVolume, read_app_volumes, set_app_volume
from poppy.core.storage import data_path, write_json
from poppy.core.system_features import AudioEndpointManager
from poppy.ui.components import ClickableSlider, IconButton, ScrollArea
from poppy.ui.icons import Icons
from poppy.ui.spotify_controls import SpotifyVolumeBinding
from poppy.ui.theme import set_widget_style, surface_colors


class _AppVolumeSlider(ClickableSlider):
    def wheelEvent(self, event):
        event.ignore()  # Let the app list scroll without changing volume.


class AppMixerMenu(QMenu):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
        self._output = None
        self._last_apps = []
        self._rows = {}
        self._spotify_rows = {}
        self._spotify_restore_volumes = {}
        self._spotify_app = None
        self._spotify_connected = False
        self._playback = getattr(parent, "spotify_playback", None)
        self._spotify_timer = QTimer(self, interval=1000)
        if self._playback is not None:
            self._spotify_timer.timeout.connect(self._playback.refresh)
            self._playback.changed.connect(self._spotify_changed)
        self._pending_level = None
        self._level_timer = QTimer(self, interval=50, singleShot=True)
        self._level_timer.timeout.connect(self._flush_level)
        self._pin_file = data_path("mixer_pins.json")
        try:
            saved = json.loads(self._pin_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = []
        self._pins = list(dict.fromkeys(path for path in saved if isinstance(path, str)))[:24] if isinstance(saved, list) else []
        self._icons = QFileIconProvider()
        panel = QWidget()
        panel.setFixedWidth(400)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(7)

        self.title = QLabel("App mixer")
        set_widget_style(self.title, "font-family: 'Segoe UI'; font-weight: 700; font-size: 14px; color: #ffffff;")
        self.output = QLabel("Default playback output")
        self.output.setWordWrap(True)
        self.output.hide()
        layout.addWidget(self.title)
        layout.addWidget(self.output)

        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.scroll = ScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setMaximumHeight(230)
        body = QWidget()
        body.setObjectName("appMixerRows")
        self.rows = QVBoxLayout(body)
        self.rows.setContentsMargins(0, 0, 4, 0)
        self.rows.setSpacing(4)
        self.rows.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.scroll.setWidget(body)
        layout.addWidget(self.scroll)
        windows_mixer = QPushButton("Windows volume mixer")
        windows_mixer.setObjectName("mixerWinMixer")
        windows_mixer.setCursor(Qt.CursorShape.PointingHandCursor)
        windows_mixer.clicked.connect(self._open_windows_mixer)
        layout.addWidget(windows_mixer, alignment=Qt.AlignmentFlag.AlignLeft)

        action = QWidgetAction(self)
        action.setDefaultWidget(panel)
        self.addAction(action)
        self._refresh_timer = QTimer(self, interval=750)
        self._refresh_timer.timeout.connect(self.refresh)
        self.aboutToHide.connect(self._closed)

    def prepare(self):
        colors = surface_colors()
        accent = "#f28c5a"
        if hasattr(self.parent(), "_theme") and isinstance(self.parent()._theme, dict):
            accent = self.parent()._theme.get("accent", "#f28c5a")
        self.setStyleSheet(f"""
            QMenu {{
                background-color: #161a22;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 14px;
                padding: 4px;
            }}
            QMenu::item {{
                background: transparent;
                padding: 0;
            }}
            QLabel {{
                color: #ffffff;
                font-family: 'Segoe UI', -apple-system, sans-serif;
            }}
            QScrollArea, QScrollArea > QWidget, QWidget#appMixerRows {{
                background: transparent;
                border: none;
            }}
            QAbstractScrollArea::corner, QScrollBar::corner {{ background: transparent; }}
            QScrollBar:vertical {{
                background: transparent;
                width: 6px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(255, 255, 255, 0.2);
                border-radius: 3px;
                min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
                background: transparent;
            }}
            QSlider {{
                height: 22px;
            }}
            QSlider:focus {{ border: none; outline: none; }}
            QSlider::groove:horizontal {{
                height: 5px;
                background: rgba(255, 255, 255, 0.12);
                border-radius: 2.5px;
            }}
            QSlider::sub-page:horizontal {{
                background: {accent};
                border-radius: 2.5px;
            }}
            QSlider::handle:horizontal {{
                width: 14px;
                height: 14px;
                margin: -4.5px 0;
                border-radius: 7px;
                background: #ffffff;
            }}
            QSlider::handle:horizontal:hover {{
                background: {accent};
            }}
            QPushButton#mixerMute {{
                background: rgba(255, 255, 255, 0.06);
                border: 1px solid rgba(255, 255, 255, 0.09);
                border-radius: 6px;
                color: rgba(255, 255, 255, 0.85);
                font-family: 'Segoe UI';
                font-size: 11px;
                font-weight: 600;
                padding: 3px 6px;
            }}
            QPushButton#mixerMute:hover {{
                background: rgba(255, 255, 255, 0.12);
            }}
            QPushButton#mixerMute[app_muted="true"] {{
                background: rgba(239, 68, 68, 0.2);
                border: 1px solid rgba(239, 68, 68, 0.4);
                color: #fca5a5;
            }}
            QPushButton#mixerWinMixer {{
                background: transparent;
                border: none;
                color: {accent};
                font-family: 'Segoe UI';
                font-size: 11.5px;
                font-weight: 600;
                padding: 4px 0;
            }}
            QPushButton#mixerWinMixer:hover {{
                text-decoration: underline;
            }}
        """)
        for label in (self.output, self.status):
            set_widget_style(label, f"color: {colors['muted']}; font-family: 'Segoe UI'; font-size: 11px;")
        self.refresh()
        self._refresh_timer.start()
        self._sync_spotify_polling()
        if self._playback is not None and self._playback.connected:
            self._playback.refresh()

    def refresh(self):
        try:
            output, apps = read_app_volumes()
            self._last_apps = apps
        except OSError:
            output, apps = self._output, self._last_apps
        self._spotify_connected = self._playback is not None and self._playback.connected
        if self._spotify_connected:
            spotify = next((app for app in apps if self._is_spotify(app)), None)
            self._spotify_app = spotify or self._spotify_app or AppVolume("Spotify", "", (), 0, False, False)
            # Spotify Connect is independent of Windows' changing audio-session IDs.
            source = self._spotify_app
            stable = AppVolume(source.name, source.path, ("spotify-playback",), 0, False, False)
            apps = sorted([app for app in apps if not self._is_spotify(app)] + [stable],
                          key=lambda app: (app.name.casefold(), app.sessions))
        else:
            self._spotify_app = None
        if self._output != output:
            for key in tuple(self._rows):
                if key not in self._spotify_rows or not self._spotify_rows[key].active:
                    self._remove_row(key)
            self._output = output
            name = next((item["name"] for item in AudioEndpointManager.get_output_endpoints()
                         if item["id"] == output), "Default playback output") if output else ""
            self.output.setText(name)
            self.output.setVisible(bool(name))
        if any(slider.isSliderDown() for _, slider, _, _ in self._rows.values()):
            return
        wanted = {app.sessions for app in apps}
        for key in self._rows.keys() - wanted:
            self._remove_row(key)
        pin_order = {key: index for index, key in enumerate(self._pins)}
        ordered = sorted(apps, key=lambda app: pin_order.get(self._app_key(app), len(pin_order)))
        for index, app in enumerate(ordered):
            if app.sessions not in self._rows:
                self._add_row(app)
            row, slider, readout, mute = self._rows[app.sessions]
            if self.rows.indexOf(row) != index:
                self.rows.removeWidget(row)
                self.rows.insertWidget(index, row)
            pin = row.findChild(IconButton, "mixerPin")
            if pin:
                pinned = self._app_key(app) in self._pins
                label = f"{'Unpin' if pinned else 'Pin'} {app.name}"
                pin.setText(Icons.UNPIN if pinned else Icons.PIN)
                pin.setAccessibleName(label)
                pin.setToolTip(label)
            binding = self._spotify_rows.get(app.sessions)
            if binding is not None and binding.active and getattr(binding.playback, "can_set_volume", False):
                binding._update()
            else:
                slider.setEnabled(True)
                mute.setEnabled(True)
                row.setToolTip(f"{app.name} · Windows app volume")
                slider.setAccessibleName(f"{app.name} volume")
                target_app = self._spotify_app if (app.sessions == ("spotify-playback",) and self._spotify_app) else app
                with QSignalBlocker(slider):
                    slider.setValue(target_app.volume)
                readout.setText("Mixed" if target_app.mixed else f"{target_app.volume}%")
                mute.setText("Unmute" if target_app.muted else "Mute")
                mute.setAccessibleName(f"{mute.text()} {target_app.name}")
                mute.setProperty("app_muted", target_app.muted)
                mute.style().unpolish(mute)
                mute.style().polish(mute)
        self.status.setText("Start playing sound in an app to adjust it here." if output
                            else "Windows playback output is unavailable.")
        self.status.setVisible(not apps)
        self.scroll.setVisible(bool(apps))
        if apps:
            self.scroll.setFixedHeight(min(230, self.rows.sizeHint().height()))

    def _clear_rows(self):
        for key in tuple(self._rows):
            self._remove_row(key)

    @staticmethod
    def _is_spotify(app):
        return app.name.casefold() == "spotify" or os.path.basename(app.path).casefold() == "spotify.exe"

    def _sync_spotify_polling(self):
        if self._playback is not None and self._playback.connected:
            if not self._spotify_timer.isActive():
                self._spotify_timer.start()
        else:
            self._spotify_timer.stop()

    def _spotify_changed(self):
        if self.isVisible():
            self._sync_spotify_polling()
            if self._spotify_connected != self._playback.connected:
                self.refresh()

    def _closed(self):
        self._refresh_timer.stop()
        self._spotify_timer.stop()
        self._clear_rows()

    def _remove_row(self, key):
        binding = self._spotify_rows.pop(key, None)
        if binding is not None:
            binding.close()
        row, slider, _, mute = self._rows.pop(key)
        if self._pending_level and self._pending_level[0] is slider:
            self._level_timer.stop()
            self._pending_level = None
        slider.blockSignals(True)
        slider.setSliderDown(False)
        mute.blockSignals(True)
        self.rows.removeWidget(row)
        row.hide()
        row.deleteLater()

    def _add_row(self, app):
        row = QWidget()
        row.setObjectName("mixerRow")
        set_widget_style(row, """
            QWidget#mixerRow {
                background: rgba(255, 255, 255, 0.035);
                border: 1px solid rgba(255, 255, 255, 0.06);
                border-radius: 8px;
            }
            QWidget#mixerRow:hover {
                background: rgba(255, 255, 255, 0.06);
            }
        """)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        artwork = QLabel()
        artwork.setFixedSize(20, 20)
        artwork.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if app.path and os.path.exists(app.path):
            artwork.setPixmap(self._icons.icon(QFileInfo(app.path)).pixmap(20, 20))
        else:
            set_widget_style(artwork, "font-family: 'Segoe UI'; font-size: 13px; color: #a7adab; background: transparent;")
            artwork.setText(Icons.VOLUME)
        layout.addWidget(artwork)

        name = QLabel(app.name)
        name.setTextFormat(Qt.TextFormat.PlainText)
        name.setToolTip(app.name)
        name.setFixedWidth(94)
        set_widget_style(name, "font-family: 'Segoe UI'; font-size: 12px; font-weight: 600; color: #ffffff; background: transparent;")
        layout.addWidget(name)

        slider = _AppVolumeSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setAccessibleName(f"{app.name} volume")
        layout.addWidget(slider, 1)

        readout = QLabel(f"{app.volume}%")
        readout.setFixedWidth(38)
        readout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        set_widget_style(readout, "font-family: 'Segoe UI'; font-size: 11px; font-weight: 600; color: rgba(255, 255, 255, 0.85); background: transparent;")
        layout.addWidget(readout)

        mute = QPushButton("Unmute" if app.muted else "Mute")
        mute.setObjectName("mixerMute")
        mute.setProperty("app_muted", app.muted)
        mute.setFixedWidth(56)
        mute.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(mute)

        key = self._app_key(app)
        if key:
            pin = IconButton(Icons.PIN, f"Pin {app.name}", size=24, font_size=11, is_fluent=True)
            pin.setObjectName("mixerPin")
            pin.clicked.connect(lambda: self._toggle_pin(key, pin))
            layout.addWidget(pin)

        output = self._output
        slider.sliderMoved.connect(lambda value: readout.setText(f"{value}%"))
        slider.actionTriggered.connect(lambda _: self._slider_action(slider, output, app.sessions))
        slider.sliderReleased.connect(lambda: self._finish_level(slider))
        mute.clicked.connect(lambda: self._apply(output, app.sessions, muted=not mute.property("app_muted")))
        self._rows[app.sessions] = row, slider, readout, mute
        if self._playback is not None and self._is_spotify(app):
            self._spotify_rows[app.sessions] = SpotifyVolumeBinding(
                self._playback, slider, readout, mute, row, self._spotify_restore_volumes)
        self.rows.addWidget(row)

    @staticmethod
    def _app_key(app):
        return os.path.normcase(app.path) if app.path else ""

    def _toggle_pin(self, key, button):
        pins = [item for item in self._pins if item != key]
        if key not in self._pins:
            pins.insert(0, key)
        pins = pins[:24]
        try:
            write_json(self._pin_file, pins)
        except OSError:
            QToolTip.showText(button.mapToGlobal(button.rect().bottomLeft()), "Could not save mixer pins.", button)
            return
        self._pins = pins
        self.refresh()

    def _slider_action(self, slider, output, sessions):
        binding = self._spotify_rows.get(sessions)
        if binding is not None and binding.active and getattr(binding.playback, "can_set_volume", False):
            binding.volume_gesture()
            return
        real_sessions = sessions
        if sessions == ("spotify-playback",) and self._spotify_app and self._spotify_app.sessions:
            real_sessions = self._spotify_app.sessions
        level = slider.sliderPosition()
        if not slider.isVisible() or level == slider.value():
            return
        if slider.isSliderDown():
            self._pending_level = slider, output, real_sessions, level
            if not self._level_timer.isActive():
                self._level_timer.start()
        else:
            self._apply(output, real_sessions, level=level)

    def _flush_level(self):
        pending, self._pending_level = self._pending_level, None
        if pending:
            slider, output, sessions, level = pending
            if self.isVisible() and slider.isVisible():
                self._apply(output, sessions, level=level)

    def _finish_level(self, slider):
        binding = next((item for item in self._spotify_rows.values() if item.slider is slider), None)
        if binding is not None and binding.active and getattr(binding.playback, "can_set_volume", False):
            binding._write_volume()
            return
        if self._pending_level and self._pending_level[0] is slider:
            self._level_timer.stop()
            self._flush_level()
        QTimer.singleShot(0, self, self._refresh_if_open)

    def _apply(self, output, sessions, **change):
        binding = self._spotify_rows.get(sessions)
        if binding is not None and binding.active and getattr(binding.playback, "can_set_volume", False):
            if "muted" in change:
                binding.toggle_mute()
            return
        real_sessions = sessions
        if sessions == ("spotify-playback",) and self._spotify_app and self._spotify_app.sessions:
            real_sessions = self._spotify_app.sessions
        try:
            set_app_volume(output, real_sessions, **change)
        except OSError as error:
            QToolTip.showText(self.mapToGlobal(self.rect().bottomLeft()), str(error), self)
        if not any(slider.isSliderDown() for _, slider, _, _ in self._rows.values()):
            QTimer.singleShot(0, self, self._refresh_if_open)

    def _refresh_if_open(self):
        if self.isVisible():
            self.refresh()

    def _open_windows_mixer(self):
        self.hide()
        QDesktopServices.openUrl(QUrl("ms-settings:apps-volume"))
