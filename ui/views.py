"""
Poppy Tab Views
Faithfully inspired by NotchX's official interface (home-v2.png, now-playing-v2.png).
"""

import os
import ast
import operator as op
import re
import time
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QUrl, QMimeData, QTimer, QSize, QRect, QEvent
from PySide6.QtGui import QPixmap, QImage, QColor, QPainter, QPainterPath, QDesktopServices, QFont, QPalette
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QLineEdit, QTextEdit, QPushButton, QSlider,
    QFrame, QScrollArea, QApplication, QMenu, QSizePolicy, QFileDialog, QLayout, QBoxLayout,
    QComboBox, QSpinBox, QStackedWidget
)

from poppy.ui.theme import set_widget_style, LAYOUT_THEMES, is_light_theme, current_layout, home_order, home_slots
from poppy.ui.components import (
    IconButton, CircularProgressRing, MetricLabel, SquircleTileButton,
    CardFrame, DraggableThumbnail, ClickableSlider, SpotifyLyricsWidget,
    ScreenTimeHomeWidget, CapsuleSlider, ScrollArea, PlaybackSlider,
    ControlPillTile, StatRingGauge, WaveformSeekBar, StackedClockWidget,
    WeekCalendarStrip, PomodoroFocusWidget, TodoChecklistWidget
)
from poppy.ui.icons import Icons
from poppy.core.storage import data_path, write_text
from poppy.core.lyrics_manager import LyricsManager


def _visible_sessions(sessions, active_index, limit=4):
    visible = list(sessions[:limit])
    active = next((session for session in sessions if session["index"] == active_index), None)
    if active is not None and active not in visible:
        visible[-1] = active
    return visible


class WeatherLabel(QLabel):
    """Keep the full forecast available while the dashboard row stays compact."""

    def setText(self, text):
        self._forecast = text
        self._fit_forecast()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_forecast()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._fit_forecast()

    def _fit_forecast(self):
        if hasattr(self, "_forecast"):
            super().setText(self.fontMetrics().elidedText(self._forecast, Qt.TextElideMode.ElideRight, self.width()))


