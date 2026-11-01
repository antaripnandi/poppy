"""
Poppy Dynamic Notch Window
Faithfully inspired by NotchX (by Navneet Kaur / Raho Osman) and macOS Dynamic Island.
Features hardware-accelerated rendering, smooth spring animations, deep Windows GSMTC media
integration, Discord RPC, Pomodoro focus tracking, and dedicated settings app.

States:
- Collapsed: Sleek top-bezel pill (Audio visualizer + Tabular Clock + Pomodoro badge)
- Peek: Blooms into Spotify / YouTube Media HUD on mouse hover
- Expanded: Full Productivity Drawer with Tab bar (Home, Music, Timer, Shelf, Notes)
"""

import os
import psutil
from enum import Enum
from datetime import datetime

from PySide6.QtCore import (
    Qt, QRect, QSize, QPoint, QPropertyAnimation, QEasingCurve, QTimer
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPainterPath, QRegion, QPixmap, QImage, QKeyEvent, QLinearGradient, QGuiApplication, QCursor
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QApplication,
    QStackedWidget, QPushButton, QFrame, QGraphicsOpacityEffect, QMenu
)

from poppy.ui.components import (
    IconButton, TabButton, AudioVisualizerBars, DraggableThumbnail
)
from poppy.ui.icons import Icons
from poppy.ui.views import (
    HomeTabView, MusicTabView, TimerTabView, ShelfTabView, NotesTabView
)
from poppy.ui.sticky_note import FloatingStickyNote, FloatingStickyImage
from poppy.ui.settings_window import SettingsWindow
from poppy.ui.styles import DEFAULT_THEME, get_theme
from poppy.core.pomodoro import PomodoroManager
from poppy.core.media_manager import MediaManager
from poppy.core.drop_shelf import DropShelfManager
from poppy.core.discord_rpc import DiscordRPCManager
from poppy.core.screenshot_watcher import ScreenshotWatcher
from poppy.core.system_controls import SystemAudioController, SystemBrightnessController
from poppy.core.weather_manager import WeatherManager
from poppy.core.system_tools import (
    CaffeineManager, ColorEyedropperOverlay,
    launch_screen_snip, lock_workstation
)


class NotchState(Enum):
    COLLAPSED = "collapsed"
    PEEK = "peek"
    ISLAND = "island"
    EXPANDED = "expanded"


def _get_gpu_utilization() -> int | None:
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        return int(pynvml.nvmlDeviceGetUtilizationRates(handle).gpu)
    except Exception:
        return None


