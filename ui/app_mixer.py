"""Compact app-volume controls shared by Home and the hover player."""

import json
import os

from PySide6.QtCore import QFileInfo, QSignalBlocker, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileIconProvider, QHBoxLayout, QLabel, QLayout, QMenu, QPushButton,
    QSlider, QToolTip, QVBoxLayout, QWidget, QWidgetAction,
)

from poppy.core.app_mixer import read_app_volumes, set_app_volume
from poppy.core.storage import data_path, write_json
from poppy.core.system_features import AudioEndpointManager
from poppy.ui.components import IconButton, ScrollArea
from poppy.ui.icons import Icons
from poppy.ui.theme import set_widget_style, surface_colors


class AppMixerMenu(QMenu):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
        self._output = None
        self._rows = {}
        self._pin_file = data_path("mixer_pins.json")
        try:
            saved = json.loads(self._pin_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = []
        self._pins = list(dict.fromkeys(path for path in saved if isinstance(path, str)))[:24] if isinstance(saved, list) else []
        self._icons = QFileIconProvider()
        panel = QWidget()
        panel.setFixedWidth(386)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(7)

        self.title = QLabel("App mixer")
        set_widget_style(self.title, "font-weight: 600; font-size: 14px;")
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
        self.setStyleSheet(f"""
            QMenu {{ background: {colors['root']}; border: 1px solid {colors['card']}; padding: 0; }}
            QLabel {{ color: {colors['text']}; }}
            QScrollArea, QScrollArea > QWidget, QWidget#appMixerRows {{
                background: {colors['root']}; border: none;
            }}
            QScrollBar::corner {{ background: transparent; }}
            QSlider::groove:horizontal {{ height: 3px; background: {colors['card']}; }}
            QSlider::sub-page:horizontal {{ background: {colors['muted']}; }}
            QSlider::handle:horizontal {{
                width: 9px; margin: -3px 0; border-radius: 4px; background: {colors['text']};
            }}
            QSlider:focus {{ border: 1px solid {colors['muted']}; border-radius: 4px; }}
        """)
        for label in (self.output, self.status):
            set_widget_style(label, f"color: {colors['muted']};")
        self.refresh()
        self._refresh_timer.start()

    def refresh(self):
        try:
            output, apps = read_app_volumes()
        except OSError:
            output, apps = None, []
        if self._output != output:
            self._clear_rows()
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
            with QSignalBlocker(slider):
                slider.setValue(app.volume)
            readout.setText("Mixed" if app.mixed else f"{app.volume}%")
            mute.setText("Unmute" if app.muted else "Mute")
            mute.setAccessibleName(f"{mute.text()} {app.name}")
            mute.setProperty("app_muted", app.muted)
        self.status.setText("Start playing sound in an app to adjust it here." if output
                            else "Windows playback output is unavailable.")
        self.status.setVisible(not apps)
        self.scroll.setVisible(bool(apps))
        if apps:
            self.scroll.setFixedHeight(min(230, self.rows.sizeHint().height()))

    def _clear_rows(self):
        for key in tuple(self._rows):
            self._remove_row(key)

    def _closed(self):
        self._refresh_timer.stop()
        self._clear_rows()

    def _remove_row(self, key):
        row, slider, _, mute = self._rows.pop(key)
        slider.blockSignals(True)
        slider.setSliderDown(False)
        mute.blockSignals(True)
        self.rows.removeWidget(row)
        row.hide()
        row.deleteLater()

    def _add_row(self, app):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(8)
        name = QLabel(app.name)
        name.setTextFormat(Qt.TextFormat.PlainText)
        name.setToolTip(app.name)
        name.setWordWrap(True)
        name.setFixedWidth(86)
        artwork = QLabel()
        artwork.setFixedWidth(18)
        if app.path:
            artwork.setPixmap(self._icons.icon(QFileInfo(app.path)).pixmap(18, 18))
        layout.addWidget(artwork)
        layout.addWidget(name)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setTracking(False)
        slider.setAccessibleName(f"{app.name} volume")
        layout.addWidget(slider, 1)
        readout = QLabel()
        readout.setFixedWidth(42)
        readout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(readout)
        mute = QPushButton()
        mute.setFixedWidth(64)
        layout.addWidget(mute)
        key = self._app_key(app)
        if key:
            pin = IconButton(Icons.PIN, f"Pin {app.name}", size=24, font_size=12, is_fluent=True)
            pin.setObjectName("mixerPin")
            pin.clicked.connect(lambda: self._toggle_pin(key, pin))
            layout.addWidget(pin)
        output = self._output
        slider.sliderMoved.connect(lambda value: readout.setText(f"{value}%"))
        slider.actionTriggered.connect(lambda _: self._slider_action(slider, output, app.sessions))
        mute.clicked.connect(lambda: self._apply(output, app.sessions, muted=not mute.property("app_muted")))
        self._rows[app.sessions] = row, slider, readout, mute
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
        level = slider.sliderPosition()
        if slider.isVisible() and level != slider.value():
            self._apply(output, sessions, level=level)

    def _apply(self, output, sessions, **change):
        try:
            set_app_volume(output, sessions, **change)
        except OSError:
            pass
        QTimer.singleShot(0, self, self._refresh_if_open)

    def _refresh_if_open(self):
        if self.isVisible():
            self.refresh()

    def _open_windows_mixer(self):
        self.hide()
        QDesktopServices.openUrl(QUrl("ms-settings:apps-volume"))
