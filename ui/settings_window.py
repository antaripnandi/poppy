"""
Poppy Dedicated Settings Application ("Make it yours")
Faithfully recreating NotchX's Appearance & Configuration studio:
- 7 Theme preset cards (Graphite, Midnight, Aurora, Ember, Lime, Rose, Pure black)
- Size & Shape controls with live updates (Notch vs Pill style, width, height, corner radius, top offset, display)
- Tabs Manager (Show/hide individual tabs, Smart default tab)
- Behavior & Gestures (Hover bloom, scroll on pill for volume, Windows autostart)
- Notifications & Islands (Pop-up alerts, Do Not Disturb, sound chimes, text privacy)
- Screen Time & Digital Wellbeing (Active tracking, AFK detection, daily targets, healthy rest breaks)
- Media & Spotify Lyrics (Direct Spotify sp_dc color-lyrics, NetEase Romanized lyrics)
- Weather & Location (Custom city geocoding, Celsius/Fahrenheit units)
- Pomodoro timer settings
- Discord Rich Presence customizer
- Hardware HUD telemetry options
- Quick actions (Open config.json, Open app folder)
Zero external dependencies (pure stdlib + PySide6).
"""

import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor, QPainter, QBrush, QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QSpinBox, QPushButton, QStackedWidget, QListWidget,
    QFrame, QComboBox, QSlider, QScrollArea, QProgressBar
)

from poppy.ui.styles import THEME_PRESETS, DEFAULT_THEME
from poppy.core.system_features import get_autostart_state, set_autostart_state
from poppy.ui.components import ToggleSwitch, SettingRow


def _create_setting_card(rows: list[QWidget]) -> QFrame:
    """Frosted obsidian glass container grouping setting rows with subtle dividers."""
    card = QFrame()
    card.setStyleSheet("""
        QFrame {
            background-color: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.065);
            border-radius: 12px;
        }
    """)
    l = QVBoxLayout(card)
    l.setContentsMargins(16, 6, 16, 6)
    l.setSpacing(0)
    for i, row in enumerate(rows):
        if i > 0:
            div = QFrame()
            div.setFixedHeight(1)
            div.setStyleSheet("background-color: rgba(255, 255, 255, 0.035); border: none;")
            l.addWidget(div)
        l.addWidget(row)
    return card