class DynamicNotchWindow(QWidget):
    def __init__(self, config: dict = None):
        super().__init__()
        self.config = config or {}

        # Frameless, Always on Top, Hidden from Alt+Tab / Taskbar
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Core Engines
        pomo_cfg = self.config.get("pomodoro", {})
        self.pomodoro = PomodoroManager(
            work_duration=pomo_cfg.get("work_duration", 1500),
            break_duration=pomo_cfg.get("break_duration", 300),
            long_break_duration=pomo_cfg.get("long_break_duration", 900),
            parent=self
        )
        self.media_manager = MediaManager(parent=self)
        self.drop_shelf = DropShelfManager(parent=self)
        self.screenshot_watcher = ScreenshotWatcher(parent=self)
        self._last_screenshot_path: str | None = None
        rpc_cfg = self.config.get("discord_rpc", {})
        self.discord_rpc = DiscordRPCManager(config=rpc_cfg, parent=self)
        self.audio_ctrl = SystemAudioController()
        self.bright_ctrl = SystemBrightnessController()
        self.caffeine = CaffeineManager()
        self._eyedropper_overlay = None
        self.weather_manager = WeatherManager(parent=self)

        # Sizing and Themes
        self._load_appearance_config()

        # State & Animation
        self.state = NotchState.COLLAPSED
        self._target_size = (self._collapsed_w, self._collapsed_h)
        self.anim = QPropertyAnimation(self, b"geometry")
        self.anim.setDuration(self.config.get("notch", {}).get("animation_duration_ms", 200))
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.finished.connect(self._on_animation_finished)

        # Registries
        self._floating_notes = []
        self._settings_window = None

        # Smooth leave timer (400ms grace period)
        self._leave_timer = QTimer(self)
        self._leave_timer.setSingleShot(True)
        self._leave_timer.setInterval(400)
        self._leave_timer.timeout.connect(self._on_leave_timeout)

        # Hover intent debounce timer (120ms hysteresis to avoid accidental Peek bloom)
        self._hover_peek_timer = QTimer(self)
        self._hover_peek_timer.setSingleShot(True)
        self._hover_peek_timer.setInterval(120)
        self._hover_peek_timer.timeout.connect(self._on_hover_peek_timeout)

        # Island auto-dismiss timer (4.5s)
        self._island_timer = QTimer(self)
        self._island_timer.setSingleShot(True)
        self._island_timer.setInterval(4500)
        self._island_timer.timeout.connect(self._on_island_timeout)

        # Periodic Timers
        self._sys_timer = QTimer(self)
        self._sys_timer.setInterval(2000)
        self._sys_timer.timeout.connect(self._update_system_metrics)

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._update_clock)

        self._init_views()
        self._connect_signals()

        # Start background workers
        self.media_manager.start()
        self.discord_rpc.start()
        self.screenshot_watcher.start()
        self.weather_manager.start()
        self._sys_timer.start()
        self._clock_timer.start()

        # Apply initial collapsed geometry
        self._apply_geometry_for_state(NotchState.COLLAPSED, animate=False)

    def _load_appearance_config(self):
        app_cfg = self.config.get("appearance", {})
        self._theme_name = app_cfg.get("theme", DEFAULT_THEME)
        self._theme = get_theme(self._theme_name)
        self._style = app_cfg.get("style", "Notch")  # "Notch" or "Pill"
        self._collapsed_w = app_cfg.get("collapsed_width", 210)
        self._collapsed_h = app_cfg.get("collapsed_height", 30)
        self._open_w = app_cfg.get("open_width", 660)
        self._open_h = app_cfg.get("open_height", 340)
        self._corner_radius = app_cfg.get("corner_radius", 16)

    def minimumSizeHint(self) -> QSize:
        return QSize(self._target_size[0], self._target_size[1])

    def sizeHint(self) -> QSize:
        return QSize(self._target_size[0], self._target_size[1])

    def _init_views(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # =====================================================================
        # 1. Collapsed View: Minimalist Top Pill (pill-v2.png)
        # Symmetrical 3-zone architecture: Left (Media icon) - Center (Time) - Right (Visualizer)
        # =====================================================================
        self.view_collapsed = QWidget(self)
        self.view_collapsed.setFixedHeight(self._collapsed_h)
        v_coll_layout = QHBoxLayout(self.view_collapsed)
        v_coll_layout.setContentsMargins(12, 0, 12, 0)
        v_coll_layout.setSpacing(0)
        v_coll_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Left Zone: Album Art thumbnail (20x20, rounded 5px)
        left_box = QWidget(self)
        l_layout = QHBoxLayout(left_box)
        l_layout.setContentsMargins(0, 0, 0, 0)
        l_layout.setSpacing(6)
        l_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.coll_thumb = QLabel()
        self.coll_thumb.setFixedSize(20, 20)
        self.coll_thumb.setStyleSheet("background-color: rgba(255,255,255,0.08); border-radius: 5px; font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets'; font-size: 10px; color: #94a3b8;")
        self.coll_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.coll_thumb.setText(Icons.MUSIC)
        l_layout.addWidget(self.coll_thumb)
        v_coll_layout.addWidget(left_box, 1)

        # Center Zone: Dead-center Clock & Pomodoro Badge
        center_box = QWidget(self)
        c_layout = QHBoxLayout(center_box)
        c_layout.setContentsMargins(0, 0, 0, 0)
        c_layout.setSpacing(6)
        c_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_clock = QLabel("12:00")
        self.lbl_clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_clock.setStyleSheet("""
            color: #e2e8f0;
            font-size: 11px;
            font-weight: 600;
            background: transparent;
            border: none;
        """)
        c_layout.addWidget(self.lbl_clock)

        self.lbl_coll_pomo = QLabel("")
        self.lbl_coll_pomo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_coll_pomo.setStyleSheet(f"""
            color: {self._theme['accent']};
            font-size: 11px;
            font-weight: 600;
            background: transparent;
            border: none;
        """)
        self.lbl_coll_pomo.setVisible(False)
        c_layout.addWidget(self.lbl_coll_pomo)
        v_coll_layout.addWidget(center_box, 0)

        # Right Zone: Equalizer bars and status dot (symmetrical to Left Zone)
        right_box = QWidget(self)
        r_layout = QHBoxLayout(right_box)
        r_layout.setContentsMargins(0, 0, 0, 0)
        r_layout.setSpacing(6)
        r_layout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.coll_visualizer = AudioVisualizerBars(self)
        r_layout.addWidget(self.coll_visualizer)

        self.coll_status_dot = QLabel("•")
        self.coll_status_dot.setStyleSheet("color: rgba(255,255,255,0.25); font-size: 14px; background: transparent; border: none;")
        r_layout.addWidget(self.coll_status_dot)
        v_coll_layout.addWidget(right_box, 1)

        self.main_layout.addWidget(self.view_collapsed)

        # =====================================================================
        # 2. Peek View (Hover HUD: Spotify / YouTube Media HUD)
        # =====================================================================
        self.view_peek = QWidget(self)
        self.view_peek.setFixedHeight(68)
        v_peek_layout = QHBoxLayout(self.view_peek)
        v_peek_layout.setContentsMargins(14, 6, 14, 8)
        v_peek_layout.setSpacing(12)
        v_peek_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Thumbnail
        self.peek_thumb = QLabel()
        self.peek_thumb.setFixedSize(38, 38)
        self.peek_thumb.setStyleSheet("background-color: rgba(255,255,255,0.06); border-radius: 8px; font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets'; font-size: 14px; color: #94a3b8;")
        self.peek_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.peek_thumb.setText(Icons.MUSIC)
        v_peek_layout.addWidget(self.peek_thumb)

        # Metadata
        meta_col = QVBoxLayout()
        meta_col.setSpacing(1)
        meta_col.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        title_row = QHBoxLayout()
        title_row.setSpacing(4)
        self.lbl_peek_title = QLabel("No Media Playing")
        self.lbl_peek_title.setStyleSheet("color: #f1f5f9; font-size: 11px; font-weight: 600;")
        self.btn_peek_cycle = QPushButton("")
        self.btn_peek_cycle.setVisible(False)
        self.btn_peek_cycle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_peek_cycle.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 4px;
                color: #94a3b8;
                font-size: 9px;
                padding: 1px 5px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.16);
                color: #ffffff;
            }
        """)
        self.btn_peek_cycle.clicked.connect(self.media_manager.next_session)
        title_row.addWidget(self.lbl_peek_title, stretch=1)
        title_row.addWidget(self.btn_peek_cycle)
        meta_col.addLayout(title_row)

        self.lbl_peek_artist = QLabel("Desktop Audio")
        self.lbl_peek_artist.setStyleSheet("color: #94a3b8; font-size: 10px;")
        meta_col.addWidget(self.lbl_peek_artist)
        v_peek_layout.addLayout(meta_col, stretch=1)

        # Playback Controls
        self.btn_peek_prev = IconButton(Icons.PREV, "Previous Track", size=24, font_size=10, is_fluent=True)
        self.btn_peek_prev.clicked.connect(self.media_manager.previous_track)
        self.btn_peek_play = IconButton(Icons.PLAY, "Play/Pause", size=28, font_size=12, is_fluent=True)
        self.btn_peek_play.clicked.connect(self.media_manager.toggle_play_pause)
        self.btn_peek_next = IconButton(Icons.NEXT, "Next Track", size=24, font_size=10, is_fluent=True)
        self.btn_peek_next.clicked.connect(self.media_manager.next_track)

        v_peek_layout.addWidget(self.btn_peek_prev)
        v_peek_layout.addWidget(self.btn_peek_play)
        v_peek_layout.addWidget(self.btn_peek_next)

        self.btn_peek_expand = IconButton(Icons.TEAR_OFF, "Open Drawer", size=22, font_size=10, is_fluent=True)
        self.btn_peek_expand.clicked.connect(lambda: self._transition_to(NotchState.EXPANDED))
        v_peek_layout.addWidget(self.btn_peek_expand)

        self.main_layout.addWidget(self.view_peek)
        self.view_peek.setVisible(False)

        # =====================================================================
        # 2b. Island View (Dynamic Island HUD for Screenshot & Staging)
        # =====================================================================
        self.view_island = QWidget(self)
        self.view_island.setFixedHeight(64)
        v_isl_layout = QHBoxLayout(self.view_island)
        v_isl_layout.setContentsMargins(12, 6, 12, 8)
        v_isl_layout.setSpacing(10)
        v_isl_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Draggable Thumbnail Preview (44x44, rounded 8px)
        self.island_thumb = DraggableThumbnail(size=44, border_radius=8, parent=self)
        self._thumb_opacity_fx = QGraphicsOpacityEffect(self.island_thumb)
        self.island_thumb.setGraphicsEffect(self._thumb_opacity_fx)
        self._thumb_anim = QPropertyAnimation(self._thumb_opacity_fx, b"opacity")
        self._thumb_anim.setDuration(240)
        self._thumb_anim.setStartValue(0.0)
        self._thumb_anim.setEndValue(1.0)
        self._thumb_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        v_isl_layout.addWidget(self.island_thumb)

        # Meta info
        isl_meta = QVBoxLayout()
        isl_meta.setSpacing(2)
        isl_meta.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        isl_title_row = QHBoxLayout()
        isl_title_row.setSpacing(6)
        lbl_isl_dot = QLabel("●")
        lbl_isl_dot.setStyleSheet("color: #3ddc97; font-size: 8px; background: transparent; border: none;")
        self.lbl_isl_title = QLabel("Screenshot Staged")
        self.lbl_isl_title.setStyleSheet("color: #f8fafc; font-size: 11.5px; font-weight: 600; background: transparent; border: none;")
        isl_title_row.addWidget(lbl_isl_dot)
        isl_title_row.addWidget(self.lbl_isl_title)
        isl_title_row.addStretch()
        isl_meta.addLayout(isl_title_row)

        self.lbl_isl_sub = QLabel("Drag to screen or paste in chat")
        self.lbl_isl_sub.setStyleSheet("color: #94a3b8; font-size: 10px; background: transparent; border: none;")
        isl_meta.addWidget(self.lbl_isl_sub)
        v_isl_layout.addLayout(isl_meta, stretch=1)

        # Action Buttons
        self.btn_isl_chat = QPushButton("Copy")
        self.btn_isl_chat.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_isl_chat.setToolTip("Copy formatted image to paste directly into Discord, WhatsApp, Slack, etc.")
        self.btn_isl_chat.setStyleSheet("""
            QPushButton {
                background: rgba(14, 165, 233, 0.2);
                border: 1px solid rgba(56, 189, 248, 0.45);
                border-radius: 6px;
                color: #38bdf8;
                font-size: 10.5px;
                font-weight: 600;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background: rgba(14, 165, 233, 0.35);
                color: #ffffff;
            }
        """)
        self.btn_isl_chat.clicked.connect(self._copy_island_for_chat)
        v_isl_layout.addWidget(self.btn_isl_chat)

        self.btn_isl_pin = QPushButton("Pin")
        self.btn_isl_pin.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_isl_pin.setToolTip("Pin screenshot as a floating sticky note on screen")
        self.btn_isl_pin.setStyleSheet("""
            QPushButton {
                background: rgba(234, 179, 8, 0.2);
                border: 1px solid rgba(234, 179, 8, 0.45);
                border-radius: 6px;
                color: #facc15;
                font-size: 10.5px;
                font-weight: 600;
                padding: 4px 9px;
            }
            QPushButton:hover {
                background: rgba(234, 179, 8, 0.35);
                color: #ffffff;
            }
        """)
        self.btn_isl_pin.clicked.connect(lambda: self._pin_screenshot_to_screen(self._last_screenshot_path))
        v_isl_layout.addWidget(self.btn_isl_pin)

        self.btn_isl_shelf = QPushButton("Shelf")
        self.btn_isl_shelf.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_isl_shelf.setToolTip("Open temporary file shelf")
        self.btn_isl_shelf.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 6px;
                color: #cbd5e1;
                font-size: 10.5px;
                font-weight: 500;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.16);
                color: #ffffff;
            }
        """)
        self.btn_isl_shelf.clicked.connect(self._open_shelf_from_island)
        v_isl_layout.addWidget(self.btn_isl_shelf)

        self.btn_isl_close = IconButton(Icons.CLOSE, "Dismiss", size=22, font_size=10, is_fluent=True)
        self.btn_isl_close.clicked.connect(self._collapse_to_pill)
        v_isl_layout.addWidget(self.btn_isl_close)

        self.main_layout.addWidget(self.view_island)
        self.view_island.setVisible(False)

        # =====================================================================
        # 3. Expanded View (NotchX Navigation & Full Tabbed Suite)
        # =====================================================================
        self.view_expanded = QWidget(self)
        v_exp_layout = QVBoxLayout(self.view_expanded)
        v_exp_layout.setContentsMargins(14, 8, 14, 12)
        v_exp_layout.setSpacing(8)

        # Header Bar: Tabs on the Left, Clock & Controls Capsule on the Right
        header_bar = QHBoxLayout()
        header_bar.setSpacing(6)
        header_bar.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Clean Typographic Tab Pills matching NotchX
        self.tab_buttons = []
        tabs = ["Home", "Music", "Timer", "Shelf", "Notes"]
        for idx, name in enumerate(tabs):
            t_btn = TabButton(name, idx, parent=self, accent=self._theme["accent"])
            t_btn.clicked.connect(lambda checked=False, i=idx: self._switch_tab(i))
            self.tab_buttons.append(t_btn)
            header_bar.addWidget(t_btn)

        header_bar.addStretch()

        # Right Capsule: Tabular Time, Battery, Settings Button, Close Button (home-v2.png)
        capsule = QFrame()
        capsule.setStyleSheet("""
            QFrame {
                background-color: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 14px;
            }
        """)
        cap_layout = QHBoxLayout(capsule)
        cap_layout.setContentsMargins(10, 2, 8, 2)
        cap_layout.setSpacing(8)

        self.lbl_hdr_clock = QLabel("12:11:28 AM")
        self.lbl_hdr_clock.setStyleSheet("font-size: 11px; font-weight: 600; color: #f1f5f9; border: none; background: transparent;")
        cap_layout.addWidget(self.lbl_hdr_clock)

        self.lbl_hdr_bat = QLabel("BAT --%")
        self.lbl_hdr_bat.setStyleSheet("font-size: 10px; color: #94a3b8; border: none; background: transparent;")
        cap_layout.addWidget(self.lbl_hdr_bat)

        self.btn_hdr_caffeine = IconButton(Icons.POWER, "Keep Awake: OFF", size=24, font_size=11, is_fluent=True)
        self.btn_hdr_caffeine.clicked.connect(self._toggle_caffeine)
        cap_layout.addWidget(self.btn_hdr_caffeine)

        btn_settings = IconButton(Icons.SETTINGS, "Settings", size=24, font_size=11, is_fluent=True)
        btn_settings.clicked.connect(self.open_settings)
        cap_layout.addWidget(btn_settings)

        btn_close = IconButton(Icons.CLOSE, "Close (Esc)", size=24, font_size=10, is_fluent=True)
        btn_close.clicked.connect(self._collapse_to_pill)
        cap_layout.addWidget(btn_close)

        header_bar.addWidget(capsule)
        v_exp_layout.addLayout(header_bar)

        # Stacked Widget for Tab Views
        self.tab_stack = QStackedWidget(self)

        # 0: Home Tab
        self.tab_home = HomeTabView(self)
        self.tab_home.tear_off_requested.connect(self._tear_off_sticky_note)
        self.tab_home.pin_requested.connect(self._pin_screenshot_to_screen)
        self.tab_home.btn_ctrl_prev.clicked.connect(self.media_manager.previous_track)
        self.tab_home.btn_ctrl_play.clicked.connect(self.media_manager.toggle_play_pause)
        self.tab_home.btn_ctrl_next.clicked.connect(self.media_manager.next_track)
        self.tab_home.btn_clear_shelf.clicked.connect(self.drop_shelf.clear_shelf)
        self.tab_home.btn_home_shelf_chat.clicked.connect(self._copy_latest_shelf_for_chat)
        self.tab_home.session_select_requested.connect(self.media_manager.select_session)
        self.tab_home.slider_vol.valueChanged.connect(self._on_volume_slider_changed)
        self.tab_home.btn_vol_mute.clicked.connect(self._on_mute_clicked)
        self.tab_home.slider_bright.valueChanged.connect(self._on_brightness_slider_changed)
        self.tab_home.btn_bright_icon.clicked.connect(self._on_brightness_cycle_clicked)
        self.tab_home.caffeine_toggle_requested.connect(self._toggle_caffeine)
        self.tab_home.mic_mute_toggle_requested.connect(self._toggle_mic_mute)
        self.tab_home.focus_shield_requested.connect(self._toggle_focus_shield)
        self.tab_home.screen_snip_requested.connect(self._trigger_screen_snip)
        self.tab_home.eyedropper_requested.connect(self._trigger_color_eyedropper)
        self.tab_home.quick_search_requested.connect(self._trigger_quick_search)
        self.tab_home.lock_workstation_requested.connect(self._lock_workstation)
        self.tab_home.player_menu_requested.connect(self._show_player_dropdown)
        self.tab_home.weather_refresh_requested.connect(self.weather_manager.refresh)
        self.weather_manager.weather_updated.connect(self._on_weather_updated)
        self.tab_stack.addWidget(self.tab_home)

        # 1: Music Tab
        self.tab_music = MusicTabView(self, accent=self._theme["accent"])
        self.tab_music.btn_prev.clicked.connect(self.media_manager.previous_track)
        self.tab_music.btn_play.clicked.connect(self.media_manager.toggle_play_pause)
        self.tab_music.btn_next.clicked.connect(self.media_manager.next_track)
        self.tab_music.session_select_requested.connect(self.media_manager.select_session)
        self.tab_music.btn_prev_session.clicked.connect(self.media_manager.previous_session)
        self.tab_music.btn_next_session.clicked.connect(self.media_manager.next_session)
        self.tab_music.vol_slider.valueChanged.connect(self._on_volume_slider_changed)
        self.tab_music.btn_vol_music.clicked.connect(self._on_mute_clicked)
        self.tab_stack.addWidget(self.tab_music)

        # 2: Timer Tab
        self.tab_timer = TimerTabView(self, accent=self._theme["accent"])
        self.tab_timer.btn_toggle.clicked.connect(self.pomodoro.toggle)
        self.tab_timer.btn_reset.clicked.connect(self.pomodoro.reset)
        self.tab_timer.btn_skip.clicked.connect(self.pomodoro.skip)
        self.tab_timer.btn_phase_focus.clicked.connect(lambda: self.pomodoro.set_phase_focus())
        self.tab_timer.btn_phase_short.clicked.connect(lambda: self.pomodoro.set_phase_break())
        self.tab_stack.addWidget(self.tab_timer)

        # 3: Shelf Tab
        self.tab_shelf = ShelfTabView(self.drop_shelf, screenshot_watcher=self.screenshot_watcher, parent=self)
        self.tab_shelf.pin_requested.connect(self._pin_screenshot_to_screen)
        self.tab_stack.addWidget(self.tab_shelf)

        # 4: Notes Tab
        self.tab_notes = NotesTabView(self)
        self.tab_notes.tear_off_requested.connect(self._tear_off_sticky_note)
        self.tab_stack.addWidget(self.tab_notes)

        v_exp_layout.addWidget(self.tab_stack, stretch=1)
        self.main_layout.addWidget(self.view_expanded)
        self.view_expanded.setVisible(False)

        # Activate initial tab (Home)
        self._switch_tab(0)

    def _switch_tab(self, index: int):
        self.tab_stack.setCurrentIndex(index)
        for i, btn in enumerate(self.tab_buttons):
            btn.set_active(i == index, accent=self._theme["accent"])

    def _connect_signals(self):
        # Pomodoro
        self.pomodoro.time_updated.connect(self._on_pomo_time_updated)
        self.pomodoro.state_changed.connect(self._on_pomo_state_changed)

        # Media
        self.media_manager.media_changed.connect(self._on_media_changed)
        self.media_manager.playback_changed.connect(self._on_playback_changed)
        self.media_manager.sessions_updated.connect(self._on_sessions_updated)

        # Shelf & Screenshot
        self.drop_shelf.shelf_updated.connect(self._on_shelf_updated)
        self.screenshot_watcher.screenshot_captured.connect(self._on_screenshot_captured)

    def _update_clock(self):
        now = datetime.now()
        time_12 = now.strftime("%I:%M:%S %p").lstrip("0")
        time_short = now.strftime("%I:%M %p").lstrip("0")
        date_str = now.strftime("%A, %d %B")
        self.lbl_clock.setText(time_short)
        self.lbl_hdr_clock.setText(f"{date_str}  {time_12}")
        self.tab_home.lbl_big_time.setText(time_12)
        self.tab_home.lbl_date.setText(date_str)

    def _update_system_metrics(self):
        try:
            cpu = int(psutil.cpu_percent())
            ram = int(psutil.virtual_memory().percent)
            self.tab_home.lbl_cpu.set_val(f"{cpu}%")
            self.tab_home.lbl_ram.set_val(f"{ram}%")

            gpu = _get_gpu_utilization()
            if gpu is not None:
                self.tab_home.lbl_gpu.set_val(f"{gpu}%")
                self.tab_home.lbl_gpu.setVisible(True)
            else:
                self.tab_home.lbl_gpu.setVisible(False)

            bat = psutil.sensors_battery()
            if bat:
                plugged = "+" if bat.power_plugged else ""
                bat_text = f"{int(bat.percent)}%{plugged}"
                self.tab_home.lbl_bat.set_val(bat_text)
                self.tab_home.lbl_bat.setVisible(True)
                self.lbl_hdr_bat.setText(f"BAT {bat_text}")
                self.lbl_hdr_bat.setVisible(True)
            else:
                self.tab_home.lbl_bat.setVisible(False)
                self.lbl_hdr_bat.setVisible(False)
        except Exception:
            pass

        # Periodic background sync for hardware sliders if user is not actively dragging
        self._sync_system_controls()

    def _sync_system_controls(self, force: bool = False):
        """Synchronizes UI volume and brightness sliders with actual Windows hardware levels."""
        try:
            # Volume sync
            if force or (not self.tab_home.slider_vol.isSliderDown() and not self.tab_music.vol_slider.isSliderDown()):
                vol = self.audio_ctrl.get_volume()
                muted = self.audio_ctrl.get_mute()
                self.tab_home.set_volume_display(vol, muted)
                self.tab_music.set_volume_display(vol, muted)

            # Brightness sync
            if force or not self.tab_home.slider_bright.isSliderDown():
                bright = self.bright_ctrl.get_brightness()
                self.tab_home.set_brightness_display(bright)

            # Mic mute sync
            mic_muted = self.audio_ctrl.get_mic_mute()
            self._update_mic_button_ui(mic_muted)
        except Exception:
            pass

    def _on_volume_slider_changed(self, value: int):
        self.audio_ctrl.set_volume(value)
        muted = self.audio_ctrl.get_mute()
        if muted and value > 0:
            self.audio_ctrl.set_mute(False)
            muted = False
        self.tab_home.set_volume_display(value, muted)
        self.tab_music.set_volume_display(value, muted)

    def _on_mute_clicked(self):
        new_muted = self.audio_ctrl.toggle_mute()
        vol = self.audio_ctrl.get_volume()
        self.tab_home.set_volume_display(vol, new_muted)
        self.tab_music.set_volume_display(vol, new_muted)

    def _on_brightness_slider_changed(self, value: int):
        self.bright_ctrl.set_brightness(value)
        self.tab_home.set_brightness_display(value)

    def _on_brightness_cycle_clicked(self):
        next_val = self.bright_ctrl.cycle_brightness()
        self.tab_home.set_brightness_display(next_val)

    def _on_weather_updated(self, data: dict):
        self.tab_home.update_weather(data)

    def _toggle_caffeine(self):
        is_on = self.caffeine.toggle()
        self._update_caffeine_ui(is_on)

    def _update_caffeine_ui(self, is_on: bool):
        if is_on:
            tip = "Keep Awake: ON (Display & PC won't sleep)"
            style = """
                background: rgba(245, 158, 11, 0.18);
                border: 1px solid rgba(245, 158, 11, 0.4);
                border-radius: 6px;
                color: #fbbf24;
                font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets';
                font-size: 11px;
            """
        else:
            tip = "Keep Awake: OFF (Click to prevent sleep)"
            style = """
                background: transparent;
                border: none;
                border-radius: 6px;
                color: #94a3b8;
                font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets';
                font-size: 11px;
            """
        self.tab_home.btn_act_caffeine.setStyleSheet(style)
        self.tab_home.btn_act_caffeine.setToolTip(tip)
        if hasattr(self, 'btn_hdr_caffeine') and self.btn_hdr_caffeine:
            self.btn_hdr_caffeine.setStyleSheet(style)
            self.btn_hdr_caffeine.setToolTip(tip)

    def _toggle_mic_mute(self):
        new_state = self.audio_ctrl.toggle_mic_mute()
        self._update_mic_button_ui(new_state)

    def _update_mic_button_ui(self, is_muted: bool):
        if is_muted:
            self.tab_home.btn_act_mic.setText(Icons.MIC_MUTE)
            self.tab_home.btn_act_mic.setToolTip("Microphone: MUTED (Click to Unmute)")
            self.tab_home.btn_act_mic.setStyleSheet("""
                background: rgba(239, 68, 68, 0.15);
                border: 1px solid rgba(239, 68, 68, 0.35);
                border-radius: 6px;
                color: #f87171;
                font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets';
                font-size: 11px;
            """)
        else:
            self.tab_home.btn_act_mic.setText(Icons.MIC)
            self.tab_home.btn_act_mic.setToolTip("Microphone: LIVE (Click to Mute)")
            self.tab_home.btn_act_mic.setStyleSheet("""
                background: transparent;
                border: none;
                border-radius: 6px;
                color: #94a3b8;
                font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets';
                font-size: 11px;
            """)

    def _toggle_focus_shield(self):
        if self.pomodoro.is_running:
            self.pomodoro.pause()
            self.tab_home.btn_act_shield.setStyleSheet("""
                background: transparent;
                border: none;
                border-radius: 6px;
                color: #94a3b8;
                font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets';
                font-size: 11px;
            """)
            self.tab_home.btn_act_shield.setToolTip("Focus Shield: OFF (Click to Start Focus Sprint)")
        else:
            self.pomodoro.start()
            self.tab_home.btn_act_shield.setStyleSheet(f"""
                background: rgba(99, 102, 241, 0.2);
                border: 1px solid {self._theme['accent']};
                border-radius: 6px;
                color: #a5b4fc;
                font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets';
                font-size: 11px;
            """)
            self.tab_home.btn_act_shield.setToolTip("Focus Shield: ACTIVE (Focus Sprint in progress)")
            QTimer.singleShot(300, self._collapse_to_pill)

    def _trigger_screen_snip(self):
        self._collapse_to_pill()
        QTimer.singleShot(250, launch_screen_snip)

    def _trigger_color_eyedropper(self):
        self._collapse_to_pill()
        def _open_eyedropper():
            self._eyedropper_overlay = ColorEyedropperOverlay()
            self._eyedropper_overlay.color_picked.connect(self._on_color_picked)
            self._eyedropper_overlay.show()
        QTimer.singleShot(250, _open_eyedropper)

    def _on_color_picked(self, hex_color: str):
        self.tab_home.txt_notes.setPlaceholderText(f"Copied {hex_color} to clipboard!")
        QTimer.singleShot(4000, lambda: self.tab_home.txt_notes.setPlaceholderText("Jot down quick thought..."))

    def _trigger_quick_search(self):
        if self.state != NotchState.EXPANDED:
            self._transition_to(NotchState.EXPANDED)
        self._switch_tab(0)
        self.tab_home.input_calc.setFocus()
        self.tab_home.input_calc.selectAll()

    def _lock_workstation(self):
        lock_workstation()

    def _show_player_dropdown(self):
        sessions = self.media_manager.get_sessions()
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #181d27;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 8px;
                padding: 4px;
                color: #f1f5f9;
                font-size: 11px;
            }
            QMenu::item {
                padding: 6px 18px 6px 10px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: rgba(255, 255, 255, 0.1);
                color: #ffffff;
            }
        """)
        active_idx = self.media_manager.get_active_index()
        for s in sessions:
            idx = s["index"]
            name = s["display_name"]
            prefix = "✓  " if idx == active_idx else "    "
            action = menu.addAction(f"{prefix}{name}")
            action.triggered.connect(lambda checked=False, i=idx, n=name: self._on_player_session_selected(i, n))

        if not sessions:
            act = menu.addAction("No active media sessions")
            act.setEnabled(False)

        btn = self.tab_home.btn_player_drop
        pos = btn.mapToGlobal(QPoint(0, btn.height() + 2))
        menu.exec(pos)

    def _on_player_session_selected(self, idx: int, name: str):
        self.media_manager.select_session(idx)
        self.tab_home.btn_player_drop.setText(f"Speakers ({name} ▾)")

    def _on_pomo_time_updated(self, rem_sec, total_sec, fmt_time, progress):
        self.tab_timer.lbl_time.setText(fmt_time)
        self.tab_timer.ring.set_progress(progress)

        if self.pomodoro.is_running:
            self.lbl_coll_pomo.setText(fmt_time)
            self.lbl_coll_pomo.setVisible(True)
        else:
            self.lbl_coll_pomo.setVisible(False)

        # Discord RPC
        status = self.pomodoro.get_discord_status()
        if status:
            self.discord_rpc.update_pomodoro(
                self.pomodoro.state.value,
                self.pomodoro.completed_cycles + 1,
                fmt_time,
                status.get("end")
            )

    def _on_pomo_state_changed(self, state, label):
        self.tab_timer.lbl_phase.setText(label)
        btn_text = "Pause" if self.pomodoro.is_running else "Start"
        self.tab_timer.btn_toggle.setText(btn_text)
        cycles = self.pomodoro.completed_cycles
        self.tab_timer.lbl_streak.setText(f"Streak: {cycles} sprint{'s' if cycles != 1 else ''} completed")
        mins = cycles * (self.pomodoro.work_duration // 60)
        self.tab_timer.lbl_daily.setText(f"Today: {mins // 60}h {mins % 60}m of deep focus")

    def _on_media_changed(self, data: dict):
        title = data.get("title", "No Media Playing")
        artist = data.get("artist", "")
        source = data.get("display_name") or data.get("source_app", "")
        is_playing = data.get("is_playing", False)

        # Peek update
        trunc_title = (title[:24] + "..") if len(title) > 24 else title
        trunc_artist = (artist[:26] + "..") if len(artist) > 26 else artist
        self.lbl_peek_title.setText(trunc_title)
        self.lbl_peek_artist.setText(trunc_artist)

        # Home update
        if hasattr(self.tab_home, "lbl_music_title"):
            self.tab_home.lbl_music_title.setText(trunc_title)
        if hasattr(self.tab_home, "lbl_music_artist"):
            self.tab_home.lbl_music_artist.setText(trunc_artist)
        if hasattr(self.tab_home, "lbl_music_source"):
            self.tab_home.lbl_music_source.setText(source.upper() if source else "")
        if hasattr(self.tab_home, "btn_player_drop") and source:
            self.tab_home.btn_player_drop.setText(f"Speakers ({source} ▾)")

        # Music Tab update
        self.tab_music.update_media(data)

        # Thumbnails
        thumb_bytes = data.get("thumbnail_bytes")
        if thumb_bytes:
            pix = QPixmap()
            if pix.loadFromData(thumb_bytes):
                scaled_peek = pix.scaled(38, 38, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                self.peek_thumb.setPixmap(scaled_peek)
                scaled_coll = pix.scaled(20, 20, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                self.coll_thumb.setPixmap(scaled_coll)
                self.coll_thumb.setText("")
            else:
                self.peek_thumb.setText(Icons.MUSIC)
                self.coll_thumb.setText(Icons.MUSIC)
        else:
            self.peek_thumb.setText(Icons.MUSIC)
            self.coll_thumb.setText(Icons.MUSIC)

        if is_playing and not self.pomodoro.is_running:
            self.discord_rpc.update_media(title, artist, data.get("album", ""), is_playing)

    def _on_playback_changed(self, is_playing: bool):
        self.coll_visualizer.set_playing(is_playing)
        self.tab_home.music_bars.set_playing(is_playing)
        self.tab_music.bars.set_playing(is_playing)

        play_symbol = Icons.PAUSE if is_playing else Icons.PLAY
        self.btn_peek_play.setText(play_symbol)
        self.tab_home.btn_ctrl_play.setText(play_symbol)
        self.tab_music.btn_play.setText(play_symbol)

    def _on_sessions_updated(self, sessions_list: list, active_index: int):
        accent = self._theme["accent"]
        self.tab_home.update_sessions_list(sessions_list, active_index, accent=accent)
        self.tab_music.update_sessions_list(sessions_list, active_index, accent=accent)

        # In Peek mode, if multiple sessions exist, show source switch pill
        if len(sessions_list) > 1 and active_index < len(sessions_list):
            curr_name = sessions_list[active_index]["display_name"]
            self.btn_peek_cycle.setText(f"{curr_name} ▾")
            self.btn_peek_cycle.setVisible(True)
            self.btn_peek_cycle.setToolTip(f"Player {active_index + 1} of {len(sessions_list)}. Click to switch media player.")
        else:
            self.btn_peek_cycle.setVisible(False)

    def _on_shelf_updated(self):
        self.tab_home.update_shelf_display(self.drop_shelf.staged_items)

    def _on_screenshot_captured(self, file_path: str, qimage: QImage):
        self._last_screenshot_path = file_path
        self.drop_shelf.add_paths([file_path])
        self.tab_home.update_shelf_display(self.drop_shelf.staged_items)

        # Setup Island view
        pix = QPixmap.fromImage(qimage)
        self.island_thumb.set_image(file_path, pix)
        self.lbl_isl_sub.setText(f"{qimage.width()} × {qimage.height()} · Ready to drop or copy")
        self.btn_isl_chat.setText("Copy")
        self.btn_isl_chat.setStyleSheet("""
            QPushButton {
                background: rgba(14, 165, 233, 0.2);
                border: 1px solid rgba(56, 189, 248, 0.45);
                border-radius: 6px;
                color: #38bdf8;
                font-size: 10.5px;
                font-weight: 600;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background: rgba(14, 165, 233, 0.35);
                color: #ffffff;
            }
        """)

        # Thumbnail flying / entrance animation
        self._thumb_opacity_fx.setOpacity(0.0)
        self._thumb_anim.start()

        # If drawer is not already expanded, expand to Island
        if self.state != NotchState.EXPANDED:
            self._transition_to(NotchState.ISLAND)
            self._island_timer.start(4500)

    def _copy_island_for_chat(self):
        if self._last_screenshot_path:
            ok = self.screenshot_watcher.copy_image_for_chat(self._last_screenshot_path)
            if ok:
                self.btn_isl_chat.setText("Copied!")
                self.btn_isl_chat.setStyleSheet("""
                    QPushButton {
                        background: rgba(34, 197, 94, 0.25);
                        border: 1px solid rgba(34, 197, 94, 0.6);
                        border-radius: 6px;
                        color: #4ade80;
                        font-size: 10.5px;
                        font-weight: 700;
                        padding: 4px 10px;
                    }
                """)
                QTimer.singleShot(1800, self._reset_island_chat_btn)

    def _reset_island_chat_btn(self):
        self.btn_isl_chat.setText("Copy")
        self.btn_isl_chat.setStyleSheet("""
            QPushButton {
                background: rgba(14, 165, 233, 0.2);
                border: 1px solid rgba(56, 189, 248, 0.45);
                border-radius: 6px;
                color: #38bdf8;
                font-size: 10.5px;
                font-weight: 600;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background: rgba(14, 165, 233, 0.35);
                color: #ffffff;
            }
        """)

    def _copy_latest_shelf_for_chat(self):
        if self.drop_shelf.staged_items:
            latest = self.drop_shelf.staged_items[-1]
            ok = self.screenshot_watcher.copy_image_for_chat(latest.path)
            if ok:
                self.tab_home.btn_home_shelf_chat.setText("Copied!")
                self.tab_home.btn_home_shelf_chat.setStyleSheet("""
                    QPushButton {
                        background: rgba(34, 197, 94, 0.25);
                        border: 1px solid rgba(34, 197, 94, 0.6);
                        border-radius: 5px;
                        color: #4ade80;
                        font-size: 9.5px;
                        font-weight: 700;
                        padding: 2px 7px;
                    }
                """)
                QTimer.singleShot(1800, self._reset_home_shelf_chat_btn)

    def _reset_home_shelf_chat_btn(self):
        self.tab_home.btn_home_shelf_chat.setText("Copy")
        self.tab_home.btn_home_shelf_chat.setStyleSheet("""
            QPushButton {
                background: rgba(14, 165, 233, 0.18);
                border: 1px solid rgba(56, 189, 248, 0.35);
                border-radius: 5px;
                color: #38bdf8;
                font-size: 9.5px;
                font-weight: 600;
                padding: 2px 7px;
            }
        """)

    def _open_shelf_from_island(self):
        self._island_timer.stop()
        self._switch_tab(3)
        self._transition_to(NotchState.EXPANDED)

    def _on_island_timeout(self):
        from PySide6.QtGui import QCursor
        if self.geometry().contains(QCursor.pos()):
            self._island_timer.start(1500)
            return
        if self.state == NotchState.ISLAND:
            self._collapse_to_pill()

    def _tear_off_sticky_note(self, text: str):
        note = FloatingStickyNote(initial_text=text)
        screen = self._get_current_screen_geometry()
        offset = (len(self._floating_notes) % 8) * 28
        x = max(20, self.x() + 40 + offset)
        y = max(40, self.y() + self.height() + 16 + offset)
        if x + 280 > screen.x() + screen.width():
            x = screen.x() + screen.width() - 300
        if y + 250 > screen.y() + screen.height():
            y = screen.y() + screen.height() - 270
        note.move(x, y)
        note.show()
        note.raise_()
        note.activateWindow()
        note.editor.setFocus()
        self._floating_notes.append(note)
        note.closed.connect(lambda n: self._floating_notes.remove(n) if n in self._floating_notes else None)

    def _pin_screenshot_to_screen(self, file_path: str):
        if not file_path or not os.path.exists(file_path):
            return
        img_note = FloatingStickyImage(file_path)
        screen = self._get_current_screen_geometry()
        offset = (len(self._floating_notes) % 6) * 32
        x = max(40, screen.x() + (screen.width() - img_note.width()) // 2 + offset)
        y = max(60, screen.y() + 120 + offset)
        img_note.move(x, y)
        img_note.show()
        img_note.raise_()
        img_note.activateWindow()
        self._floating_notes.append(img_note)
        img_note.closed.connect(lambda n: self._floating_notes.remove(n) if n in self._floating_notes else None)

    def open_settings(self):
        """Open the dedicated Poppy Settings application window."""
        if self._settings_window is None:
            self._settings_window = SettingsWindow(config=self.config)
            self._settings_window.settings_saved.connect(self._on_settings_saved)
            self._settings_window.appearance_live_updated.connect(self._apply_live_appearance)

        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    def _apply_live_appearance(self, app_cfg: dict):
        self._theme_name = app_cfg.get("theme", DEFAULT_THEME)
        self._theme = get_theme(self._theme_name)
        self._style = app_cfg.get("style", "Notch")
        self._collapsed_w = app_cfg.get("collapsed_width", 210)
        self._collapsed_h = app_cfg.get("collapsed_height", 30)
        self._open_w = app_cfg.get("open_width", 660)
        self._open_h = app_cfg.get("open_height", 340)
        self._corner_radius = app_cfg.get("corner_radius", 16)

        accent = self._theme["accent"]
        self.lbl_coll_pomo.setStyleSheet(f"color: {accent}; font-size: 11px; font-weight: 600; min-width: 44px;")
        for i, btn in enumerate(self.tab_buttons):
            btn.set_accent(accent)
            btn.set_active(i == self.tab_stack.currentIndex(), accent=accent)
        self.tab_music.set_accent(accent)
        self.tab_timer.set_accent(accent)

        self.view_collapsed.setFixedHeight(self._collapsed_h)
        self._apply_geometry_for_state(self.state, animate=False)
        self.update()

    def _on_settings_saved(self, new_config: dict):
        self.config = new_config or {}
        self._load_appearance_config()
        self._apply_live_appearance(self.config.get("appearance", {}))

        pomo = self.config.get("pomodoro", {})
        if pomo:
            self.pomodoro.work_duration = pomo.get("work_duration", 1500)
            self.pomodoro.break_duration = pomo.get("break_duration", 300)
            self.pomodoro.long_break_duration = pomo.get("long_break_duration", 900)

        notch_cfg = self.config.get("notch", {})
        if notch_cfg:
            self.anim.setDuration(notch_cfg.get("animation_duration_ms", 200))

        rpc_cfg = self.config.get("discord_rpc", {})
        if rpc_cfg:
            self.discord_rpc.update_config(rpc_cfg)

    # --- Mouse & State Transitions ---
    def enterEvent(self, event):
        self._leave_timer.stop()
        if self.state == NotchState.ISLAND:
            self._island_timer.stop()
        auto_peek = self.config.get("notch", {}).get("auto_hover_peek", True)
        if self.state == NotchState.COLLAPSED and auto_peek:
            self._hover_peek_timer.start(120)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_peek_timer.stop()
        from PySide6.QtGui import QCursor
        # Crucial: if cursor is still geometrically within the window, ignore false leave events
        if self.geometry().contains(QCursor.pos()):
            return
        if self.state == NotchState.ISLAND:
            self._island_timer.start(1800)
        elif self.state == NotchState.PEEK:
            self._leave_timer.start()
        super().leaveEvent(event)

    def _on_hover_peek_timeout(self):
        from PySide6.QtGui import QCursor
        if self.state == NotchState.COLLAPSED and self.geometry().contains(QCursor.pos()):
            self._transition_to(NotchState.PEEK)

    def _on_leave_timeout(self):
        from PySide6.QtGui import QCursor
        if self.state == NotchState.PEEK:
            # Double check cursor is really outside before collapsing
            if self.geometry().contains(QCursor.pos()):
                return
            self._transition_to(NotchState.COLLAPSED)

    def mousePressEvent(self, event):
        pos = event.position().toPoint()
        child = self.childAt(pos)
        if child and (isinstance(child, QPushButton) or isinstance(child.parent(), QPushButton)):
            super().mousePressEvent(event)
            return

        if event.button() == Qt.MouseButton.LeftButton:
            if self.state in (NotchState.PEEK, NotchState.COLLAPSED):
                self._leave_timer.stop()
                self._transition_to(NotchState.EXPANDED)
                event.accept()
                return
            elif self.state == NotchState.ISLAND:
                self._open_shelf_from_island()
                event.accept()
                return

        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            if self.state != NotchState.COLLAPSED:
                self._collapse_to_pill()
                event.accept()
                return
        # Ctrl + 1-5 for Quick Tab Switching (NotchX feature)
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            key_map = {
                Qt.Key.Key_1: 0,
                Qt.Key.Key_2: 1,
                Qt.Key.Key_3: 2,
                Qt.Key.Key_4: 3,
                Qt.Key.Key_5: 4
            }
            if event.key() in key_map:
                self._switch_tab(key_map[event.key()])
                event.accept()
                return
        super().keyPressEvent(event)

    def _collapse_to_pill(self):
        self._leave_timer.stop()
        self._island_timer.stop()
        self._transition_to(NotchState.COLLAPSED)

    def _transition_to(self, new_state: NotchState):
        self.state = new_state

        if new_state == NotchState.COLLAPSED:
            self._target_size = (self._collapsed_w, self._collapsed_h)
            self.view_collapsed.setVisible(True)
            self.view_peek.setVisible(False)
            self.view_island.setVisible(False)
            self.view_expanded.setVisible(False)
        elif new_state == NotchState.PEEK:
            self._target_size = (380, 68)
            self.view_collapsed.setVisible(False)
            self.view_peek.setVisible(True)
            self.view_island.setVisible(False)
            self.view_expanded.setVisible(False)
        elif new_state == NotchState.ISLAND:
            self._target_size = (420, 64)
            self.view_collapsed.setVisible(False)
            self.view_peek.setVisible(False)
            self.view_island.setVisible(True)
            self.view_expanded.setVisible(False)
        elif new_state == NotchState.EXPANDED:
            self._target_size = (self._open_w, self._open_h)
            self.view_collapsed.setVisible(False)
            self.view_peek.setVisible(False)
            self.view_island.setVisible(False)
            self.view_expanded.setVisible(True)
            self._sync_system_controls(force=True)

        self._apply_geometry_for_state(new_state, animate=True)

    def _get_current_screen_geometry(self) -> QRect:
        """Multi-monitor aware screen lookup using window center and cursor fallback."""
        screen = QGuiApplication.screenAt(self.geometry().center())
        if not screen:
            screen = QGuiApplication.screenAt(QCursor.pos())
        if not screen:
            screen = QApplication.primaryScreen()
        return screen.geometry() if screen else QRect(0, 0, 1920, 1080)

    def _recenter_window(self):
        """Ensure the window is mathematically centered on the active screen at all times."""
        screen = self._get_current_screen_geometry()
        w = self.width()
        expected_x = screen.x() + (screen.width() - w) // 2
        expected_y = screen.y() if self._style == "Notch" else screen.y() + 8
        if self.x() != expected_x or self.y() != expected_y:
            self.move(expected_x, expected_y)

    def _apply_geometry_for_state(self, state: NotchState, animate: bool = True):
        if state == NotchState.COLLAPSED:
            self._target_size = (self._collapsed_w, self._collapsed_h)
        elif state == NotchState.PEEK:
            self._target_size = (380, 68)
        elif state == NotchState.ISLAND:
            self._target_size = (420, 64)
        elif state == NotchState.EXPANDED:
            min_w = self.view_expanded.minimumSizeHint().width()
            min_h = self.view_expanded.minimumSizeHint().height()
            w = max(self._open_w, min_w)
            h = max(self._open_h, min_h)
            self._target_size = (w, h)

        screen = self._get_current_screen_geometry()
        w, h = self._target_size
        x = screen.x() + (screen.width() - w) // 2
        y = screen.y() if self._style == "Notch" else screen.y() + 8
        target_rect = QRect(x, y, w, h)

        if animate:
            self.anim.stop()
            # Fast snappy spring duration matching NotchX FastDuration (0.14s)
            duration = 140 if state != NotchState.EXPANDED else 180
            self.anim.setDuration(duration)
            self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            # Clear mask during animation to eliminate SetWindowRgn DWM pipeline stalls
            self.clearMask()
            self.anim.setStartValue(self.geometry())
            self.anim.setEndValue(target_rect)
            self.anim.start()
        else:
            self.anim.stop()
            self.setGeometry(target_rect)
            self._recenter_window()
            self._update_clickthrough_mask()

    def _on_animation_finished(self):
        self.resize(*self._target_size)
        self._recenter_window()
        self._update_clickthrough_mask()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # NEVER call SetWindowRgn during a live animation frame
        if not (self.anim and self.anim.state() == QPropertyAnimation.State.Running):
            self._recenter_window()
            self._update_clickthrough_mask()

    def _update_clickthrough_mask(self):
        w = self.width()
        h = self.height()
        radius = float(self._corner_radius if self.state == NotchState.EXPANDED else (14 if self.state == NotchState.ISLAND else 12))

        path = QPainterPath()
        if self._style == "Notch":
            # Hugs top edge: Top corners are square (0,0), bottom corners are rounded
            path.moveTo(0, 0)
            path.lineTo(w, 0)
            path.lineTo(w, h - radius)
            path.quadTo(w, h, w - radius, h)
            path.lineTo(radius, h)
            path.quadTo(0, h, 0, h - radius)
            path.closeSubpath()
        else:
            # Floating Pill: All 4 corners rounded
            path.addRoundedRect(0, 0, w, h, radius, radius)

        polygon = path.toFillPolygon().toPolygon()
        self.setMask(QRegion(polygon))

    # --- Drag & Drop Handlers ---
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            if self.state != NotchState.EXPANDED:
                self._transition_to(NotchState.EXPANDED)
                self._switch_tab(3)  # Switch to Shelf
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
            if paths:
                self.drop_shelf.add_paths(paths)
                self._switch_tab(3)  # Shelf tab
                event.acceptProposedAction()
                return
        event.ignore()

    # --- Painter Logic: NotchX Theme Surface & Hairline Highlight ---
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        h = float(self.height())
        radius = float(self._corner_radius if self.state == NotchState.EXPANDED else (14 if self.state == NotchState.ISLAND else 12))

        path = QPainterPath()
        if self._style == "Notch":
            path.moveTo(0, 0)
            path.lineTo(w, 0)
            path.lineTo(w, h - radius)
            path.quadTo(w, h, w - radius, h)
            path.lineTo(radius, h)
            path.quadTo(0, h, 0, h - radius)
            path.closeSubpath()
        else:
            path.addRoundedRect(0, 0, w, h, radius, radius)

        # Gradient / Surface Fill from active theme
        bg_col = QColor(self._theme["bg"])
        grad_col = QColor(self._theme["gradient"])
        gradient = QLinearGradient(0, 0, 0, h)
        gradient.setColorAt(0.0, grad_col)
        gradient.setColorAt(1.0, bg_col)
        painter.setBrush(QBrush(gradient))

        # Quiet hairline rim highlight
        painter.setPen(QPen(QColor(255, 255, 255, 16), 1.0))
        painter.drawPath(path)

    def closeEvent(self, event):
        self.media_manager.stop()
        self.discord_rpc.close()
        self.screenshot_watcher.stop()
        for note in self._floating_notes:
            note.close()
        if self._settings_window:
            self._settings_window.close()
        super().closeEvent(event)
