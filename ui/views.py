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
from PySide6.QtCore import Qt, Signal, QUrl, QMimeData, QTimer
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QLineEdit, QTextEdit, QPushButton, QSlider,
    QFrame, QScrollArea, QApplication
)

from poppy.ui.components import (
    IconButton, CircularProgressRing, AudioVisualizerBars, MetricLabel,
    CardFrame, SourcePill, DraggableThumbnail, ClickableSlider, SpotifyLyricsWidget
)
from poppy.ui.icons import Icons


class HomeTabView(QWidget):
    """Home dashboard featuring 4 responsive cards inspired by home-v2.png."""
    tear_off_requested = Signal(str)
    session_select_requested = Signal(int)
    pin_requested = Signal(str)
    caffeine_toggle_requested = Signal()
    mic_mute_toggle_requested = Signal()
    focus_shield_requested = Signal()
    screen_snip_requested = Signal()
    eyedropper_requested = Signal()
    quick_search_requested = Signal()
    lock_workstation_requested = Signal()
    player_menu_requested = Signal()
    weather_refresh_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_pills = []
        self._latest_shelf_path = ""
        self._init_ui()

    def _init_ui(self):
        grid = QGridLayout(self)
        grid.setContentsMargins(12, 8, 12, 10)
        grid.setSpacing(12)

        # -------------------------------------------------------------
        # Card 1: Clock, Date & Hardware Telemetry (home-v2 Card 1)
        # -------------------------------------------------------------
        card_clock = CardFrame(self)
        l_clock = QVBoxLayout(card_clock)
        l_clock.setContentsMargins(16, 14, 16, 14)
        l_clock.setSpacing(4)

        self.lbl_big_time = QLabel("12:11:29 AM")
        self.lbl_big_time.setStyleSheet("""
            QLabel {
                font-size: 28px;
                font-weight: 700;
                color: #f8fafc;
                background: transparent;
                border: none;
                letter-spacing: -0.5px;
            }
        """)
        self.lbl_date = QLabel("Monday, 5 October")
        self.lbl_date.setStyleSheet("QLabel { font-size: 11px; color: #94a3b8; font-weight: 500; background: transparent; border: none; }")

        # Weather / Status row
        weather_row = QHBoxLayout()
        weather_row.setSpacing(6)
        self.lbl_weather_icon = QLabel(Icons.WEATHER_SUN)
        self.lbl_weather_icon.setStyleSheet("font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets'; font-size: 13px; color: #94a3b8; background: transparent; border: none;")
        self.lbl_weather_text = QLabel("Fetching live weather...")
        self.lbl_weather_text.setStyleSheet("font-size: 11px; color: #cbd5e1; background: transparent; border: none;")
        self.lbl_weather_text.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_weather_text.setToolTip("Click to Refresh Weather")
        self.lbl_weather_text.mousePressEvent = lambda e: self.weather_refresh_requested.emit()
        weather_row.addWidget(self.lbl_weather_icon)
        weather_row.addWidget(self.lbl_weather_text)
        weather_row.addStretch()

        # Telemetry pills row
        telemetry_row = QHBoxLayout()
        telemetry_row.setSpacing(5)
        self.lbl_cpu = MetricLabel("CPU", "0%")
        self.lbl_gpu = MetricLabel("GPU", "--%")
        self.lbl_ram = MetricLabel("RAM", "0%")
        self.lbl_bat = MetricLabel("BAT", "--%")
        telemetry_row.addWidget(self.lbl_cpu)
        telemetry_row.addWidget(self.lbl_gpu)
        telemetry_row.addWidget(self.lbl_ram)
        telemetry_row.addWidget(self.lbl_bat)
        telemetry_row.addStretch()

        l_clock.addWidget(self.lbl_big_time)
        l_clock.addWidget(self.lbl_date)
        l_clock.addSpacing(4)
        l_clock.addLayout(weather_row)
        l_clock.addStretch()
        l_clock.addLayout(telemetry_row)
        grid.addWidget(card_clock, 0, 0)

        # -------------------------------------------------------------
        # Card 2: Audio, Sliders & Quick Controls (home-v2 Card 2)
        # -------------------------------------------------------------
        card_controls = CardFrame(self)
        l_ctrl = QVBoxLayout(card_controls)
        l_ctrl.setContentsMargins(16, 12, 16, 12)
        l_ctrl.setSpacing(8)

        # Volume Slider row with numeric readout
        row_vol = QHBoxLayout()
        row_vol.setSpacing(8)
        self.btn_vol_mute = QPushButton(Icons.VOLUME)
        self.btn_vol_mute.setFixedSize(22, 22)
        self.btn_vol_mute.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_vol_mute.setToolTip("Click to Mute / Unmute")
        self.btn_vol_mute.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets';
                font-size: 13px;
                color: #94a3b8;
                padding: 0px;
            }
            QPushButton:hover {
                color: #ffffff;
            }
        """)
        self.slider_vol = QSlider(Qt.Orientation.Horizontal)
        self.slider_vol.setRange(0, 100)
        self.slider_vol.setValue(50)
        self.lbl_vol_num = QLabel("50")
        self.lbl_vol_num.setFixedWidth(24)
        self.lbl_vol_num.setStyleSheet("font-size: 11px; color: #94a3b8; font-weight: 600; background: transparent; border: none;")
        self.slider_vol.valueChanged.connect(lambda v: self.lbl_vol_num.setText(str(v)))
        row_vol.addWidget(self.btn_vol_mute)
        row_vol.addWidget(self.slider_vol, stretch=1)
        row_vol.addWidget(self.lbl_vol_num)
        l_ctrl.addLayout(row_vol)

        # Brightness / Playback Slider row
        row_bright = QHBoxLayout()
        row_bright.setSpacing(8)
        self.btn_bright_icon = QPushButton(Icons.BRIGHTNESS)
        self.btn_bright_icon.setFixedSize(22, 22)
        self.btn_bright_icon.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_bright_icon.setToolTip("Click to cycle brightness presets (25% → 50% → 75% → 100%)")
        self.btn_bright_icon.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets';
                font-size: 13px;
                color: #94a3b8;
                padding: 0px;
            }
            QPushButton:hover {
                color: #ffffff;
            }
        """)
        self.slider_bright = QSlider(Qt.Orientation.Horizontal)
        self.slider_bright.setRange(0, 100)
        self.slider_bright.setValue(75)
        self.lbl_bright_num = QLabel("75")
        self.lbl_bright_num.setFixedWidth(24)
        self.lbl_bright_num.setStyleSheet("font-size: 11px; color: #94a3b8; font-weight: 600; background: transparent; border: none;")
        self.slider_bright.valueChanged.connect(lambda v: self.lbl_bright_num.setText(str(v)))
        row_bright.addWidget(self.btn_bright_icon)
        row_bright.addWidget(self.slider_bright, stretch=1)
        row_bright.addWidget(self.lbl_bright_num)
        l_ctrl.addLayout(row_bright)

        # Media Player Selector Pill + Controls row
        row_dev = QHBoxLayout()
        row_dev.setSpacing(6)
        self.btn_player_drop = QPushButton("Speakers (Spotify ▾)")
        self.btn_player_drop.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.09);
                border-radius: 12px;
                color: #e2e8f0;
                font-size: 11px;
                font-weight: 500;
                padding: 3px 10px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.1);
            }
        """)
        self.btn_dev_lock = QPushButton("Lock")
        self.btn_dev_lock.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_dev_lock.setToolTip("Lock Windows Workstation (Win + L)")
        self.btn_dev_lock.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.09);
                border-radius: 12px;
                color: #94a3b8;
                font-size: 11px;
                font-weight: 500;
                padding: 3px 8px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.1);
                color: #ffffff;
            }
        """)
        self.btn_dev_lock.clicked.connect(self.lock_workstation_requested.emit)
        self.btn_player_drop.clicked.connect(self.player_menu_requested.emit)

        # Transport icons inside controls card
        self.btn_ctrl_prev = IconButton(Icons.PREV, "Previous", size=22, font_size=10, is_fluent=True)
        self.btn_ctrl_play = IconButton(Icons.PLAY, "Play/Pause", size=24, font_size=11, is_fluent=True)
        self.btn_ctrl_next = IconButton(Icons.NEXT, "Next", size=22, font_size=10, is_fluent=True)
        self.music_bars = AudioVisualizerBars(self)

        row_dev.addWidget(self.btn_player_drop)
        row_dev.addWidget(self.btn_dev_lock)
        row_dev.addStretch()
        row_dev.addWidget(self.btn_ctrl_prev)
        row_dev.addWidget(self.btn_ctrl_play)
        row_dev.addWidget(self.btn_ctrl_next)
        row_dev.addWidget(self.music_bars)
        l_ctrl.addLayout(row_dev)

        # Track metadata labels referenced by window updates
        self.lbl_music_title = QLabel("", self)
        self.lbl_music_title.setVisible(False)
        self.lbl_music_artist = QLabel("", self)
        self.lbl_music_artist.setVisible(False)
        self.lbl_music_source = QLabel("", self)
        self.lbl_music_source.setVisible(False)

        # Quick Actions Row (home-v2.png bottom pill strip)
        row_actions = QHBoxLayout()
        row_actions.setSpacing(6)

        self.btn_act_caffeine = IconButton(Icons.POWER, "Keep Awake (Caffeine: OFF)", size=24, font_size=11, is_fluent=True)
        self.btn_act_caffeine.clicked.connect(self.caffeine_toggle_requested.emit)
        row_actions.addWidget(self.btn_act_caffeine)

        self.btn_act_mic = IconButton(Icons.MIC, "Microphone (Mute / Unmute)", size=24, font_size=11, is_fluent=True)
        self.btn_act_mic.clicked.connect(self.mic_mute_toggle_requested.emit)
        row_actions.addWidget(self.btn_act_mic)

        self.btn_act_shield = IconButton(Icons.SHIELD, "Focus Shield (Toggle Pomodoro Focus Sprint)", size=24, font_size=11, is_fluent=True)
        self.btn_act_shield.clicked.connect(self.focus_shield_requested.emit)
        row_actions.addWidget(self.btn_act_shield)

        self.btn_act_snip = IconButton(Icons.SNIP, "Screen Snip (Win + Shift + S)", size=24, font_size=11, is_fluent=True)
        self.btn_act_snip.clicked.connect(self.screen_snip_requested.emit)
        row_actions.addWidget(self.btn_act_snip)

        self.btn_act_eyedropper = IconButton(Icons.COLOR, "Color Eyedropper (Pick Screen Color)", size=24, font_size=11, is_fluent=True)
        self.btn_act_eyedropper.clicked.connect(self.eyedropper_requested.emit)
        row_actions.addWidget(self.btn_act_eyedropper)

        self.btn_act_search = IconButton(Icons.SEARCH, "Quick Search / Calculator", size=24, font_size=11, is_fluent=True)
        self.btn_act_search.clicked.connect(self.quick_search_requested.emit)
        row_actions.addWidget(self.btn_act_search)

        row_actions.addStretch()
        l_ctrl.addLayout(row_actions)

        grid.addWidget(card_controls, 0, 1)

        # -------------------------------------------------------------
        # Card 3: Notes & Scratchpad (home-v2 Card 3)
        # -------------------------------------------------------------
        card_notes = CardFrame(self)
        l_notes = QVBoxLayout(card_notes)
        l_notes.setContentsMargins(16, 12, 16, 12)
        l_notes.setSpacing(8)

        notes_hdr = QHBoxLayout()
        lbl_notes_title = QLabel("NOTES")
        lbl_notes_title.setStyleSheet("QLabel { font-size: 10.5px; font-weight: 700; color: #94a3b8; letter-spacing: 0.8px; background: transparent; border: none; }")
        self.btn_pop_note = QPushButton("Tear Off")
        self.btn_pop_note.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pop_note.setToolTip("Spawn an on-screen floating sticky note")
        self.btn_pop_note.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.07);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 5px;
                color: #e2e8f0;
                font-size: 10px;
                font-weight: 600;
                padding: 2px 8px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.14);
                color: #ffffff;
            }
        """)
        self.btn_pop_note.clicked.connect(self._on_tear_off)
        notes_hdr.addWidget(lbl_notes_title)
        notes_hdr.addStretch()
        notes_hdr.addWidget(self.btn_pop_note)
        l_notes.addLayout(notes_hdr)

        self.txt_notes = QTextEdit()
        self.txt_notes.setPlaceholderText("Jot something down...")
        self.txt_notes.setStyleSheet("""
            QTextEdit {
                background: rgba(255, 255, 255, 0.035);
                border: 1px solid rgba(255, 255, 255, 0.07);
                border-radius: 10px;
                padding: 8px;
                color: #f1f5f9;
                font-size: 11px;
            }
            QTextEdit:focus {
                border: 1px solid rgba(110, 155, 255, 0.6);
            }
        """)
        self._notes_file = Path(os.path.expanduser("~/.poppy/home_notes.txt"))
        if self._notes_file.exists():
            try:
                self.txt_notes.setText(self._notes_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        self._notes_timer = QTimer(self)
        self._notes_timer.setSingleShot(True)
        self._notes_timer.setInterval(600)
        self._notes_timer.timeout.connect(self._save_notes)
        self.txt_notes.textChanged.connect(self._notes_timer.start)
        l_notes.addWidget(self.txt_notes)
        grid.addWidget(card_notes, 1, 0)

        # -------------------------------------------------------------
        # Card 4: Quick Shelf & Calculator
        # -------------------------------------------------------------
        card_shelf = CardFrame(self)
        l_shelf = QVBoxLayout(card_shelf)
        l_shelf.setContentsMargins(16, 12, 16, 12)
        l_shelf.setSpacing(8)

        shelf_hdr = QHBoxLayout()
        self.lbl_shelf_status = QLabel("SHELF · 0 FILES")
        self.lbl_shelf_status.setStyleSheet("QLabel { font-size: 10.5px; font-weight: 700; color: #94a3b8; letter-spacing: 0.8px; background: transparent; border: none; }")
        self.btn_clear_shelf = QPushButton("Clear")
        self.btn_clear_shelf.setStyleSheet("font-size: 9px; padding: 2px 7px; border-radius: 4px; background: rgba(255,255,255,0.06);")
        shelf_hdr.addWidget(self.lbl_shelf_status)
        shelf_hdr.addStretch()
        shelf_hdr.addWidget(self.btn_clear_shelf)
        l_shelf.addLayout(shelf_hdr)

        # Staged preview frame
        self.shelf_preview_frame = QFrame()
        self.shelf_preview_frame.setStyleSheet("""
            QFrame {
                background: rgba(255, 255, 255, 0.03);
                border: 1px solid rgba(255, 255, 255, 0.07);
                border-radius: 8px;
            }
        """)
        spf_layout = QHBoxLayout(self.shelf_preview_frame)
        spf_layout.setContentsMargins(6, 4, 6, 4)
        spf_layout.setSpacing(8)

        self.shelf_thumb = DraggableThumbnail(size=34, border_radius=6, parent=self)
        spf_layout.addWidget(self.shelf_thumb)

        meta_spf = QVBoxLayout()
        meta_spf.setSpacing(1)
        self.lbl_shelf_item_name = QLabel("Screenshot.png")
        self.lbl_shelf_item_name.setStyleSheet("font-size: 10.5px; font-weight: 600; color: #f1f5f9; background: transparent; border: none;")
        self.lbl_shelf_item_sub = QLabel("Drag to screen")
        self.lbl_shelf_item_sub.setStyleSheet("font-size: 9.5px; color: #94a3b8; background: transparent; border: none;")
        meta_spf.addWidget(self.lbl_shelf_item_name)
        meta_spf.addWidget(self.lbl_shelf_item_sub)
        spf_layout.addLayout(meta_spf, stretch=1)

        self.btn_home_shelf_chat = QPushButton("Copy")
        self.btn_home_shelf_chat.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_home_shelf_chat.setStyleSheet("""
            QPushButton {
                background: rgba(14, 165, 233, 0.18);
                border: 1px solid rgba(56, 189, 248, 0.35);
                border-radius: 5px;
                color: #38bdf8;
                font-size: 9.5px;
                font-weight: 600;
                padding: 2px 7px;
            }
            QPushButton:hover {
                background: rgba(14, 165, 233, 0.3);
                color: #ffffff;
            }
        """)
        spf_layout.addWidget(self.btn_home_shelf_chat)

        self.btn_home_shelf_pin = QPushButton("Pin")
        self.btn_home_shelf_pin.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_home_shelf_pin.setToolTip("Pin to screen as a floating sticky note")
        self.btn_home_shelf_pin.setStyleSheet("""
            QPushButton {
                background: rgba(234, 179, 8, 0.18);
                border: 1px solid rgba(234, 179, 8, 0.38);
                border-radius: 5px;
                color: #facc15;
                font-size: 9.5px;
                font-weight: 600;
                padding: 2px 7px;
            }
            QPushButton:hover {
                background: rgba(234, 179, 8, 0.3);
                color: #ffffff;
            }
        """)
        self.btn_home_shelf_pin.clicked.connect(lambda: self.pin_requested.emit(self._latest_shelf_path))
        spf_layout.addWidget(self.btn_home_shelf_pin)
        l_shelf.addWidget(self.shelf_preview_frame)
        self.shelf_preview_frame.setVisible(False)

        # Empty hint
        self.lbl_shelf_empty = QLabel("Drop files or snip (Win+Shift+S / PrtScn)")
        self.lbl_shelf_empty.setStyleSheet("font-size: 10px; color: #64748b; background: transparent; border: none;")
        l_shelf.addWidget(self.lbl_shelf_empty)

        # Multi-session switcher pills strip
        self.pills_container = QHBoxLayout()
        self.pills_container.setSpacing(4)
        l_shelf.addLayout(self.pills_container)

        # Inline Calculator
        calc_row = QHBoxLayout()
        self.input_calc = QLineEdit()
        self.input_calc.setPlaceholderText("calc: 45*12, 120/3, 50^2...")
        self.input_calc.textChanged.connect(self._eval_calc)
        self.lbl_calc_res = QLabel("")
        self.lbl_calc_res.setStyleSheet("QLabel { color: #38bdf8; font-size: 11px; font-weight: 600; background: transparent; border: none; }")
        calc_row.addWidget(self.input_calc, stretch=1)
        calc_row.addWidget(self.lbl_calc_res)
        l_shelf.addLayout(calc_row)

        l_shelf.addStretch()
        grid.addWidget(card_shelf, 1, 1)

    def update_sessions_list(self, sessions: list, active_index: int, accent: str = "#6e9bff"):
        while self.pills_container.count() > 0:
            item = self.pills_container.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._source_pills.clear()

        if sessions and active_index < len(sessions):
            curr_name = sessions[active_index]["display_name"]
            self.btn_player_drop.setText(f"Speakers ({curr_name} ▾)")

        for s in sessions:
            idx = s["index"]
            name = s["display_name"]
            is_active = (idx == active_index)
            icon = f"{Icons.MUSIC} " if "spotify" in name.lower() or "apple" in name.lower() else f"{Icons.PLAY} "
            pill = SourcePill(f"{icon}{name}", session_index=idx, is_active=is_active, accent=accent, parent=self)
            pill.clicked.connect(lambda checked=False, i=idx: self.session_select_requested.emit(i))
            self.pills_container.addWidget(pill)
            self._source_pills.append(pill)

    def update_shelf_display(self, items: list):
        count = len(items)
        self.lbl_shelf_status.setText(f"SHELF · {count} FILE{'S' if count != 1 else ''}")
        if count > 0:
            latest = items[-1]
            self._latest_shelf_path = latest.path
            self.shelf_thumb.set_image(latest.path, latest.thumbnail)
            name = latest.name
            trunc_name = (name[:20] + "..") if len(name) > 20 else name
            self.lbl_shelf_item_name.setText(trunc_name)
            size_kb = max(1, latest.size_bytes // 1024)
            self.lbl_shelf_item_sub.setText(f"{size_kb} KB · Pin / Copy / Drag")
            self.shelf_preview_frame.setVisible(True)
            self.lbl_shelf_empty.setVisible(False)
        else:
            self.shelf_preview_frame.setVisible(False)
            self.lbl_shelf_empty.setVisible(True)

    def _save_notes(self):
        try:
            self._notes_file.parent.mkdir(parents=True, exist_ok=True)
            self._notes_file.write_text(self.txt_notes.toPlainText(), encoding="utf-8")
        except Exception:
            pass

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
        text = self.txt_notes.toPlainText().strip()
        self.tear_off_requested.emit(text)
        self.txt_notes.clear()
        self._save_notes()

    def set_volume_display(self, vol: int, is_muted: bool = False):
        self.slider_vol.blockSignals(True)
        self.slider_vol.setValue(vol)
        self.slider_vol.blockSignals(False)
        self.lbl_vol_num.setText(str(vol))
        if is_muted:
            self.btn_vol_mute.setText(Icons.MUTE)
            self.btn_vol_mute.setToolTip("Audio Muted (Click to Unmute)")
        else:
            if vol == 0:
                icon = Icons.MUTE
            elif vol < 35:
                icon = Icons.VOLUME_LOW
            elif vol < 70:
                icon = Icons.VOLUME_MED
            else:
                icon = Icons.VOLUME
            self.btn_vol_mute.setText(icon)
            self.btn_vol_mute.setToolTip("Audio (Click to Mute)")

    def set_brightness_display(self, bright: int):
        self.slider_bright.blockSignals(True)
        self.slider_bright.setValue(bright)
        self.slider_bright.blockSignals(False)
        self.lbl_bright_num.setText(str(bright))

    def update_weather(self, data: dict):
        """Updates the weather display with live meteorological data."""
        icon = data.get("icon", Icons.WEATHER_SUN)
        text = data.get("display_text", "")
        city = data.get("city", "")
        cond = data.get("condition", "")
        temp = data.get("temp", 0)
        h = data.get("high", 0)
        l = data.get("low", 0)
        hum = data.get("humidity", 0)

        self.lbl_weather_icon.setText(icon)
        self.lbl_weather_text.setText(text)
        self.lbl_weather_text.setToolTip(f"{city}\n{temp}°C · {cond}\nHigh: {h}°C · Low: {l}°C\nHumidity: {hum}%\n(Click to Refresh)")


class MusicTabView(QWidget):
    """Full dedicated Now Playing view matching now-playing-v2.png with Spotify-grade animated lyrics."""
    session_select_requested = Signal(int)
    seek_requested = Signal(float)

    def __init__(self, parent=None, accent="#6e9bff"):
        super().__init__(parent)
        self._accent = accent
        self._source_pills = []
        self._pos_sec = 0.0
        self._dur_sec = 0.0
        self._is_playing = False
        self._last_tick_ts = time.time()
        self._is_user_scrubbing = False

        self._init_ui()

        self._playback_timer = QTimer(self)
        self._playback_timer.setInterval(100)
        self._playback_timer.timeout.connect(self._on_local_playback_tick)
        self._playback_timer.start()

    def _init_ui(self):
        v_main = QVBoxLayout(self)
        v_main.setContentsMargins(18, 12, 18, 14)
        v_main.setSpacing(10)

        # Top Session Switcher Strip
        session_row = QHBoxLayout()
        session_row.setSpacing(6)
        lbl_s_hdr = QLabel("MEDIA PLAYERS:")
        lbl_s_hdr.setStyleSheet("QLabel { font-size: 10px; font-weight: 700; color: #64748b; letter-spacing: 0.5px; background: transparent; border: none; }")
        session_row.addWidget(lbl_s_hdr)

        self.btn_prev_session = IconButton("‹", "Previous Player", size=22, font_size=13)
        self.btn_next_session = IconButton("›", "Next Player", size=22, font_size=13)
        session_row.addWidget(self.btn_prev_session)
        session_row.addWidget(self.btn_next_session)

        self.pills_layout = QHBoxLayout()
        self.pills_layout.setSpacing(6)
        session_row.addLayout(self.pills_layout)
        session_row.addStretch()
        v_main.addLayout(session_row)

        # Center Content (Left: Album Art, Middle: Controls, Right: Spotify Animated Lyrics)
        main_layout = QHBoxLayout()
        main_layout.setSpacing(16)

        # Left: Album Art Card (144x144)
        self.art_container = CardFrame(self)
        self.art_container.setFixedSize(144, 144)
        art_layout = QVBoxLayout(self.art_container)
        art_layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_large_art = QLabel()
        self.lbl_large_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_large_art.setStyleSheet("font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets'; font-size: 40px; color: #64748b; border: none; background: transparent;")
        self.lbl_large_art.setText(Icons.MUSIC)
        art_layout.addWidget(self.lbl_large_art)
        main_layout.addWidget(self.art_container)

        # Center: Track Metadata, Scrubber, Transport Controls
        info_col = QVBoxLayout()
        info_col.setContentsMargins(0, 4, 0, 4)
        info_col.setSpacing(5)

        self.lbl_title = QLabel("No Media Playing")
        self.lbl_title.setStyleSheet("QLabel { font-size: 17px; font-weight: 700; color: #f8fafc; background: transparent; border: none; }")
        self.lbl_artist = QLabel("Desktop Audio")
        self.lbl_artist.setStyleSheet("QLabel { font-size: 12px; color: #94a3b8; background: transparent; border: none; }")

        source_row = QHBoxLayout()
        self.lbl_source = QLabel("Desktop Audio")
        self.lbl_source.setStyleSheet("QLabel { font-size: 10px; font-weight: 600; color: #64748b; letter-spacing: 0.5px; background: transparent; border: none; }")
        self.bars = AudioVisualizerBars(self)
        source_row.addWidget(self.lbl_source)
        source_row.addWidget(self.bars)
        source_row.addStretch()

        info_col.addWidget(self.lbl_title)
        info_col.addWidget(self.lbl_artist)
        info_col.addLayout(source_row)

        # Scrubber Progress Slider with interactive click & seek
        self.scrubber = ClickableSlider(Qt.Orientation.Horizontal)
        self.scrubber.setRange(0, 100)
        self.scrubber.setValue(0)
        self.scrubber.seek_clicked.connect(self._on_scrubber_clicked)
        self.scrubber.sliderPressed.connect(self._on_scrubber_pressed)
        self.scrubber.sliderMoved.connect(self._on_scrubber_moved)
        self.scrubber.sliderReleased.connect(self._on_scrubber_released)

        time_row = QHBoxLayout()
        self.lbl_elapsed = QLabel("00:00")
        self.lbl_elapsed.setStyleSheet("QLabel { font-size: 10px; color: #94a3b8; background: transparent; border: none; }")
        self.lbl_remaining = QLabel("-00:00")
        self.lbl_remaining.setStyleSheet("QLabel { font-size: 10px; color: #94a3b8; background: transparent; border: none; }")
        time_row.addWidget(self.lbl_elapsed)
        time_row.addStretch()
        time_row.addWidget(self.lbl_remaining)

        info_col.addWidget(self.scrubber)
        info_col.addLayout(time_row)

        # Transport Controls row (now-playing-v2.png)
        transport_row = QHBoxLayout()
        transport_row.setSpacing(14)
        transport_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.btn_shuffle = IconButton(Icons.SHUFFLE, "Shuffle: OFF", size=26, font_size=11, is_fluent=True)
        self._is_shuffle = False
        self.btn_shuffle.clicked.connect(self._toggle_shuffle)

        self.btn_prev = IconButton(Icons.PREV, "Previous Track", size=28, font_size=12, is_fluent=True)
        self.btn_play = QPushButton(Icons.PAUSE)
        self.btn_play.setFixedSize(38, 38)
        self.btn_play.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_play.setStyleSheet(f"""
            QPushButton {{
                background-color: {self._accent};
                border: none;
                border-radius: 19px;
                color: #ffffff;
                font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets';
                font-size: 13px;
            }}
            QPushButton:hover {{
                opacity: 0.9;
            }}
        """)

        self.btn_next = IconButton(Icons.NEXT, "Next Track", size=28, font_size=12, is_fluent=True)
        self.btn_repeat = IconButton(Icons.REPEAT, "Repeat: OFF", size=26, font_size=11, is_fluent=True)
        self._is_repeat = False
        self.btn_repeat.clicked.connect(self._toggle_repeat)

        transport_row.addWidget(self.btn_shuffle)
        transport_row.addWidget(self.btn_prev)
        transport_row.addWidget(self.btn_play)
        transport_row.addWidget(self.btn_next)
        transport_row.addWidget(self.btn_repeat)
        transport_row.addStretch()

        # Volume slider row
        self.btn_vol_music = QPushButton(Icons.VOLUME)
        self.btn_vol_music.setFixedSize(20, 20)
        self.btn_vol_music.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_vol_music.setToolTip("Click to Mute / Unmute")
        self.btn_vol_music.setStyleSheet("background: transparent; border: none; font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets'; font-size: 12px; color: #94a3b8;")
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(50)
        self.vol_slider.setFixedWidth(80)
        transport_row.addWidget(self.btn_vol_music)
        transport_row.addWidget(self.vol_slider)

        info_col.addLayout(transport_row)
        main_layout.addLayout(info_col, stretch=1)

        # Right: Spotify Animated Lyrics View (280px width)
        self.lyrics_widget = SpotifyLyricsWidget(self)
        self.lyrics_widget.setFixedWidth(280)
        self.lyrics_widget.seek_requested.connect(self.seek_requested.emit)
        main_layout.addWidget(self.lyrics_widget)

        # Backwards compatibility dummy labels
        self.txt_lyrics = QLabel(self)
        self.txt_lyrics.setVisible(False)
        self.lbl_album_info = QLabel(self)
        self.lbl_album_info.setVisible(False)

        v_main.addLayout(main_layout)

    def _on_scrubber_clicked(self, val: int):
        self._pos_sec = float(val)
        self._update_time_labels()
        self.seek_requested.emit(float(val))

    def _on_scrubber_pressed(self):
        self._is_user_scrubbing = True

    def _on_scrubber_moved(self, val: int):
        self._pos_sec = float(val)
        self._update_time_labels()

    def _on_scrubber_released(self):
        self._is_user_scrubbing = False
        val = self.scrubber.value()
        self._pos_sec = float(val)
        self._update_time_labels()
        self.seek_requested.emit(float(val))

    def _format_time(self, seconds: float) -> str:
        s = int(round(max(0.0, seconds)))
        mins = s // 60
        secs = s % 60
        return f"{mins:02d}:{secs:02d}"

    def _update_time_labels(self):
        self.lbl_elapsed.setText(self._format_time(self._pos_sec))
        rem = max(0.0, self._dur_sec - self._pos_sec)
        self.lbl_remaining.setText(f"-{self._format_time(rem)}")

    def update_timeline(self, pos_sec: float, dur_sec: float, is_playing: bool):
        self._is_playing = is_playing
        self._last_tick_ts = time.time()
        if not self._is_user_scrubbing:
            self._pos_sec = pos_sec
            self._dur_sec = dur_sec
            if dur_sec > 0:
                self.scrubber.setEnabled(True)
                self.scrubber.blockSignals(True)
                self.scrubber.setRange(0, int(dur_sec))
                self.scrubber.setValue(int(pos_sec))
                self.scrubber.blockSignals(False)
                self._update_time_labels()
            else:
                self.scrubber.setEnabled(False)
                self.lbl_elapsed.setText("00:00")
                self.lbl_remaining.setText("--:--")
            self.lyrics_widget.update_playback_time(self._pos_sec)

    def _on_local_playback_tick(self):
        if self._is_playing and self._dur_sec > 0 and not self._is_user_scrubbing:
            now = time.time()
            delta = now - self._last_tick_ts
            self._last_tick_ts = now
            self._pos_sec = min(self._dur_sec, self._pos_sec + delta)
            self.scrubber.blockSignals(True)
            self.scrubber.setValue(int(self._pos_sec))
            self.scrubber.blockSignals(False)
            self._update_time_labels()
            self.lyrics_widget.update_playback_time(self._pos_sec)

    def set_playback_state(self, is_playing: bool):
        self._is_playing = is_playing
        self._last_tick_ts = time.time()
        self.lyrics_widget.set_playback_state(is_playing)

    def set_lyrics(self, track_key: str, plain_lyrics: str, synced_lines: list):
        if synced_lines:
            self.lyrics_widget.set_synced_lyrics(synced_lines)
        elif plain_lyrics:
            self.lyrics_widget.set_plain_lyrics(plain_lyrics)
        else:
            self.lyrics_widget.set_not_found(self.lbl_title.text(), self.lbl_artist.text())

    def set_lyrics_loading(self, title: str, artist: str):
        self.lyrics_widget.set_loading(title, artist)

    def set_lyrics_not_found(self, track_key: str):
        self.lyrics_widget.set_not_found(self.lbl_title.text(), self.lbl_artist.text())

    def update_sessions_list(self, sessions: list, active_index: int, accent: str = "#6e9bff"):
        while self.pills_layout.count() > 0:
            item = self.pills_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._source_pills.clear()

        has_multi = len(sessions) > 1
        self.btn_prev_session.setVisible(has_multi)
        self.btn_next_session.setVisible(has_multi)

        for s in sessions:
            idx = s["index"]
            name = s["display_name"]
            is_active = (idx == active_index)
            icon = f"{Icons.MUSIC} " if "spotify" in name.lower() or "apple" in name.lower() else f"{Icons.PLAY} "
            pill = SourcePill(f"{icon}{name}", session_index=idx, is_active=is_active, accent=accent, parent=self)
            pill.clicked.connect(lambda checked=False, i=idx: self.session_select_requested.emit(i))
            self.pills_layout.addWidget(pill)
            self._source_pills.append(pill)

    def set_accent(self, accent: str):
        self._accent = accent
        self.btn_play.setStyleSheet(f"""
            QPushButton {{
                background-color: {accent};
                border: none;
                border-radius: 19px;
                color: #ffffff;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {accent};
                opacity: 0.9;
            }}
        """)

    def _toggle_shuffle(self):
        self._is_shuffle = not self._is_shuffle
        color = "#ffffff" if self._is_shuffle else "#94a3b8"
        bg = "rgba(255, 255, 255, 0.12)" if self._is_shuffle else "transparent"
        self.btn_shuffle.setStyleSheet(f"background: {bg}; border-radius: 6px; color: {color}; font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets'; font-size: 11px;")
        self.btn_shuffle.setToolTip(f"Shuffle: {'ON' if self._is_shuffle else 'OFF'}")

    def _toggle_repeat(self):
        self._is_repeat = not self._is_repeat
        color = "#ffffff" if self._is_repeat else "#94a3b8"
        bg = "rgba(255, 255, 255, 0.12)" if self._is_repeat else "transparent"
        self.btn_repeat.setStyleSheet(f"background: {bg}; border-radius: 6px; color: {color}; font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets'; font-size: 11px;")
        self.btn_repeat.setToolTip(f"Repeat: {'ON' if self._is_repeat else 'OFF'}")

    def update_media(self, data: dict):
        title = data.get("title", "No Media Playing")
        artist = data.get("artist", "Desktop Audio")
        source = data.get("display_name") or data.get("source_app", "SYSTEM")
        self.lbl_title.setText(title)
        self.lbl_artist.setText(artist)
        self.lbl_source.setText(source)

        pos_sec = data.get("position_sec", 0.0)
        dur_sec = data.get("duration_sec", 0.0)
        is_playing = data.get("is_playing", False)
        self.update_timeline(pos_sec, dur_sec, is_playing)

        thumb_bytes = data.get("thumbnail_bytes")
        if thumb_bytes:
            pix = QPixmap()
            if pix.loadFromData(thumb_bytes):
                scaled = pix.scaled(144, 144, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                self.lbl_large_art.setPixmap(scaled)
                return
        self.lbl_large_art.setText(Icons.MUSIC)
        self.lbl_large_art.setStyleSheet("font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets'; font-size: 40px; color: #64748b; border: none; background: transparent;")

    def set_volume_display(self, vol: int, is_muted: bool = False):
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


class TimerTabView(QWidget):
    """Full dedicated Pomodoro / Focus tab matching NotchX TimerView.cs."""
    def __init__(self, parent=None, accent="#6e9bff"):
        super().__init__(parent)
        self._accent = accent
        self._init_ui()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(18, 14, 18, 14)
        main_layout.setSpacing(24)

        # Left Column: Ring, Time, and Controls
        left_col = QVBoxLayout()
        left_col.setSpacing(8)
        left_col.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Phase Pills
        pills_row = QHBoxLayout()
        pills_row.setSpacing(6)
        pills_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn_phase_focus = QPushButton("Focus")
        self.btn_phase_short = QPushButton("Short Break")
        self.btn_phase_long = QPushButton("Long Break")
        for b in (self.btn_phase_focus, self.btn_phase_short, self.btn_phase_long):
            b.setStyleSheet("font-size: 10px; padding: 3px 10px; border-radius: 12px; background: rgba(255,255,255,0.05);")
            pills_row.addWidget(b)
        left_col.addLayout(pills_row)

        # Progress Ring and Time
        ring_container = QWidget()
        ring_container.setFixedSize(140, 140)
        self.ring = CircularProgressRing(size=130, track_width=6, accent=self._accent)

        self.lbl_time = QLabel("25:00")
        self.lbl_time.setStyleSheet("QLabel { font-size: 26px; font-weight: 700; color: #f8fafc; background: transparent; border: none; }")
        self.lbl_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_phase = QLabel("Focus Sprint")
        self.lbl_phase.setStyleSheet("QLabel { font-size: 11px; color: #94a3b8; background: transparent; border: none; }")
        self.lbl_phase.setAlignment(Qt.AlignmentFlag.AlignCenter)

        l_ring = QGridLayout(ring_container)
        l_ring.setContentsMargins(0, 0, 0, 0)
        l_ring.addWidget(self.ring, 0, 0, Qt.AlignmentFlag.AlignCenter)

        text_widget = QWidget()
        l_tw = QVBoxLayout(text_widget)
        l_tw.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l_tw.setSpacing(0)
        l_tw.addWidget(self.lbl_time)
        l_tw.addWidget(self.lbl_phase)
        l_ring.addWidget(text_widget, 0, 0, Qt.AlignmentFlag.AlignCenter)

        left_col.addWidget(ring_container, alignment=Qt.AlignmentFlag.AlignCenter)

        # Control Buttons
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(10)
        ctrl_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.btn_reset = IconButton(Icons.CLEAR, "Reset Timer", size=30, font_size=12, is_fluent=True)
        self.btn_toggle = QPushButton("Start")
        self.btn_toggle.setFixedSize(68, 28)
        self.btn_toggle.setStyleSheet(f"background-color: {self._accent}; border-radius: 14px; font-weight: bold; font-size: 11px; color: white;")
        self.btn_skip = IconButton(Icons.NEXT, "Skip to Next", size=30, font_size=12, is_fluent=True)

        ctrl_row.addWidget(self.btn_reset)
        ctrl_row.addWidget(self.btn_toggle)
        ctrl_row.addWidget(self.btn_skip)
        left_col.addLayout(ctrl_row)

        main_layout.addLayout(left_col, stretch=1)

        # Right Column: Focus Streaks & History Card
        right_card = CardFrame(self)
        right_l = QVBoxLayout(right_card)
        right_l.setContentsMargins(14, 12, 14, 12)
        right_l.setSpacing(10)

        lbl_hdr = QLabel("FOCUS · STATS")
        lbl_hdr.setStyleSheet("QLabel { font-size: 10px; font-weight: 700; color: #64748b; letter-spacing: 0.5px; background: transparent; border: none; }")
        right_l.addWidget(lbl_hdr)

        self.lbl_streak = QLabel("Streak: 0 sprints completed")
        self.lbl_streak.setStyleSheet("QLabel { font-size: 12px; font-weight: 600; color: #e2e8f0; background: transparent; border: none; }")
        right_l.addWidget(self.lbl_streak)

        self.lbl_daily = QLabel("Today: 0h 0m of deep focus")
        self.lbl_daily.setStyleSheet("QLabel { font-size: 11px; color: #94a3b8; background: transparent; border: none; }")
        right_l.addWidget(self.lbl_daily)

        right_l.addStretch()

        lbl_tip = QLabel("Tip: Use Ctrl+1-5 to quickly switch between tabs.")
        lbl_tip.setStyleSheet("QLabel { font-size: 10px; color: #64748b; background: transparent; border: none; }")
        lbl_tip.setWordWrap(True)
        right_l.addWidget(lbl_tip)

        main_layout.addWidget(right_card, stretch=1)

    def set_accent(self, accent: str):
        self._accent = accent
        self.ring.set_color(accent)
        self.btn_toggle.setStyleSheet(f"background-color: {accent}; border-radius: 14px; font-weight: bold; font-size: 11px; color: white;")


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
        self.setToolTip("Click Pin or double-click to pin as floating note on screen, or drag to apps (Discord/Explorer)")
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet("""
            ShelfItemRow {
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.07);
                border-radius: 8px;
            }
            ShelfItemRow:hover {
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.18);
            }
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        # Thumbnail preview
        self.thumb = DraggableThumbnail(size=40, border_radius=6, parent=self)
        if self.item.is_image:
            self.thumb.set_image(self.item.path, self.item.thumbnail)
        else:
            self.thumb.set_image(self.item.path)
        # Allow mouse events on thumbnail to bubble up to row or trigger row drag
        self.thumb.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.thumb)

        # Details
        meta = QVBoxLayout()
        meta.setSpacing(2)
        lbl_name = QLabel(self.item.name)
        lbl_name.setStyleSheet("font-size: 11px; font-weight: 600; color: #f1f5f9; background: transparent; border: none;")
        lbl_name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        size_kb = max(1, self.item.size_bytes // 1024)
        time_str = self.item.created_at.strftime("%I:%M %p")
        lbl_sub = QLabel(f"{size_kb} KB · {time_str} · Drag to apps or click Pin")
        lbl_sub.setStyleSheet("font-size: 10px; color: #94a3b8; background: transparent; border: none;")
        lbl_sub.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        meta.addWidget(lbl_name)
        meta.addWidget(lbl_sub)
        layout.addLayout(meta, stretch=1)

        # Pin to Screen Button (Floating Sticky Image)
        self.btn_pin = QPushButton("Pin")
        self.btn_pin.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pin.setToolTip("Pin screenshot directly on screen as a floating sticky note widget")
        self.btn_pin.setStyleSheet("""
            QPushButton {
                background: rgba(99, 102, 241, 0.18);
                border: 1px solid rgba(129, 140, 248, 0.35);
                border-radius: 5px;
                color: #a5b4fc;
                font-size: 10px;
                font-weight: 600;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background: rgba(99, 102, 241, 0.35);
                color: #ffffff;
            }
        """)
        self.btn_pin.clicked.connect(lambda: self.pin_requested.emit(self.item.path))
        layout.addWidget(self.btn_pin)

        # Copy for Chat Button
        self.btn_chat = QPushButton("Copy")
        self.btn_chat.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_chat.setToolTip("Copy formatted image to paste directly into Discord, Slack, WhatsApp, ChatGPT, etc.")
        self.btn_chat.setStyleSheet("""
            QPushButton {
                background: rgba(14, 165, 233, 0.18);
                border: 1px solid rgba(56, 189, 248, 0.35);
                border-radius: 5px;
                color: #38bdf8;
                font-size: 10px;
                font-weight: 600;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background: rgba(14, 165, 233, 0.32);
                color: #ffffff;
            }
        """)
        self.btn_chat.clicked.connect(self._copy_for_chat)
        layout.addWidget(self.btn_chat)

        # Delete / clear button
        btn_del = IconButton(Icons.CLOSE, "Remove from Shelf", size=22, font_size=10, is_fluent=True)
        btn_del.clicked.connect(lambda: self.removed.emit(self.item.path))
        layout.addWidget(btn_del)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.pin_requested.emit(self.item.path)
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
            Qt.DropAction.CopyAction | Qt.DropAction.MoveAction | Qt.DropAction.LinkAction,
            Qt.DropAction.CopyAction
        )
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def _copy_for_chat(self):
        if self.watcher:
            self.watcher.copy_image_for_chat(self.item.path)
        else:
            cb = QApplication.clipboard()
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(self.item.path)])
            if self.item.is_image:
                mime.setImageData(QImage(self.item.path))
            cb.setMimeData(mime)

        self.btn_chat.setText("Copied!")
        self.btn_chat.setStyleSheet("""
            QPushButton {
                background: rgba(34, 197, 94, 0.25);
                border: 1px solid rgba(34, 197, 94, 0.6);
                border-radius: 5px;
                color: #4ade80;
                font-size: 10px;
                font-weight: 700;
                padding: 4px 10px;
            }
        """)
        QTimer.singleShot(1800, self._reset_chat_btn)

    def _reset_chat_btn(self):
        self.btn_chat.setText("Copy")
        self.btn_chat.setStyleSheet("""
            QPushButton {
                background: rgba(14, 165, 233, 0.18);
                border: 1px solid rgba(56, 189, 248, 0.35);
                border-radius: 5px;
                color: #38bdf8;
                font-size: 10px;
                font-weight: 600;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background: rgba(14, 165, 233, 0.32);
                color: #ffffff;
            }
        """)


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
        self.lbl_title = QLabel("TEMPORARY FILE SHELF")
        self.lbl_title.setStyleSheet("QLabel { font-size: 10px; font-weight: 700; color: #64748b; letter-spacing: 0.5px; background: transparent; border: none; }")
        self.btn_clear = QPushButton("Clear All")
        self.btn_clear.setStyleSheet("font-size: 10px; padding: 2px 8px; border-radius: 4px; background: rgba(255,255,255,0.06);")
        self.btn_clear.clicked.connect(self.shelf_mgr.clear_shelf)
        hdr.addWidget(self.lbl_title)
        hdr.addStretch()
        hdr.addWidget(self.btn_clear)
        layout.addLayout(hdr)

        # Scroll area for items
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
        """)
        self.items_container = QWidget()
        self.items_layout = QVBoxLayout(self.items_container)
        self.items_layout.setContentsMargins(0, 0, 0, 0)
        self.items_layout.setSpacing(6)
        self.scroll_area.setWidget(self.items_container)
        layout.addWidget(self.scroll_area, stretch=1)

        # Empty State Placeholder
        self.empty_card = QFrame()
        self.empty_card.setStyleSheet("""
            QFrame {
                background: rgba(255, 255, 255, 0.02);
                border: 1px dashed rgba(255, 255, 255, 0.12);
                border-radius: 10px;
                padding: 16px;
            }
        """)
        l_emp = QVBoxLayout(self.empty_card)
        l_emp.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_emp_icon = QLabel(Icons.IMAGE)
        lbl_emp_icon.setStyleSheet("font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets'; font-size: 26px; color: #64748b; background: transparent; border: none;")
        lbl_emp_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_emp_text = QLabel("Drop files or snip screenshot (Win+Shift+S / PrtScn) to stage.\nClick Pin on any item to float on screen, or drag to external apps.")
        lbl_emp_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_emp_text.setStyleSheet("font-size: 11px; color: #94a3b8; background: transparent; border: none; line-height: 1.4;")
        l_emp.addWidget(lbl_emp_icon)
        l_emp.addWidget(lbl_emp_text)
        layout.addWidget(self.empty_card, stretch=1)

        self.shelf_mgr.shelf_updated.connect(self.refresh_items)
        self.refresh_items()

    def refresh_items(self):
        # Clear existing items
        while self.items_layout.count() > 0:
            item = self.items_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        items = self.shelf_mgr.staged_items
        count = len(items)
        self.lbl_title.setText(f"TEMPORARY FILE SHELF · {count} FILE{'S' if count != 1 else ''}")

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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scratch_file = Path(os.path.expanduser("~/.poppy/scratchpad.txt"))
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(8)

        # Header
        hdr = QHBoxLayout()
        lbl_title = QLabel("SCRATCHPAD & NOTES")
        lbl_title.setStyleSheet("QLabel { font-size: 10.5px; font-weight: 700; color: #94a3b8; letter-spacing: 0.5px; background: transparent; border: none; }")
        self.btn_tear = QPushButton("Tear Off Floating Note")
        self.btn_tear.setStyleSheet("font-size: 10px; padding: 3px 10px; border-radius: 4px; background: rgba(255,255,255,0.06);")
        self.btn_tear.clicked.connect(self._tear_off)
        hdr.addWidget(lbl_title)
        hdr.addStretch()
        hdr.addWidget(self.btn_tear)
        layout.addLayout(hdr)

        # Multiline Note Editor
        self.editor = QTextEdit()
        self.editor.setPlaceholderText("Write notes, snippets, or tasks here...")
        if self._scratch_file.exists():
            try:
                self.editor.setText(self._scratch_file.read_text(encoding="utf-8"))
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
        self.lbl_word_count.setStyleSheet("QLabel { font-size: 10px; color: #94a3b8; background: transparent; border: none; }")
        btn_clear = QPushButton("Clear")
        btn_clear.setStyleSheet("font-size: 9px; padding: 2px 6px; border: none;")
        btn_clear.clicked.connect(self._clear_notes)
        ftr.addWidget(self.lbl_word_count)
        ftr.addStretch()
        ftr.addWidget(btn_clear)
        layout.addLayout(ftr)
        self._on_text_changed()

    def _save_scratch(self):
        try:
            self._scratch_file.parent.mkdir(parents=True, exist_ok=True)
            self._scratch_file.write_text(self.editor.toPlainText(), encoding="utf-8")
        except Exception:
            pass

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
        text = self.editor.toPlainText().strip()
        self.tear_off_requested.emit(text)
        self.editor.clear()
        self._save_scratch()