class HomeTabView(QWidget):
    """Home dashboard featuring 4 responsive cards inspired by home-v2.png."""
    tear_off_requested = Signal(str)
    pin_requested = Signal(str)
    caffeine_toggle_requested = Signal()
    mic_mute_toggle_requested = Signal()
    focus_shield_requested = Signal()
    screen_snip_requested = Signal()
    eyedropper_requested = Signal()
    quick_search_requested = Signal()
    lock_workstation_requested = Signal()
    player_menu_requested = Signal()
    audio_device_menu_requested = Signal()
    audio_gear_menu_requested = Signal(object)
    bluetooth_menu_requested = Signal()
    weather_refresh_requested = Signal()
    screentime_clicked = Signal()
    customize_requested = Signal()
    layout_changed = Signal()

    @staticmethod
    def _kicker_font() -> QFont:
        font = QFont("Segoe UI")
        font.setPixelSize(10)
        font.setWeight(QFont.Weight.Bold)
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 108.0)
        return font

    def __init__(self, parent=None):
        super().__init__(parent)
        self._latest_shelf_path = ""
        self._track_title = "Nothing playing"
        self._track_artist = ""
        self._audio_muted = False
        self._layout_name = "Classic"
        self._dashboard_wide = True
        self._hidden_sections = set()
        self._init_ui()
        self._design_sources = {widget: widget.property("poppyStyleSource") for widget in
            (self.lbl_big_time, self.lbl_date, self.txt_notes, self.lbl_music_title, self.lbl_music_artist,
             self.lbl_notes_title, self.lbl_shelf_status)}
        self._design_headers = []
        for card, text in ((self.card_clock, "SYSTEM"), (self.card_controls, "CONTROLS")):
            label = QLabel(text)
            label.setFont(self._kicker_font())
            card.layout().insertWidget(0, label)
            label.hide()
            self._design_headers.append(label)

    def _init_ui(self):
        home = QVBoxLayout(self)
        home.setContentsMargins(12, 8, 12, 10)
        home.setSpacing(12)
        self._init_player()
        home.addWidget(self.mini_player)

        body = QWidget()
        body.setObjectName("homeBody")
        set_widget_style(body, "QWidget#homeBody { background: transparent; }")
        self.body_layout = QGridLayout(body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.home_scroll = ScrollArea()
        self.home_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.home_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.home_scroll.setWidgetResizable(True)
        self.home_scroll.setWidget(body)
        self.home_scroll.setAccessibleName("Home dashboard")
        self.home_scroll.verticalScrollBar().setSingleStep(24)
        set_widget_style(self.home_scroll, """
            QScrollArea { background: transparent; border: none; }
            QAbstractScrollArea::corner, QScrollBar::corner { background: transparent; border: none; }
            QScrollBar:horizontal { height: 0px; }
        """)
        home.addWidget(self.home_scroll, 1)

        grid = QGridLayout()
        self.dashboard_grid = grid
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)
        self.body_layout.addLayout(grid, 0, 0)
        self.body_layout.setColumnStretch(0, 3)
        self.body_layout.setRowStretch(0, 1)
        self.screentime_widget = ScreenTimeHomeWidget()
        self.screentime_widget.clicked.connect(self.screentime_clicked.emit)
        self.body_layout.addWidget(self.screentime_widget, 1, 0)
        self.screentime_widget.hide()
        self.btn_customize = self._text_action("Customize Home", "Choose which sections appear on Home")
        self.btn_customize.clicked.connect(self.customize_requested.emit)
        home.addWidget(self.btn_customize, alignment=Qt.AlignmentFlag.AlignCenter)
        self.btn_customize.hide()

        # -------------------------------------------------------------
        # Card 1: Clock, Date & Hardware Telemetry (home-v2 Card 1)
        # -------------------------------------------------------------
        card_clock = CardFrame(self)
        self.card_clock = card_clock
        l_clock = QVBoxLayout(card_clock)
        l_clock.setContentsMargins(18, 16, 18, 14)
        l_clock.setSpacing(4)

        self.lbl_big_time = QLabel("12:11:29 AM")
        set_widget_style(self.lbl_big_time, """
            QLabel {
                font-size: 36px;
                font-weight: 700;
                color: #ffffff;
                background: transparent;
                border: none;
            }
        """)
        self.lbl_date = QLabel("Monday, 5 October")
        set_widget_style(self.lbl_date, "QLabel { font-size: 11.5px; color: rgba(255, 255, 255, 0.65); font-weight: 500; background: transparent; border: none; }")

        self.lbl_weather_text = WeatherLabel()
        self.lbl_weather_text.setText("Fetching weather…")
        self.lbl_weather_text.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_weather_text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        set_widget_style(self.lbl_weather_text, "font-size: 12.5px; font-weight: 600; color: #f28c5a; background: transparent;")
        self.lbl_weather_text.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_weather_text.setToolTip("Refresh weather")
        self.lbl_weather_text.mousePressEvent = lambda e: self.weather_refresh_requested.emit()

        # Hardware readings
        telemetry_row = QGridLayout()
        self.telemetry_grid = telemetry_row
        telemetry_row.setSpacing(6)
        self.lbl_cpu = MetricLabel("CPU", "--%")
        self.lbl_gpu = MetricLabel("GPU", "--%")
        self.lbl_ram = MetricLabel("RAM", "--%")
        self.lbl_bat = MetricLabel("Battery", "--%")
        self.metrics = (self.lbl_cpu, self.lbl_gpu, self.lbl_ram, self.lbl_bat)
        for column, metric in enumerate(self.metrics):
            telemetry_row.addWidget(metric, 0, column)
            telemetry_row.setColumnStretch(column, 1)
        self.clock_face = QBoxLayout(QBoxLayout.Direction.TopToBottom)
        self.clock_face.setSpacing(4)
        self.clock_detail = QVBoxLayout()
        self.clock_detail.setSpacing(2)
        self.clock_detail.addWidget(self.lbl_big_time)
        self.clock_detail.addWidget(self.lbl_weather_text)
        self.clock_face.addLayout(self.clock_detail)
        self.clock_face.addWidget(self.lbl_date)
        l_clock.addLayout(self.clock_face)

        l_clock.addStretch()
        l_clock.addLayout(telemetry_row)
        grid.addWidget(card_clock, 0, 0)

        # -------------------------------------------------------------
        # System controls stay separate from playback.
        card_controls = CardFrame(self)
        self.card_controls = card_controls
        l_ctrl = QVBoxLayout(card_controls)
        self.controls_layout = l_ctrl
        l_ctrl.setContentsMargins(18, 14, 18, 14)
        l_ctrl.setSpacing(6)

        self.slider_vol = CapsuleSlider(icon=Icons.VOLUME, parent=self, compact_track=False)
        self.slider_bright = CapsuleSlider(icon=Icons.BRIGHTNESS, parent=self, compact_track=False)
        for slider, label in ((self.slider_vol, "Volume"), (self.slider_bright, "Brightness")):
            slider.setAccessibleName(label)
            slider.setToolTip(label)
            slider.installEventFilter(self)

        self.vol_row_widget = QWidget(card_controls)
        vol_row = QHBoxLayout(self.vol_row_widget)
        vol_row.setContentsMargins(0, 0, 0, 0)
        vol_row.setSpacing(4)
        vol_row.addWidget(self.slider_vol, 1)
        self.btn_audio_gear = IconButton(Icons.SETTINGS, "Audio options (Mute, App mixer, Sound output)",
                                         parent=self.vol_row_widget, size=26, font_size=13, is_fluent=True)
        self.btn_audio_gear.clicked.connect(lambda: self.audio_gear_menu_requested.emit(self.btn_audio_gear))
        vol_row.addWidget(self.btn_audio_gear)
        l_ctrl.addWidget(self.vol_row_widget)
        l_ctrl.addWidget(self.slider_bright)

        # Hidden compatibility triggers (surfaced inside the volume gear menu)
        self.btn_vol_mute = self._text_action("Mute", "Mute system audio")
        self.btn_app_mixer = self._text_action("App mixer", "Set volume and mute for individual apps")
        self.btn_audio_drop = self._text_action("Sound output", "Choose an output or open Windows Sound Settings")
        self.btn_audio_drop.clicked.connect(self.audio_device_menu_requested.emit)
        for hidden_btn in (self.btn_vol_mute, self.btn_app_mixer, self.btn_audio_drop):
            hidden_btn.setParent(card_controls)
            hidden_btn.hide()

        actions = QGridLayout()
        self.quick_actions_grid = actions
        actions.setContentsMargins(0, 2, 0, 0)
        actions.setSpacing(6)
        self.quick_actions = []
        for index, (attr, icon_glyph, label, tip, signal, toggle) in enumerate((
            ("btn_act_caffeine", Icons.POWER, "Awake", "Keep the PC awake", self.caffeine_toggle_requested, True),
            ("btn_act_mic", Icons.MIC, "Mic", "Mute or unmute microphone", self.mic_mute_toggle_requested, True),
            ("btn_act_shield", Icons.SHIELD, "Focus", "Start or pause a focus sprint", self.focus_shield_requested, True),
            ("btn_act_snip", Icons.SNIP, "Snip", "Take a screen snip", self.screen_snip_requested, False),
            ("btn_act_eyedropper", Icons.COLOR, "Color", "Pick a screen color", self.eyedropper_requested, False),
            ("btn_act_search", Icons.CALCULATOR, "Calc", "Open calculator in commands", self.quick_search_requested, False),
            ("btn_act_bt", Icons.BLUETOOTH, "Bluetooth", "Show Bluetooth devices", self.bluetooth_menu_requested, False),
            ("btn_dev_lock", Icons.LOCK, "Lock", "Lock Windows", self.lock_workstation_requested, False),
        )):
            button = SquircleTileButton(icon_glyph, label, tip, toggle=toggle, parent=card_controls)
            button.clicked.connect(signal.emit)
            setattr(self, attr, button)
            self.quick_actions.append((button, label, button.property("poppyStyleSource")))
            actions.addWidget(button, index // 4, index % 4)
        for col in range(4):
            actions.setColumnStretch(col, 1)
        l_ctrl.addLayout(actions)
        l_ctrl.addStretch()
        grid.addWidget(card_controls, 0, 1)

        # -------------------------------------------------------------
        # Card 3: Notes & Scratchpad (home-v2 Card 3)
        # -------------------------------------------------------------
        card_notes = CardFrame(self)
        self.card_notes = card_notes
        l_notes = QVBoxLayout(card_notes)
        l_notes.setContentsMargins(16, 12, 16, 12)
        l_notes.setSpacing(8)

        notes_hdr = QHBoxLayout()
        lbl_notes_title = QLabel("SCRATCHPAD")
        lbl_notes_title.setFont(self._kicker_font())
        self.lbl_notes_title = lbl_notes_title
        set_widget_style(lbl_notes_title, "QLabel { font-size: 10px; font-weight: 700; color: rgba(255, 255, 255, 0.35); background: transparent; border: none; }")
        self.btn_pop_note = self._text_action("Floating copy", "Open a floating copy of these notes")
        self.btn_pop_note.clicked.connect(self._on_tear_off)
        notes_hdr.addWidget(lbl_notes_title)
        notes_hdr.addStretch()
        notes_hdr.addWidget(self.btn_pop_note)
        l_notes.addLayout(notes_hdr)

        self.txt_notes = QTextEdit()
        self.txt_notes.setMinimumHeight(64)
        self.txt_notes.setPlaceholderText("Jot something down...")
        notes_pal = self.txt_notes.palette()
        notes_pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(255, 255, 255, 64))
        self.txt_notes.setPalette(notes_pal)
        set_widget_style(self.txt_notes, """
            QTextEdit {
                background: rgba(0, 0, 0, 0.25);
                border: 1px solid rgba(255, 255, 255, 0.04);
                border-radius: 8px;
                padding: 10px;
                color: #f1f5f9;
                font-size: 12px;
            }
            QTextEdit:focus {
                border: 1px solid rgba(100, 160, 240, 0.4);
            }
        """)
        self._notes_file = data_path("home_notes.txt")
        if self._notes_file.exists():
            try:
                self.txt_notes.setPlainText(self._notes_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        self._notes_timer = QTimer(self)
        self._notes_timer.setSingleShot(True)
        self._notes_timer.setInterval(600)
        self._notes_timer.timeout.connect(self._save_notes)
        self.txt_notes.textChanged.connect(self._notes_timer.start)
        l_notes.addWidget(self.txt_notes)
        self.lbl_note_save = QLabel("")
        self.lbl_note_save.setWordWrap(False)
        l_notes.addWidget(self.lbl_note_save)
        grid.addWidget(card_notes, 1, 0)

        # -------------------------------------------------------------
        # Card 4: Quick Shelf & Calculator
        # -------------------------------------------------------------
        card_shelf = CardFrame(self)
        self.card_shelf = card_shelf
        l_shelf = QVBoxLayout(card_shelf)
        l_shelf.setContentsMargins(18, 14, 18, 14)
        l_shelf.setSpacing(6)

        shelf_hdr = QHBoxLayout()
        self.lbl_shelf_status = QLabel("Shelf · 0 files")
        set_widget_style(self.lbl_shelf_status, "font-size: 13px; font-weight: 500; color: #edf1f0; background: transparent;")
        self.btn_clear_shelf = self._text_action("Clear", "Clear the shelf")
        self.btn_clear_shelf.hide()
        shelf_hdr.addWidget(self.lbl_shelf_status)
        shelf_hdr.addStretch()
        shelf_hdr.addWidget(self.btn_clear_shelf)
        l_shelf.addLayout(shelf_hdr)

        # Primary staged file row (latest file with Copy/Pin actions)
        self.shelf_preview_frame = QFrame()
        set_widget_style(self.shelf_preview_frame, """
            QFrame {
                background: rgba(255, 255, 255, 0.03);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
            QFrame:hover {
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.14);
            }
        """)
        spf_layout = QHBoxLayout(self.shelf_preview_frame)
        spf_layout.setContentsMargins(6, 4, 6, 4)
        spf_layout.setSpacing(8)

        self.shelf_thumb = DraggableThumbnail(size=30, border_radius=6, parent=self)
        spf_layout.addWidget(self.shelf_thumb)

        meta_spf = QVBoxLayout()
        meta_spf.setSpacing(1)
        self.lbl_shelf_item_name = QLabel("Screenshot.png")
        self.lbl_shelf_item_name.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_shelf_item_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        set_widget_style(self.lbl_shelf_item_name, "font-size: 12px; font-weight: 600; color: #ffffff; background: transparent; border: none;")
        self.lbl_shelf_item_sub = QLabel()
        set_widget_style(self.lbl_shelf_item_sub, "font-size: 10.5px; color: rgba(255, 255, 255, 0.45); background: transparent; border: none;")
        meta_spf.addWidget(self.lbl_shelf_item_name)
        meta_spf.addWidget(self.lbl_shelf_item_sub)
        spf_layout.addLayout(meta_spf, stretch=1)

        self.btn_home_shelf_chat = QPushButton("Copy")
        self.btn_home_shelf_chat.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_home_shelf_chat.setToolTip("Copy file or image to clipboard")
        self.btn_home_shelf_chat.setMinimumWidth(52)
        spf_layout.addWidget(self.btn_home_shelf_chat)

        self.btn_home_shelf_pin = QPushButton("Pin")
        self.btn_home_shelf_pin.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_home_shelf_pin.setToolTip("Pin to screen as a floating sticky note")
        self.btn_home_shelf_pin.clicked.connect(lambda: self.pin_requested.emit(self._latest_shelf_path))
        spf_layout.addWidget(self.btn_home_shelf_pin)
        l_shelf.addWidget(self.shelf_preview_frame)
        self.shelf_preview_frame.setVisible(False)

        # Empty hint
        self.lbl_shelf_empty = QLabel("Drop files here")
        self.lbl_shelf_empty.setToolTip("Drop files or use Windows + Shift + S to take a snip")
        set_widget_style(self.lbl_shelf_empty, "font-size: 12px; color: rgba(255, 255, 255, 0.45); background: transparent; border: none;")
        l_shelf.addWidget(self.lbl_shelf_empty)

        # Inline Calculator
        calc_row = QHBoxLayout()
        calc_row.setSpacing(6)
        self.input_calc = QLineEdit()
        self.input_calc.setPlaceholderText("Calculate…")
        self.input_calc.setAccessibleName("Calculator")
        set_widget_style(self.input_calc, """
            QLineEdit {
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
                padding: 4px 10px;
                color: #ffffff;
                font-family: 'Segoe UI';
                font-size: 11px;
            }
            QLineEdit:focus {
                border: 1px solid rgba(10, 132, 255, 0.6);
                background: rgba(255, 255, 255, 0.07);
            }
        """)
        self.input_calc.textChanged.connect(self._eval_calc)
        self.lbl_calc_res = QLabel("")
        set_widget_style(self.lbl_calc_res, "QLabel { color: #38bdf8; font-size: 11px; font-weight: 600; background: transparent; border: none; }")
        calc_row.addWidget(self.input_calc, stretch=1)
        calc_row.addWidget(self.lbl_calc_res)
        l_shelf.addLayout(calc_row)

        l_shelf.addStretch()
        grid.addWidget(card_shelf, 1, 1)

    @staticmethod
    def _text_action(text, tip):
        button = QPushButton(text)
        button.setToolTip(tip)
        button.setAccessibleName(tip)
        button.setMinimumHeight(24)
        set_widget_style(button, """
            QPushButton {
                background: transparent; border: none; border-radius: 5px; outline: none;
                color: #b9bfbd; font-family: 'Segoe UI'; font-size: 12px; padding: 2px 5px;
            }
            QPushButton:hover, QPushButton:checked {
                background: rgba(255,255,255,0.08); color: #edf1f0;
            }
            QPushButton:focus {
                background: rgba(255,255,255,0.24); color: #edf1f0;
            }
        """)
        return button

    def _init_player(self):
        self.mini_player = CardFrame(self)
        self.mini_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self.mini_player)
        self.mini_layout.setContentsMargins(12, 8, 12, 8)
        self.mini_layout.setSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.mini_layout.addLayout(row, 1)

        self.lbl_music_art = QLabel(Icons.MUSIC)
        self.lbl_music_art.setFixedSize(36, 36)
        self.lbl_music_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_widget_style(self.lbl_music_art, """
            background: rgba(255,255,255,0.05); border-radius: 6px; color: #a7adab;
            font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets'; font-size: 16px;
        """)
        row.addWidget(self.lbl_music_art)

        metadata = QHBoxLayout()
        metadata.setSpacing(6)
        metadata.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.lbl_music_title = QLabel(self._track_title)
        self.lbl_music_sep = QLabel("·")
        self.lbl_music_artist = QLabel()
        for label, style in (
            (self.lbl_music_title, "font-size: 14px; font-weight: 700; color: #ffffff;"),
            (self.lbl_music_sep, "font-size: 12px; font-weight: 600; color: rgba(255, 255, 255, 0.35);"),
            (self.lbl_music_artist, "font-size: 12px; font-weight: 400; color: rgba(255, 255, 255, 0.55);"),
        ):
            label.setTextFormat(Qt.TextFormat.PlainText)
            set_widget_style(label, style)
        self.lbl_music_title.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self.lbl_music_artist.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        metadata.addWidget(self.lbl_music_title)
        metadata.addWidget(self.lbl_music_sep)
        metadata.addWidget(self.lbl_music_artist, 1)
        self.lbl_music_sep.hide()
        self.lbl_music_artist.hide()
        row.addLayout(metadata, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)

        transport = QHBoxLayout()
        transport.setSpacing(6)
        self.btn_ctrl_prev = IconButton(Icons.PREV, "Previous track", size=32, font_size=15, is_fluent=True)
        self.btn_ctrl_play = IconButton(Icons.PLAY, "Play", size=34, font_size=15, is_fluent=True)
        set_widget_style(self.btn_ctrl_play, """
            QPushButton {
                background: #f28c5a;
                border: none;
                border-radius: 11px;
                color: #0e1117;
                font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets';
                font-size: 15px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: #ff9f70;
                color: #0e1117;
            }
            QPushButton:pressed {
                background: #e07a4a;
                color: #0e1117;
            }
            QPushButton:disabled {
                background: rgba(255, 255, 255, 0.08);
                color: rgba(255, 255, 255, 0.35);
            }
        """)
        self.btn_ctrl_next = IconButton(Icons.NEXT, "Next track", size=32, font_size=15, is_fluent=True)
        for button in (self.btn_ctrl_prev, self.btn_ctrl_play, self.btn_ctrl_next):
            button.setEnabled(False)
            transport.addWidget(button)
        actions.addLayout(transport)
        actions.addStretch(1)

        self.btn_player_drop = QPushButton("Players")
        self.btn_player_drop.setToolTip("Switch media player")
        self.btn_player_drop.setAccessibleName("Switch media player")
        self.btn_player_drop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_player_drop.setFixedHeight(26)
        self.btn_player_drop.setMaximumWidth(150)
        set_widget_style(self.btn_player_drop, """
            QPushButton {
                background: rgba(255, 255, 255, 0.06);
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 13px;
                color: rgba(255, 255, 255, 0.85);
                font-family: 'Segoe UI';
                font-size: 11.5px;
                font-weight: 500;
                padding: 2px 10px;
                outline: none;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.11);
                color: #ffffff;
            }
            QPushButton:focus {
                border: 1px solid rgba(190, 211, 242, 0.7);
            }
        """)
        self.btn_player_drop.clicked.connect(self.player_menu_requested.emit)
        self.btn_player_drop.hide()
        actions.addWidget(self.btn_player_drop)

        self.mini_layout.addLayout(actions, 1)
        self.daily_audio = QWidget(self.mini_player)
        self.daily_audio_layout = QHBoxLayout(self.daily_audio)
        self.daily_audio_layout.setContentsMargins(4, 0, 0, 0)
        self.daily_audio_layout.setSpacing(4)
        self.mini_layout.addWidget(self.daily_audio, 1)
        self.daily_audio.hide()

    def update_track_info(self, title, artist):
        available = title not in ("No Media Playing", "Unknown Title", "")
        self._track_title = title if available else "Nothing playing"
        self._track_artist = artist if available else ""
        self.lbl_music_title.setToolTip(self._track_title)
        self.lbl_music_artist.setToolTip(self._track_artist)
        has_artist = bool(self._track_artist)
        self.lbl_music_sep.setVisible(has_artist)
        self.lbl_music_artist.setVisible(has_artist)
        for button in (self.btn_ctrl_prev, self.btn_ctrl_play, self.btn_ctrl_next):
            button.setEnabled(available)
        self._update_home_player_chrome()
        self._elide_track_labels()
        QTimer.singleShot(0, self, self._elide_track_labels)

    def _update_home_player_chrome(self):
        compact_idle = self._layout_name == "Classic" and not self.btn_ctrl_play.isEnabled()
        for button in (self.btn_ctrl_prev, self.btn_ctrl_play, self.btn_ctrl_next):
            button.setVisible(not compact_idle)
        self.mini_layout.setContentsMargins(12, 4 if compact_idle else 8, 12, 4 if compact_idle else 8)

    def _elide_track_labels(self):
        avail = max(80, self.mini_player.width() // 2 - 64)
        title_cap = int(avail * 0.6) if self._track_artist else avail
        self.lbl_music_title.setText(self.lbl_music_title.fontMetrics().elidedText(
            self._track_title, Qt.TextElideMode.ElideRight, max(48, title_cap)))
        if self._track_artist:
            artist_w = max(40, self.lbl_music_artist.width() or int(avail * 0.4))
            self.lbl_music_artist.setText(self.lbl_music_artist.fontMetrics().elidedText(
                self._track_artist, Qt.TextElideMode.ElideRight, artist_w))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "lbl_music_title"):
            QTimer.singleShot(0, self, self._elide_track_labels)

    def _position_screen_time(self, width):
        has_cards = self.dashboard_grid.count() > 0
        sideways = has_cards and width >= 1000 and not self.screentime_widget.isHidden()
        row = 0 if sideways or not has_cards else 1
        column = 1 if sideways else 0
        index = self.body_layout.indexOf(self.screentime_widget)
        if self.body_layout.getItemPosition(index)[:2] != (row, column):
            self.body_layout.removeWidget(self.screentime_widget)
            self.body_layout.addWidget(self.screentime_widget, row, column, alignment=Qt.AlignmentFlag.AlignTop)
        self.body_layout.setRowStretch(0, int(has_cards))
        self.body_layout.setColumnStretch(1, int(sideways))
        self.screentime_widget.setMinimumWidth(220 if sideways else 0)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel and self.home_scroll.verticalScrollBar().maximum() > 0:
            self.home_scroll.wheelEvent(event)
            return True
        return super().eventFilter(watched, event)

    def set_sections(self, hidden, screen_time):
        self._hidden_sections = set(hidden)
        self.screentime_widget.setVisible(screen_time)
        self.apply_layout(self._layout_name, self._card_order)
        self.layout_changed.emit()

    def apply_layout(self, name, order=None):
        self._layout_name = name
        self._card_order = home_order(name, {name: order})
        spec = LAYOUT_THEMES.get(name, LAYOUT_THEMES["Classic"])
        cards = {"clock": self.card_clock, "controls": self.card_controls,
                 "notes": self.card_notes, "shelf": self.card_shelf}
        for key, card in cards.items():
            card.apply_layout(name, outline=False)
            card.layout().setContentsMargins(spec["padding"], spec["padding"], spec["padding"], spec["padding"])
        self._arrange_dashboard()
        self.dashboard_grid.setSpacing(spec["spacing"])
        inset = spec["inset"]
        self.layout().setContentsMargins(inset, 8, inset, 10)
        self.layout().setSpacing(spec["spacing"])
        self.mini_player.apply_layout(name, outline=False)
        self.screentime_widget.apply_layout(name, outline=False)
        self.screentime_widget.layout().setContentsMargins(spec["padding"], 10, spec["padding"], 10)
        self._apply_design(name)
        QTimer.singleShot(0, self, self._elide_track_labels)

    def _arrange_dashboard(self):
        name, grid = self._layout_name, self.dashboard_grid
        cards = {"clock": self.card_clock, "controls": self.card_controls,
                 "notes": self.card_notes, "shelf": self.card_shelf}
        visible = [key for key in self._card_order if key not in self._hidden_sections]
        player_visible = "player" not in self._hidden_sections
        slots = home_slots(name, len(visible))
        for card in (*cards.values(), self.mini_player):
            grid.removeWidget(card)
        self.layout().removeWidget(self.mini_player)
        for key, slot in zip(visible, slots):
            grid.addWidget(cards[key], *slot)
        self.layout().insertWidget(0, self.mini_player)
        self.mini_layout.setDirection(QBoxLayout.Direction.LeftToRight)
        self.daily_audio.setVisible(False)
        for key, card in cards.items():
            card.setVisible(key in visible)
        self.mini_player.setVisible(player_visible)
        body_visible = bool(visible) or not self.screentime_widget.isHidden()
        self.home_scroll.setVisible(body_visible)
        self.btn_customize.setVisible(not (player_visible or body_visible))
        columns = LAYOUT_THEMES[name]["columns"]
        for column in range(2):
            grid.setColumnStretch(column, columns[column] if column < len(columns) else 1)
        rows = max((row + span for row, _, span, _ in slots), default=0)
        for row in range(max(2, rows)):
            grid.setRowStretch(row, 1)

    def _apply_design(self, name):
        for widget, source in self._design_sources.items():
            set_widget_style(widget, source)
        for label in self._design_headers:
            label.hide()
        controls_title = self._design_headers[1]
        controls_title.setText("System controls")
        controls_title.show()
        set_widget_style(controls_title, "font-size: 14px; font-weight: 600; color: #edf1f0;")
        for card in (self.card_clock, self.card_notes, self.card_shelf):
            set_widget_style(card, "CardFrame#cardFrame { background: transparent; border: none; }")
        set_widget_style(self.lbl_big_time, "font-size: 40px; font-weight: 500; color: #edf1f0;")
        set_widget_style(self.lbl_date, "font-size: 13px; color: #a7adab;")
        set_widget_style(self.txt_notes, """
            QTextEdit { background: rgba(255,255,255,0.035); border: 1px solid transparent;
                        border-radius: 6px; color: #edf1f0; padding: 8px; font-size: 13px; }
            QTextEdit:focus { border-color: #a7adab; }
        """)
        clock_layout = self.card_clock.layout()
        before, after = clock_layout.count() - 2, clock_layout.count() - 1
        if clock_layout.itemAt(before).spacerItem() is not None:
            spacer = clock_layout.takeAt(before).spacerItem()
            clock_layout.insertSpacerItem(after, spacer)
            clock_layout.setStretch(after, 1)
        labels = ("Keep awake", "Microphone", "Focus", "Screen snip",
                  "Pick color", "Calculator", "Bluetooth", "Lock PC")
        for (button, original, source), label in zip(self.quick_actions, labels):
            button.setText(label)
            set_widget_style(button, source + " QPushButton { text-align: left; }")
        self._update_home_player_chrome()
        self.clock_face.setDirection(QBoxLayout.Direction.TopToBottom)
        self.clock_face.removeWidget(self.lbl_date)
        self.clock_detail.removeWidget(self.lbl_date)
        self.clock_detail.removeWidget(self.lbl_weather_text)
        self.clock_detail.insertWidget(0, self.lbl_date)
        self.clock_detail.addWidget(self.lbl_weather_text)
        for i, metric in enumerate(self.metrics):
            self.telemetry_grid.removeWidget(metric)
            self.telemetry_grid.addWidget(metric, 0, i, Qt.AlignmentFlag.AlignLeft)
            metric.apply_design("Classic")

    def fit_height(self, available_height, width=None, *, max_height=None):
        """Fit the cards first and scroll any extra content on shorter displays."""
        width = self.width() if width is None else width
        self._position_screen_time(width)
        spec = LAYOUT_THEMES.get(self._layout_name, LAYOUT_THEMES["Classic"])
        cards = (self.card_clock, self.card_controls, self.card_notes, self.card_shelf)

        def set_spacing(vertical_padding, gap):
            for card in cards:
                card.layout().setContentsMargins(spec["padding"], vertical_padding, spec["padding"], vertical_padding)
                card.layout().activate()
                card.updateGeometry()
            self.layout().setSpacing(gap)
            self.body_layout.setSpacing(gap)
            self.dashboard_grid.setSpacing(gap)
            self.dashboard_grid.invalidate()
            self.body_layout.invalidate()

        def fixed_height():
            margins = self.layout().contentsMargins()
            space = margins.top() + margins.bottom()
            if self.layout().indexOf(self.mini_player) >= 0 and not self.mini_player.isHidden():
                space += self.mini_player.minimumSizeHint().height() + self.layout().spacing()
            return space

        def body_height():
            return max(1, available_height - fixed_height())

        padding, gap = spec["padding"], spec["spacing"]
        set_spacing(padding, gap)
        overflow = self.dashboard_grid.minimumSize().height() - body_height()
        if overflow > 0:
            padding = max(8, padding - (overflow + 3) // 4)
            set_spacing(padding, gap)
            overflow = self.dashboard_grid.minimumSize().height() - body_height()
            if overflow > 0:
                set_spacing(padding, max(4, gap - overflow))
        minimum = self.body_layout.minimumSize().height()
        viewport_height = body_height()
        if max_height is not None:
            grid_height = self.dashboard_grid.minimumSize().height()
            needed = minimum if self.screentime_widget.isHidden() else grid_height
            viewport_height += min(max(0, needed - viewport_height), max(0, max_height - available_height))
        self.home_scroll.setMinimumHeight(min(minimum, viewport_height))
        self.body_layout.activate()  # Apply the new content minimum before the scroll area sizes it.
        return 0 if self.home_scroll.isHidden() else fixed_height() + self.home_scroll.minimumHeight()

    def update_sessions_list(self, sessions, active_index):
        self.btn_player_drop.setVisible(len(sessions) > 1)
        if 0 <= active_index < len(sessions):
            name = sessions[active_index]["display_name"]
            text = self.btn_player_drop.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, 122)
            self.btn_player_drop.setText(f"{text} ▾")
            self.btn_player_drop.setToolTip(f"Switch media player. Current player: {name}")
        self.layout().activate()
        self._elide_track_labels()

    def update_shelf_display(self, items: list):
        count = len(items)
        self.btn_clear_shelf.setVisible(count > 0)
        self.lbl_shelf_status.setText(f"Shelf · {count} file{'s' if count != 1 else ''}")
        if count > 0:
            latest = items[-1]
            self._latest_shelf_path = latest.path
            self.shelf_thumb.set_image(latest.path, latest.thumbnail)
            name = latest.name
            trunc_name = (name[:20] + "..") if len(name) > 20 else name
            self.lbl_shelf_item_name.setText(trunc_name)
            self.lbl_shelf_item_name.setToolTip(name)
            size_kb = max(1, latest.size_bytes // 1024)
            self.lbl_shelf_item_sub.setText(f"{size_kb} KB")
            self.shelf_preview_frame.setVisible(True)
            self.lbl_shelf_empty.setVisible(False)
        else:
            self.shelf_preview_frame.setVisible(False)
            self.lbl_shelf_empty.setVisible(True)
        self.layout_changed.emit()

    def _save_notes(self):
        had_error = bool(self.lbl_note_save.text())
        try:
            write_text(self._notes_file, self.txt_notes.toPlainText())
            self.lbl_note_save.clear()
            if had_error:
                self.layout_changed.emit()
            return True
        except OSError as error:
            self.lbl_note_save.setText("Not saved. Check the data folder and try again.")
            self.lbl_note_save.setToolTip(str(error))
            if not had_error:
                self.layout_changed.emit()
            return False

    def flush_notes(self):
        pending = self._notes_timer.isActive()
        self._notes_timer.stop()
        return self._save_notes() if pending or self.lbl_note_save.text() else True

    def _eval_calc(self, text: str):
        text = text.strip()
        if not text:
            self.lbl_calc_res.setText("")
            return
        operators = {
            ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul,
            ast.Div: op.truediv, ast.FloorDiv: op.floordiv,
            ast.Mod: op.mod, ast.Pow: op.pow, ast.USub: op.neg
        }
        def _eval_node(node):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return node.value
            elif isinstance(node, ast.BinOp) and type(node.op) in operators:
                left = _eval_node(node.left)
                right = _eval_node(node.right)
                if isinstance(node.op, ast.Pow) and (abs(right) > 100 or abs(left) > 10000):
                    raise OverflowError("Exponent too large")
                return operators[type(node.op)](left, right)
            elif isinstance(node, ast.UnaryOp) and type(node.op) in operators:
                return operators[type(node.op)](_eval_node(node.operand))
            raise ValueError("Unsupported expression")

        try:
            parsed = ast.parse(text.replace('^', '**'), mode='eval')
            val = _eval_node(parsed.body)
            if isinstance(val, (int, float)):
                res_str = f"= {val:,.4g}" if isinstance(val, float) else f"= {val:,}"
                self.lbl_calc_res.setText(res_str)
                return
        except Exception:
            pass
        self.lbl_calc_res.setText("")

    def _on_tear_off(self):
        text = self.txt_notes.toPlainText()
        self.tear_off_requested.emit(text)

    def set_volume_display(self, vol: int, is_muted: bool = False, *, sync_slider=True):
        if sync_slider:
            self.slider_vol.blockSignals(True)
            self.slider_vol.setValue(vol)
            self.slider_vol.blockSignals(False)
        action = "Unmute" if is_muted else "Mute"
        self.btn_vol_mute.setText(action)
        self.btn_vol_mute.setAccessibleName(f"{action} system audio")
        self.btn_vol_mute.setToolTip(f"{action} system audio")

    def set_brightness_display(self, bright: int):
        self.slider_bright.blockSignals(True)
        self.slider_bright.setValue(bright)
        self.slider_bright.blockSignals(False)

    def update_weather(self, data: dict):
        """Updates the weather display with live meteorological data."""
        text = data.get("display_text", "")
        city = data.get("city", "")
        cond = data.get("condition", "")
        temp = data.get("temp", 0)
        h = data.get("high", 0)
        l = data.get("low", 0)
        hum = data.get("humidity", 0)
        unit = data.get("unit", "°C")

        self.lbl_weather_text.setText(text)
        self.lbl_weather_text.setToolTip(
            f"{city}\n{temp}{unit} · {cond}\nHigh: {h}{unit} · Low: {l}{unit}\nHumidity: {hum}%\n(Click to Refresh)"
            if city else text
        )


class TodayTabView(QWidget):
    """
    Hitodama-grade Bento Today Dashboard View (Image 1).
    3-column tactile Bento layout:
    - Left Column:
      - Card 1: Stacked Clock (09 over ··· over 41, AM • Tue 29)
      - Card 2: Weather Card (Amber Sun, 32°C, Mostly clear)
    - Center Column:
      - Card 3: 'This week' horizontal day-picker calendar strip + Next event pill
      - Card 4: Pomodoro Focus Timer with circular dial (05:00), preset pills, Start/Reset
    - Right Column:
      - Card 5: 'Today' To-Do checklist with 0/1 badge, interactive checkmarks,
        and '+ Add a to-do...' input field with peach arrow submit button.
    """
    layout_changed = Signal()
    tear_off_requested = Signal()
    pin_requested = Signal(str)

    def __init__(self, parent=None, accent="#f28c5a"):
        super().__init__(parent)
        self._accent = accent
        self._init_ui()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(16, 8, 16, 10)
        main_layout.setSpacing(14)

        # ---------------------------------------------------------
        # Column 1 (Left): Stacked Clock + Weather Bento Card
        # ---------------------------------------------------------
        col1 = QVBoxLayout()
        col1.setSpacing(10)

        # Card 1: Stacked Clock Card
        card_stacked_clock = CardFrame(self)
        c1_lay = QVBoxLayout(card_stacked_clock)
        c1_lay.setContentsMargins(14, 12, 14, 12)
        c1_lay.setSpacing(0)
        self.stacked_clock = StackedClockWidget(card_stacked_clock, accent=self._accent)
        c1_lay.addWidget(self.stacked_clock)
        col1.addWidget(card_stacked_clock, 3)

        # Card 2: Weather Bento Card
        card_weather = CardFrame(self)
        card_weather.setFixedHeight(105)
        w_lay = QVBoxLayout(card_weather)
        w_lay.setContentsMargins(14, 10, 14, 10)
        w_lay.setSpacing(3)

        sun_icon = QLabel("☀")
        set_widget_style(sun_icon, "font-size: 24px; color: #fbbf24; background: transparent;")
        w_lay.addWidget(sun_icon)

        self.lbl_hitodama_temp = QLabel("32°C")
        set_widget_style(self.lbl_hitodama_temp, "font-size: 22px; font-weight: 700; color: #ffffff; background: transparent;")
        w_lay.addWidget(self.lbl_hitodama_temp)

        self.lbl_hitodama_cond = QLabel("Mostly clear")
        set_widget_style(self.lbl_hitodama_cond, "font-size: 11.5px; font-weight: 500; color: rgba(255,255,255,0.6); background: transparent;")
        w_lay.addWidget(self.lbl_hitodama_cond)
        col1.addWidget(card_weather, 2)

        col1_w = QWidget(self)
        col1_w.setLayout(col1)
        col1_w.setFixedWidth(190)
        main_layout.addWidget(col1_w)

        # ---------------------------------------------------------
        # Column 2 (Center): This week strip + Pomodoro Focus Timer
        # ---------------------------------------------------------
        col2 = QVBoxLayout()
        col2.setSpacing(10)

        # Card 3: This week strip
        card_week = CardFrame(self)
        cw_lay = QVBoxLayout(card_week)
        cw_lay.setContentsMargins(12, 10, 12, 12)
        self.calendar_strip = WeekCalendarStrip(card_week, accent=self._accent)
        cw_lay.addWidget(self.calendar_strip)
        col2.addWidget(card_week)

        # Card 4: Pomodoro Focus Timer
        card_pomo = CardFrame(self)
        cp_lay = QVBoxLayout(card_pomo)
        cp_lay.setContentsMargins(12, 8, 12, 8)
        self.pomodoro_widget = PomodoroFocusWidget(card_pomo, accent=self._accent)
        cp_lay.addWidget(self.pomodoro_widget)
        col2.addWidget(card_pomo)

        col2_w = QWidget(self)
        col2_w.setLayout(col2)
        main_layout.addWidget(col2_w, 2)

        # ---------------------------------------------------------
        # Column 3 (Right): Today To-Do Checklist
        # ---------------------------------------------------------
        card_todo = CardFrame(self)
        ct_lay = QVBoxLayout(card_todo)
        ct_lay.setContentsMargins(8, 8, 8, 8)
        self.todo_widget = TodoChecklistWidget(card_todo, accent=self._accent)
        ct_lay.addWidget(self.todo_widget)
        main_layout.addWidget(card_todo, 2)

    def update_weather(self, data: dict):
        temp = data.get("temp", 32)
        cond = data.get("condition", "Mostly clear")
        unit = data.get("unit", "°C")
        if hasattr(self, "lbl_hitodama_temp"):
            self.lbl_hitodama_temp.setText(f"{temp}{unit}")
        if hasattr(self, "lbl_hitodama_cond"):
            self.lbl_hitodama_cond.setText(cond)

    def set_accent(self, accent: str):
        self._accent = accent
        self.stacked_clock.set_accent(accent)
        self.calendar_strip.set_accent(accent)
        self.pomodoro_widget.set_accent(accent)
        self.todo_widget.set_accent(accent)


class ControlsTabView(QWidget):
    """
    Hitodama-grade Controls tab view.
    Featuring:
    - 2x3 tactile squircle control tiles:
      Wi-Fi, Bluetooth, Audio, Power, Night Light, Dark mode with active peach glow
    - Thick capsule volume slider (32px) with embedded speaker icon and percentage readout
    - Dedicated Now Playing card with '< Speakers' output pill, album art thumbnail,
      playback controls (prev, light-blue play pill, next), and waveform seek bar.
    """
    wifi_menu_requested = Signal()
    bluetooth_menu_requested = Signal()
    audio_device_menu_requested = Signal()
    power_options_requested = Signal()
    night_light_toggle_requested = Signal()
    dark_mode_toggle_requested = Signal()
    volume_changed = Signal(int)
    play_pause_clicked = Signal()
    prev_clicked = Signal()
    next_clicked = Signal()
    seek_requested = Signal(float)
    layout_changed = Signal()

    def __init__(self, parent=None, accent="#f28c5a"):
        super().__init__(parent)
        self._accent = accent
        self._is_playing = False
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 12, 16, 14)
        main_layout.setSpacing(12)

        # 1. 2x3 Tactile Control Tiles Grid
        grid = QGridLayout()
        grid.setSpacing(8)

        # Row 0: Wi-Fi, Bluetooth, Audio
        self.tile_wifi = ControlPillTile(Icons.WIFI, "Wi-Fi", "Home 5G", "Wi-Fi settings", toggle=True, has_menu=True, accent=self._accent, parent=self)
        self.tile_wifi.setChecked(True)
        self.tile_wifi.menu_requested.connect(self.wifi_menu_requested.emit)
        grid.addWidget(self.tile_wifi, 0, 0)

        self.tile_bt = ControlPillTile(Icons.BLUETOOTH, "Bluetooth", "Off", "Bluetooth settings", toggle=True, has_menu=True, accent=self._accent, parent=self)
        self.tile_bt.setChecked(False)
        self.tile_bt.menu_requested.connect(self.bluetooth_menu_requested.emit)
        grid.addWidget(self.tile_bt, 0, 1)

        self.tile_audio = ControlPillTile(Icons.VOLUME, "Audio", "Speakers", "Audio devices", toggle=True, has_menu=True, accent=self._accent, parent=self)
        self.tile_audio.setChecked(True)
        self.tile_audio.menu_requested.connect(self.audio_device_menu_requested.emit)
        grid.addWidget(self.tile_audio, 0, 2)

        # Row 1: Power, Night Light, Dark mode
        self.tile_power = ControlPillTile(Icons.POWER, "Power", "Power options", "Power options", toggle=False, has_menu=False, accent=self._accent, parent=self)
        self.tile_power.clicked.connect(self.power_options_requested.emit)
        grid.addWidget(self.tile_power, 1, 0)

        self.tile_night = ControlPillTile(Icons.SHIELD, "Night Light", "Off", "Night light settings", toggle=True, has_menu=True, accent=self._accent, parent=self)
        self.tile_night.setChecked(False)
        self.tile_night.clicked.connect(self.night_light_toggle_requested.emit)
        grid.addWidget(self.tile_night, 1, 1)

        self.tile_dark = ControlPillTile(Icons.COLOR, "Dark mode", "On", "Dark mode toggle", toggle=True, has_menu=False, accent=self._accent, parent=self)
        self.tile_dark.setChecked(True)
        self.tile_dark.clicked.connect(self.dark_mode_toggle_requested.emit)
        grid.addWidget(self.tile_dark, 1, 2)

        for col in range(3):
            grid.setColumnStretch(col, 1)
        main_layout.addLayout(grid)

        # 2. Volume Capsule Slider
        vol_box = QWidget(self)
        vol_lay = QHBoxLayout(vol_box)
        vol_lay.setContentsMargins(0, 2, 0, 2)
        vol_lay.setSpacing(12)

        self.slider_vol = CapsuleSlider(icon=Icons.VOLUME, parent=self, compact_track=False)
        self.slider_vol.setFixedHeight(34)
        self.slider_vol.set_accent(self._accent)
        self.slider_vol.setValue(64)
        self.slider_vol.valueChanged.connect(self.volume_changed.emit)
        vol_lay.addWidget(self.slider_vol, 1)

        self.lbl_vol_pct = QLabel("64%")
        set_widget_style(self.lbl_vol_pct, "font-size: 13px; font-weight: 700; color: #ffffff; background: transparent; min-width: 38px;")
        self.slider_vol.valueChanged.connect(lambda v: self.lbl_vol_pct.setText(f"{v}%"))
        vol_lay.addWidget(self.lbl_vol_pct)
        main_layout.addWidget(vol_box)

        # 3. Dedicated Now Playing Card
        self.card_player = CardFrame(self)
        card_lay = QVBoxLayout(self.card_player)
        card_lay.setContentsMargins(18, 14, 18, 14)
        card_lay.setSpacing(10)

        # Top Output Device Pill (< Speakers)
        top_pill_row = QHBoxLayout()
        self.btn_output_device = QPushButton("< Speakers")
        self.btn_output = self.btn_output_device
        self.btn_output_device.setCursor(Qt.CursorShape.PointingHandCursor)
        set_widget_style(self.btn_output_device, """
            QPushButton {
                background: rgba(255, 255, 255, 0.06);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 9px;
                color: rgba(255, 255, 255, 0.75);
                font-size: 11px;
                font-weight: 600;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.1);
                color: #ffffff;
            }
        """)
        self.btn_output_device.clicked.connect(self.audio_device_menu_requested.emit)
        top_pill_row.addWidget(self.btn_output_device)
        top_pill_row.addStretch()
        card_lay.addLayout(top_pill_row)

        # Middle Media Info & Controls
        mid_row = QHBoxLayout()
        mid_row.setSpacing(14)

        # Artwork
        self.lbl_art = QLabel()
        self.lbl_art.setFixedSize(54, 54)
        self.lbl_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_widget_style(self.lbl_art, "background: rgba(255, 255, 255, 0.08); border-radius: 12px; color: rgba(255, 255, 255, 0.4); font-size: 20px;")
        self.lbl_art.setText("♫")
        mid_row.addWidget(self.lbl_art)

        # Title & Artist
        meta_box = QVBoxLayout()
        meta_box.setSpacing(2)
        meta_box.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.lbl_title = QLabel("lofi beats to study and relax")
        set_widget_style(self.lbl_title, "font-size: 15px; font-weight: 700; color: #ffffff; background: transparent;")
        self.lbl_artist = QLabel("lofi radio")
        set_widget_style(self.lbl_artist, "font-size: 12px; font-weight: 500; color: rgba(255, 255, 255, 0.55); background: transparent;")
        meta_box.addWidget(self.lbl_title)
        meta_box.addWidget(self.lbl_artist)
        mid_row.addLayout(meta_box, 1)

        # Transport pills (Prev, Play/Pause, Next)
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)

        self.btn_prev = QPushButton("◀◀")
        self.btn_prev.setFixedSize(36, 36)
        self.btn_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        set_widget_style(self.btn_prev, "QPushButton { background: rgba(255, 255, 255, 0.06); border-radius: 18px; color: #ffffff; font-size: 11px; border: none; } QPushButton:hover { background: rgba(255, 255, 255, 0.12); }")
        self.btn_prev.clicked.connect(self.prev_clicked.emit)
        ctrl_row.addWidget(self.btn_prev)

        # Light blue play pill
        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedSize(52, 36)
        self.btn_play.setCursor(Qt.CursorShape.PointingHandCursor)
        set_widget_style(self.btn_play, "QPushButton { background: #93c5fd; border-radius: 18px; color: #0e1117; font-size: 14px; font-weight: 800; border: none; } QPushButton:hover { background: #bfdbfe; }")
        self.btn_play.clicked.connect(self.play_pause_clicked.emit)
        ctrl_row.addWidget(self.btn_play)

        self.btn_next = QPushButton("▶▶")
        self.btn_next.setFixedSize(36, 36)
        self.btn_next.setCursor(Qt.CursorShape.PointingHandCursor)
        set_widget_style(self.btn_next, "QPushButton { background: rgba(255, 255, 255, 0.06); border-radius: 18px; color: #ffffff; font-size: 11px; border: none; } QPushButton:hover { background: rgba(255, 255, 255, 0.12); }")
        self.btn_next.clicked.connect(self.next_clicked.emit)
        ctrl_row.addWidget(self.btn_next)

        mid_row.addLayout(ctrl_row)
        card_lay.addLayout(mid_row)

        # Bottom Waveform Seek Bar
        seek_row = QHBoxLayout()
        seek_row.setSpacing(10)
        self.lbl_pos = QLabel("22:57")
        set_widget_style(self.lbl_pos, "font-size: 11px; font-weight: 600; color: rgba(255, 255, 255, 0.5); background: transparent;")
        seek_row.addWidget(self.lbl_pos)

        self.waveform_bar = WaveformSeekBar(self, accent="#93c5fd")
        self.waveform_bar.set_duration(3735)
        self.waveform_bar.set_position(1377)
        self.waveform_bar.seek_requested.connect(self.seek_requested.emit)
        seek_row.addWidget(self.waveform_bar, 1)

        self.lbl_dur = QLabel("62:15")
        set_widget_style(self.lbl_dur, "font-size: 11px; font-weight: 600; color: rgba(255, 255, 255, 0.5); background: transparent;")
        seek_row.addWidget(self.lbl_dur)

        card_lay.addLayout(seek_row)
        main_layout.addWidget(self.card_player)

        # Stub for lyrics button for compatibility
        self.btn_lyrics = QPushButton("Lyrics", self)
        self.btn_lyrics.setCheckable(True)
        self.btn_lyrics.setChecked(False)
        self.btn_lyrics.hide()

    def set_track(self, title: str, artist: str, art_pixmap: QPixmap = None):
        self.lbl_title.setText(title or "Nothing playing")
        self.lbl_artist.setText(artist or "Play music on Windows")
        if art_pixmap and not art_pixmap.isNull():
            self.lbl_art.setPixmap(art_pixmap.scaled(54, 54, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
        else:
            self.lbl_art.setText("♫")

    def set_playing(self, is_playing: bool):
        self._is_playing = is_playing
        self.btn_play.setText("⏸" if is_playing else "▶")

    def set_timeline(self, pos_sec: float, dur_sec: float):
        if dur_sec > 0:
            self.waveform_bar.set_duration(dur_sec)
            self.waveform_bar.set_position(pos_sec)
            m_pos, s_pos = int(pos_sec) // 60, int(pos_sec) % 60
            m_dur, s_dur = int(dur_sec) // 60, int(dur_sec) % 60
            self.lbl_pos.setText(f"{m_pos:02d}:{s_pos:02d}")
            self.lbl_dur.setText(f"{m_dur:02d}:{s_dur:02d}")

    def set_accent(self, accent: str):
        self._accent = accent
        self.slider_vol.set_accent(accent)
        self.tile_wifi.set_accent(accent)
        self.tile_audio.set_accent(accent)
        self.tile_dark.set_accent(accent)


class MusicTabView(QWidget):
    """Desktop media player and lyrics columns with real session switching."""
    session_select_requested = Signal(int)
    seek_requested = Signal(float)
    sound_settings_requested = Signal()
    layout_changed = Signal()

    def __init__(self, parent=None, accent="#6e9bff"):
        super().__init__(parent)
        self._accent = accent
        self._source_pills = []
        self._pos_sec = 0.0
        self._dur_sec = 0.0
        self._is_playing = False
        self._last_tick_ts = time.time()
        self._reported_timeline = (0.0, 0.0, False)
        self._track_key = ()
        self._can_seek = False
        self._surface_mode = "theme"
        self._theme_surface = QColor("#1c2723")
        self._show_player_tiles = True
        self._artwork_pixmap = QPixmap()
        self._media_title = "Nothing playing"
        self._media_artist = "Play something in your music app"
        self._layout_name = current_layout()

        self._init_ui()
        player = self.player_body
        for widget in (self.lbl_large_art, self.lbl_title, self.lbl_artist):
            player.removeWidget(widget)
        self.identity = QWidget()
        self.identity_layout = QBoxLayout(QBoxLayout.Direction.TopToBottom, self.identity)
        self.identity_layout.setContentsMargins(0, 0, 0, 0)
        self.identity_layout.setSpacing(8)
        self.identity_layout.addWidget(self.lbl_large_art, alignment=Qt.AlignmentFlag.AlignCenter)
        metadata = QWidget()
        metadata_layout = QVBoxLayout(metadata)
        metadata_layout.setContentsMargins(0, 0, 0, 0)
        metadata_layout.setSpacing(6)
        metadata_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        metadata_layout.addWidget(self.lbl_title)
        metadata_layout.addWidget(self.lbl_artist)
        self.identity_layout.addWidget(metadata, 1)
        self.identity_metadata = metadata
        player.insertWidget(1, self.identity)
        self.apply_layout(self._layout_name)

        self._playback_timer = QTimer(self)
        self._playback_timer.setInterval(100)
        self._playback_timer.timeout.connect(self._on_local_playback_tick)

    def showEvent(self, event):
        super().showEvent(event)
        if self._is_playing:
            self._last_tick_ts = time.time()
            self._playback_timer.start()

    def hideEvent(self, event):
        self._playback_timer.stop()
        super().hideEvent(event)

    def _init_ui(self):
        columns = QHBoxLayout(self)
        columns.setContentsMargins(8, 4, 8, 8)
        columns.setSpacing(20)

        self.player_card = QFrame()
        self.player_card.setObjectName("mediaCard")
        self._set_surface(QColor("#202329"))
        self.player_shell = QHBoxLayout(self.player_card)
        self.player_shell.setContentsMargins(0, 0, 0, 0)
        self.player_shell.setSpacing(0)
        controls = QWidget(self.player_card)
        self.player_shell.addWidget(controls, 1)
        player = self.player_body = QVBoxLayout(controls)
        player.setContentsMargins(24, 18, 24, 18)
        player.setSpacing(8)
        source_row = QHBoxLayout()
        self.btn_source = QPushButton("Player")
        self.btn_source.setAccessibleName("Choose media player")
        self.btn_source.setToolTip("Choose media player")
        self.btn_source.clicked.connect(self._show_source_menu)
        source_row.addWidget(self.btn_source)
        source_row.addStretch()
        self.btn_lyrics = QPushButton("Lyrics")
        self.btn_lyrics.setCheckable(True)
        self.btn_lyrics.setChecked(True)
        self.btn_lyrics.clicked.connect(self._toggle_lyrics)
        for button in (self.btn_source, self.btn_lyrics):
            set_widget_style(button, "QPushButton { background: transparent; color: #a7adab; border: none; border-radius: 4px; font-family: 'Segoe UI'; font-size: 12px; font-weight: 400; padding: 5px 8px; } QPushButton:hover { color: #edf1f0; background: rgba(255,255,255,0.05); } QPushButton:focus { border: 1px solid #a7adab; }")
        source_row.addWidget(self.btn_lyrics)
        player.addLayout(source_row)

        self.lbl_large_art = QLabel(Icons.MUSIC)
        self.lbl_large_art.setFixedSize(144, 144)
        self.lbl_large_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_widget_style(self.lbl_large_art, "background: rgba(255,255,255,0.05); border-radius: 10px; color: #94a3b8; font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets'; font-size: 36px;")
        self.art_container = self.lbl_large_art
        player.addWidget(self.lbl_large_art, alignment=Qt.AlignmentFlag.AlignCenter)
        self.lbl_title = QLabel("Nothing playing")
        self.lbl_title.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_title.setWordWrap(False)
        self.lbl_title.setMaximumHeight(52)
        self.lbl_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        title_font = QFont("Segoe UI")
        title_font.setPixelSize(18)
        title_font.setWeight(QFont.Weight.Medium)
        self.lbl_title.setFont(title_font)
        set_widget_style(self.lbl_title, "font-size: 18px; font-weight: 500; color: #edf1f0;")
        self.lbl_artist = QLabel("Play something in your music app")
        self.lbl_artist.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_artist.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_artist.setMaximumHeight(34)
        self.lbl_artist.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        artist_font = QFont("Segoe UI")
        artist_font.setPixelSize(12)
        self.lbl_artist.setFont(artist_font)
        set_widget_style(self.lbl_artist, "color: #a7adab;")
        player.addWidget(self.lbl_title)
        player.addWidget(self.lbl_artist)
        self.lbl_source = QLabel(self)
        self.lbl_source.hide()

        self.scrubber = PlaybackSlider(Qt.Orientation.Horizontal)
        self.scrubber.setRange(0, 100)
        self.scrubber.setEnabled(False)
        self.scrubber.setAccessibleName("Playback position")
        self.scrubber.setFixedHeight(18)
        self.scrubber.seek_clicked.connect(self._on_scrubber_clicked)
        self.scrubber.seek_cancelled.connect(lambda: self.update_timeline(*self._reported_timeline))
        self.scrubber.sliderMoved.connect(self._on_scrubber_moved)
        player.addWidget(self.scrubber)
        times = QHBoxLayout()
        self.lbl_elapsed, self.lbl_remaining = QLabel("00:00"), QLabel("--:--")
        for label in (self.lbl_elapsed, self.lbl_remaining):
            set_widget_style(label, "font-size: 11px; color: #a7adab;")
        times.addWidget(self.lbl_elapsed)
        times.addStretch()
        times.addWidget(self.lbl_remaining)
        player.addLayout(times)
        transport = QHBoxLayout()
        transport.setAlignment(Qt.AlignmentFlag.AlignCenter)
        transport.setSpacing(12)
        self.btn_prev = IconButton(Icons.PREV, "Previous track", size=36, font_size=16, is_fluent=True)
        self.btn_play = QPushButton(Icons.PLAY)
        self.btn_play.setFixedSize(36, 36)
        self.btn_play.setAccessibleName("Play")
        self.btn_play.setToolTip("Play")
        set_widget_style(self.btn_play, self._play_button_style())
        self.btn_next = IconButton(Icons.NEXT, "Next track", size=36, font_size=16, is_fluent=True)
        self._transport_styles = {button: button.property("poppyStyleSource") for button in (self.btn_prev, self.btn_next)}
        for button in (self.btn_prev, self.btn_play, self.btn_next):
            button.setEnabled(False)
            transport.addWidget(button)
        player.addLayout(transport)
        volume = QHBoxLayout()
        volume.setSpacing(4)
        self.btn_vol_music = IconButton(Icons.VOLUME, "Mute or unmute", size=24, font_size=12, is_fluent=True)
        self.vol_slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setAccessibleName("System volume")
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(50)
        self.vol_slider.setMinimumWidth(48)
        self.vol_slider.setFixedHeight(24)
        self.btn_output = IconButton(Icons.SPEAKER, "Choose sound output", size=24, font_size=12, is_fluent=True)
        self.btn_output.clicked.connect(self.sound_settings_requested.emit)
        volume.addWidget(self.btn_vol_music)
        volume.addWidget(self.vol_slider)
        volume.addWidget(self.btn_output)
        player.addLayout(volume)
        for slider in (self.scrubber, self.vol_slider):
            set_widget_style(slider, """
                QSlider:focus { border: none; outline: none; }
                QSlider::groove:horizontal { height: 2px; background: rgba(255,255,255,0.15); border-radius: 1px; }
                QSlider::sub-page:horizontal { background: #b6c4be; border-radius: 1px; }
                QSlider::handle:horizontal {
                    background: #b6c4be; border: 1px solid #b6c4be; width: 6px; margin: -3px 0; border-radius: 4px;
                }
                QSlider::handle:horizontal:hover { background: #edf1f0; }
                QSlider::handle:horizontal:focus { background: #edf1f0; border-color: #61776d; }
                QSlider::handle:horizontal:disabled { background: transparent; border-color: transparent; }
            """)
        self.sessions_widget = QWidget()
        self.pills_layout = QHBoxLayout(self.sessions_widget)
        self.pills_layout.setContentsMargins(0, 0, 0, 0)
        self.pills_layout.setSpacing(5)
        player.addWidget(self.sessions_widget)
        self.sessions_widget.hide()
        player.addStretch()
        columns.addWidget(self.player_card, 1)
        self.lyrics_widget = SpotifyLyricsWidget(self)
        self.lyrics_widget.setMinimumWidth(180)
        self.lyrics_widget.seek_requested.connect(self.seek_requested.emit)
        columns.addWidget(self.lyrics_widget, 1)
        self.btn_prev_session, self.btn_next_session = QPushButton(self), QPushButton(self)
        self.btn_shuffle, self.btn_repeat = QPushButton(self), QPushButton(self)
        self.txt_lyrics, self.lbl_album_info = QLabel(self), QLabel(self)
        for control in (self.btn_prev_session, self.btn_next_session, self.btn_shuffle, self.btn_repeat, self.txt_lyrics, self.lbl_album_info):
            control.hide()
        self._sessions = []

    def _elide_metadata(self):
        for label, text in ((self.lbl_title, self._media_title), (self.lbl_artist, self._media_artist)):
            label.setText(label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, max(40, label.width())))
        for button in self._source_pills:
            name = button.property("playerName")
            if name:
                button.setText(button.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, max(1, button.width() - 12)))

    def fit_height(self, available_height):
        """Keep transport and volume controls visible; reduce art size before clipping."""
        spec = LAYOUT_THEMES[self._layout_name]
        player = self.player_body
        padding = spec["padding"]
        gap = min(8, spec["spacing"])
        deck = self._layout_name == "Deck"
        horizontal = deck or self.identity_layout.direction() == QBoxLayout.Direction.LeftToRight
        # Read the fixed rows directly. A hidden player's cached size hint
        # can still describe the previous theme during a layout switch.
        fixed = sum(player.itemAt(i).minimumSize().height() for i in range(player.count())
                    if player.itemAt(i).widget() is not self.identity)
        metadata = self.identity_metadata.minimumSizeHint().height()
        identity_gap = self.identity_layout.spacing() if not horizontal else 0
        room = available_height - self.layout().contentsMargins().top() - self.layout().contentsMargins().bottom()
        room -= fixed + (player.count() - 1) * gap + 2 * padding
        if not horizontal:
            room -= metadata + identity_gap
        min_art = min(96, spec["art_size"])
        if room < min_art:
            room += 2 * (padding - 10) + (player.count() - 1) * (gap - 4)
            vertical, gap = 10, 4
        else:
            vertical = padding
        size = spec["art_size"] if deck else max(min_art, min(spec["art_size"], room))
        self.player_shell.setContentsMargins(padding if deck else 0, 0, 0, 0)
        player.setContentsMargins(padding, vertical, padding, vertical)
        player.setSpacing(gap)
        self.lbl_large_art.setFixedSize(size, size)
        self.identity.setMinimumHeight(metadata if deck else max(size, metadata) if horizontal else size + metadata + identity_gap)
        self.identity_layout.invalidate()
        player.invalidate()
        player.parentWidget().updateGeometry()
        self.player_shell.invalidate()
        self.player_card.updateGeometry()
        self.layout().invalidate()
        if not self._artwork_pixmap.isNull():
            key = (self._artwork_pixmap.cacheKey(), size, self._art_radius())
            if key != getattr(self, "_fitted_art_key", None):
                self.lbl_large_art.setPixmap(self._rounded_art(self._artwork_pixmap, size, self._art_radius()))
                self._fitted_art_key = key

    def _art_radius(self):
        return 10

    def apply_layout(self, name):
        self._layout_name = "Classic"
        spec = LAYOUT_THEMES["Classic"]
        if self.player_shell.indexOf(self.lbl_large_art) >= 0:
            self.player_shell.removeWidget(self.lbl_large_art)
            self.identity_layout.insertWidget(0, self.lbl_large_art)
        self.identity_layout.setDirection(QBoxLayout.Direction.TopToBottom)
        alignment = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        self.lbl_title.setAlignment(alignment)
        self.lbl_artist.setAlignment(alignment)
        self.identity_layout.setAlignment(self.lbl_large_art, Qt.AlignmentFlag.AlignCenter)
        set_widget_style(self.lbl_title, "font-family: 'Segoe UI'; font-size: 18px; font-weight: 500; color: #edf1f0;")
        for control, glyph in ((self.btn_prev, Icons.PREV), (self.btn_next, Icons.NEXT)):
            control.setText(glyph)
            control.setFixedWidth(36)
            set_widget_style(control, self._transport_styles[control])
        self.btn_play.setFixedWidth(36)
        set_widget_style(self.btn_play, self._play_button_style())
        self.btn_play.setText(Icons.PAUSE if self._is_playing else Icons.PLAY)
        self.lyrics_widget.apply_design("Classic")
        for label in (self.lbl_elapsed, self.lbl_remaining):
            set_widget_style(label, "font-family: 'Segoe UI'; font-size: 11px; color: #a7adab;")
        columns = self.layout()
        columns.removeWidget(self.player_card)
        columns.removeWidget(self.lyrics_widget)
        widgets = (self.player_card, self.lyrics_widget)
        for widget, stretch in zip(widgets, spec["media_columns"]):
            columns.addWidget(widget, stretch)
        columns.setContentsMargins(spec["inset"], 4, spec["inset"], 8)
        columns.setSpacing(spec["spacing"])
        self._set_surface(self._artwork_surface)
        self.fit_height(self.height())
        QTimer.singleShot(0, self, self._elide_metadata)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "lyrics_widget"):
            self.fit_height(self.height())
            QTimer.singleShot(0, self, self._elide_metadata)

    def _play_button_style(self):
        return "QPushButton { background: transparent; color: #edf1f0; border: none; border-radius: 4px; font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets'; font-size: 17px; padding: 0; } QPushButton:hover { background: rgba(255,255,255,0.08); } QPushButton:pressed { background: rgba(255,255,255,0.14); } QPushButton:disabled { color: #64748b; } QPushButton:focus { border: 1px solid #a7bbc7; }"

    def _set_surface(self, color):
        self._artwork_surface = QColor(color)
        color = self._theme_surface if self._surface_mode == "theme" else color
        if is_light_theme() and self._surface_mode == "artwork":
            hue, saturation, _, _ = color.getHsl()
            color = QColor.fromHsl(max(0, hue), min(saturation, 65), 242)
        spec = LAYOUT_THEMES["Classic"]
        background = color.name()
        set_widget_style(self.player_card, f"QFrame#mediaCard {{ background: {background}; border: none; border-radius: {spec['radius']}px; }} QFrame#mediaCard QLabel {{ background: transparent; border: none; }}")
        set_widget_style(self.player_card, f"QFrame#mediaCard {{ background: {background}; border: none; border-radius: {spec['radius']}px; }} QFrame#mediaCard QLabel {{ background: transparent; border: none; }}")

    @property
    def has_player_tiles(self):
        return self._show_player_tiles and len(self._sessions) > 1

    def configure_appearance(self, media_config, theme):
        previously_visible = self.has_player_tiles
        self._surface_mode = media_config.get("background", "theme")
        self._theme_surface = QColor(theme["bg"])
        self._show_player_tiles = media_config.get("show_player_tiles", True)
        self.lyrics_widget.set_auto_scroll_enabled(media_config.get("auto_scroll_lyrics", True))
        self._set_surface(self._artwork_surface)
        self.sessions_widget.setVisible(self.has_player_tiles)
        if self.has_player_tiles != previously_visible:
            self.layout_changed.emit()

    @staticmethod
    def _rounded_art(pixmap, size, radius=10):
        ratio = QApplication.instance().devicePixelRatio() if QApplication.instance() else 1.0
        pixels = round(size * ratio)
        scaled = pixmap.toImage().scaled(pixels, pixels, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        result = QImage(pixels, pixels, QImage.Format.Format_ARGB32_Premultiplied)
        result.setDevicePixelRatio(ratio)
        result.fill(Qt.GlobalColor.transparent)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(0, 0, size, size, radius, radius)
        painter.setClipPath(clip)
        source = QRect((scaled.width() - pixels) // 2, (scaled.height() - pixels) // 2, pixels, pixels)
        painter.drawImage(QRect(0, 0, size, size), scaled, source)
        painter.end()
        return QPixmap.fromImage(result)

    def _toggle_lyrics(self, checked):
        self.lyrics_widget.setVisible(checked)
        self.btn_lyrics.setAccessibleName("Hide lyrics" if checked else "Show lyrics")
        self.layout_changed.emit()

    def _show_source_menu(self):
        menu = QMenu(self)
        for session in self._sessions:
            action = menu.addAction(session["display_name"])
            action.triggered.connect(lambda checked=False, index=session["index"]: self.session_select_requested.emit(index))
        if not menu.actions():
            menu.addAction("No active players").setEnabled(False)
        try:
            menu.exec(self.btn_source.mapToGlobal(self.btn_source.rect().bottomLeft()))
        finally:
            menu.deleteLater()

    def _on_scrubber_clicked(self, val: int):
        self._pos_sec = float(val)
        self._update_time_labels()
        self.seek_requested.emit(float(val))

    def _on_scrubber_moved(self, val: int):
        self._pos_sec = float(val)
        self._update_time_labels()

    def _format_time(self, seconds: float) -> str:
        s = int(round(max(0.0, seconds)))
        mins = s // 60
        secs = s % 60
        return f"{mins:02d}:{secs:02d}"

    def _update_time_labels(self):
        self.lbl_elapsed.setText(self._format_time(self._pos_sec))
        self.lbl_remaining.setText(self._format_time(self._dur_sec) if self._dur_sec > 0 else "--:--")

    def update_timeline(self, pos_sec: float, dur_sec: float, is_playing: bool):
        self._reported_timeline = (pos_sec, dur_sec, is_playing)
        self._is_playing = is_playing
        self._last_tick_ts = time.time()
        seekable = dur_sec > 0 and self._can_seek
        if self.scrubber.isSliderDown():
            if not seekable:
                self.scrubber.cancel_drag()
            return
        self._pos_sec = pos_sec if dur_sec > 0 else 0.0
        self._dur_sec = dur_sec
        self.scrubber.setEnabled(seekable)
        self.scrubber.setRange(0, max(1, round(dur_sec)))
        self.scrubber.setValue(round(self._pos_sec))
        self._update_time_labels()
        self.lyrics_widget.update_playback_time(self._pos_sec)

    def _on_local_playback_tick(self):
        if self._is_playing and self._dur_sec > 0 and not self.scrubber.isSliderDown():
            now = time.time()
            delta = now - self._last_tick_ts
            self._last_tick_ts = now
            self._pos_sec = min(self._dur_sec, self._pos_sec + delta)
            self.scrubber.setValue(round(self._pos_sec))
            self._update_time_labels()
            self.lyrics_widget.update_playback_time(self._pos_sec)

    def set_playback_state(self, is_playing: bool):
        self._is_playing = is_playing
        self._last_tick_ts = time.time()
        self.btn_play.setText(("Pause" if is_playing else "Play") if self._layout_name == "Console" else (Icons.PAUSE if is_playing else Icons.PLAY))
        self.btn_play.setAccessibleName("Pause" if is_playing else "Play")
        self.btn_play.setToolTip("Pause" if is_playing else "Play")
        self.lyrics_widget.set_playback_state(is_playing)
        if is_playing and self.isVisible():
            self._playback_timer.start()
        else:
            self._playback_timer.stop()

    def set_lyrics(self, track_key: str, plain_lyrics: str, synced_lines: list):
        if track_key != getattr(self, "_lyrics_track_key", None):
            return
        signature = (track_key, plain_lyrics, tuple(synced_lines))
        if signature == getattr(self, "_rendered_lyrics_signature", None):
            return
        self._rendered_lyrics_signature = signature
        if synced_lines:
            self.lyrics_widget.set_synced_lyrics(synced_lines)
        elif plain_lyrics:
            self.lyrics_widget.set_plain_lyrics(plain_lyrics)
        else:
            self.lyrics_widget.set_not_found(self.lbl_title.text(), self.lbl_artist.text())

    def set_lyrics_loading(self, title: str, artist: str, album: str = "", duration: float = 0):
        key = LyricsManager._make_key(title, artist, album, duration)
        if key == getattr(self, "_lyrics_track_key", None):
            return
        self._lyrics_track_key = key
        self._rendered_lyrics_signature = None
        self.lyrics_widget.set_loading(title, artist)

    def set_lyrics_not_found(self, track_key: str):
        if track_key not in ("No Media Playing", "Unknown Title", "") and track_key != getattr(self, "_lyrics_track_key", None):
            return
        if track_key in ("No Media Playing", "Unknown Title", ""):
            self._lyrics_track_key = None
        self.lyrics_widget.set_not_found(self.lbl_title.text(), self.lbl_artist.text())

    def update_sessions_list(self, sessions: list, active_index: int, accent: str = "#6e9bff"):
        self._sessions = sessions
        while self.pills_layout.count():
            item = self.pills_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self._source_pills.clear()
        self.sessions_widget.setVisible(self.has_player_tiles)
        self.btn_source.setEnabled(bool(sessions))
        visible_sessions = _visible_sessions(sessions, active_index)
        for session in visible_sessions:
            tile = QPushButton(session["display_name"], self.sessions_widget)
            tile.setProperty("playerName", session["display_name"])
            tile.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            tile.setFixedHeight(26)
            tile.setCursor(Qt.CursorShape.PointingHandCursor)
            tile.setCheckable(True)
            tile.setAutoExclusive(True)
            tile.setChecked(session["index"] == active_index)
            set_widget_style(tile, "QPushButton { background: transparent; color: #a7adab; border: none; border-radius: 6px; font-family: 'Segoe UI'; font-size: 11px; font-weight: 400; padding: 3px 6px; } QPushButton:checked { color: #edf1f0; background: rgba(255,255,255,0.08); } QPushButton:hover { color: #edf1f0; background: rgba(255,255,255,0.05); } QPushButton:focus { border: 1px solid #a7adab; }")
            tile.setAccessibleName(f"Switch to {session['display_name']}")
            tile.setToolTip(session.get("title", session["display_name"]))
            tile.clicked.connect(lambda checked=False, index=session["index"]: self.session_select_requested.emit(index))
            self.pills_layout.addWidget(tile, 1)
            self._source_pills.append(tile)
            tile.show()
        if sessions and 0 <= active_index < len(sessions):
            self.btn_source.setText(sessions[active_index]["display_name"])
        self.player_card.updateGeometry()
        self.layout().invalidate()
        self.layout_changed.emit()

    def set_accent(self, accent: str):
        self._accent = accent
        set_widget_style(self.btn_play, self._play_button_style())

    def update_media(self, data: dict):
        track_key = tuple(data.get(key) for key in ("index", "source_app", "title", "artist", "album"))
        if track_key != self._track_key:
            self._track_key = track_key
            self.scrubber.cancel_drag()
        self._can_seek = data.get("can_seek", False)
        title = data.get("title", "No Media Playing")
        available = title not in ("No Media Playing", "Unknown Title", "")
        artist = data.get("artist", "")
        source = data.get("display_name") or "Player"
        self._media_title = title if available else "Nothing playing"
        self._media_artist = artist if available else "Play something in your music app"
        self._elide_metadata()
        self.lbl_title.setToolTip(title if available else "")
        self.lbl_artist.setToolTip(artist if available else "")
        self.set_playback_state(bool(data.get("is_playing", False)))
        self.lbl_source.setText(source)
        self.btn_source.setText(source if available else "Player")
        self.btn_source.setEnabled(available)
        for control in (self.btn_play, self.btn_prev, self.btn_next):
            control.setEnabled(available)
        self.update_timeline(data.get("position_sec", 0.0), data.get("duration_sec", 0.0), data.get("is_playing", False))
        thumbnail = data.get("thumbnail_bytes")
        if thumbnail == getattr(self, "_last_thumbnail", object()):
            return
        self._last_thumbnail = thumbnail
        pixmap = QPixmap()
        if data.get("thumbnail_bytes") and pixmap.loadFromData(data["thumbnail_bytes"]):
            self._artwork_pixmap = QPixmap(pixmap)
            self.lbl_large_art.setPixmap(self._rounded_art(pixmap, self.lbl_large_art.width(), self._art_radius()))
            self._fitted_art_key = (self._artwork_pixmap.cacheKey(), self.lbl_large_art.width(), self._art_radius())
            sample = pixmap.toImage().scaled(8, 8)
            colors = [sample.pixelColor(x, y) for x in range(8) for y in range(8)]
            average = QColor(*(sum(getattr(c, channel)() for c in colors) // len(colors) for channel in ("red", "green", "blue")))
            hue, saturation, lightness, alpha = average.getHsl()
            tint = QColor.fromHsl(max(0, hue), min(65, saturation), 31)
            self._set_surface(tint)
        else:
            self._artwork_pixmap = QPixmap()
            self.lbl_large_art.clear()
            self.lbl_large_art.setText(Icons.MUSIC)
            self._set_surface(QColor("#1c2723"))

    def set_volume_display(self, vol: int, is_muted: bool = False, *, sync_slider=True):
        if sync_slider:
            self.vol_slider.blockSignals(True)
            self.vol_slider.setValue(vol)
            self.vol_slider.blockSignals(False)
        if is_muted:
            self.btn_vol_music.setText(Icons.MUTE)
            self.btn_vol_music.setToolTip("Audio Muted (Click to Unmute)")
        else:
            if vol == 0:
                icon = Icons.MUTE
            elif vol < 35:
                icon = Icons.VOLUME_LOW
            elif vol < 70:
                icon = Icons.VOLUME_MED
            else:
                icon = Icons.VOLUME
            self.btn_vol_music.setText(icon)
            self.btn_vol_music.setToolTip("Audio (Click to Mute)")


class BasicTimer(QWidget):
    """An independent stopwatch or countdown driven by monotonic time."""

    finished = Signal()

    def __init__(self, *, countdown):
        super().__init__()
        self._countdown = countdown
        self._started = None
        self._elapsed = 0.0
        self._clock = time.monotonic
        self._ticker = QTimer(self, interval=100)
        self._ticker.timeout.connect(self._update_time)
        layout = QVBoxLayout(self)
        layout.addStretch()
        self.readout = QLabel()
        self.readout.setAccessibleName("Time remaining" if countdown else "Elapsed time")
        self.readout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_widget_style(self.readout, "font-size: 52px; font-weight: 500; color: #f0f2f2;")
        layout.addWidget(self.readout)
        self.duration = QSpinBox()
        self.duration.setRange(1, 1440)
        self.duration.setValue(5)
        self.duration.setSuffix(" min")
        self.duration.setAccessibleName("Countdown duration in minutes")
        set_widget_style(self.duration, "QSpinBox { background: #242829; color: #edf0f0; "
                                        "border: 1px solid #3a3d3e; border-radius: 6px; padding: 4px 8px; }"
                                        " QSpinBox:focus { border-color: #a6b0b1; }")
        self.duration.setVisible(countdown)
        self.duration.valueChanged.connect(self._reset)
        layout.addWidget(self.duration, alignment=Qt.AlignmentFlag.AlignHCenter)
        actions = QHBoxLayout()
        actions.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.toggle = QPushButton("Start")
        self.toggle.setMinimumWidth(84)
        set_widget_style(self.toggle, "QPushButton { background: #e4eae7; color: #17201c; border: 1px solid transparent;"
                                      " border-radius: 5px; padding: 6px 12px; font-weight: 600; }"
                                      " QPushButton:hover { background: #ffffff; }"
                                      " QPushButton:focus { border-color: #97b2a3; }")
        self.toggle.clicked.connect(self._toggle)
        self.reset = QPushButton("Reset")
        self.reset.clicked.connect(self._reset)
        actions.addWidget(self.toggle)
        actions.addWidget(self.reset)
        layout.addLayout(actions)
        layout.addStretch()
        self._update_time()

    def _toggle(self):
        now = self._clock()
        if self._started is None:
            if self._countdown and self._elapsed >= self.duration.value() * 60:
                self._elapsed = 0.0
            self._started = now
            self.duration.setEnabled(False)
            self.toggle.setText("Pause")
            self._ticker.start()
        else:
            self._update_time()
            if self._started is None:
                return
            self._elapsed += now - self._started
            self._started = None
            self._ticker.stop()
            self.toggle.setText("Resume")
        self._update_time()

    def _reset(self):
        self._started = None
        self._elapsed = 0.0
        self._ticker.stop()
        self.toggle.setText("Start")
        self.duration.setEnabled(True)
        self._update_time()

    def _update_time(self):
        elapsed = self._elapsed if self._started is None else self._elapsed + self._clock() - self._started
        seconds = int(elapsed)
        if self._countdown:
            limit = self.duration.value() * 60
            seconds = max(0, limit - seconds)
            if not seconds and self._started is not None:
                self._started = None
                self._elapsed = limit
                self._ticker.stop()
                self.toggle.setText("Start")
                self.duration.setEnabled(True)
                self.finished.emit()
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        prefix = f"{hours}:" if hours else ""
        self.readout.setText(f"{prefix}{minutes:02d}:{seconds:02d}")


class TimerTabView(QWidget):
    """Full dedicated Pomodoro / Focus tab matching NotchX TimerView.cs."""
    def __init__(self, parent=None, accent="#6e9bff"):
        super().__init__(parent)
        self._accent = accent
        self._init_ui()

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 8, 16, 8)
        header = QHBoxLayout()
        heading = QLabel("Timer")
        set_widget_style(heading, "font-size: 16px; font-weight: 600; color: #edf1f0;")
        header.addWidget(heading)
        header.addStretch()
        self.mode = QComboBox()
        self.mode.setAccessibleName("Timer mode")
        self.mode.addItems(["Focus sessions", "Countdown", "Stopwatch"])
        set_widget_style(self.mode, "QComboBox { background: #242829; color: #edf0f0; "
                                    "border: 1px solid #3a3d3e; border-radius: 6px; padding: 4px 8px; }"
                                    " QComboBox:focus { border-color: #a6b0b1; }"
                                    " QComboBox QAbstractItemView { background: #242829; color: #edf0f0; }")
        header.addWidget(self.mode)
        outer.addLayout(header)
        modes = QStackedWidget()
        self.mode.currentIndexChanged.connect(modes.setCurrentIndex)
        focus = QWidget()
        self.countdown = BasicTimer(countdown=True)
        self.stopwatch = BasicTimer(countdown=False)
        for page in (focus, self.countdown, self.stopwatch):
            modes.addWidget(page)
        outer.addWidget(modes, 1)
        layout = QVBoxLayout(focus)
        layout.setContentsMargins(20, 8, 20, 12)
        layout.setSpacing(14)
        phase_row = QHBoxLayout()
        phase_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn_phase_focus = QPushButton("Focus")
        self.btn_phase_short = QPushButton("Short break")
        self.btn_phase_long = QPushButton("Long break")
        for button in (self.btn_phase_focus, self.btn_phase_short, self.btn_phase_long):
            button.setCheckable(True)
            button.setAutoExclusive(True)
            set_widget_style(button, "QPushButton { background: transparent; border: none; padding: 6px 14px; color: #9ba1a2; } QPushButton:checked { background: #2b2e2f; color: #f0f2f2; } QPushButton:focus { border: 1px solid #a6b0b1; }")
            phase_row.addWidget(button)
        self.btn_phase_focus.setChecked(True)
        layout.addLayout(phase_row)
        layout.addStretch()

        ring_container = QWidget()
        ring_container.setFixedSize(190, 190)
        self.ring = CircularProgressRing(size=184, track_width=3, accent="#bcc8c3")
        ring_layout = QGridLayout(ring_container)
        ring_layout.setContentsMargins(0, 0, 0, 0)
        ring_layout.addWidget(self.ring, 0, 0, Qt.AlignmentFlag.AlignCenter)
        text = QWidget()
        text_layout = QVBoxLayout(text)
        text_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text_layout.setSpacing(0)
        self.lbl_time = QLabel("25:00")
        self.lbl_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_widget_style(self.lbl_time, "font-size: 40px; font-weight: 400; color: #f0f2f2;")
        self.lbl_phase = QLabel("Focus")
        self.lbl_phase.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_widget_style(self.lbl_phase, "font-size: 12px; color: #9ba3a1;")
        text_layout.addWidget(self.lbl_time)
        text_layout.addWidget(self.lbl_phase)
        ring_layout.addWidget(text, 0, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(ring_container, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()

        controls = QHBoxLayout()
        controls.setAlignment(Qt.AlignmentFlag.AlignCenter)
        controls.setSpacing(18)
        self.btn_reset = IconButton(Icons.CLEAR, "Reset timer", size=34, font_size=16, is_fluent=True)
        self.btn_toggle = QPushButton("Start")
        self.btn_toggle.setFixedSize(104, 36)
        set_widget_style(self.btn_toggle, "QPushButton { background: #e4eae7; color: #17201c; border: none; border-radius: 18px; font-size: 13px; font-weight: 600; } QPushButton:hover { background: #ffffff; } QPushButton:focus { border: 2px solid #97b2a3; }")
        self.btn_skip = IconButton(Icons.NEXT, "Skip phase", size=34, font_size=16, is_fluent=True)
        controls.addWidget(self.btn_reset)
        controls.addWidget(self.btn_toggle)
        controls.addWidget(self.btn_skip)
        layout.addLayout(controls)
        stats = QHBoxLayout()
        stats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        stats.setSpacing(14)
        self.lbl_streak = QLabel("0 sessions completed")
        self.lbl_daily = QLabel("0m this run")
        for label in (self.lbl_streak, self.lbl_daily):
            set_widget_style(label, "font-size: 11px; color: #929a97;")
            stats.addWidget(label)
        layout.addLayout(stats)

    def set_accent(self, accent: str):
        self._accent = accent



class ShelfItemRow(QFrame):
    chat_copied = Signal()
    pin_requested = Signal(str)
    removed = Signal(str)

    def __init__(self, staged_item, screenshot_watcher=None, shelf_mgr=None, parent=None):
        super().__init__(parent)
        self.item = staged_item
        self.watcher = screenshot_watcher
        self.shelf_mgr = shelf_mgr
        self._drag_start_pos = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(self.item.path)
        self._init_ui()

    def _init_ui(self):
        self.setFixedHeight(82)
        set_widget_style(self, "ShelfItemRow { background: #1a1d1e; border: none; border-radius: 12px; } ShelfItemRow:hover { background: #232728; }")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(14)
        self.thumb = DraggableThumbnail(size=56, border_radius=8, parent=self)
        self.thumb.set_image(self.item.path, self.item.thumbnail if self.item.is_image else None)
        if not self.item.is_image and self.item.icon and not self.item.icon.isNull():
            self.thumb.setPixmap(self.item.icon.pixmap(32, 32))
        self.thumb.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.thumb)
        metadata = QVBoxLayout()
        metadata.setSpacing(4)
        self.lbl_name = QLabel(self.item.name)
        self.lbl_name.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        set_widget_style(self.lbl_name, "font-size: 13px; font-weight: 500; color: #e9edec;")
        self.lbl_name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        metadata.addWidget(self.lbl_name)
        size = "Folder" if self.item.is_dir else (f"{self.item.size_bytes / 1048576:.1f} MB" if self.item.size_bytes >= 1048576 else f"{max(1, self.item.size_bytes // 1024)} KB")
        subtitle = QLabel(f"{size}  ·  Drag to another app")
        set_widget_style(subtitle, "font-size: 11px; color: #9ca5a1;")
        subtitle.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        metadata.addWidget(subtitle)
        layout.addLayout(metadata, 1)
        self.btn_pin = QPushButton("Pin" if self.item.is_image else "Open")
        self.btn_pin.setToolTip("Float image on screen" if self.item.is_image else "Open with the default app")
        self.btn_pin.clicked.connect(self._open_item)
        layout.addWidget(self.btn_pin)
        self.btn_chat = QPushButton("Copy")
        self.btn_chat.setToolTip("Copy image and file" if self.item.is_image else "Copy file")
        self.btn_chat.clicked.connect(self._copy_for_chat)
        layout.addWidget(self.btn_chat)
        remove = IconButton(Icons.CLOSE, "Remove from shelf. Original file is kept.", size=28, font_size=12, is_fluent=True)
        remove.clicked.connect(lambda: self.removed.emit(self.item.path))
        layout.addWidget(remove)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.lbl_name.setText(self.lbl_name.fontMetrics().elidedText(self.item.name, Qt.TextElideMode.ElideMiddle, max(20, self.lbl_name.width())))

    def _open_item(self):
        if self.item.is_image:
            self.pin_requested.emit(self.item.path)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.item.path))

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._open_item()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

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
        if not self.item or not os.path.exists(self.item.path):
            return

        drag = self.shelf_mgr.create_drag(self, self.item)
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        drag.exec(
            Qt.DropAction.CopyAction,
            Qt.DropAction.CopyAction
        )
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def _copy_for_chat(self):
        if self.watcher and self.item.is_image:
            if not self.watcher.copy_image_for_chat(self.item.path):
                self.btn_chat.setText("Retry")
                QTimer.singleShot(1800, self.btn_chat, self._reset_chat_btn)
                return
        else:
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(self.item.path)])
            if self.item.is_image:
                mime.setImageData(QImage(self.item.path))
            QApplication.clipboard().setMimeData(mime)
        self.btn_chat.setText("Copied")
        QTimer.singleShot(1800, self.btn_chat, self._reset_chat_btn)

    def _reset_chat_btn(self):
        self.btn_chat.setText("Copy")


