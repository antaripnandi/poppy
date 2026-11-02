"""
Poppy Dedicated Settings Application ("Make it yours")
Faithfully recreating NotchX's Appearance & Configuration studio:
- 7 Theme preset cards (Graphite, Midnight, Aurora, Ember, Lime, Rose, Pure black)
- Size & Shape controls with live updates (Notch vs Pill style, width, height, corner radius, top offset, display)
- Tabs Manager (Show/hide individual tabs, Smart default tab)
- Behavior & Gestures (Hover bloom, scroll on pill for volume, Windows autostart)
- Notifications & Islands (Pop-up alerts, Do Not Disturb, sound chimes, text privacy)
- Media & Spotify Lyrics (Direct Spotify sp_dc color-lyrics, NetEase Romanized lyrics)
- Weather & Location (Custom city geocoding, Celsius/Fahrenheit units)
- Pomodoro timer settings
- Discord Rich Presence customizer
- Hardware HUD telemetry options
- Quick actions (Open config.json, Open app folder)
"""

import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor, QPainter, QBrush, QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QSpinBox, QCheckBox, QPushButton, QStackedWidget, QListWidget,
    QFrame, QComboBox, QSlider, QScrollArea
)

from poppy.ui.styles import THEME_PRESETS, DEFAULT_THEME
from poppy.core.system_features import get_autostart_state, set_autostart_state


ALL_AVAILABLE_TABS = [
    ("Home", "Home dashboard, clocks, volume/brightness, notes, shelf & calc"),
    ("Music", "Now playing media player, timeline scrubbing & synced lyrics"),
    ("Calendar", "Interactive monthly calendar, reminders & agenda view"),
    ("Clipboard", "Clipboard history manager with search, copy & pinned clips"),
    ("Docs", "Document reader, quick preview & PDF converter utilities"),
    ("Desktops", "Windows Virtual Desktops switcher & active workspace overview"),
    ("Timer", "Pomodoro sprint focus tracker with short/long break cycles"),
    ("Shelf", "Staging drop shelf for files, dragged assets & snips"),
    ("Notes", "In-notch scratchpad with detachable desktop floating notes")
]


class ThemeCard(QFrame):
    """Visual theme preset selector card matching NotchX's Appearance page."""
    clicked = Signal(str)

    def __init__(self, theme_key: str, theme_data: dict, is_selected: bool = False, parent=None):
        super().__init__(parent)
        self.theme_key = theme_key
        self.theme_data = theme_data
        self.is_selected = is_selected
        self.setFixedSize(115, 65)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_appearance()

    def set_selected(self, selected: bool):
        self.is_selected = selected
        self.update_appearance()

    def update_appearance(self):
        bg = self.theme_data["bg"]
        accent = self.theme_data["accent"]
        border_col = accent if self.is_selected else "rgba(255, 255, 255, 0.12)"
        border_w = 2 if self.is_selected else 1

        self.setStyleSheet(f"""
            ThemeCard {{
                background-color: {bg};
                border: {border_w}px solid {border_col};
                border-radius: 8px;
            }}
            ThemeCard:hover {{
                border: {border_w}px solid {accent};
            }}
        """)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.theme_key)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw Accent dot inside
        accent = QColor(self.theme_data["accent"])
        painter.setBrush(QBrush(accent))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(self.width() - 20, self.height() - 20, 10, 10)

        # Theme Name text
        painter.setPen(QColor("#f1f5f9" if self.is_selected else "#94a3b8"))
        font = QFont("Segoe UI", 8, QFont.Weight.DemiBold if self.is_selected else QFont.Weight.Medium)
        painter.setFont(font)
        painter.drawText(10, 22, self.theme_data["name"])