def _make_scroll_area(page_widget: QWidget) -> QScrollArea:
    """Zero-artifact transparent scroll container with auto-hidden horizontal bar."""
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.Shape.NoFrame)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    sa.setWidget(page_widget)
    return sa


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
    screentime_reset_requested = Signal()

    def __init__(self, config: dict = None, parent=None):
        super().__init__(parent)
        self.config = config or {}
        self.setWindowTitle("Poppy Settings — Make it yours")
        self.resize(840, 580)
        self.setMinimumSize(780, 520)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)

        self._theme_cards = {}
        self._tab_checkboxes = {}
        self._init_ui()
        self._load_values()

    def _init_ui(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #07080c;
                color: #e2e8f0;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI Variable Text', 'Segoe UI', system-ui, sans-serif;
            }
            QListWidget {
                background-color: #040508;
                border: none;
                border-right: 1px solid rgba(255, 255, 255, 0.05);
                padding: 14px 6px;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 8px 12px;
                border-radius: 8px;
                color: #94a3b8;
                font-weight: 500;
                margin: 2px 2px;
            }
            QListWidget::item:selected {
                background-color: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.12);
                color: #ffffff;
                font-weight: 600;
            }
            QListWidget::item:hover:!selected {
                background-color: rgba(255, 255, 255, 0.035);
                color: #f1f5f9;
            }
            QSpinBox, QComboBox, QLineEdit {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
                padding: 5px 9px;
                color: #f8fafc;
                font-size: 11px;
            }
            QSpinBox:focus, QComboBox:focus, QLineEdit:focus {
                border: 1px solid rgba(10, 132, 255, 0.5);
                background-color: rgba(255, 255, 255, 0.08);
            }
            QComboBox::drop-down {
                border: none;
                width: 18px;
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
            QScrollBar:vertical {
                width: 5px;
                background: transparent;
                margin: 2px 0px;
            }
            QScrollBar::horizontal {
                height: 0px;
                border: none;
                background: transparent;
            }
            QScrollBar::corner {
                background: transparent;
                border: none;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.14);
                min-height: 28px;
                border-radius: 2.5px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.28);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
        """)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Left Nav Sidebar
        self.nav_list = QListWidget()
        self.nav_list.setFixedWidth(186)
        self.nav_list.addItem("🎨  Appearance")
        self.nav_list.addItem("🗂️  Tabs Manager")
        self.nav_list.addItem("⚡  Behavior & Gestures")
        self.nav_list.addItem("🔔  Notifications")
        self.nav_list.addItem("⏳  Screen Time")
        self.nav_list.addItem("🎵  Media & Lyrics")
        self.nav_list.addItem("⛅  Weather & Location")
        self.nav_list.addItem("⏱️  Pomodoro")
        self.nav_list.addItem("🎮  Discord RPC")
        self.nav_list.addItem("📊  Hardware HUD")
        self.nav_list.addItem("⚙️  About & System")
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)
        main_layout.addWidget(self.nav_list)

        # Right Content Area
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(22, 18, 22, 16)
        right_layout.setSpacing(12)

        self.stack = QStackedWidget()

        # =====================================================================
        # 0. Appearance Page
        # =====================================================================
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

        self.combo_style = QComboBox()
        self.combo_style.addItems(["Notch", "Pill"])
        self.combo_style.setToolTip("Notch hugs top screen edge (y=0); Pill floats with top padding.")
        self.combo_style.currentTextChanged.connect(self._on_live_appearance_change)

        self.combo_display = QComboBox()
        self.combo_display.addItem("Primary")
        for i, s in enumerate(QGuiApplication.screens()):
            self.combo_display.addItem(f"Display {i + 1} ({s.geometry().width()}x{s.geometry().height()})")

        row_style = SettingRow("Window Display Style", "Notch hugs top screen edge; Pill floats with top gap", self.combo_style)
        row_disp = SettingRow("Target Monitor", "Active screen display monitor for Poppy", self.combo_display)

        self.slider_col_w, self.lbl_val_col_w, row_col_w = self._make_slider_setting("Collapsed Width", "Width when notch is closed (px)", 180, 360, 240)
        self.slider_col_h, self.lbl_val_col_h, row_col_h = self._make_slider_setting("Collapsed Height", "Height of the compact pill (px)", 24, 44, 30)
        self.slider_open_w, self.lbl_val_open_w, row_open_w = self._make_slider_setting("Open Width", "Width when drawer is expanded (px)", 700, 1100, 940)
        self.slider_open_h, self.lbl_val_open_h, row_open_h = self._make_slider_setting("Open Height", "Height when drawer is expanded (px)", 360, 560, 460)
        self.slider_radius, self.lbl_val_radius, row_radius = self._make_slider_setting("Corner Radius", "Curvature for rounded bezel corners (px)", 8, 24, 16)
        self.slider_top_offset, self.lbl_val_top_offset, row_top = self._make_slider_setting("Top Offset Gap", "Vertical padding gap from top bezel (px)", 0, 40, 0)

        card_shape = _create_setting_card([
            row_style, row_disp, row_col_w, row_col_h, row_open_w, row_open_h, row_radius, row_top
        ])
        l_app.addWidget(card_shape)
        l_app.addStretch()

        self.stack.addWidget(_make_scroll_area(page_app))

        # =====================================================================
        # 1. Tabs Manager Page
        # =====================================================================
        page_tabs = QWidget()
        l_tabs = QVBoxLayout(page_tabs)
        l_tabs.setContentsMargins(0, 0, 8, 0)
        l_tabs.setSpacing(12)

        lbl_tabs_hdr = QLabel("Tabs & Module Manager")
        lbl_tabs_hdr.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        lbl_tabs_sub = QLabel("Select which tabs appear in the top bar. Disable unused tabs to keep your notch clean.")
        lbl_tabs_sub.setStyleSheet("font-size: 11px; color: #94a3b8;")
        l_tabs.addWidget(lbl_tabs_hdr)
        l_tabs.addWidget(lbl_tabs_sub)

        # Default tab dropdown
        self.combo_default_tab = QComboBox()
        self.combo_default_tab.addItem("Smart (Music if playing, Timer if active, else Home)")
        for tab_name, _ in ALL_AVAILABLE_TABS:
            self.combo_default_tab.addItem(tab_name)

        card_dtab = _create_setting_card([
            SettingRow("Default Active Tab", "Tab opened automatically when expanding the drawer", self.combo_default_tab)
        ])
        l_tabs.addWidget(card_dtab)

        l_tabs.addSpacing(4)
        lbl_list_hdr = QLabel("Enabled Navigation Tabs")
        lbl_list_hdr.setStyleSheet("font-size: 13px; font-weight: 700; color: #f8fafc;")
        l_tabs.addWidget(lbl_list_hdr)

        tab_rows = []
        for tab_name, tab_desc in ALL_AVAILABLE_TABS:
            toggle = ToggleSwitch(checked=True)
            self._tab_checkboxes[tab_name] = toggle
            row = SettingRow(tab_name, tab_desc, toggle)
            tab_rows.append(row)

        card_tabs = _create_setting_card(tab_rows)
        l_tabs.addWidget(card_tabs)
        l_tabs.addStretch()

        self.stack.addWidget(_make_scroll_area(page_tabs))

        # =====================================================================
        # 2. Behavior & Gestures Page
        # =====================================================================
        page_beh = QWidget()
        l_beh = QVBoxLayout(page_beh)
        l_beh.setContentsMargins(0, 0, 8, 0)
        l_beh.setSpacing(12)

        lbl_beh_hdr = QLabel("Behavior & Gestures")
        lbl_beh_hdr.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        lbl_beh_sub = QLabel("Notch interaction models, gestures, and system startup behavior.")
        lbl_beh_sub.setStyleSheet("font-size: 11px; color: #94a3b8;")
        l_beh.addWidget(lbl_beh_hdr)
        l_beh.addWidget(lbl_beh_sub)

        self.chk_hover_peek = ToggleSwitch(checked=True)
        self.chk_scroll_volume = ToggleSwitch(checked=True)
        self.chk_autostart = ToggleSwitch(checked=False)
        self.chk_tray_close = ToggleSwitch(checked=True)

        self.spin_anim_ms = QSpinBox()
        self.spin_anim_ms.setRange(80, 500)
        self.spin_anim_ms.setSingleStep(20)

        card_beh = _create_setting_card([
            SettingRow("Media HUD Hover Peek", "Bloom to compact Media HUD automatically on mouse hover", self.chk_hover_peek),
            SettingRow("Volume Wheel Gesture", "Scroll mouse wheel on closed pill to adjust Windows master volume", self.chk_scroll_volume),
            SettingRow("Windows Startup Boot", "Start Poppy automatically when Windows logs in (Run registry key)", self.chk_autostart),
            SettingRow("System Tray Resident", "Keep Poppy active in System Tray when drawer is closed", self.chk_tray_close),
            SettingRow("Spring Animation Duration", "Duration for expansion and collapse springs in milliseconds", self.spin_anim_ms)
        ])
        l_beh.addWidget(card_beh)
        l_beh.addStretch()

        self.stack.addWidget(_make_scroll_area(page_beh))

        # =====================================================================
        # 3. Notifications Page
        # =====================================================================
        page_notif = QWidget()
        l_notif = QVBoxLayout(page_notif)
        l_notif.setContentsMargins(0, 0, 8, 0)
        l_notif.setSpacing(12)

        lbl_notif_hdr = QLabel("Notifications & Island Alerts")
        lbl_notif_hdr.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        lbl_notif_sub = QLabel("Control banner pop-ups, toast alerts, chime sounds, and Focus rules.")
        lbl_notif_sub.setStyleSheet("font-size: 11px; color: #94a3b8;")
        l_notif.addWidget(lbl_notif_hdr)
        l_notif.addWidget(lbl_notif_sub)

        self.chk_notif_enabled = ToggleSwitch(checked=True)
        self.chk_notif_show_island = ToggleSwitch(checked=True)
        self.chk_notif_mute_focus = ToggleSwitch(checked=True)
        self.chk_notif_sound = ToggleSwitch(checked=True)
        self.chk_notif_preview = ToggleSwitch(checked=True)

        card_notif = _create_setting_card([
            SettingRow("Poppy Notification Alerts", "Enable popup alerts for notifications and downloads", self.chk_notif_enabled),
            SettingRow("Dynamic Island Pop-up", "Expand notch into a floating island when notifications arrive", self.chk_notif_show_island),
            SettingRow("Do Not Disturb in Focus", "Silence incoming notification popups during Pomodoro sprints", self.chk_notif_mute_focus),
            SettingRow("Chime Sound", "Play an acoustic chime sound on notification arrival", self.chk_notif_sound),
            SettingRow("Preview Message Content", "Display message text in alert (disable to protect privacy)", self.chk_notif_preview)
        ])
        l_notif.addWidget(card_notif)
        l_notif.addStretch()

        self.stack.addWidget(_make_scroll_area(page_notif))

        # =====================================================================
        # 4. Screen Time Page (Digital Wellbeing)
        # =====================================================================
        page_st = QWidget()
        l_st = QVBoxLayout(page_st)
        l_st.setContentsMargins(0, 0, 8, 0)
        l_st.setSpacing(12)

        lbl_st_hdr = QLabel("Screen Time & Digital Wellbeing")
        lbl_st_hdr.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        lbl_st_sub = QLabel("Monitor daily active usage, track top applications, enforce daily targets, and schedule rest breaks.")
        lbl_st_sub.setStyleSheet("font-size: 11px; color: #94a3b8;")
        l_st.addWidget(lbl_st_hdr)
        l_st.addWidget(lbl_st_sub)

        # Clean obsidian stat card
        card_st_summary = QFrame()
        card_st_summary.setStyleSheet("""
            QFrame {
                background-color: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 12px;
            }
        """)
        l_card_summary = QVBoxLayout(card_st_summary)
        l_card_summary.setContentsMargins(16, 14, 16, 14)
        l_card_summary.setSpacing(10)

        row_top_stat = QHBoxLayout()
        stat_left = QVBoxLayout()
        stat_left.setSpacing(2)
        lbl_st_tag = QLabel("TODAY'S SCREEN TIME")
        lbl_st_tag.setStyleSheet("font-size: 9.5px; font-weight: 700; color: #64748b; letter-spacing: 0.5px; background: transparent; border: none;")
        self.lbl_st_today_time = QLabel("0m")
        self.lbl_st_today_time.setStyleSheet("font-size: 26px; font-weight: 700; color: #f8fafc; background: transparent; border: none;")
        stat_left.addWidget(lbl_st_tag)
        stat_left.addWidget(self.lbl_st_today_time)
        row_top_stat.addLayout(stat_left)
        row_top_stat.addStretch()

        badges_layout = QHBoxLayout()
        badges_layout.setSpacing(8)
        self.lbl_st_streak = QLabel("Active Streak: 0m")
        self.lbl_st_streak.setStyleSheet("""
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            padding: 4px 10px;
            font-size: 11px;
            color: #cbd5e1;
            font-weight: 500;
        """)
        self.lbl_st_goal_pct = QLabel("Goal: 0%")
        self.lbl_st_goal_pct.setStyleSheet("""
            background: rgba(10, 132, 255, 0.12);
            border: 1px solid rgba(10, 132, 255, 0.28);
            border-radius: 12px;
            padding: 4px 10px;
            font-size: 11px;
            color: #38bdf8;
            font-weight: 600;
        """)
        badges_layout.addWidget(self.lbl_st_streak)
        badges_layout.addWidget(self.lbl_st_goal_pct)
        row_top_stat.addLayout(badges_layout)
        l_card_summary.addLayout(row_top_stat)

        # Micro progress bar
        self.bar_st_goal = QProgressBar()
        self.bar_st_goal.setFixedHeight(5)
        self.bar_st_goal.setTextVisible(False)
        self.bar_st_goal.setStyleSheet("""
            QProgressBar {
                background-color: rgba(255, 255, 255, 0.08);
                border: none;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background-color: #0a84ff;
                border-radius: 2px;
            }
        """)
        self.bar_st_goal.setRange(0, 100)
        self.bar_st_goal.setValue(0)
        l_card_summary.addWidget(self.bar_st_goal)

        # Top Apps Breakdown row
        self.lbl_st_top_apps = QLabel("Top apps will appear as you work...")
        self.lbl_st_top_apps.setStyleSheet("font-size: 11px; color: #94a3b8; background: transparent; border: none;")
        l_card_summary.addWidget(self.lbl_st_top_apps)
        l_st.addWidget(card_st_summary)

        # Card 1: Tracking & Display
        self.chk_st_enabled = ToggleSwitch(checked=True)
        self.chk_st_show_main_menu = ToggleSwitch(checked=True)
        self.chk_st_track_apps = ToggleSwitch(checked=True)

        self.combo_st_afk = QComboBox()
        self.combo_st_afk.addItem("1 minute", 60)
        self.combo_st_afk.addItem("2 minutes (Recommended)", 120)
        self.combo_st_afk.addItem("5 minutes", 300)
        self.combo_st_afk.addItem("10 minutes", 600)

        card_st_track = _create_setting_card([
            SettingRow("Active Usage Tracking", "Monitor active keyboard/mouse foreground session time", self.chk_st_enabled),
            SettingRow("Show in Notch Home Tab", "Display live Screen Time pill directly on notch home dashboard", self.chk_st_show_main_menu),
            SettingRow("Application Breakdown Tracking", "Record per-application duration (Code, Brave, Spotify, etc.)", self.chk_st_track_apps),
            SettingRow("Away / AFK Inactivity Timeout", "Pause tracking when mouse and keyboard are idle", self.combo_st_afk)
        ])
        l_st.addWidget(card_st_track)

        # Card 2: Daily Target & Wellbeing
        self.slider_st_goal = QSlider(Qt.Orientation.Horizontal)
        self.slider_st_goal.setRange(1, 16)
        self.slider_st_goal.setValue(6)
        self.slider_st_goal.setFixedWidth(130)
        self.lbl_goal_val = QLabel("6 hrs")
        self.lbl_goal_val.setStyleSheet("font-size: 11px; font-weight: 600; color: #0a84ff; min-width: 42px;")
        self.slider_st_goal.valueChanged.connect(lambda v: self.lbl_goal_val.setText(f"{v} hrs"))

        goal_widget = QWidget()
        gw_l = QHBoxLayout(goal_widget)
        gw_l.setContentsMargins(0, 0, 0, 0)
        gw_l.setSpacing(8)
        gw_l.addWidget(self.slider_st_goal)
        gw_l.addWidget(self.lbl_goal_val)

        self.chk_st_goal_alert = ToggleSwitch(checked=True)
        self.chk_st_break_reminder = ToggleSwitch(checked=True)

        self.combo_st_break_interval = QComboBox()
        self.combo_st_break_interval.addItem("Every 30 minutes", 30)
        self.combo_st_break_interval.addItem("Every 45 minutes", 45)
        self.combo_st_break_interval.addItem("Every 60 minutes (Recommended)", 60)
        self.combo_st_break_interval.addItem("Every 90 minutes", 90)
        self.combo_st_break_interval.addItem("Every 120 minutes", 120)

        card_st_goals = _create_setting_card([
            SettingRow("Daily Target Goal", "Maximum desired screen time per day", goal_widget),
            SettingRow("Target Limit Reached Alert", "Pop up dynamic island alert when reaching daily limit", self.chk_st_goal_alert),
            SettingRow("Healthy Rest Break Alerts", "Prompt rest breaks during continuous uninterrupted screen time", self.chk_st_break_reminder),
            SettingRow("Break Reminder Frequency", "Interval between posture and eye rest reminders", self.combo_st_break_interval)
        ])
        l_st.addWidget(card_st_goals)

        # Card 3: Privacy & Reset
        self.txt_st_excluded = QLineEdit()
        self.txt_st_excluded.setPlaceholderText("e.g. keepass, 1password, bitwarden")
        self.txt_st_excluded.setFixedWidth(200)

        self.btn_st_reset = QPushButton("Reset Today")
        self.btn_st_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_st_reset.setStyleSheet("""
            QPushButton {
                background-color: rgba(239, 68, 68, 0.12);
                border: 1px solid rgba(239, 68, 68, 0.3);
                border-radius: 6px;
                color: #fca5a5;
                font-size: 11px;
                font-weight: 600;
                padding: 5px 14px;
            }
            QPushButton:hover {
                background-color: rgba(239, 68, 68, 0.25);
                color: #ffffff;
            }
        """)
        self.btn_st_reset.clicked.connect(self._on_screentime_reset_clicked)

        card_st_privacy = _create_setting_card([
            SettingRow("Excluded Applications", "Sensitive apps to omit from logs (comma-separated)", self.txt_st_excluded),
            SettingRow("Reset Today's Screen Time", "Clear active session counter and app stats for today", self.btn_st_reset)
        ])
        l_st.addWidget(card_st_privacy)
        l_st.addStretch()

        self.stack.addWidget(_make_scroll_area(page_st))

        # =====================================================================
        # 5. Media & Lyrics Page
        # =====================================================================
        page_media = QWidget()
        l_media = QVBoxLayout(page_media)
        l_media.setContentsMargins(0, 0, 8, 0)
        l_media.setSpacing(12)

        lbl_media_hdr = QLabel("Media & Spotify Lyrics")
        lbl_media_hdr.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        lbl_media_sub = QLabel("High-accuracy Romanized synchronized lyrics matching Spotify desktop.")
        lbl_media_sub.setStyleSheet("font-size: 11px; color: #94a3b8;")
        l_media.addWidget(lbl_media_hdr)
        l_media.addWidget(lbl_media_sub)

        self.txt_sp_dc = QLineEdit()
        self.txt_sp_dc.setPlaceholderText("Paste sp_dc cookie from open.spotify.com")
        self.txt_sp_dc.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        self.txt_sp_dc.setFixedWidth(240)

        self.chk_lyrics_auto_scroll = ToggleSwitch(checked=True)

        card_media = _create_setting_card([
            SettingRow("Spotify sp_dc Cookie", "Optional cookie for genuine Spotify Color Lyrics", self.txt_sp_dc),
            SettingRow("Auto-Scroll Synced Lyrics", "Follow song timeline and center current line in real time", self.chk_lyrics_auto_scroll)
        ])
        l_media.addWidget(card_media)

        lbl_cookie_hint = QLabel(
            "💡 How it works:\n"
            "• Poppy automatically fetches Romanized synchronized lyrics via NetEase & LRCLIB without any login.\n"
            "• If you want 100% genuine direct Spotify Color Lyrics for rare or regional songs, log into open.spotify.com, "
            "open DevTools (F12) → Application → Cookies → copy 'sp_dc' value and paste above."
        )
        lbl_cookie_hint.setStyleSheet("""
            background-color: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-radius: 8px;
            padding: 10px 12px;
            font-size: 10.5px;
            color: #94a3b8;
            line-height: 1.4;
        """)
        lbl_cookie_hint.setWordWrap(True)
        l_media.addWidget(lbl_cookie_hint)
        l_media.addStretch()

        self.stack.addWidget(_make_scroll_area(page_media))

        # =====================================================================
        # 6. Weather & Location Page
        # =====================================================================
        page_weath = QWidget()
        l_weath = QVBoxLayout(page_weath)
        l_weath.setContentsMargins(0, 0, 8, 0)
        l_weath.setSpacing(12)

        lbl_weath_hdr = QLabel("Weather & Forecast")
        lbl_weath_hdr.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        lbl_weath_sub = QLabel("Powered by Open-Meteo public forecast. Auto-detects via IP or specify any city.")
        lbl_weath_sub.setStyleSheet("font-size: 11px; color: #94a3b8;")
        l_weath.addWidget(lbl_weath_hdr)
        l_weath.addWidget(lbl_weath_sub)

        self.txt_weather_city = QLineEdit()
        self.txt_weather_city.setPlaceholderText("Auto-detect or type city (e.g. London, Tokyo, Delhi)")
        self.txt_weather_city.setFixedWidth(220)

        self.combo_weather_unit = QComboBox()
        self.combo_weather_unit.addItems(["Celsius (°C)", "Fahrenheit (°F)"])
        self.combo_weather_unit.setFixedWidth(140)

        card_weath = _create_setting_card([
            SettingRow("City / Location", "Auto-detect by IP or specify custom city", self.txt_weather_city),
            SettingRow("Temperature Unit", "Display temperatures in Celsius or Fahrenheit", self.combo_weather_unit)
        ])
        l_weath.addWidget(card_weath)
        l_weath.addStretch()

        self.stack.addWidget(_make_scroll_area(page_weath))

        # =====================================================================
        # 7. Pomodoro Page
        # =====================================================================
        page_pomo = QWidget()
        l_pomo = QVBoxLayout(page_pomo)
        l_pomo.setContentsMargins(0, 0, 8, 0)
        l_pomo.setSpacing(12)

        lbl_pomo_hdr = QLabel("Pomodoro Timer")
        lbl_pomo_hdr.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        lbl_pomo_sub = QLabel("Configure focus sprints, rest intervals, and acoustic completion chimes.")
        lbl_pomo_sub.setStyleSheet("font-size: 11px; color: #94a3b8;")
        l_pomo.addWidget(lbl_pomo_hdr)
        l_pomo.addWidget(lbl_pomo_sub)

        self.spin_pomo_work = QSpinBox()
        self.spin_pomo_work.setRange(1, 120)
        self.spin_pomo_work.setValue(25)

        self.spin_pomo_break = QSpinBox()
        self.spin_pomo_break.setRange(1, 60)
        self.spin_pomo_break.setValue(5)

        self.spin_pomo_long = QSpinBox()
        self.spin_pomo_long.setRange(1, 90)
        self.spin_pomo_long.setValue(15)

        self.chk_pomo_sound = ToggleSwitch(checked=True)

        card_pomo = _create_setting_card([
            SettingRow("Focus Sprint Duration", "Minutes dedicated to focused work", self.spin_pomo_work),
            SettingRow("Short Break Duration", "Minutes for quick recharge breaks", self.spin_pomo_break),
            SettingRow("Long Break Duration", "Minutes for extended recovery after 4 sprints", self.spin_pomo_long),
            SettingRow("Completion Chime", "Play acoustic chime when sprint or break finishes", self.chk_pomo_sound)
        ])
        l_pomo.addWidget(card_pomo)
        l_pomo.addStretch()

        self.stack.addWidget(_make_scroll_area(page_pomo))

        # =====================================================================
        # 8. Discord RPC Page
        # =====================================================================
        page_rpc = QWidget()
        l_rpc = QVBoxLayout(page_rpc)
        l_rpc.setContentsMargins(0, 0, 8, 0)
        l_rpc.setSpacing(12)

        lbl_rpc_hdr = QLabel("Discord Rich Presence")
        lbl_rpc_hdr.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        lbl_rpc_sub = QLabel("Broadcast active Spotify media and Pomodoro status to Discord.")
        lbl_rpc_sub.setStyleSheet("font-size: 11px; color: #94a3b8;")
        l_rpc.addWidget(lbl_rpc_hdr)
        l_rpc.addWidget(lbl_rpc_sub)

        self.chk_rpc_enable = ToggleSwitch(checked=False)

        self.txt_rpc_client = QLineEdit()
        self.txt_rpc_client.setPlaceholderText("Enter Discord Client ID")
        self.txt_rpc_client.setFixedWidth(200)

        self.combo_rpc_mode = QComboBox()
        self.combo_rpc_mode.addItems(["Dynamic (Follows Pomodoro & Media)", "Static Custom Presence"])

        card_rpc = _create_setting_card([
            SettingRow("Broadcasting State", "Broadcast active Poppy activity to Discord profile", self.chk_rpc_enable),
            SettingRow("Application Client ID", "Discord Developer Portal application ID", self.txt_rpc_client),
            SettingRow("Presence Mode", "Dynamic sync (Media & Pomodoro) or static status", self.combo_rpc_mode)
        ])
        l_rpc.addWidget(card_rpc)
        l_rpc.addStretch()

        self.stack.addWidget(_make_scroll_area(page_rpc))

        # =====================================================================
        # 9. Hardware HUD Page
        # =====================================================================
        page_hw = QWidget()
        l_hw = QVBoxLayout(page_hw)
        l_hw.setContentsMargins(0, 0, 8, 0)
        l_hw.setSpacing(12)

        lbl_hw_hdr = QLabel("Hardware Telemetry HUD")
        lbl_hw_hdr.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        lbl_hw_sub = QLabel("Select background hardware telemetry polling options.")
        lbl_hw_sub.setStyleSheet("font-size: 11px; color: #94a3b8;")
        l_hw.addWidget(lbl_hw_hdr)
        l_hw.addWidget(lbl_hw_sub)

        self.chk_monitor_gpu = ToggleSwitch(checked=True)
        self.chk_monitor_bat = ToggleSwitch(checked=True)

        card_hw = _create_setting_card([
            SettingRow("NVIDIA GPU Telemetry", "Query GPU core utilization and temperature via NVML", self.chk_monitor_gpu),
            SettingRow("Battery & AC Power State", "Monitor laptop battery percentage and charging state", self.chk_monitor_bat)
        ])
        l_hw.addWidget(card_hw)
        l_hw.addStretch()

        self.stack.addWidget(_make_scroll_area(page_hw))

        # =====================================================================
        # 10. About & System Page
        # =====================================================================
        page_abt = QWidget()
        l_abt = QVBoxLayout(page_abt)
        l_abt.setContentsMargins(0, 0, 8, 0)
        l_abt.setSpacing(12)

        lbl_abt_hdr = QLabel("Poppy Dynamic Notch")
        lbl_abt_hdr.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        lbl_abt_ver = QLabel("Version 2.0 (Windows 11 / 10)")
        lbl_abt_ver.setStyleSheet("font-size: 11px; color: #94a3b8;")
        lbl_abt_desc = QLabel("Hardware-accelerated top-bezel notch inspired by NotchX and Apple Dynamic Island.\nBuilt in Python with PySide6 and native Windows Win32 ctypes.")
        lbl_abt_desc.setStyleSheet("font-size: 11px; color: #64748b; line-height: 1.5;")
        l_abt.addWidget(lbl_abt_hdr)
        l_abt.addWidget(lbl_abt_ver)
        l_abt.addWidget(lbl_abt_desc)

        btn_open_cfg = QPushButton("Edit config.json")
        btn_open_cfg.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_open_cfg.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 5px 12px;
                color: #e2e8f0;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.12);
                color: #ffffff;
            }
        """)
        btn_open_cfg.clicked.connect(self._open_config_file)

        btn_open_folder = QPushButton("Open Poppy Folder")
        btn_open_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_open_folder.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 5px 12px;
                color: #e2e8f0;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.12);
                color: #ffffff;
            }
        """)
        btn_open_folder.clicked.connect(self._open_poppy_folder)

        card_abt = _create_setting_card([
            SettingRow("Configuration File", "Open config.json directly in your default editor", btn_open_cfg),
            SettingRow("App Directory", "Browse Poppy installation and assets directory", btn_open_folder)
        ])
        l_abt.addWidget(card_abt)
        l_abt.addStretch()

        self.stack.addWidget(_make_scroll_area(page_abt))

        right_layout.addWidget(self.stack, stretch=1)

        # Bottom Action Footer
        bottom_bar = QHBoxLayout()
        bottom_bar.setContentsMargins(4, 4, 4, 0)

        lbl_auto_save = QLabel("●  Settings are saved automatically")
        lbl_auto_save.setStyleSheet("font-size: 10.5px; color: #64748b; background: transparent; border: none;")
        bottom_bar.addWidget(lbl_auto_save)
        bottom_bar.addStretch()

        self.btn_done = QPushButton("Done")
        self.btn_done.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_done.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 8px;
                padding: 7px 24px;
                font-size: 12px;
                font-weight: 600;
                color: #f8fafc;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.16);
                border: 1px solid rgba(255, 255, 255, 0.22);
                color: #ffffff;
            }
        """)
        self.btn_done.clicked.connect(self._save_and_close)
        self.btn_save = self.btn_done
        self.btn_close = self.btn_done
        bottom_bar.addWidget(self.btn_done)

        right_layout.addLayout(bottom_bar)

        main_layout.addWidget(right_container, stretch=1)
        self.nav_list.setCurrentRow(0)

    def _save_and_close(self):
        self._save_settings()
        self.close()

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

    def _make_slider_setting(self, title: str, subtitle: str, min_v: int, max_v: int, default_v: int):
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(min_v, max_v)
        slider.setValue(default_v)
        slider.setFixedWidth(130)

        val_lbl = QLabel(str(default_v))
        val_lbl.setFixedWidth(32)
        val_lbl.setStyleSheet("font-size: 11px; color: #0a84ff; font-weight: 600; background: transparent; border: none;")

        slider.valueChanged.connect(lambda v: val_lbl.setText(str(v)))
        slider.valueChanged.connect(self._on_live_appearance_change)

        ctrl_wrap = QWidget()
        ctrl_l = QHBoxLayout(ctrl_wrap)
        ctrl_l.setContentsMargins(0, 0, 0, 0)
        ctrl_l.setSpacing(8)
        ctrl_l.addWidget(slider)
        ctrl_l.addWidget(val_lbl)

        row = SettingRow(title, subtitle, ctrl_wrap)
        return slider, val_lbl, row

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
            chk.setChecked(name in enabled_tabs, animate=False)

        dtab = self.config.get("notch", {}).get("default_tab", "Smart")
        for i in range(self.combo_default_tab.count()):
            if dtab.lower() in self.combo_default_tab.itemText(i).lower():
                self.combo_default_tab.setCurrentIndex(i)
                break

        # 2. Behavior
        notch_cfg = self.config.get("notch", {})
        self.chk_hover_peek.setChecked(notch_cfg.get("auto_hover_peek", True), animate=False)
        self.chk_scroll_volume.setChecked(notch_cfg.get("scroll_volume", True), animate=False)
        self.spin_anim_ms.setValue(notch_cfg.get("animation_duration_ms", 200))
        self.chk_tray_close.setChecked(notch_cfg.get("keep_in_tray", True), animate=False)
        self.chk_autostart.setChecked(get_autostart_state(), animate=False)

        # 3. Notifications
        notif_cfg = self.config.get("notifications", {})
        self.chk_notif_enabled.setChecked(notif_cfg.get("enabled", True), animate=False)
        self.chk_notif_show_island.setChecked(notif_cfg.get("show_island_on_notify", True), animate=False)
        self.chk_notif_mute_focus.setChecked(notif_cfg.get("mute_in_focus", True), animate=False)
        self.chk_notif_sound.setChecked(notif_cfg.get("sound", True), animate=False)
        self.chk_notif_preview.setChecked(notif_cfg.get("preview_text", True), animate=False)

        # 4. Screen Time
        st_cfg = self.config.get("screentime", {})
        self.chk_st_enabled.setChecked(st_cfg.get("enabled", True), animate=False)
        self.chk_st_show_main_menu.setChecked(st_cfg.get("show_in_main_menu", True), animate=False)
        self.chk_st_track_apps.setChecked(st_cfg.get("track_apps", True), animate=False)

        afk_sec = st_cfg.get("idle_threshold_seconds", 120)
        for i in range(self.combo_st_afk.count()):
            if self.combo_st_afk.itemData(i) == afk_sec:
                self.combo_st_afk.setCurrentIndex(i)
                break

        goal_h = int(st_cfg.get("daily_goal_hours", 6))
        self.slider_st_goal.setValue(goal_h)
        self.lbl_goal_val.setText(f"{goal_h} hrs")

        self.chk_st_goal_alert.setChecked(st_cfg.get("goal_alert_enabled", True), animate=False)
        self.chk_st_break_reminder.setChecked(st_cfg.get("break_reminders_enabled", True), animate=False)

        break_int = st_cfg.get("break_interval_minutes", 60)
        for i in range(self.combo_st_break_interval.count()):
            if self.combo_st_break_interval.itemData(i) == break_int:
                self.combo_st_break_interval.setCurrentIndex(i)
                break

        excl_list = st_cfg.get("excluded_apps", [])
        self.txt_st_excluded.setText(", ".join(excl_list))

        # 5. Media & Lyrics
        media_cfg = self.config.get("media", {})
        self.txt_sp_dc.setText(media_cfg.get("spotify_sp_dc", ""))
        self.chk_lyrics_auto_scroll.setChecked(media_cfg.get("auto_scroll_lyrics", True), animate=False)

        # 6. Weather
        w_cfg = self.config.get("weather", {})
        self.txt_weather_city.setText(w_cfg.get("city", "Auto-detect"))
        u_idx = 1 if w_cfg.get("unit", "celsius").lower() == "fahrenheit" else 0
        self.combo_weather_unit.setCurrentIndex(u_idx)

        # 7. Pomodoro
        pomo_cfg = self.config.get("pomodoro", {})
        self.spin_pomo_work.setValue(pomo_cfg.get("work_duration", 1500) // 60)
        self.spin_pomo_break.setValue(pomo_cfg.get("break_duration", 300) // 60)
        self.spin_pomo_long.setValue(pomo_cfg.get("long_break_duration", 900) // 60)
        self.chk_pomo_sound.setChecked(pomo_cfg.get("sound_enabled", True), animate=False)

        # 8. Discord RPC
        rpc_cfg = self.config.get("discord_rpc", {})
        self.chk_rpc_enable.setChecked(rpc_cfg.get("enabled", False), animate=False)
        self.txt_rpc_client.setText(rpc_cfg.get("client_id", "120000000000000000"))
        mode_idx = 0 if rpc_cfg.get("mode") == "dynamic" else 1
        self.combo_rpc_mode.setCurrentIndex(mode_idx)

        # 9. Hardware HUD
        hw_cfg = self.config.get("hardware_hud", {})
        self.chk_monitor_gpu.setChecked(hw_cfg.get("monitor_gpu", True), animate=False)
        self.chk_monitor_bat.setChecked(hw_cfg.get("monitor_battery", True), animate=False)

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
            "screentime": {
                "enabled": self.chk_st_enabled.isChecked(),
                "show_in_main_menu": self.chk_st_show_main_menu.isChecked(),
                "track_apps": self.chk_st_track_apps.isChecked(),
                "idle_threshold_seconds": self.combo_st_afk.currentData() or 120,
                "daily_goal_hours": self.slider_st_goal.value(),
                "goal_alert_enabled": self.chk_st_goal_alert.isChecked(),
                "break_reminders_enabled": self.chk_st_break_reminder.isChecked(),
                "break_interval_minutes": self.combo_st_break_interval.currentData() or 60,
                "excluded_apps": [x.strip() for x in self.txt_st_excluded.text().split(",") if x.strip()]
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

    def _on_screentime_reset_clicked(self):
        self.screentime_reset_requested.emit()
        self.lbl_st_today_time.setText("0m")
        self.lbl_st_goal_pct.setText("Goal: 0%")
        self.bar_st_goal.setValue(0)
        self.lbl_st_streak.setText("Active Streak: 0m")
        self.lbl_st_top_apps.setText("Reset complete.")

    def update_screentime_display(self, total_sec: int, streak_sec: int, top_apps: list, active_app: str, goal_hours: float):
        h = total_sec // 3600
        m = (total_sec % 3600) // 60
        time_str = f"{h}h {m:02d}m" if h > 0 else f"{m}m"
        self.lbl_st_today_time.setText(time_str)

        goal_sec = max(1.0, goal_hours * 3600.0)
        pct = min(100, int((total_sec / goal_sec) * 100))
        self.lbl_st_goal_pct.setText(f"Goal: {pct}% of {int(goal_hours)}h")
        self.bar_st_goal.setValue(pct)

        self.lbl_st_streak.setText(f"Active Streak: {streak_sec // 60}m")

        if top_apps:
            app_text = "Top Apps: " + "  •  ".join(f"{name}: {fmt}" for name, sec, fmt in top_apps[:3])
            self.lbl_st_top_apps.setText(app_text)
        else:
            self.lbl_st_top_apps.setText(f"Active now: {active_app}")

    def select_page(self, page_name: str):
        target = page_name.strip().lower()
        for idx in range(self.nav_list.count()):
            text = self.nav_list.item(idx).text().strip().lower()
            if target in text:
                self.nav_list.setCurrentRow(idx)
                break