class ShelfTabView(QWidget):
    """File staging shelf matching NotchX ShelfView.xaml."""
    pin_requested = Signal(str)

    def __init__(self, drop_shelf_manager, screenshot_watcher=None, parent=None):
        super().__init__(parent)
        self.shelf_mgr = drop_shelf_manager
        self.watcher = screenshot_watcher
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(8)

        # Header
        hdr = QHBoxLayout()
        self.lbl_title = QLabel("Shelf")
        set_widget_style(self.lbl_title, "QLabel { font-size: 15px; font-weight: 700; color: #ffffff; background: transparent; border: none; }")
        self.btn_clear = QPushButton("Clear shelf")
        set_widget_style(self.btn_clear, "font-size: 11.5px; padding: 5px 12px; border-radius: 9px; background: rgba(255, 255, 255, 0.05); color: rgba(255, 255, 255, 0.7); border: 1px solid rgba(255, 255, 255, 0.08);")
        self.btn_clear.clicked.connect(self.shelf_mgr.clear_shelf)
        hdr.addWidget(self.lbl_title)
        hdr.addStretch()
        self.btn_downloads = QPushButton("Downloads")
        self.btn_downloads.hide()
        hdr.addWidget(self.btn_downloads)
        self.btn_add = QPushButton("Add files")
        set_widget_style(self.btn_add, "font-size: 11.5px; padding: 5px 12px; border-radius: 9px; background: #f28c5a; color: #0e1117; font-weight: 600; border: none;")
        self.btn_add.clicked.connect(self._browse_files)
        hdr.addWidget(self.btn_add)
        hdr.addWidget(self.btn_clear)
        layout.addLayout(hdr)

        # Scroll area for items
        self.scroll_area = ScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        set_widget_style(self.scroll_area, """
            QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget {
                background: transparent;
                border: none;
            }
        """)
        self.items_container = QWidget()
        self.items_layout = QVBoxLayout(self.items_container)
        self.items_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.items_layout.setContentsMargins(0, 0, 0, 0)
        self.items_layout.setSpacing(6)
        self.scroll_area.setWidget(self.items_container)
        layout.addWidget(self.scroll_area, stretch=1)

        # Empty State Placeholder
        self.empty_card = QFrame()
        set_widget_style(self.empty_card, """
            QFrame {
                background: rgba(255, 255, 255, 0.025);
                border: none;
                border-radius: 10px;
                padding: 16px;
            }
        """)
        l_emp = QVBoxLayout(self.empty_card)
        l_emp.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_emp_icon = QLabel(Icons.IMAGE)
        set_widget_style(lbl_emp_icon, "font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets'; font-size: 26px; color: #64748b; background: transparent; border: none;")
        lbl_emp_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_emp_text = QLabel("Drop files here\nThen drag them into another app. Originals stay where they are.")
        lbl_emp_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_emp_text.setWordWrap(True)
        set_widget_style(lbl_emp_text, "font-size: 13px; color: #a0aaa5; background: transparent; border: none;")
        l_emp.addWidget(lbl_emp_icon)
        l_emp.addWidget(lbl_emp_text)
        layout.addWidget(self.empty_card, stretch=1)

        self.shelf_mgr.shelf_updated.connect(self.refresh_items)
        self.refresh_items()

    def _browse_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Add files to shelf")
        if paths:
            self.shelf_mgr.add_paths(paths)

    def refresh_items(self):
        # Clear existing items
        while self.items_layout.count() > 0:
            item = self.items_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        items = self.shelf_mgr.staged_items
        count = len(items)
        self.lbl_title.setText(f"Shelf · {count} file{'s' if count != 1 else ''}")
        self.btn_clear.setEnabled(count > 0)

        if count == 0:
            self.scroll_area.setVisible(False)
            self.empty_card.setVisible(True)
        else:
            self.empty_card.setVisible(False)
            self.scroll_area.setVisible(True)
            for it in reversed(items):  # Newest items first
                row = ShelfItemRow(it, self.watcher, self.shelf_mgr, self.items_container)
                row.removed.connect(self.shelf_mgr.remove_item)
                row.pin_requested.connect(self.pin_requested.emit)
                self.items_layout.addWidget(row)
            self.items_layout.addStretch()