class SettingsWindow(QWidget):
    settings_saved = Signal(dict)
    appearance_live_updated = Signal(dict)

    def __init__(self, config: dict = None, parent=None):
        super().__init__(parent)
        self.config = config or {}
        self.setWindowTitle("Poppy Settings — Make it yours")
        self.resize(740, 530)
        self.setMinimumSize(660, 470)

        self._theme_cards = {}
        self._tab_checkboxes = {}
        self._init_ui()
        self._load_values()

    def _init_ui(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #08090d;
                color: #e2e8f0;
                font-family: 'Segoe UI Variable Display', 'Segoe UI', system-ui, sans-serif;
            }
            QListWidget {
                background-color: #050608;
                border: none;
                border-right: 1px solid rgba(255, 255, 255, 0.06);
                padding: 10px 6px;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 9px 14px;
                border-radius: 6px;
                color: #94a3b8;
                font-weight: 500;
            }
            QListWidget::item:selected {
                background-color: rgba(10, 132, 255, 0.16);
                color: #0a84ff;
                font-weight: 600;
            }
            QListWidget::item:hover:!selected {
                background-color: rgba(255, 255, 255, 0.04);
                color: #f1f5f9;
            }
            QSpinBox, QComboBox, QLineEdit {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.09);
                border-radius: 6px;
                padding: 5px 8px;
                color: #f8fafc;
            }
            QSlider::groove:horizontal {
                height: 4px;
                background: rgba(255, 255, 255, 0.12);
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #0a84ff;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #f8fafc;
                width: 12px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 6px;
            }
            QCheckBox {
                spacing: 8px;
                color: #cbd5e1;
                font-size: 11px;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                background-color: rgba(255, 255, 255, 0.06);
            }
            QCheckBox::indicator:checked {
                background-color: #0a84ff;
                border: 1px solid #0a84ff;
            }
        """)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Left Nav Sidebar
        self.nav_list = QListWidget()
        self.nav_list.setFixedWidth(172)
        self.nav_list.addItem("Appearance")
        self.nav_list.addItem("Tabs Manager")
        self.nav_list.addItem("Behavior & Gestures")
        self.nav_list.addItem("Notifications")
        self.nav_list.addItem("Media & Lyrics")
        self.nav_list.addItem("Weather & Location")
        self.nav_list.addItem("Pomodoro")
        self.nav_list.addItem("Discord RPC")
        self.nav_list.addItem("Hardware HUD")
        self.nav_list.addItem("About & System")
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)
        main_layout.addWidget(self.nav_list)

        # Right Content Area
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(22, 16, 22, 16)
        right_layout.setSpacing(12)

        self.stack = QStackedWidget()

        # =====================================================================
        # 0. Appearance Page
        # =====================================================================
        scroll_app = QScrollArea()
        scroll_app.setWidgetResizable(True)
        scroll_app.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        page_app = QWidget()
        l_app = QVBoxLayout(page_app)
        l_app.setContentsMargins(0, 0, 8, 0)
        l_app.setSpacing(12)

        lbl_app_hdr = QLabel("Appearance & Themes")
        lbl_app_hdr.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        lbl_app_sub = QLabel("One click sets the background, gradient, and accent together.")
        lbl_app_sub.setStyleSheet("font-size: 11px; color: #94a3b8;")
        l_app.addWidget(lbl_app_hdr)
        l_app.addWidget(lbl_app_sub)

        # Theme preset grid
        theme_grid = QGridLayout()
        theme_grid.setSpacing(10)
        row, col = 0, 0
        for key, data in THEME_PRESETS.items():
            card = ThemeCard(key, data, is_selected=(key == DEFAULT_THEME), parent=self)
            card.clicked.connect(self._on_theme_card_clicked)
            self._theme_cards[key] = card
            theme_grid.addWidget(card, row, col)
            col += 1
            if col >= 4:
                col = 0
                row += 1
        l_app.addLayout(theme_grid)

        # Size & Shape Section
        l_app.addSpacing(6)
        lbl_shape_hdr = QLabel("Size, Position & Shape")
        lbl_shape_hdr.setStyleSheet("font-size: 13px; font-weight: 700; color: #f8fafc;")
        lbl_shape_sub = QLabel("Adjust dimensions and screen anchoring with live preview.")
        lbl_shape_sub.setStyleSheet("font-size: 11px; color: #94a3b8;")
        l_app.addWidget(lbl_shape_hdr)
        l_app.addWidget(lbl_shape_sub)

        # Style & Display row
        row_pos = QHBoxLayout()
        lbl_style = QLabel("Style:")
        lbl_style.setStyleSheet("font-size: 11px; color: #cbd5e1;")
        self.combo_style = QComboBox()
        self.combo_style.addItems(["Notch", "Pill"])
        self.combo_style.setToolTip("Notch hugs top screen edge (y=0); Pill floats with top padding.")
        self.combo_style.currentTextChanged.connect(self._on_live_appearance_change)

        lbl_disp = QLabel("Target Display:")
        lbl_disp.setStyleSheet("font-size: 11px; color: #cbd5e1; margin-left: 12px;")
        self.combo_display = QComboBox()
        self.combo_display.addItem("Primary")
        for i, s in enumerate(QGuiApplication.screens()):
            self.combo_display.addItem(f"Display {i + 1} ({s.geometry().width()}x{s.geometry().height()})")

        row_pos.addWidget(lbl_style)
        row_pos.addWidget(self.combo_style)
        row_pos.addWidget(lbl_disp)
        row_pos.addWidget(self.combo_display)
        row_pos.addStretch()
        l_app.addLayout(row_pos)

        # Sliders: Collapsed W, Collapsed H, Open W, Open H, Radius, Top Offset
        self.slider_col_w, self.lbl_val_col_w = self._create_slider_row(l_app, "Collapsed width (px)", 180, 360, 240)
        self.slider_col_h, self.lbl_val_col_h = self._create_slider_row(l_app, "Collapsed height (px)", 24, 44, 30)
        self.slider_open_w, self.lbl_val_open_w = self._create_slider_row(l_app, "Open width (px)", 700, 1100, 940)
        self.slider_open_h, self.lbl_val_open_h = self._create_slider_row(l_app, "Open height (px)", 360, 560, 460)
        self.slider_radius, self.lbl_val_radius = self._create_slider_row(l_app, "Corner radius (px)", 8, 24, 16)
        self.slider_top_offset, self.lbl_val_top_offset = self._create_slider_row(l_app, "Top offset / Taskbar gap (px)", 0, 40, 0)

        scroll_app.setWidget(page_app)
        self.stack.addWidget(scroll_app)

        # =====================================================================
        # 1. Tabs Manager Page
        # =====================================================================
        page_tabs = QWidget()
        l_tabs = QVBoxLayout(page_tabs)
        l_tabs.setSpacing(10)

        lbl_tabs_hdr = QLabel("Tabs & Module Manager")
        lbl_tabs_hdr.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        lbl_tabs_sub = QLabel("Select which tabs appear in the top bar. Disable unused tabs to keep your notch clean.")
        lbl_tabs_sub.setStyleSheet("font-size: 11px; color: #94a3b8;")
        l_tabs.addWidget(lbl_tabs_hdr)
        l_tabs.addWidget(lbl_tabs_sub)

        # Default tab dropdown
        row_dtab = QHBoxLayout()
        lbl_dtab = QLabel("Default Active Tab on Expand:")
        lbl_dtab.setStyleSheet("font-size: 11px; color: #cbd5e1; font-weight: 600;")
        self.combo_default_tab = QComboBox()
        self.combo_default_tab.addItem("Smart (Music if playing, Timer if active, else Home)")
        for tab_name, _ in ALL_AVAILABLE_TABS:
            self.combo_default_tab.addItem(tab_name)
        row_dtab.addWidget(lbl_dtab)
        row_dtab.addWidget(self.combo_default_tab)
        row_dtab.addStretch()
        l_tabs.addLayout(row_dtab)

        l_tabs.addSpacing(6)
        lbl_list_hdr = QLabel("Enabled Navigation Tabs:")
        lbl_list_hdr.setStyleSheet("font-size: 12px; font-weight: 600; color: #cbd5e1;")
        l_tabs.addWidget(lbl_list_hdr)

        tabs_grid = QGridLayout()
        tabs_grid.setSpacing(8)
        r_idx, c_idx = 0, 0
        for tab_name, tab_desc in ALL_AVAILABLE_TABS:
            box = QFrame()
            box.setStyleSheet("""
                QFrame {
                    background-color: rgba(255, 255, 255, 0.03);
                    border: 1px solid rgba(255, 255, 255, 0.06);
                    border-radius: 6px;
                    padding: 4px;
                }
                QFrame:hover {
                    border: 1px solid rgba(10, 132, 255, 0.3);
                }
            """)
            b_layout = QVBoxLayout(box)
            b_layout.setContentsMargins(6, 6, 6, 6)
            b_layout.setSpacing(2)

            chk = QCheckBox(f"{tab_name}")
            chk.setStyleSheet("font-weight: 600; font-size: 11px; color: #f1f5f9;")
            lbl_desc = QLabel(tab_desc)
            lbl_desc.setStyleSheet("font-size: 9px; color: #94a3b8; border: none;")
            lbl_desc.setWordWrap(True)

            b_layout.addWidget(chk)
            b_layout.addWidget(lbl_desc)

            self._tab_checkboxes[tab_name] = chk
            tabs_grid.addWidget(box, r_idx, c_idx)
            c_idx += 1
            if c_idx >= 2:
                c_idx = 0
                r_idx += 1

        l_tabs.addLayout(tabs_grid)
        l_tabs.addStretch()
        self.stack.addWidget(page_tabs)

        # =====================================================================
        # 2. Behavior & Gestures Page
        # =====================================================================
        page_beh = QWidget()
        l_beh = QVBoxLayout(page_beh)
        l_beh.setSpacing(12)

        lbl_beh_hdr = QLabel("Behavior & Gestures")
        lbl_beh_hdr.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        l_beh.addWidget(lbl_beh_hdr)

        self.chk_hover_peek = QCheckBox("Bloom to Media HUD automatically on mouse hover")
        l_beh.addWidget(self.chk_hover_peek)

        self.chk_scroll_volume = QCheckBox("Scroll on closed pill to adjust Windows master volume")
        self.chk_scroll_volume.setToolTip("Hover over the collapsed notch and roll mouse wheel up/down.")
        l_beh.addWidget(self.chk_scroll_volume)

        self.chk_autostart = QCheckBox("Start Poppy automatically when Windows boots (Run key)")
        l_beh.addWidget(self.chk_autostart)

        self.chk_tray_close = QCheckBox("Keep Poppy active in System Tray when drawer is closed")
        l_beh.addWidget(self.chk_tray_close)

        row_dur = QHBoxLayout()
        lbl_dur = QLabel("Animation Spring Duration (ms):")
        lbl_dur.setStyleSheet("font-size: 11px; color: #cbd5e1;")
        self.spin_anim_ms = QSpinBox()
        self.spin_anim_ms.setRange(80, 500)
        self.spin_anim_ms.setSingleStep(20)
        row_dur.addWidget(lbl_dur)
        row_dur.addWidget(self.spin_anim_ms)
        row_dur.addStretch()
        l_beh.addLayout(row_dur)

        l_beh.addStretch()
        self.stack.addWidget(page_beh)

        # =====================================================================
        # 3. Notifications Page (NEW)
        # =====================================================================
        page_notif = QWidget()
        l_notif = QVBoxLayout(page_notif)
        l_notif.setSpacing(12)

        lbl_notif_hdr = QLabel("Notifications & Island Alerts")
        lbl_notif_hdr.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        lbl_notif_sub = QLabel("Control banner pop-ups, toast alerts, sounds, and Focus / Do Not Disturb rules.")
        lbl_notif_sub.setStyleSheet("font-size: 11px; color: #94a3b8;")
        l_notif.addWidget(lbl_notif_hdr)
        l_notif.addWidget(lbl_notif_sub)

        self.chk_notif_enabled = QCheckBox("Enable Poppy Notification Alerts")
        l_notif.addWidget(self.chk_notif_enabled)

        self.chk_notif_show_island = QCheckBox("Show dynamic pop-up island when notifications or downloads arrive")
        l_notif.addWidget(self.chk_notif_show_island)

        self.chk_notif_mute_focus = QCheckBox("Mute notifications during Pomodoro Focus sprints (Do Not Disturb)")
        l_notif.addWidget(self.chk_notif_mute_focus)

        self.chk_notif_sound = QCheckBox("Play notification chime sound on arrival")
        l_notif.addWidget(self.chk_notif_sound)

        self.chk_notif_preview = QCheckBox("Show notification message preview text (Uncheck to hide sensitive text)")
        l_notif.addWidget(self.chk_notif_preview)

        l_notif.addStretch()
        self.stack.addWidget(page_notif)

        # =====================================================================
        # 4. Media & Lyrics Page (NEW)
        # =====================================================================
        page_media = QWidget()
        l_media = QVBoxLayout(page_media)
        l_media.setSpacing(12)

        lbl_media_hdr = QLabel("Media & Spotify Lyrics")
        lbl_media_hdr.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        lbl_media_sub = QLabel("High-accuracy Romanized synchronized lyrics matching Spotify desktop.")
        lbl_media_sub.setStyleSheet("font-size: 11px; color: #94a3b8;")
        l_media.addWidget(lbl_media_hdr)
        l_media.addWidget(lbl_media_sub)

        row_spdc = QVBoxLayout()
        row_spdc.setSpacing(4)
        lbl_spdc_title = QLabel("Spotify Direct Cookie (Optional for Official Lyrics):")
        lbl_spdc_title.setStyleSheet("font-size: 11px; font-weight: 600; color: #f1f5f9;")
        self.txt_sp_dc = QLineEdit()
        self.txt_sp_dc.setPlaceholderText("Paste sp_dc cookie from open.spotify.com")
        self.txt_sp_dc.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        row_spdc.addWidget(lbl_spdc_title)
        row_spdc.addWidget(self.txt_sp_dc)
        l_media.addLayout(row_spdc)

        lbl_cookie_hint = QLabel(
            "💡 How it works:\n"
            "• Poppy automatically fetches official Romanized synced lyrics via NetEase & LRCLIB without any login.\n"
            "• If you want 100% genuine direct Spotify Color Lyrics for rare or regional songs, log into open.spotify.com, "
            "open DevTools (F12) → Application → Cookies → copy 'sp_dc' value and paste above."
        )
        lbl_cookie_hint.setStyleSheet("""
            background-color: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 6px;
            padding: 8px 10px;
            font-size: 10px;
            color: #94a3b8;
            line-height: 1.4;
        """)
        lbl_cookie_hint.setWordWrap(True)
        l_media.addWidget(lbl_cookie_hint)

        self.chk_lyrics_auto_scroll = QCheckBox("Automatically scroll synced lyrics to follow song timeline")
        self.chk_lyrics_auto_scroll.setChecked(True)
        l_media.addWidget(self.chk_lyrics_auto_scroll)

        l_media.addStretch()
        self.stack.addWidget(page_media)

        # =====================================================================
        # 5. Weather & Location Page
        # =====================================================================
        page_weath = QWidget()
        l_weath = QVBoxLayout(page_weath)
        l_weath.setSpacing(12)

        lbl_weath_hdr = QLabel("Weather & Forecast")
        lbl_weath_hdr.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        lbl_weath_sub = QLabel("Powered by Open-Meteo free public forecast. Auto-detects via IP or specify any city.")
        lbl_weath_sub.setStyleSheet("font-size: 11px; color: #94a3b8;")
        l_weath.addWidget(lbl_weath_hdr)
        l_weath.addWidget(lbl_weath_sub)

        row_city = QHBoxLayout()
        lbl_city = QLabel("City / Location:")
        lbl_city.setStyleSheet("font-size: 11px; color: #cbd5e1;")
        self.txt_weather_city = QLineEdit()
        self.txt_weather_city.setPlaceholderText("Auto-detect or type city (e.g. New York, London, Tokyo, Delhi)")
        row_city.addWidget(lbl_city)
        row_city.addWidget(self.txt_weather_city, stretch=1)
        l_weath.addLayout(row_city)

        row_unit = QHBoxLayout()
        lbl_unit = QLabel("Temperature Unit:")
        lbl_unit.setStyleSheet("font-size: 11px; color: #cbd5e1;")
        self.combo_weather_unit = QComboBox()
        self.combo_weather_unit.addItems(["Celsius (°C)", "Fahrenheit (°F)"])
        row_unit.addWidget(lbl_unit)
        row_unit.addWidget(self.combo_weather_unit)
        row_unit.addStretch()
        l_weath.addLayout(row_unit)

        l_weath.addStretch()
        self.stack.addWidget(page_weath)

        # =====================================================================
        # 6. Pomodoro Page
        # =====================================================================
        page_pomo = QWidget()
        l_pomo = QVBoxLayout(page_pomo)
        l_pomo.setSpacing(12)

        lbl_pomo_hdr = QLabel("Pomodoro Timer")
        lbl_pomo_hdr.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        l_pomo.addWidget(lbl_pomo_hdr)

        self.spin_pomo_work = self._create_spin_row(l_pomo, "Focus Sprint (minutes):", 1, 120, 25)
        self.spin_pomo_break = self._create_spin_row(l_pomo, "Short Break (minutes):", 1, 60, 5)
        self.spin_pomo_long = self._create_spin_row(l_pomo, "Long Break (minutes):", 1, 90, 15)

        self.chk_pomo_sound = QCheckBox("Play notification chime on cycle completion")
        l_pomo.addWidget(self.chk_pomo_sound)

        l_pomo.addStretch()
        self.stack.addWidget(page_pomo)

        # =====================================================================
        # 7. Discord RPC Page
        # =====================================================================
        page_rpc = QWidget()
        l_rpc = QVBoxLayout(page_rpc)
        l_rpc.setSpacing(10)

        lbl_rpc_hdr = QLabel("Discord Rich Presence")
        lbl_rpc_hdr.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        l_rpc.addWidget(lbl_rpc_hdr)

        self.chk_rpc_enable = QCheckBox("Enable Discord Rich Presence status broadcasting")
        l_rpc.addWidget(self.chk_rpc_enable)

        row_client = QHBoxLayout()
        lbl_cid = QLabel("Application Client ID:")
        lbl_cid.setStyleSheet("font-size: 11px; color: #cbd5e1;")
        self.txt_rpc_client = QLineEdit()
        self.txt_rpc_client.setPlaceholderText("Enter your Discord Developer Client ID")
        row_client.addWidget(lbl_cid)
        row_client.addWidget(self.txt_rpc_client)
        l_rpc.addLayout(row_client)

        row_mode = QHBoxLayout()
        lbl_mode = QLabel("Presence Mode:")
        lbl_mode.setStyleSheet("font-size: 11px; color: #cbd5e1;")
        self.combo_rpc_mode = QComboBox()
        self.combo_rpc_mode.addItems(["Dynamic (Follows Pomodoro & Media)", "Static Custom Presence"])
        row_mode.addWidget(lbl_mode)
        row_mode.addWidget(self.combo_rpc_mode)
        row_mode.addStretch()
        l_rpc.addLayout(row_mode)

        l_rpc.addStretch()
        self.stack.addWidget(page_rpc)

        # =====================================================================
        # 8. Hardware HUD Page
        # =====================================================================
        page_hw = QWidget()
        l_hw = QVBoxLayout(page_hw)
        l_hw.setSpacing(12)

        lbl_hw_hdr = QLabel("Hardware Telemetry HUD")
        lbl_hw_hdr.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        l_hw.addWidget(lbl_hw_hdr)

        self.chk_monitor_gpu = QCheckBox("Query NVIDIA GPU Utilization (via NVML)")
        l_hw.addWidget(self.chk_monitor_gpu)

        self.chk_monitor_bat = QCheckBox("Monitor Battery Level & AC Power State")
        l_hw.addWidget(self.chk_monitor_bat)

        l_hw.addStretch()
        self.stack.addWidget(page_hw)

        # =====================================================================
        # 9. About & System Page
        # =====================================================================
        page_abt = QWidget()
        l_abt = QVBoxLayout(page_abt)
        l_abt.setSpacing(12)

        lbl_abt_hdr = QLabel("Poppy Dynamic Notch")
        lbl_abt_hdr.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        lbl_abt_ver = QLabel("Version 2.0 (Windows 11 / 10)")
        lbl_abt_ver.setStyleSheet("font-size: 11px; color: #94a3b8;")
        lbl_abt_desc = QLabel("Hardware-accelerated top-bezel notch inspired by NotchX and Apple Dynamic Island.\nBuilt in Python with PySide6.")
        lbl_abt_desc.setStyleSheet("font-size: 11px; color: #64748b; line-height: 1.5;")
        l_abt.addWidget(lbl_abt_hdr)
        l_abt.addWidget(lbl_abt_ver)
        l_abt.addWidget(lbl_abt_desc)

        l_abt.addSpacing(8)
        lbl_sys_hdr = QLabel("Configuration & Diagnostics")
        lbl_sys_hdr.setStyleSheet("font-size: 13px; font-weight: 700; color: #f8fafc;")
        l_abt.addWidget(lbl_sys_hdr)

        row_sys_btns = QHBoxLayout()
        btn_open_cfg = QPushButton("Edit config.json")
        btn_open_cfg.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 6px;
                padding: 6px 14px;
                color: #e2e8f0;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.14);
            }
        """)
        btn_open_cfg.clicked.connect(self._open_config_file)

        btn_open_folder = QPushButton("Open Poppy Folder")
        btn_open_folder.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 6px;
                padding: 6px 14px;
                color: #e2e8f0;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.14);
            }
        """)
        btn_open_folder.clicked.connect(self._open_poppy_folder)

        row_sys_btns.addWidget(btn_open_cfg)
        row_sys_btns.addWidget(btn_open_folder)
        row_sys_btns.addStretch()
        l_abt.addLayout(row_sys_btns)

        l_abt.addStretch()
        self.stack.addWidget(page_abt)

        right_layout.addWidget(self.stack, stretch=1)

        # Bottom Bar: Save & Close button
        bottom_bar = QHBoxLayout()
        bottom_bar.addStretch()
        self.btn_save = QPushButton("Save & Apply")
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #0a84ff;
                border: none;
                border-radius: 6px;
                padding: 7px 22px;
                font-weight: 600;
                font-size: 12px;
                color: #ffffff;
            }
            QPushButton:hover {
                background-color: #38bdf8;
            }
        """)
        self.btn_save.clicked.connect(self._save_settings)
        bottom_bar.addWidget(self.btn_save)
        right_layout.addLayout(bottom_bar)

        main_layout.addWidget(right_container, stretch=1)
        self.nav_list.setCurrentRow(0)

    def _open_config_file(self):
        cfg_path = Path(__file__).resolve().parent.parent / "config.json"
        try:
            os.startfile(str(cfg_path))
        except Exception:
            pass

    def _open_poppy_folder(self):
        folder_path = Path(__file__).resolve().parent.parent
        try:
            os.startfile(str(folder_path))
        except Exception:
            pass

    def _create_slider_row(self, layout, label_text: str, min_v: int, max_v: int, default_v: int):
        row = QHBoxLayout()
        lbl = QLabel(label_text)
        lbl.setStyleSheet("font-size: 11px; color: #cbd5e1;")
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(min_v, max_v)
        slider.setValue(default_v)
        val_lbl = QLabel(str(default_v))
        val_lbl.setFixedWidth(36)
        val_lbl.setStyleSheet("font-size: 11px; color: #0a84ff; font-weight: 600;")
        slider.valueChanged.connect(lambda v: val_lbl.setText(str(v)))
        slider.valueChanged.connect(self._on_live_appearance_change)

        row.addWidget(lbl, stretch=1)
        row.addWidget(slider, stretch=2)
        row.addWidget(val_lbl)
        layout.addLayout(row)
        return slider, val_lbl

    def _create_spin_row(self, layout, label_text: str, min_v: int, max_v: int, default_v: int):
        row = QHBoxLayout()
        lbl = QLabel(label_text)
        lbl.setStyleSheet("font-size: 11px; color: #cbd5e1;")
        spin = QSpinBox()
        spin.setRange(min_v, max_v)
        spin.setValue(default_v)
        row.addWidget(lbl)
        row.addWidget(spin)
        row.addStretch()
        layout.addLayout(row)
        return spin

    def _on_nav_changed(self, row: int):
        self.stack.setCurrentIndex(row)

    def _on_theme_card_clicked(self, theme_key: str):
        for k, card in self._theme_cards.items():
            card.set_selected(k == theme_key)
        self._on_live_appearance_change()

    def _get_current_selected_theme(self) -> str:
        for k, card in self._theme_cards.items():
            if card.is_selected:
                return k
        return DEFAULT_THEME

    def _on_live_appearance_change(self):
        appearance_dict = {
            "theme": self._get_current_selected_theme(),
            "style": self.combo_style.currentText(),
            "collapsed_width": self.slider_col_w.value(),
            "collapsed_height": self.slider_col_h.value(),
            "open_width": self.slider_open_w.value(),
            "open_height": self.slider_open_h.value(),
            "corner_radius": self.slider_radius.value(),
            "top_offset": self.slider_top_offset.value(),
            "display": self.combo_display.currentText()
        }
        self.appearance_live_updated.emit(appearance_dict)

    def _load_values(self):
        # 0. Appearance
        app_cfg = self.config.get("appearance", {})
        active_theme = app_cfg.get("theme", DEFAULT_THEME)
        for k, card in self._theme_cards.items():
            card.set_selected(k == active_theme)

        style = app_cfg.get("style", "Notch")
        idx = self.combo_style.findText(style)
        if idx >= 0:
            self.combo_style.setCurrentIndex(idx)

        display = app_cfg.get("display", "Primary")
        d_idx = self.combo_display.findText(display)
        if d_idx >= 0:
            self.combo_display.setCurrentIndex(d_idx)

        self.slider_col_w.setValue(app_cfg.get("collapsed_width", 240))
        self.slider_col_h.setValue(app_cfg.get("collapsed_height", 30))
        self.slider_open_w.setValue(app_cfg.get("open_width", 940))
        self.slider_open_h.setValue(app_cfg.get("open_height", 460))
        self.slider_radius.setValue(app_cfg.get("corner_radius", 16))
        self.slider_top_offset.setValue(app_cfg.get("top_offset", 0))

        # 1. Tabs
        tabs_cfg = self.config.get("tabs", {})
        enabled_tabs = tabs_cfg.get("enabled", [name for name, _ in ALL_AVAILABLE_TABS])
        for name, chk in self._tab_checkboxes.items():
            chk.setChecked(name in enabled_tabs)

        dtab = self.config.get("notch", {}).get("default_tab", "Smart")
        for i in range(self.combo_default_tab.count()):
            if dtab.lower() in self.combo_default_tab.itemText(i).lower():
                self.combo_default_tab.setCurrentIndex(i)
                break

        # 2. Behavior
        notch_cfg = self.config.get("notch", {})
        self.chk_hover_peek.setChecked(notch_cfg.get("auto_hover_peek", True))
        self.chk_scroll_volume.setChecked(notch_cfg.get("scroll_volume", True))
        self.spin_anim_ms.setValue(notch_cfg.get("animation_duration_ms", 200))
        self.chk_tray_close.setChecked(notch_cfg.get("keep_in_tray", True))
        self.chk_autostart.setChecked(get_autostart_state())

        # 3. Notifications
        notif_cfg = self.config.get("notifications", {})
        self.chk_notif_enabled.setChecked(notif_cfg.get("enabled", True))
        self.chk_notif_show_island.setChecked(notif_cfg.get("show_island_on_notify", True))
        self.chk_notif_mute_focus.setChecked(notif_cfg.get("mute_in_focus", True))
        self.chk_notif_sound.setChecked(notif_cfg.get("sound", True))
        self.chk_notif_preview.setChecked(notif_cfg.get("preview_text", True))

        # 4. Media & Lyrics
        media_cfg = self.config.get("media", {})
        self.txt_sp_dc.setText(media_cfg.get("spotify_sp_dc", ""))
        self.chk_lyrics_auto_scroll.setChecked(media_cfg.get("auto_scroll_lyrics", True))

        # 5. Weather
        w_cfg = self.config.get("weather", {})
        self.txt_weather_city.setText(w_cfg.get("city", "Auto-detect"))
        u_idx = 1 if w_cfg.get("unit", "celsius").lower() == "fahrenheit" else 0
        self.combo_weather_unit.setCurrentIndex(u_idx)

        # 6. Pomodoro
        pomo_cfg = self.config.get("pomodoro", {})
        self.spin_pomo_work.setValue(pomo_cfg.get("work_duration", 1500) // 60)
        self.spin_pomo_break.setValue(pomo_cfg.get("break_duration", 300) // 60)
        self.spin_pomo_long.setValue(pomo_cfg.get("long_break_duration", 900) // 60)
        self.chk_pomo_sound.setChecked(pomo_cfg.get("sound_enabled", True))

        # 7. Discord RPC
        rpc_cfg = self.config.get("discord_rpc", {})
        self.chk_rpc_enable.setChecked(rpc_cfg.get("enabled", False))
        self.txt_rpc_client.setText(rpc_cfg.get("client_id", "120000000000000000"))
        mode_idx = 0 if rpc_cfg.get("mode") == "dynamic" else 1
        self.combo_rpc_mode.setCurrentIndex(mode_idx)

        # 8. Hardware HUD
        hw_cfg = self.config.get("hardware_hud", {})
        self.chk_monitor_gpu.setChecked(hw_cfg.get("monitor_gpu", True))
        self.chk_monitor_bat.setChecked(hw_cfg.get("monitor_battery", True))

    def _save_settings(self):
        # Update Windows autostart registry state
        set_autostart_state(self.chk_autostart.isChecked())

        # Collect enabled tabs (ensure at least Home is enabled)
        enabled_tabs = [name for name, chk in self._tab_checkboxes.items() if chk.isChecked()]
        if not enabled_tabs:
            enabled_tabs = ["Home"]

        sel_dtab_txt = self.combo_default_tab.currentText()
        if "smart" in sel_dtab_txt.lower():
            saved_dtab = "Smart"
        else:
            saved_dtab = sel_dtab_txt

        unit_str = "fahrenheit" if self.combo_weather_unit.currentIndex() == 1 else "celsius"
        city_str = self.txt_weather_city.text().strip() or "Auto-detect"

        new_config = {
            "appearance": {
                "theme": self._get_current_selected_theme(),
                "style": self.combo_style.currentText(),
                "collapsed_width": self.slider_col_w.value(),
                "collapsed_height": self.slider_col_h.value(),
                "open_width": self.slider_open_w.value(),
                "open_height": self.slider_open_h.value(),
                "corner_radius": self.slider_radius.value(),
                "top_offset": self.slider_top_offset.value(),
                "display": self.combo_display.currentText()
            },
            "tabs": {
                "enabled": enabled_tabs
            },
            "notifications": {
                "enabled": self.chk_notif_enabled.isChecked(),
                "show_island_on_notify": self.chk_notif_show_island.isChecked(),
                "mute_in_focus": self.chk_notif_mute_focus.isChecked(),
                "sound": self.chk_notif_sound.isChecked(),
                "preview_text": self.chk_notif_preview.isChecked(),
            },
            "media": {
                "spotify_sp_dc": self.txt_sp_dc.text().strip(),
                "auto_scroll_lyrics": self.chk_lyrics_auto_scroll.isChecked()
            },
            "weather": {
                "city": city_str,
                "unit": unit_str
            },
            "pomodoro": {
                "work_duration": self.spin_pomo_work.value() * 60,
                "break_duration": self.spin_pomo_break.value() * 60,
                "long_break_duration": self.spin_pomo_long.value() * 60,
                "sound_enabled": self.chk_pomo_sound.isChecked(),
            },
            "notch": {
                "auto_hover_peek": self.chk_hover_peek.isChecked(),
                "scroll_volume": self.chk_scroll_volume.isChecked(),
                "default_tab": saved_dtab,
                "animation_duration_ms": self.spin_anim_ms.value(),
                "keep_in_tray": self.chk_tray_close.isChecked(),
                "autostart": self.chk_autostart.isChecked()
            },
            "discord_rpc": {
                "enabled": self.chk_rpc_enable.isChecked(),
                "client_id": self.txt_rpc_client.text().strip(),
                "mode": "dynamic" if self.combo_rpc_mode.currentIndex() == 0 else "custom",
                "custom_presence": self.config.get("discord_rpc", {}).get("custom_presence", {}),
                "dynamic_templates": self.config.get("discord_rpc", {}).get("dynamic_templates", {}),
            },
            "hardware_hud": {
                "monitor_gpu": self.chk_monitor_gpu.isChecked(),
                "monitor_battery": self.chk_monitor_bat.isChecked(),
            }
        }

        # Save to config.json
        cfg_path = Path(__file__).resolve().parent.parent / "config.json"
        try:
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(new_config, f, indent=2)
        except Exception as e:
            print(f"[Poppy Settings] Error saving config: {e}")

        self.config = new_config
        self.settings_saved.emit(new_config)
        self.close()