class NotesTabView(QWidget):
    """Full scratchpad view with instant tear-off sticky note spawning and persistence."""
    tear_off_requested = Signal(str)
    saved_note_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scratch_file = data_path("scratchpad.txt")
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(8)

        # Header
        hdr = QHBoxLayout()
        lbl_title = QLabel("Notes")
        set_widget_style(lbl_title, "QLabel { font-size: 14px; font-weight: 500; color: #dce3df; background: transparent; border: none; }")
        self.btn_tear = QPushButton("Floating copy")
        set_widget_style(self.btn_tear, "font-size: 12px; padding: 5px 10px; border-radius: 6px; background: #242829;")
        self.btn_tear.clicked.connect(self._tear_off)
        hdr.addWidget(lbl_title)
        hdr.addStretch()
        self.btn_saved = QPushButton("Saved notes")
        self.btn_saved.clicked.connect(self._show_saved_notes)
        hdr.addWidget(self.btn_saved)
        hdr.addWidget(self.btn_tear)
        layout.addLayout(hdr)

        # Multiline Note Editor
        self.editor = QTextEdit()
        self.editor.setPlaceholderText("Write a note…")
        self.editor.setAcceptRichText(False)
        self.editor.setAccessibleName("Notes editor")
        set_widget_style(self.editor, "QTextEdit { background: #171a19; border: 1px solid #272d2a; border-radius: 12px; padding: 14px; color: #e2e8e4; font-size: 14px; selection-background-color: #40584a; } QTextEdit:focus { border-color: #414e46; }")
        if self._scratch_file.exists():
            try:
                self.editor.setPlainText(self._scratch_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(600)
        self._save_timer.timeout.connect(self._save_scratch)
        self.editor.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.editor)

        # Footer
        ftr = QHBoxLayout()
        self.lbl_word_count = QLabel("0 words · 0 characters")
        set_widget_style(self.lbl_word_count, "QLabel { font-size: 11px; color: #94a3b8; background: transparent; border: none; }")
        ftr.addWidget(self.lbl_word_count)
        ftr.addStretch()
        layout.addLayout(ftr)
        self._on_text_changed()

    def _save_scratch(self):
        try:
            write_text(self._scratch_file, self.editor.toPlainText())
            self.lbl_word_count.setToolTip("")
            return True
        except OSError as error:
            self.lbl_word_count.setText("Not saved. Check the data folder and try again.")
            self.lbl_word_count.setToolTip(str(error))
            return False

    def flush_notes(self):
        pending = self._save_timer.isActive()
        self._save_timer.stop()
        return self._save_scratch() if pending or self.lbl_word_count.toolTip() else True

    def _show_saved_notes(self):
        from PySide6.QtWidgets import QMenu
        from poppy.ui.sticky_note import FloatingStickyNote
        menu = QMenu(self)
        for note in FloatingStickyNote.saved_notes():
            title = note["text"].splitlines()[0][:60] if note["text"].strip() else "Empty note"
            action = menu.addAction(title)
            action.triggered.connect(lambda checked=False, key=note["id"]: self.saved_note_requested.emit(key))
        if not menu.actions():
            menu.addAction("No saved floating notes").setEnabled(False)
        menu.exec(self.btn_saved.mapToGlobal(self.btn_saved.rect().bottomLeft()))

    def _clear_notes(self):
        self.editor.clear()
        self._save_scratch()

    def _on_text_changed(self):
        text = self.editor.toPlainText()
        words = len(text.split()) if text.strip() else 0
        chars = len(text)
        self.lbl_word_count.setText(f"{words} words · {chars} characters")
        self._save_timer.start()

    def _tear_off(self):
        text = self.editor.toPlainText()
        self.tear_off_requested.emit(text)
