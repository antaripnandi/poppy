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
import ctypes
import psutil
import atexit
from enum import Enum
from datetime import datetime

from PySide6.QtCore import (
    Qt, QRect, QSize, QPoint, QPropertyAnimation, QEasingCurve, QTimer, QEvent, Signal
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPainterPath, QRegion, QPixmap, QImage, QKeyEvent, QLinearGradient, QGuiApplication, QCursor
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QApplication,
    QStackedWidget, QPushButton, QFrame, QGraphicsOpacityEffect, QMenu, QLayout, QSizePolicy
)

from poppy.ui.theme import set_widget_style, configure_theme, refresh_theme, surface_colors, is_light_theme, resolve_light_mode, LAYOUT_THEMES, home_order
from poppy.ui.components import (
    IconButton, TabButton, AudioVisualizerBars, DraggableThumbnail,
    AnimatedTabStrip, AnimatedStackedWidget, CardFrame
)
from poppy.ui.icons import Icons
from poppy.ui.views import (
    HomeTabView, MusicTabView, TimerTabView, ShelfTabView, NotesTabView
)
from poppy.ui.extended_views import (
    CalendarTabView, ClipboardTabView, DocsTabView,
    DesktopsTabView, ScreenAnnotationOverlay
)
from poppy.ui.sticky_note import FloatingStickyNote, FloatingStickyImage
from poppy.ui.settings_window import SettingsWindow
from poppy.ui.styles import DEFAULT_THEME, get_theme, get_stylesheet, normalize_appearance
from poppy.core.pomodoro import PomodoroManager
from poppy.core.media_manager import MediaManager
from poppy.core.lyrics_manager import LyricsManager
from poppy.core.drop_shelf import DropShelfManager
from poppy.core.discord_rpc import DiscordRPCManager
from poppy.core.screenshot_watcher import ScreenshotWatcher
from poppy.core.system_controls import SystemAudioController, SystemBrightnessController
from poppy.core.system_features import (
    PrivacyMonitor, ScreenCaptureShield, BluetoothManager,
    ClipboardHistoryManager, AudioEndpointManager, clipboard_allows_history
)
from poppy.core.weather_manager import WeatherManager
from poppy.core.screentime_manager import ScreenTimeManager
from poppy.core.system_tools import (
    CaffeineManager, ColorEyedropperOverlay,
    launch_screen_snip, lock_workstation
)


class NotchState(Enum):
    COLLAPSED = "collapsed"
    PEEK = "peek"
    ISLAND = "island"
    EXPANDED = "expanded"


_gpu_api = None
_gpu_handle = None
_gpu_unavailable = False


def _get_gpu_utilization() -> int | None:
    global _gpu_api, _gpu_handle, _gpu_unavailable
    if _gpu_unavailable:
        return None
    try:
        if _gpu_api is None:
            import pynvml
            pynvml.nvmlInit()
            _gpu_api = pynvml
            atexit.register(pynvml.nvmlShutdown)
            _gpu_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        return int(_gpu_api.nvmlDeviceGetUtilizationRates(_gpu_handle).gpu)
    except Exception:
        _gpu_unavailable = True
        return None


class DynamicNotchWindow(QWidget):
    message_requested = Signal(str, str)

    def __init__(self, config: dict = None):
        super().__init__()
        self.config = config or {}
        self._current_media = {}

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
        self.pomodoro.sound_enabled = pomo_cfg.get("sound_enabled", True)
        self.media_manager = MediaManager(parent=self)
        self.drop_shelf = DropShelfManager(parent=self)
        self.screenshot_watcher = ScreenshotWatcher(parent=self)
        self.screenshot_watcher.enabled = self.config.get("capture", {}).get("enabled", False)
        self.screenshot_watcher.protected_paths = lambda: {item.path for item in self.drop_shelf.staged_items}
        self._last_screenshot_path: str | None = None
        rpc_cfg = self.config.get("discord_rpc", {})
        self.discord_rpc = DiscordRPCManager(config=rpc_cfg, parent=self)
        self.audio_ctrl = SystemAudioController()
        self.bright_ctrl = SystemBrightnessController()
        self.caffeine = CaffeineManager()
        self._eyedropper_overlay = None
        self.weather_manager = WeatherManager(config=self.config, parent=self)
        self.lyrics_manager = LyricsManager(config=self.config, parent=self)
        self.privacy_monitor = PrivacyMonitor(parent=self)
        self.bt_manager = BluetoothManager(parent=self)
        self.clip_mgr = ClipboardHistoryManager(parent=self)
        self._is_pinned = False
        self._is_screen_shielded = False
        self._annotation_overlay = None
        self._floating_windows = []
        self._shutting_down = False

        # Sizing and Themes
        self._load_appearance_config()
        self.setMinimumSize(1, 1)
        self.screentime = ScreenTimeManager(self.config, parent=self)

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

        # Smooth leave timer (350ms grace period)
        self._leave_timer = QTimer(self)
        self._leave_timer.setSingleShot(True)
        self._leave_timer.setInterval(350)
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

        # Click outside detector for auto-dismissing expanded drawer
        self._click_outside_timer = QTimer(self)
        self._click_outside_timer.setInterval(35)
        self._click_outside_timer.timeout.connect(self._check_click_outside)

        # Periodic Timers
        self._sys_timer = QTimer(self)
        self._sys_timer.setInterval(2000)
        self._sys_timer.timeout.connect(self._update_system_metrics)

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._update_clock)

        self._init_views()
        self._connect_signals()
        self.pomodoro._emit_update()

        # Start background workers
        self.media_manager.start()
        self.discord_rpc.start()
        if self.screenshot_watcher.enabled:
            self.screenshot_watcher.start()
        self.weather_manager.start()
        self._sys_timer.start()
        self._clock_timer.start()

        # Apply initial collapsed geometry
        self._apply_geometry_for_state(NotchState.COLLAPSED, animate=False)
        self._update_clock()
        self._on_shelf_updated()
        QTimer.singleShot(0, self._restore_saved_notes)

    def _load_appearance_config(self):
        self.setMinimumSize(1, 1)
        app_cfg = normalize_appearance(self.config.get("appearance", {}))
        self._appearance = app_cfg
        configure_theme(app_cfg)
        self._theme_name = app_cfg.get("theme", DEFAULT_THEME)
        self._theme = get_theme(self._theme_name)
        self._style = app_cfg.get("style", "Notch")  # "Notch" or "Pill"
        self._collapsed_w = app_cfg.get("collapsed_width", 240)
        self._collapsed_h = app_cfg.get("collapsed_height", 30)
        self._open_w = max(app_cfg.get("open_width", 960), 480)
        self._open_h = max(app_cfg.get("open_height", 560), 360)
        self._corner_radius = app_cfg.get("corner_radius", 22)
        self._top_offset = app_cfg.get("top_offset", 0)
        self._display = app_cfg.get("display", "Primary")

    def minimumSizeHint(self) -> QSize:
        return QSize(self._collapsed_w, self._collapsed_h)

    def sizeHint(self) -> QSize:
        return QSize(self._target_size[0], self._target_size[1])

    def _init_views(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        self.main_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.main_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        # =====================================================================
        # 1. Collapsed View: Minimalist Top Pill (pill-v2.png)
        # Symmetrical 3-zone architecture: Left (Media icon) - Center (Time) - Right (Visualizer)
        # =====================================================================
        self.view_collapsed = QWidget(self)
        self.view_collapsed.setFixedSize(self._collapsed_w, self._collapsed_h)
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
        set_widget_style(self.coll_thumb, "background-color: rgba(255,255,255,0.08); border-radius: 5px; font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets'; font-size: 10px; color: #94a3b8;")
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
        set_widget_style(self.lbl_clock, """
            color: #e2e8f0;
            font-size: 11px;
            font-weight: 600;
            background: transparent;
            border: none;
        """)
        c_layout.addWidget(self.lbl_clock)

        self.lbl_coll_pomo = QLabel("")
        self.lbl_coll_pomo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_widget_style(self.lbl_coll_pomo, f"""
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
        set_widget_style(self.coll_status_dot, "color: rgba(255,255,255,0.25); font-size: 14px; background: transparent; border: none;")
        r_layout.addWidget(self.coll_status_dot)
        v_coll_layout.addWidget(right_box, 1)

        self.main_layout.addWidget(self.view_collapsed)

        # =====================================================================
        # 2. Peek View (Hover HUD: Spotify / YouTube Media HUD)
        # =====================================================================
        self.view_peek = QWidget(self)
        self.view_peek.setFixedSize(420, 72)
        v_peek_layout = QHBoxLayout(self.view_peek)
        v_peek_layout.setContentsMargins(14, 12, 14, 12)
        v_peek_layout.setSpacing(12)
        v_peek_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Thumbnail
        self.peek_thumb = QLabel()
        self.peek_thumb.setFixedSize(44, 44)
        set_widget_style(self.peek_thumb, "background-color: rgba(255,255,255,0.06); border-radius: 8px; font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets'; font-size: 14px; color: #94a3b8;")
        self.peek_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.peek_thumb.setText(Icons.MUSIC)
        self.peek_thumb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.peek_thumb.setToolTip("Click to open Music")
        v_peek_layout.addWidget(self.peek_thumb)

        # Metadata
        meta_col = QVBoxLayout()
        meta_col.setSpacing(3)
        meta_col.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.lbl_peek_title = QLabel("Nothing playing")
        self.lbl_peek_title.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_peek_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        set_widget_style(self.lbl_peek_title, "color: #edf1f0; font-size: 12px; font-weight: 600; background: transparent;")
        self.btn_peek_cycle = QPushButton("")
        self.btn_peek_cycle.setVisible(False)
        self.btn_peek_cycle.setCursor(Qt.CursorShape.PointingHandCursor)
        set_widget_style(self.btn_peek_cycle, """
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 4px;
                color: #9ca8a5;
                font-size: 11px;
                padding: 0;
            }
            QPushButton:hover {
                background: transparent;
                color: #ffffff;
            }
        """)
        self.btn_peek_cycle.clicked.connect(self.media_manager.next_session)
        self.btn_peek_cycle.setMaximumWidth(82)
        self.btn_peek_cycle.setAccessibleName("Switch media player")
        meta_col.addWidget(self.lbl_peek_title)

        self.lbl_peek_artist = QLabel("Play audio in a media app")
        self.lbl_peek_artist.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_peek_artist.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        set_widget_style(self.lbl_peek_artist, "color: #9ca8a5; font-size: 11px; background: transparent;")
        detail_row = QHBoxLayout()
        detail_row.setSpacing(6)
        detail_row.addWidget(self.lbl_peek_artist, 1)
        detail_row.addWidget(self.btn_peek_cycle)
        detail_row.addStretch(1)
        meta_col.addLayout(detail_row)
        v_peek_layout.addLayout(meta_col, stretch=1)

        # Playback Controls
        self.btn_peek_prev = IconButton(Icons.PREV, "Previous track", size=28, font_size=13, is_fluent=True)
        self.btn_peek_prev.clicked.connect(self.media_manager.previous_track)
        self.btn_peek_play = IconButton(Icons.PLAY, "Play", size=32, font_size=14, is_fluent=True)
        set_widget_style(self.btn_peek_play, "QPushButton { background: #2b3032; color: #edf1f0; border: none; border-radius: 16px; padding: 0; font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets'; font-size: 14px; } QPushButton:hover { background: #3b4344; } QPushButton:pressed { background: #46514c; } QPushButton:focus { border: 1px solid #b5c9bd; } QPushButton:disabled { color: #59615d; }")
        self.btn_peek_play.clicked.connect(self.media_manager.toggle_play_pause)
        self.btn_peek_next = IconButton(Icons.NEXT, "Next track", size=28, font_size=13, is_fluent=True)
        self.btn_peek_next.clicked.connect(self.media_manager.next_track)

        transport = QHBoxLayout()
        transport.setSpacing(3)
        for button in (self.btn_peek_prev, self.btn_peek_play, self.btn_peek_next):
            button.setEnabled(False)
            transport.addWidget(button)
        v_peek_layout.addLayout(transport)

        self.btn_peek_expand = IconButton(Icons.TEAR_OFF, "Open Drawer", size=22, font_size=10, is_fluent=True)
        self.btn_peek_expand.clicked.connect(lambda: self._transition_to(NotchState.EXPANDED, target_tab="Music"))
        self.btn_peek_expand.hide()  # The artwork and metadata open Music directly.

        self.main_layout.addWidget(self.view_peek)
        self.view_peek.setVisible(False)
        self._peek_opacity = QGraphicsOpacityEffect(self.view_peek)
        self.view_peek.setGraphicsEffect(self._peek_opacity)
        self._peek_opacity.setEnabled(False)
        self._peek_fade = QPropertyAnimation(self._peek_opacity, b"opacity", self)
        self._peek_fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._peek_fade.finished.connect(lambda: self._peek_opacity.setEnabled(False))

        # =====================================================================
        # 2b. Island View (Dynamic Island HUD for Screenshot & Staging)
        # =====================================================================
        self.view_island = QWidget(self)
        self.view_island.setFixedSize(420, 64)
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
        set_widget_style(lbl_isl_dot, "color: #3ddc97; font-size: 8px; background: transparent; border: none;")
        self.lbl_isl_title = QLabel("Screenshot Staged")
        set_widget_style(self.lbl_isl_title, "color: #f8fafc; font-size: 11.5px; font-weight: 600; background: transparent; border: none;")
        isl_title_row.addWidget(lbl_isl_dot)
        isl_title_row.addWidget(self.lbl_isl_title)
        isl_title_row.addStretch()
        isl_meta.addLayout(isl_title_row)

        self.lbl_isl_sub = QLabel("Drag to screen or paste in chat")
        set_widget_style(self.lbl_isl_sub, "color: #94a3b8; font-size: 10px; background: transparent; border: none;")
        isl_meta.addWidget(self.lbl_isl_sub)
        v_isl_layout.addLayout(isl_meta, stretch=1)

        # Action Buttons
        self.btn_isl_chat = QPushButton("Copy")
        self.btn_isl_chat.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_isl_chat.setToolTip("Copy formatted image to paste directly into Discord, WhatsApp, Slack, etc.")
        set_widget_style(self.btn_isl_chat, """
            QPushButton {
                background: rgba(14, 165, 233, 0.2);
                border: none;
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
        set_widget_style(self.btn_isl_pin, """
            QPushButton {
                background: rgba(234, 179, 8, 0.2);
                border: none;
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
        set_widget_style(self.btn_isl_shelf, """
            QPushButton {
                background: rgba(255, 255, 255, 0.08);
                border: none;
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
        self.view_expanded.setFixedSize(self._open_w, self._open_h)
        self.view_expanded.setMinimumSize(0, 0)
        self._expanded_opacity = QGraphicsOpacityEffect(self.view_expanded)
        self.view_expanded.setGraphicsEffect(self._expanded_opacity)
        self._expanded_opacity.setOpacity(1.0)
        self._expanded_opacity.setEnabled(False)
        self._anim_opacity = QPropertyAnimation(self._expanded_opacity, b"opacity", self)
        self._anim_opacity.setDuration(260)
        self._anim_opacity.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_opacity.finished.connect(lambda: self._expanded_opacity.setEnabled(False))
        v_exp_layout = QVBoxLayout(self.view_expanded)
        v_exp_layout.setContentsMargins(14, 12, 14, 12)
        v_exp_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        v_exp_layout.setSpacing(8)

        # Header Bar: Tabs on the Left, Clock & Controls Capsule on the Right
        header_bar = QHBoxLayout()
        header_bar.setSpacing(6)
        header_bar.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Smooth Segmented Tab Strip with sliding indicator pill
        self._tab_name_to_stack_idx = {
            "Home": 0,
            "Music": 1,
            "Calendar": 2,
            "Clipboard": 3,
            "Docs": 4,
            "Desktops": 5,
            "Timer": 6,
            "Shelf": 7,
            "Notes": 8
        }
        self._refresh_tab_names()
        self.tab_strip = AnimatedTabStrip([(name, "") for name in self._active_tab_names], accent=self._theme["accent"], parent=self)
        self.tab_strip.tab_changed.connect(self._switch_tab)
        header_bar.addWidget(self.tab_strip)
        header_bar.addStretch()

        self.lbl_cam_dot = QLabel("●")
        self.lbl_cam_dot.setToolTip("Camera in use")
        set_widget_style(self.lbl_cam_dot, "color: #70bd88; font-size: 11px;")
        self.lbl_mic_dot = QLabel("●")
        self.lbl_mic_dot.setToolTip("Microphone in use")
        set_widget_style(self.lbl_mic_dot, "color: #d5a66b; font-size: 11px;")
        for dot in (self.lbl_cam_dot, self.lbl_mic_dot):
            dot.hide()
            header_bar.addWidget(dot)

        # Window actions stay directly accessible below the tab content.
        window_tools = (
            ("btn_hdr_shield", Icons.SHIELD, "Hide from screen capture", self._toggle_screen_shield),
            ("btn_hdr_pencil", Icons.PENCIL, "Draw on screen", self._toggle_annotation),
            ("btn_hdr_popout", Icons.TEAR_OFF, "Float current tab", self._pop_out_current_tab),
            ("btn_hdr_pin", Icons.PIN, "Keep panel open", self._toggle_pin),
            ("btn_hdr_caffeine", Icons.POWER, "Keep awake", self._toggle_caffeine),
        )
        for name, icon, title, callback in window_tools:
            button = IconButton(icon, title, size=28, is_fluent=True, parent=self)
            button.clicked.connect(callback)
            setattr(self, name, button)

        self.btn_settings = IconButton(Icons.SETTINGS, "Settings", size=32, font_size=15, is_fluent=True)
        self.btn_settings.clicked.connect(self.open_settings)
        header_bar.addWidget(self.btn_settings)
        v_exp_layout.addLayout(header_bar)

        # Stacked Widget for Tab Views with smooth cross-fade animation
        self.tab_stack = AnimatedStackedWidget(self)

        # 0: Home Tab
        self.tab_home = HomeTabView(self)
        self.tab_home.layout_changed.connect(self._resize_expanded_panel)
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
        self.tab_music.configure_appearance(self.config.get("media", {}), self._theme)
        self._applied_media_appearance = self._media_appearance_values()
        self.tab_music.btn_prev.clicked.connect(self.media_manager.previous_track)
        self.tab_music.btn_play.clicked.connect(self.media_manager.toggle_play_pause)
        self.tab_music.btn_next.clicked.connect(self.media_manager.next_track)
        self.tab_music.session_select_requested.connect(self.media_manager.select_session)
        self.tab_music.btn_prev_session.clicked.connect(self.media_manager.previous_session)
        self.tab_music.btn_next_session.clicked.connect(self.media_manager.next_session)
        self.tab_music.vol_slider.valueChanged.connect(self._on_volume_slider_changed)
        self.tab_music.btn_vol_music.clicked.connect(self._on_mute_clicked)
        self.tab_music.seek_requested.connect(self.media_manager.seek)
        self.tab_music.sound_settings_requested.connect(lambda: os.startfile("ms-settings:sound"))
        self.tab_music.layout_changed.connect(self._resize_expanded_panel)
        self.tab_music.btn_lyrics.toggled.connect(self._on_lyrics_visibility_changed)
        self.tab_stack.addWidget(self.tab_music)

        # 2: Calendar Tab
        self.tab_calendar = CalendarTabView(self, accent=self._theme["accent"])
        self.tab_stack.addWidget(self.tab_calendar)

        # 3: Clipboard Tab
        self.tab_clipboard = ClipboardTabView(self.clip_mgr, parent=self)
        self.tab_stack.addWidget(self.tab_clipboard)

        # 4: Docs Tab
        self.tab_docs = DocsTabView(self, accent=self._theme["accent"])
        self.tab_stack.addWidget(self.tab_docs)

        # 5: Desktops Tab
        self.tab_desktops = DesktopsTabView(self, accent=self._theme["accent"])
        self.tab_stack.addWidget(self.tab_desktops)

        # 6: Timer Tab
        self.tab_timer = TimerTabView(self, accent=self._theme["accent"])
        self.tab_timer.btn_toggle.clicked.connect(self.pomodoro.toggle)
        self.tab_timer.btn_reset.clicked.connect(self.pomodoro.reset)
        self.tab_timer.btn_skip.clicked.connect(self.pomodoro.skip)
        self.tab_timer.btn_phase_focus.clicked.connect(lambda: self.pomodoro.set_phase_focus())
        self.tab_timer.btn_phase_short.clicked.connect(lambda: self.pomodoro.set_phase_break())
        self.tab_timer.btn_phase_long.clicked.connect(lambda: self.pomodoro.set_phase_break(is_long=True))
        self.tab_stack.addWidget(self.tab_timer)

        # 7: Shelf Tab
        self.tab_shelf = ShelfTabView(self.drop_shelf, screenshot_watcher=self.screenshot_watcher, parent=self)
        self.tab_shelf.pin_requested.connect(self._pin_screenshot_to_screen)
        self.tab_stack.addWidget(self.tab_shelf)

        # 8: Notes Tab
        self.tab_notes = NotesTabView(self)
        self.tab_notes.tear_off_requested.connect(self._tear_off_sticky_note)
        self.tab_notes.saved_note_requested.connect(self._open_saved_note)
        self.tab_stack.addWidget(self.tab_notes)

        v_exp_layout.addWidget(self.tab_stack, stretch=1)
        tools = QHBoxLayout()
        tools.setContentsMargins(6, 0, 6, 0)
        tools.setSpacing(6)
        tools.addStretch()
        for name, _, _, _ in window_tools:
            tools.addWidget(getattr(self, name))
        v_exp_layout.addLayout(tools)
        self.main_layout.addWidget(self.view_expanded)
        self.view_expanded.setVisible(False)

        # Activate initial tab (Home)
        self._switch_tab(0)
        self.tab_home.slider_vol.set_accent(self._theme["accent"])
        self.tab_home.slider_bright.set_accent(self._theme["accent"])
        self._apply_layout_theme(self._appearance.get("layout", "Classic"))
        refresh_theme()

    def _refresh_tab_names(self):
        enabled = self.config.get("tabs", {}).get("enabled", list(self._tab_name_to_stack_idx))
        self._enabled_tab_names = [name for name in self._tab_name_to_stack_idx if name in enabled]
        if not self._enabled_tab_names:
            self._enabled_tab_names = ["Home"]
        self._active_tab_names = list(self._enabled_tab_names)
        if not self._active_tab_names:
            self._active_tab_names = self._enabled_tab_names[:1]

    def _switch_tab(self, index: int, animate: bool = True):
        if not 0 <= index < len(self._active_tab_names):
            return
        self._switch_to_tab_by_name(self._active_tab_names[index], animate)

    def _switch_to_tab_by_name(self, tab_name: str, animate: bool = True):
        if tab_name not in self._tab_name_to_stack_idx:
            return
        self.tab_stack.slide_to_index(self._tab_name_to_stack_idx[tab_name])
        self._last_tab_name = tab_name
        self._on_lyrics_visibility_changed(tab_name == "Music" and self.tab_music.btn_lyrics.isChecked())
        if tab_name in self._active_tab_names:
            self.tab_strip.set_current_index(self._active_tab_names.index(tab_name), animate=animate, emit_signal=False)
        else:
            self.tab_strip.clear_selection()
        self._resize_expanded_panel()

    def _rebuild_tabs(self):
        previous = getattr(self, "_last_tab_name", "Home")
        self._refresh_tab_names()
        self.tab_strip.set_tabs([(name, "") for name in self._active_tab_names])
        self._switch_to_tab_by_name(previous if previous in self._enabled_tab_names else self._active_tab_names[0], animate=False)

    def _resize_expanded_panel(self):
        if self.state == NotchState.EXPANDED:
            self._apply_geometry_for_state(self.state, animate=False)

    def _on_lyrics_visibility_changed(self, visible):
        data = self._current_media
        title = data.get("title", "")
        detached = self.tab_music.window() is not self
        showing = self.tab_music.isVisible() and self.tab_music.btn_lyrics.isChecked()
        if showing and (visible or detached) and title not in ("", "No Media Playing", "Unknown Title"):
            self.lyrics_manager.request_lyrics(title, data.get("artist", ""), data.get("album", ""))
        else:
            self.lyrics_manager.cancel_request()

    def _connect_signals(self):
        # Pomodoro
        self.pomodoro.time_updated.connect(self._on_pomo_time_updated)
        self.pomodoro.state_changed.connect(self._on_pomo_state_changed)

        # Media
        self.media_manager.media_changed.connect(self._on_media_changed)
        self.media_manager.playback_changed.connect(self._on_playback_changed)
        self.media_manager.sessions_updated.connect(self._on_sessions_updated)
        self.media_manager.timeline_changed.connect(self.tab_music.update_timeline)

        # Lyrics
        self.lyrics_manager.lyrics_loaded.connect(self.tab_music.set_lyrics)
        self.lyrics_manager.lyrics_not_found.connect(self.tab_music.set_lyrics_not_found)

        # Shelf & Screenshot
        self.drop_shelf.shelf_updated.connect(self._on_shelf_updated)
        self.screenshot_watcher.screenshot_captured.connect(self._on_screenshot_captured)

        # Hardware Privacy Indicators
        self.privacy_monitor.camera_status_changed.connect(self._on_camera_status_changed)
        self.privacy_monitor.mic_status_changed.connect(self._on_mic_status_changed)

        # Clipboard Auto-Capture
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.dataChanged.connect(self._on_clipboard_data_changed)

        # Home Audio & Bluetooth Menus
        self.tab_home.audio_device_menu_requested.connect(self._show_audio_device_dropdown)
        self.tab_home.bluetooth_menu_requested.connect(self._show_bluetooth_dropdown)

        # Screen Time & Digital Wellbeing
        self.screentime.stats_updated.connect(self._on_screentime_stats_updated)
        self.screentime.break_reminder_triggered.connect(self._on_screentime_break_reminder)
        self.screentime.daily_goal_reached.connect(self._on_screentime_goal_reached)
        self.tab_home.screentime_clicked.connect(lambda: self.open_settings("Screen Time"))

    def _on_screentime_stats_updated(self, total_sec: int, streak_sec: int, top_apps: list, active_app: str):
        st_cfg = self.config.get("screentime", {})
        show_pill = st_cfg.get("enabled", True) and st_cfg.get("show_in_main_menu", True)
        if hasattr(self.tab_home, "screentime_widget"):
            self.tab_home.screentime_widget.setVisible(show_pill)
            self.tab_home.screentime_widget.update_stats(
                total_sec, streak_sec, top_apps, active_app, self.screentime.get_goal_hours()
            )
        if self._settings_window and self._settings_window.isVisible():
            self._settings_window.update_screentime_display(
                total_sec, streak_sec, top_apps, active_app, self.screentime.get_goal_hours()
            )

    def _on_screentime_break_reminder(self, streak_min: int):
        self.trigger_island("Take a Rest Break", f"You've been active for {streak_min} mins. Rest your eyes!")

    def _on_screentime_goal_reached(self, goal_hours: float):
        self.trigger_island("Screen time limit reached", f"You've reached your {goal_hours:g}-hour daily limit.")

    def trigger_island(self, title: str, text: str):
        preferences = self.config.get("notifications", {})
        if not preferences.get("enabled", True):
            return
        if preferences.get("mute_in_focus", True) and self.pomodoro.is_running and self.pomodoro.state.value == "focus":
            return
        if not preferences.get("preview_text", True):
            text = "Open Poppy for details."
        if self.state == NotchState.EXPANDED or not preferences.get("show_island_on_notify", True):
            self.message_requested.emit(title, text)
            return
        self.lbl_isl_title.setText(title)
        self.lbl_isl_sub.setText(text[:70])
        self.lbl_isl_sub.setToolTip(text)
        for control in (self.island_thumb, self.btn_isl_chat, self.btn_isl_pin, self.btn_isl_shelf):
            control.hide()
        self._transition_to(NotchState.ISLAND)
        self._island_timer.start()

    def _update_clock(self):
        now = datetime.now()
        time_12 = now.strftime("%I:%M:%S %p").lstrip("0")
        time_short = now.strftime("%I:%M %p").lstrip("0")
        date_str = now.strftime("%A, %d %B")
        self.lbl_clock.setText(time_short)
        date_short = now.strftime("%a, %d %b")
        self.tab_home.lbl_big_time.setText(time_12)
        self.tab_home.lbl_date.setText(date_str)

    def _update_system_metrics(self):
        if self._appearance.get("mode") == "System" and is_light_theme() != resolve_light_mode("System"):
            self._apply_live_appearance(self._appearance)
        try:
            cpu = int(psutil.cpu_percent())
            ram = int(psutil.virtual_memory().percent)
            self.tab_home.lbl_cpu.set_val(f"{cpu}%")
            self.tab_home.lbl_ram.set_val(f"{ram}%")

            hw = self.config.get("hardware_hud", {})
            gpu = _get_gpu_utilization() if hw.get("monitor_gpu", True) else None
            if gpu is not None:
                self.tab_home.lbl_gpu.set_val(f"{gpu}%")
                self.tab_home.lbl_gpu.setVisible(True)
            else:
                self.tab_home.lbl_gpu.set_val("N/A")
                self.tab_home.lbl_gpu.setToolTip("GPU usage is unavailable on this device. NVIDIA monitoring uses NVML.")
                self.tab_home.lbl_gpu.setVisible(hw.get("monitor_gpu", True))

            bat = psutil.sensors_battery() if hw.get("monitor_battery", True) else None
            if bat:
                bat_text = f"{int(bat.percent)}%"
                self.tab_home.lbl_bat.setToolTip("Plugged in" if bat.power_plugged else "On battery")
                self.tab_home.lbl_bat.set_val(bat_text)
                self.tab_home.lbl_bat.setVisible(True)
            else:
                self.tab_home.lbl_bat.setVisible(False)
        except Exception:
            pass

        # Periodic background sync for hardware sliders if user is not actively dragging
        self._sync_system_controls()

    def _sync_system_controls(self, force: bool = False):
        """Synchronizes UI volume and brightness sliders with actual Windows hardware levels."""
        home_visible = self.tab_home.isVisible()
        if not force and not (home_visible or self.tab_music.isVisible()):
            return
        try:
            # Volume sync
            if force or (not self.tab_home.slider_vol.isSliderDown() and not self.tab_music.vol_slider.isSliderDown()):
                vol = self.audio_ctrl.get_volume()
                muted = self.audio_ctrl.get_mute()
                self.tab_home.set_volume_display(vol, muted)
                self.tab_music.set_volume_display(vol, muted)

            # Brightness sync
            if (force or home_visible) and not self.tab_home.slider_bright.isSliderDown():
                bright = self.bright_ctrl.get_brightness()
                self.tab_home.set_brightness_display(bright)

            # Mic mute sync
            if force or home_visible:
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
                background: rgba(245, 158, 11, 0.22);
                border: none;
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
        set_widget_style(self.tab_home.btn_act_caffeine, style)
        self.tab_home.btn_act_caffeine.setToolTip(tip)
        if hasattr(self, 'btn_hdr_caffeine') and self.btn_hdr_caffeine:
            set_widget_style(self.btn_hdr_caffeine, style)
            self.btn_hdr_caffeine.setToolTip(tip)

    def _toggle_mic_mute(self):
        new_state = self.audio_ctrl.toggle_mic_mute()
        self._update_mic_button_ui(new_state)

    def _update_mic_button_ui(self, is_muted: bool):
        if is_muted:
            self.tab_home.btn_act_mic.setText(Icons.MIC_MUTE)
            self.tab_home.btn_act_mic.setToolTip("Microphone: MUTED (Click to Unmute)")
            set_widget_style(self.tab_home.btn_act_mic, """
                background: rgba(239, 68, 68, 0.22);
                border: none;
                border-radius: 6px;
                color: #f87171;
                font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets';
                font-size: 11px;
            """)
        else:
            self.tab_home.btn_act_mic.setText(Icons.MIC)
            self.tab_home.btn_act_mic.setToolTip("Microphone: LIVE (Click to Mute)")
            set_widget_style(self.tab_home.btn_act_mic, """
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
            set_widget_style(self.tab_home.btn_act_shield, """
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
            set_widget_style(self.tab_home.btn_act_shield, f"""
                background: rgba(99, 102, 241, 0.25);
                border: none;
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
        self._switch_to_tab_by_name("Home")
        self.tab_home.input_calc.setFocus()
        self.tab_home.input_calc.selectAll()

    def _lock_workstation(self):
        lock_workstation()

    def _show_player_dropdown(self):
        sessions = self.media_manager.get_sessions()
        menu = QMenu(self)
        set_widget_style(menu, """
            QMenu {
                background-color: #181d27;
                border: none;
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
        self.tab_home.btn_player_drop.setText(f"{name} ▾")

    def _show_audio_device_dropdown(self):
        endpoints = AudioEndpointManager.get_output_endpoints()
        menu = QMenu(self)
        set_widget_style(menu, """
            QMenu {
                background-color: #181d27;
                border: none;
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
            QMenu::separator {
                height: 1px;
                background: rgba(255, 255, 255, 0.08);
                margin: 4px 6px;
            }
        """)
        for ep in endpoints:
            name = ep["name"]
            action = menu.addAction(name)
            action.setEnabled(False)

        if not endpoints:
            act = menu.addAction("No active audio endpoints")
            act.setEnabled(False)

        menu.addSeparator()
        act_settings = menu.addAction("Sound Settings...")
        act_settings.triggered.connect(lambda: os.startfile("ms-settings:sound"))

        btn = self.tab_home.btn_audio_drop
        pos = btn.mapToGlobal(QPoint(0, btn.height() + 2))
        menu.exec(pos)

    def _on_audio_endpoint_selected(self, name: str):
        try:
            os.startfile("ms-settings:sound")
        except Exception:
            pass

    def _show_bluetooth_dropdown(self):
        menu = QMenu(self)
        set_widget_style(menu, """
            QMenu {
                background-color: #181d27;
                border: none;
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
            QMenu::separator {
                height: 1px;
                background: rgba(255, 255, 255, 0.08);
                margin: 4px 6px;
            }
        """)
        devices = getattr(self.bt_manager, "devices", [])
        if devices:
            for d in devices:
                is_conn = d.get("connected", False)
                status_icon = "🟢 " if is_conn else "⚪ "
                status_text = "Connected" if is_conn else "Paired"
                act = menu.addAction(f"{status_icon}{d.get('name', 'Device')}  ({status_text})")
                act.triggered.connect(lambda checked=False: os.startfile("ms-settings:bluetooth"))
        else:
            act = menu.addAction("No paired Bluetooth devices detected")
            act.setEnabled(False)

        menu.addSeparator()
        act_bt = menu.addAction("Bluetooth & Devices Settings...")
        act_bt.triggered.connect(lambda: os.startfile("ms-settings:bluetooth"))

        btn = self.tab_home.btn_act_bt
        pos = btn.mapToGlobal(QPoint(0, btn.height() + 2))
        menu.exec(pos)

    def _on_camera_status_changed(self, active: bool):
        if hasattr(self, 'lbl_cam_dot'):
            self.lbl_cam_dot.setVisible(active)

    def _on_mic_status_changed(self, active: bool):
        if hasattr(self, 'lbl_mic_dot'):
            self.lbl_mic_dot.setVisible(active)

    def _on_clipboard_data_changed(self):
        if self._shutting_down:
            return
        if not self.config.get("clipboard", {}).get("enabled", False):
            return
        if not clipboard_allows_history():
            return
        try:
            clip = QApplication.clipboard()
            if clip:
                text = clip.text()
                if text:
                    self.clip_mgr.add_clip(text)
        except Exception:
            pass

    def _toggle_pin(self):
        self._is_pinned = not self._is_pinned
        accent = self._theme["accent"]
        if self._is_pinned:
            set_widget_style(self.btn_hdr_pin, f"""
                background: rgba(110, 155, 255, 0.25);
                border: none;
                border-radius: 6px;
                color: {accent};
                font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets';
                font-size: 11px;
            """)
            self.btn_hdr_pin.setToolTip("Notch PINNED (Will not auto-collapse on desktop click)")
        else:
            set_widget_style(self.btn_hdr_pin, """
                background: transparent;
                border: none;
                border-radius: 6px;
                color: #94a3b8;
                font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets';
                font-size: 11px;
            """)
            self.btn_hdr_pin.setToolTip("Pin Notch (Keep open and disable auto-collapse)")

    def _toggle_screen_shield(self):
        self._is_screen_shielded = not self._is_screen_shielded
        ok = ScreenCaptureShield.set_shield(int(self.winId()), self._is_screen_shielded)
        if self._is_screen_shielded and ok:
            set_widget_style(self.btn_hdr_shield, """
                background: rgba(34, 197, 94, 0.25);
                border: none;
                border-radius: 6px;
                color: #4ade80;
                font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets';
                font-size: 11px;
            """)
            self.btn_hdr_shield.setToolTip("Screen Capture Shield: ACTIVE (Hidden from OBS, Discord, Zoom & Screenshots)")
        else:
            self._is_screen_shielded = False
            set_widget_style(self.btn_hdr_shield, """
                background: transparent;
                border: none;
                border-radius: 6px;
                color: #94a3b8;
                font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets';
                font-size: 11px;
            """)
            self.btn_hdr_shield.setToolTip("Screen Capture Shield: OFF (Click to hide Poppy from screen share)")

    def _toggle_annotation(self):
        if self._annotation_overlay and self._annotation_overlay.isVisible():
            self._annotation_overlay.close()
        else:
            screen = self._get_current_screen_geometry()
            self._hover_peek_timer.stop()
            self._collapse_to_pill()
            self._apply_geometry_for_state(NotchState.COLLAPSED, animate=False)
            self._annotation_overlay = ScreenAnnotationOverlay(parent=self, screen_geometry=screen)
            self._annotation_overlay.closed.connect(self._on_annotation_closed)
            self._annotation_overlay.show()

    def _on_annotation_closed(self):
        self._annotation_overlay = None

    def _pop_out_current_tab(self):
        idx = self.tab_stack.currentIndex()
        view = self.tab_stack.widget(idx)
        existing = getattr(view, "_detached_window", None)
        if existing is not None:
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return
        names = ["Home", "Music", "Calendar", "Clipboard", "Docs", "Desktops", "Timer", "Shelf", "Notes"]
        tab_name = names[idx] if idx < len(names) else f"Tab {idx}"
        from PySide6.QtWidgets import QDialog
        float_win = QDialog(None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        float_win.setWindowTitle(f"Poppy — {tab_name}")
        float_win.resize(800, 540)
        set_widget_style(float_win, f"QDialog {{ background-color: {self._theme['bg']}; color: #f1f5f9; }}")
        f_layout = QVBoxLayout(float_win)
        f_layout.setContentsMargins(12, 12, 12, 12)

        placeholder = QWidget()
        placeholder._detached_window = float_win
        placeholder._detached_view = view
        float_win._poppy_view = view
        placeholder_layout = QVBoxLayout(placeholder)
        placeholder_layout.addWidget(QLabel(f"{tab_name} is open in a floating window."))
        show_button = QPushButton("Show window")
        show_button.clicked.connect(lambda: (float_win.show(), float_win.raise_(), float_win.activateWindow()))
        placeholder_layout.addWidget(show_button)
        self.tab_stack.removeWidget(view)
        self.tab_stack.insertWidget(idx, placeholder)
        self.tab_stack.setCurrentIndex(idx)
        f_layout.addWidget(view)
        float_win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        def restore_view(result):
            selected = self.tab_stack.currentWidget()
            f_layout.removeWidget(view)
            self.tab_stack.removeWidget(placeholder)
            self.tab_stack.insertWidget(idx, view)
            self.tab_stack.setCurrentWidget(view if selected is placeholder else selected)
            placeholder.deleteLater()
            if float_win in self._floating_windows:
                self._floating_windows.remove(float_win)
            if not self._shutting_down:
                self._resize_expanded_panel()
                self._on_lyrics_visibility_changed(self.tab_music.isVisible())

        float_win.finished.connect(restore_view)
        self._fit_floating_window(float_win, center=True)
        float_win.show()
        # removeWidget() hides a stacked page; reparenting into a layout does
        # not clear that explicit hidden state, even when the dialog is shown.
        view.show()
        float_win.raise_()
        float_win.activateWindow()
        self._floating_windows.append(float_win)
        self._resize_expanded_panel()
        self._on_lyrics_visibility_changed(self.tab_music.isVisible())

    def _fit_floating_window(self, dialog, center=False):
        view = dialog._poppy_view
        geometry = self._get_current_screen_geometry()
        monitor = next((screen for screen in QGuiApplication.screens() if screen.geometry() == geometry), None)
        if monitor and dialog.isVisible():
            monitor = QGuiApplication.screenAt(dialog.frameGeometry().center()) or monitor
        available = monitor.availableGeometry() if monitor else geometry
        max_width, max_height = available.width() - 24, available.height() - 64
        if view in (self.tab_home, self.tab_music):
            view.fit_height(max_height - 24)
        minimum = view.minimumSizeHint() + QSize(24, 24)
        dialog.setMinimumSize(min(minimum.width(), max_width), min(minimum.height(), max_height))
        dialog.resize(min(max(dialog.width(), minimum.width()), max_width),
                      min(max(dialog.height(), minimum.height()), max_height))
        if center:
            dialog.move(available.x() + (available.width() - dialog.width()) // 2,
                        available.y() + (available.height() - dialog.height()) // 2)
        else:
            dialog.move(min(max(dialog.x(), available.x() + 8), available.right() - dialog.width() - 7),
                        min(max(dialog.y(), available.y() + 32), available.bottom() - dialog.height() - 31))

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
        phase = getattr(state, "value", str(state))
        self.tab_timer.btn_phase_long.setChecked(phase == "long_break")
        self.tab_timer.btn_phase_short.setChecked(phase == "short_break")
        self.tab_timer.btn_phase_focus.setChecked(phase not in ("short_break", "long_break"))
        btn_text = "Pause" if self.pomodoro.is_running else "Start"
        self.tab_timer.btn_toggle.setText(btn_text)
        cycles = self.pomodoro.completed_cycles
        self.tab_timer.lbl_streak.setText(f"{cycles} session{'s' if cycles != 1 else ''} completed")
        mins = self.pomodoro.completed_focus_seconds // 60
        self.tab_timer.lbl_daily.setText(f"{mins // 60}h {mins % 60}m this run")

    def _on_media_changed(self, data: dict):
        fields = ("index", "source_app", "display_name", "title", "artist", "album", "thumbnail_bytes", "can_seek")
        unchanged = self._current_media and all(self._current_media.get(field) == data.get(field) for field in fields)
        self._current_media = dict(data)
        if unchanged:
            self.tab_music.update_timeline(data.get("position_sec", 0), data.get("duration_sec", 0), data.get("is_playing", False))
            self._on_playback_changed(data.get("is_playing", False))
            return
        title = data.get("title", "No Media Playing")
        artist = data.get("artist", "")
        source = data.get("display_name") or data.get("source_app", "")
        is_playing = data.get("is_playing", False)

        # Fit metadata to actual pixels, leaving transport controls a stable width.
        available = title not in ("No Media Playing", "Unknown Title", "")
        self.lbl_peek_title.setToolTip(title if available else "")
        self.lbl_peek_artist.setToolTip(artist if available else "")
        for button in (self.btn_peek_prev, self.btn_peek_play, self.btn_peek_next):
            button.setEnabled(available)
        self._set_peek_playing(is_playing)
        self._elide_peek_metadata()
        QTimer.singleShot(0, self, self._elide_peek_metadata)

        # Home keeps full metadata for tooltips and elides it to the card width.
        self.tab_home.update_track_info(title, artist)
        if hasattr(self.tab_home, "lbl_music_source"):
            self.tab_home.lbl_music_source.setText(source.upper() if source else "")
        if hasattr(self.tab_home, "btn_player_drop") and source:
            self.tab_home.btn_player_drop.setText(f"{source} ▾")

        # Music Tab update
        self.tab_music.update_media(data)

        # Synchronized & Plain Lyrics (LRCLIB asynchronous fetch)
        if title and title not in ("No Media Playing", "Unknown Title", ""):
            self.tab_music.set_lyrics_loading(title, artist)
            self._on_lyrics_visibility_changed(self.tab_music.btn_lyrics.isChecked())
        else:
            self.lyrics_manager.cancel_request()
            self.tab_music.set_lyrics_not_found(title)

        # Thumbnails
        thumb_bytes = data.get("thumbnail_bytes")
        if thumb_bytes:
            pix = self.tab_music._artwork_pixmap
            if not pix.isNull():
                scaled_peek = self.tab_music._rounded_art(pix, 44, 7)
                self.peek_thumb.setPixmap(scaled_peek)
                self.tab_home.lbl_music_art.setPixmap(self.tab_music._rounded_art(pix, 48, min(8, self.tab_music._art_radius())))
                scaled_coll = pix.scaled(20, 20, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                self.coll_thumb.setPixmap(scaled_coll)
                self.coll_thumb.setText("")
            else:
                self.peek_thumb.setText(Icons.MUSIC)
                self.tab_home.lbl_music_art.setText(Icons.MUSIC)
                self.coll_thumb.setText(Icons.MUSIC)
        else:
            self.peek_thumb.setText(Icons.MUSIC)
            self.tab_home.lbl_music_art.setText(Icons.MUSIC)
            self.coll_thumb.setText(Icons.MUSIC)

        if is_playing and not self.pomodoro.is_running:
            self.discord_rpc.update_media(title, artist, data.get("album", ""), is_playing)

    def _on_playback_changed(self, is_playing: bool):
        self.coll_visualizer.set_playing(is_playing)
        self.tab_home.music_bars.set_playing(is_playing)
        self.tab_music.bars.set_playing(is_playing)
        if hasattr(self.tab_music, "set_playback_state"):
            self.tab_music.set_playback_state(is_playing)

        play_symbol = Icons.PAUSE if is_playing else Icons.PLAY
        self._set_peek_playing(is_playing)
        self.tab_home.btn_ctrl_play.setText(play_symbol)
        self.tab_music.btn_play.setText(play_symbol)

    def _set_peek_playing(self, playing):
        self.btn_peek_play.setText(Icons.PAUSE if playing else Icons.PLAY)
        label = "Pause" if playing else "Play"
        self.btn_peek_play.setAccessibleName(label)
        self.btn_peek_play.setToolTip(label)

    def _elide_peek_metadata(self):
        data = self._current_media
        title = data.get("title", "")
        available = title not in ("No Media Playing", "Unknown Title", "")
        artist = data.get("artist", "") if available else "Play audio in a media app"
        source_width = min(self.btn_peek_cycle.maximumWidth(), self.btn_peek_cycle.sizeHint().width()) + 6 if not self.btn_peek_cycle.isHidden() else 0
        artist_width = min(self.lbl_peek_artist.fontMetrics().horizontalAdvance(artist) + 1,
                           max(1, self.lbl_peek_title.width() - source_width))
        self.lbl_peek_artist.setFixedWidth(artist_width)
        for label, text in ((self.lbl_peek_title, title if available else "Nothing playing"),
                            (self.lbl_peek_artist, artist)):
            label.setText(label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, max(1, label.width())))

    def _on_sessions_updated(self, sessions_list: list, active_index: int):
        signature = (tuple((session["index"], session["display_name"]) for session in sessions_list), active_index)
        if signature == getattr(self, "_session_ui_signature", None):
            self.tab_music._sessions = sessions_list
            return
        self._session_ui_signature = signature
        accent = self._theme["accent"]
        self.tab_home.update_sessions_list(sessions_list, active_index, accent=accent)
        self.tab_music.update_sessions_list(sessions_list, active_index, accent=accent)

        # In Peek mode, if multiple sessions exist, show source switch pill
        if len(sessions_list) > 1 and active_index < len(sessions_list):
            curr_name = sessions_list[active_index]["display_name"]
            self.btn_peek_cycle.setText(self.btn_peek_cycle.fontMetrics().elidedText(f"· {curr_name}", Qt.TextElideMode.ElideRight, 82))
            self.btn_peek_cycle.setVisible(True)
            self.btn_peek_cycle.setToolTip(f"Player {active_index + 1} of {len(sessions_list)}. Click to switch media player.")
        else:
            self.btn_peek_cycle.setVisible(False)
        QTimer.singleShot(0, self, self._elide_peek_metadata)

    def _on_shelf_updated(self):
        self.tab_home.update_shelf_display(self.drop_shelf.staged_items)

    def _on_screenshot_captured(self, file_path: str, qimage: QImage):
        self._last_screenshot_path = file_path
        self.drop_shelf.add_paths([file_path])
        self.tab_home.update_shelf_display(self.drop_shelf.staged_items)

        # Setup Island view
        self.lbl_isl_title.setText("Screenshot staged")
        for control in (self.island_thumb, self.btn_isl_chat, self.btn_isl_pin, self.btn_isl_shelf):
            control.show()
        pix = QPixmap.fromImage(qimage)
        self.island_thumb.set_image(file_path, pix)
        self.lbl_isl_sub.setText(f"{qimage.width()} × {qimage.height()} · Ready to drop or copy")
        self.btn_isl_chat.setText("Copy")
        set_widget_style(self.btn_isl_chat, """
            QPushButton {
                background: rgba(14, 165, 233, 0.2);
                border: none;
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
                set_widget_style(self.btn_isl_chat, """
                    QPushButton {
                        background: rgba(34, 197, 94, 0.28);
                        border: none;
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
        set_widget_style(self.btn_isl_chat, """
            QPushButton {
                background: rgba(14, 165, 233, 0.2);
                border: none;
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
                set_widget_style(self.tab_home.btn_home_shelf_chat, """
                    QPushButton {
                        background: rgba(34, 197, 94, 0.28);
                        border: none;
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
        set_widget_style(self.tab_home.btn_home_shelf_chat, """
            QPushButton {
                background: rgba(14, 165, 233, 0.2);
                border: none;
                border-radius: 5px;
                color: #38bdf8;
                font-size: 9.5px;
                font-weight: 600;
                padding: 2px 7px;
            }
        """)

    def _open_shelf_from_island(self):
        self._island_timer.stop()
        self._transition_to(NotchState.EXPANDED, target_tab="Shelf")

    def _on_island_timeout(self):
        from PySide6.QtGui import QCursor
        if self.geometry().contains(QCursor.pos()):
            self._island_timer.start(1500)
            return
        if self.state == NotchState.ISLAND:
            self._collapse_to_pill()

    def _tear_off_sticky_note(self, text: str, note_id: str = None):
        note = FloatingStickyNote(initial_text=text, note_id=note_id)
        screen = self._get_current_screen_geometry()
        offset = (len(self._floating_notes) % 8) * 28
        x = max(20, self.x() + 40 + offset)
        y = max(40, self.y() + self.height() + 16 + offset)
        x = max(screen.left() + 16, min(x, screen.right() - note.width() - 16))
        y = max(screen.top() + 16, min(y, screen.bottom() - note.height() - 16))
        if note_id is None:
            note.move(x, y)
        note.show()
        note.raise_()
        note.activateWindow()
        note.editor.setFocus()
        self._floating_notes.append(note)
        note.closed.connect(lambda n: self._floating_notes.remove(n) if n in self._floating_notes else None)

    def _open_saved_note(self, note_id: str):
        for note in self._floating_notes:
            if getattr(note, "note_id", None) == note_id:
                note.show()
                note.raise_()
                note.activateWindow()
                return
        self._tear_off_sticky_note("", note_id=note_id)

    def _restore_saved_notes(self):
        if not self._shutting_down:
            for note in FloatingStickyNote.saved_notes():
                if note.get("open", False):
                    self._open_saved_note(note["id"])

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

    def open_settings(self, page_name: str = None):
        """Open the dedicated Poppy Settings application window."""
        # Immediately collapse the notch drawer to sleek pill mode so Settings is completely unobscured
        self._transition_to(NotchState.COLLAPSED)
        self.clearFocus()

        if self._settings_window is None:
            self._settings_window = SettingsWindow(config=self.config)
            self._settings_window.settings_saved.connect(self._on_settings_saved)
            self._settings_window.appearance_live_updated.connect(self._apply_live_appearance)
            self._settings_window.screentime_reset_requested.connect(self.screentime.reset_today)

        # Keep the dialog and Done button inside the usable monitor area.
        screen = self._get_current_screen_geometry()
        monitor = next((item for item in QGuiApplication.screens() if item.geometry() == screen), None)
        available = monitor.availableGeometry() if monitor else screen
        top = max(available.top() + 8, screen.top() + self._top_offset + self._collapsed_h + 12)
        max_w = available.width() - 16
        max_h = max(1, available.bottom() - top - 7)
        self._settings_window.setMinimumSize(min(720, max_w), min(480, max_h))
        w = min(self._settings_window.width(), max_w)
        h = min(self._settings_window.height(), max_h)
        self._settings_window.resize(w, h)
        x = available.x() + (available.width() - w) // 2
        y = max(top, available.y() + (available.height() - h) // 2)
        self._settings_window.move(x, y)

        if page_name and hasattr(self._settings_window, "select_page"):
            self._settings_window.select_page(page_name)

        if self._settings_window.isMinimized():
            self._settings_window.showNormal()
        else:
            self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    def _media_appearance_values(self):
        media = self.config.get("media", {})
        return (media.get("background", "theme"), media.get("show_player_tiles", True),
                media.get("auto_scroll_lyrics", True))

    def _apply_layout_theme(self, name):
        """Apply arrangements and surface density without recreating page content."""
        spec = LAYOUT_THEMES.get(name, LAYOUT_THEMES["Classic"])
        self.tab_home.apply_layout(name, home_order(name, self._appearance.get("home_orders")))
        self.tab_music.apply_layout(name)
        if not self.tab_music._artwork_pixmap.isNull():
            self.tab_home.lbl_music_art.setPixmap(self.tab_music._rounded_art(
                self.tab_music._artwork_pixmap, 48, min(8, self.tab_music._art_radius())))
        self.tab_strip.apply_design()
        for index in range(self.tab_stack.count()):
            stacked = self.tab_stack.widget(index)
            page = getattr(stacked, "_detached_view", stacked)
            if page in (self.tab_home, self.tab_music):
                continue
            page.layout().setContentsMargins(spec["inset"], 8, spec["inset"], 8)
            page.layout().setSpacing(spec["spacing"])
            for card in page.findChildren(CardFrame):
                card.apply_layout(name)
                if card.layout():
                    pad = spec["padding"]
                    card.layout().setContentsMargins(pad, pad, pad, pad)
            page.updateGeometry()

    def _apply_live_appearance(self, app_cfg: dict):
        app_cfg = normalize_appearance(app_cfg)
        previous = self._appearance
        palette_changed = self._theme_name != app_cfg.get("theme", DEFAULT_THEME)
        layout_changed = previous.get("layout", "Classic") != app_cfg.get("layout", "Classic")
        order_changed = home_order(app_cfg["layout"], previous.get("home_orders")) != home_order(app_cfg["layout"], app_cfg.get("home_orders"))
        light_changed = configure_theme(app_cfg)
        media_values = self._media_appearance_values()
        media_changed = media_values != self._applied_media_appearance
        if app_cfg == previous and not light_changed and not media_changed:
            return
        self._appearance = app_cfg
        self._theme_name = app_cfg.get("theme", DEFAULT_THEME)
        self._theme = get_theme(self._theme_name)
        self._style = app_cfg.get("style", "Notch")
        self._collapsed_w = app_cfg.get("collapsed_width", 240)
        self._collapsed_h = app_cfg.get("collapsed_height", 30)
        self._open_w = max(app_cfg.get("open_width", 960), 480)
        self._open_h = max(app_cfg.get("open_height", 560), 360)
        self._corner_radius = app_cfg.get("corner_radius", 22)
        self._top_offset = app_cfg.get("top_offset", 0)
        self._display = app_cfg.get("display", "Primary")

        if palette_changed:
            set_widget_style(QApplication.instance(), get_stylesheet(self._theme_name))
            accent = self._theme["accent"]
            set_widget_style(self.lbl_coll_pomo, f"color: {accent}; font-size: 11px; font-weight: 600; min-width: 44px;")
            self.tab_strip.set_accent(accent)
            self.tab_music.set_accent(accent)
            self.tab_timer.set_accent(accent)
            self.tab_home.slider_vol.set_accent(accent)
            self.tab_home.slider_bright.set_accent(accent)
        if palette_changed or light_changed or media_changed:
            self.tab_music.configure_appearance(self.config.get("media", {}), self._theme)
            self._applied_media_appearance = media_values
        if layout_changed:
            self._apply_layout_theme(app_cfg.get("layout", "Classic"))
        elif order_changed:
            self.tab_home.apply_layout(app_cfg["layout"], home_order(app_cfg["layout"], app_cfg.get("home_orders")))
        if light_changed or layout_changed:
            refresh_theme()
        if palette_changed or layout_changed or light_changed:
            for dialog in self._floating_windows:
                set_widget_style(dialog, f"QDialog {{ background-color: {self._theme['bg']}; color: #f1f5f9; }}")
                self._fit_floating_window(dialog)

        if self.view_collapsed.size() != QSize(self._collapsed_w, self._collapsed_h):
            self.view_collapsed.setFixedSize(self._collapsed_w, self._collapsed_h)
        self._apply_geometry_for_state(self.state, animate=False)
        self.update()

    def _on_settings_saved(self, new_config: dict):
        self.config = new_config or {}
        self._apply_live_appearance(self.config.get("appearance", {}))
        self._rebuild_tabs()

        if hasattr(self, "weather_manager"):
            self.weather_manager.update_config(self.config)

        if hasattr(self, "lyrics_manager"):
            self.lyrics_manager.update_config(self.config)

        pomo = self.config.get("pomodoro", {})
        if pomo:
            self.pomodoro.work_duration = pomo.get("work_duration", 1500)
            self.pomodoro.break_duration = pomo.get("break_duration", 300)
            self.pomodoro.long_break_duration = pomo.get("long_break_duration", 900)
            self.pomodoro.sound_enabled = pomo.get("sound_enabled", True)

        notch_cfg = self.config.get("notch", {})
        if notch_cfg:
            self.anim.setDuration(notch_cfg.get("animation_duration_ms", 200))

        rpc_cfg = self.config.get("discord_rpc", {})
        if rpc_cfg:
            self.discord_rpc.update_config(rpc_cfg)

        if hasattr(self, "screentime"):
            self.screentime.update_config(self.config)
            st_cfg = self.config.get("screentime", {})
            show_pill = st_cfg.get("enabled", True) and st_cfg.get("show_in_main_menu", True)
            if hasattr(self.tab_home, "screentime_widget"):
                self.tab_home.screentime_widget.setVisible(show_pill)

        capture_enabled = self.config.get("capture", {}).get("enabled", False)
        self.screenshot_watcher.enabled = capture_enabled
        if capture_enabled:
            self.screenshot_watcher.start()
        else:
            self.screenshot_watcher.stop()

        if hasattr(self.tab_home, "set_accent"):
            self.tab_home.set_accent(self._theme["accent"])

    # --- Mouse & State Transitions ---
    def enterEvent(self, event):
        self._leave_timer.stop()
        if self.state == NotchState.ISLAND:
            self._island_timer.stop()
        if self.state in (NotchState.PEEK, NotchState.EXPANDED):
            super().enterEvent(event)
            return
        auto_peek = self.config.get("notch", {}).get("auto_hover_peek", True)
        if self.state == NotchState.COLLAPSED and auto_peek:
            self._hover_peek_timer.start(140)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_peek_timer.stop()
        if self._is_pinned and self.state == NotchState.EXPANDED:
            super().leaveEvent(event)
            return
        from PySide6.QtGui import QCursor
        # If cursor is STILL geometrically within the window, ignore child switch events
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
            if self.anim.state() == QPropertyAnimation.State.Running:
                self._hover_peek_timer.start(70)
                return
            self._transition_to(NotchState.PEEK)

    def _on_leave_timeout(self):
        from PySide6.QtGui import QCursor
        if self.state == NotchState.PEEK:
            if QApplication.mouseButtons() != Qt.MouseButton.NoButton or QApplication.activePopupWidget():
                self._leave_timer.start()
                return
            if not self.geometry().contains(QCursor.pos()):
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
                self._transition_to(NotchState.EXPANDED, target_tab="Music" if self.state == NotchState.PEEK else None)
                event.accept()
                return
            elif self.state == NotchState.ISLAND:
                self._open_shelf_from_island()
                event.accept()
                return

        super().mousePressEvent(event)

    def wheelEvent(self, event):
        # NotchX Gesture: Scroll on the closed pill to adjust Windows master volume
        if self.config.get("notch", {}).get("scroll_volume", True):
            if self.state == NotchState.COLLAPSED or (hasattr(self, "view_collapsed") and self.view_collapsed.isVisible()):
                delta = event.angleDelta().y()
                if delta != 0:
                    delta_steps = 2 if delta > 0 else -2
                    cur_vol = self.audio_ctrl.get_volume()
                    new_vol = max(0, min(100, cur_vol + delta_steps))
                    self.audio_ctrl.set_volume(new_vol)
                    self.tab_home.set_volume_display(new_vol, False)
                    self.tab_music.set_volume_display(new_vol, False)
                    event.accept()
                    return
        super().wheelEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            if self.state != NotchState.COLLAPSED:
                self._collapse_to_pill()
                event.accept()
                return
        # Ctrl + 1-9 for Quick Tab Switching
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            key_map = {
                Qt.Key.Key_1: 0,
                Qt.Key.Key_2: 1,
                Qt.Key.Key_3: 2,
                Qt.Key.Key_4: 3,
                Qt.Key.Key_5: 4,
                Qt.Key.Key_6: 5,
                Qt.Key.Key_7: 6,
                Qt.Key.Key_8: 7,
                Qt.Key.Key_9: 8,
            }
            if event.key() in key_map:
                idx = key_map[event.key()]
                if hasattr(self, '_active_tab_names') and idx < len(self._active_tab_names):
                    self._switch_tab(idx)
                    event.accept()
                    return
        super().keyPressEvent(event)

    def _collapse_to_pill(self):
        self._leave_timer.stop()
        self._island_timer.stop()
        self._click_outside_timer.stop()
        self._transition_to(NotchState.COLLAPSED)

    def _start_click_outside_timer(self):
        if self.state == NotchState.EXPANDED:
            self._click_outside_timer.start()

    def _check_click_outside(self):
        if self._is_pinned:
            return
        if self.state != NotchState.EXPANDED:
            self._click_outside_timer.stop()
            return

        try:
            # 0x01 = VK_LBUTTON, 0x02 = VK_RBUTTON
            left_down = bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
            right_down = bool(ctypes.windll.user32.GetAsyncKeyState(0x02) & 0x8000)
        except Exception:
            return

        if not (left_down or right_down):
            return

        cursor_pos = QCursor.pos()
        if self.geometry().contains(cursor_pos):
            return

        # Don't collapse if user is actively dragging a slider
        if (hasattr(self.tab_home, "slider_vol") and self.tab_home.slider_vol.isSliderDown()) or \
           (hasattr(self.tab_home, "slider_bright") and self.tab_home.slider_bright.isSliderDown()) or \
           (hasattr(self.tab_music, "scrubber") and self.tab_music.scrubber.isSliderDown()) or \
           (hasattr(self.tab_music, "vol_slider") and self.tab_music.vol_slider.isSliderDown()):
            return

        # Don't collapse if clicking inside child dialogs or popups
        if self._settings_window and self._settings_window.isVisible() and self._settings_window.geometry().contains(cursor_pos):
            return
        for note in getattr(self, "_sticky_notes", []):
            if note.isVisible() and note.geometry().contains(cursor_pos):
                return
        if QApplication.activePopupWidget():
            return

        self._click_outside_timer.stop()
        self._collapse_to_pill()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.ActivationChange:
            if self._is_pinned:
                super().changeEvent(event)
                return
            if not self.isActiveWindow() and self.state == NotchState.EXPANDED:
                if self._settings_window and self._settings_window.isActiveWindow():
                    pass
                elif any(getattr(note, "isActiveWindow", lambda: False)() for note in getattr(self, "_sticky_notes", [])):
                    pass
                elif QApplication.activePopupWidget():
                    pass
                else:
                    self._click_outside_timer.stop()
                    self._collapse_to_pill()
        super().changeEvent(event)

    def _transition_to(self, new_state: NotchState, target_tab: str = None):
        if self.state == new_state:
            if target_tab:
                self._switch_to_tab_by_name(target_tab, animate=False)
            return

        old_state = self.state
        self._peek_fade.stop()
        self._peek_opacity.setEnabled(False)
        self.state = new_state

        # Capture geometry BEFORE any view visibility changes
        start_rect = self.geometry()
        if self.anim and self.anim.state() == QPropertyAnimation.State.Running:
            self.anim.stop()
            start_rect = self.geometry()

        if new_state == NotchState.COLLAPSED:
            self._target_size = (self._collapsed_w, self._collapsed_h)
            self.view_collapsed.setVisible(True)
            self.view_peek.setVisible(False)
            self.view_island.setVisible(False)
            self.view_expanded.setVisible(False)
            self._click_outside_timer.stop()
        elif new_state == NotchState.PEEK:
            self._target_size = (380, 68)
            self.view_collapsed.setVisible(False)
            self.view_peek.setVisible(True)
            self.view_island.setVisible(False)
            self.view_expanded.setVisible(False)
            self._click_outside_timer.stop()
        elif new_state == NotchState.ISLAND:
            self._target_size = (420, 64)
            self.view_collapsed.setVisible(False)
            self.view_peek.setVisible(False)
            self.view_island.setVisible(True)
            self.view_expanded.setVisible(False)
            self._click_outside_timer.stop()
        elif new_state == NotchState.EXPANDED:
            self._target_size = (self._open_w, self._open_h)
            self.view_collapsed.setVisible(False)
            self.view_peek.setVisible(False)
            self.view_island.setVisible(False)
            self.view_expanded.setVisible(True)
            self._sync_system_controls(force=True)

            # Smart Default Tab auto-selection
            dtab = self.config.get("notch", {}).get("default_tab", "Smart")
            selected_tab = "Home"
            if dtab == "Smart":
                selected_tab = "Home"
            elif hasattr(self, "_tab_name_to_stack_idx") and dtab in self._tab_name_to_stack_idx:
                selected_tab = dtab
            selected_tab = target_tab or selected_tab
            if selected_tab not in self._enabled_tab_names:
                selected_tab = self._active_tab_names[0]
            self._switch_to_tab_by_name(selected_tab, animate=False)

            self.raise_()
            self.activateWindow()
            self._click_outside_timer.stop()
            QTimer.singleShot(220, self._start_click_outside_timer)

        self._apply_geometry_for_state(new_state, animate=True, start_rect=start_rect)
        if new_state == NotchState.PEEK:
            self.view_peek.layout().activate()
            self._elide_peek_metadata()
            duration = min(160, self.config.get("notch", {}).get("animation_duration_ms", 200))
            if duration > 0:
                self._peek_opacity.setEnabled(True)
                self._peek_opacity.setOpacity(0.0)
                self._peek_fade.setDuration(duration)
                self._peek_fade.setStartValue(0.0)
                self._peek_fade.setEndValue(1.0)
                self._peek_fade.start()

    def _get_current_screen_geometry(self) -> QRect:
        """Multi-monitor aware screen lookup using configured display or cursor fallback."""
        target_disp = getattr(self, "_display", "Primary")
        screens = QGuiApplication.screens()
        if target_disp and target_disp != "Primary" and screens:
            for idx, scr in enumerate(screens):
                if target_disp.startswith(f"Display {idx + 1}") or target_disp == scr.name():
                    return scr.geometry()

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
        top_offset = getattr(self, "_top_offset", 0)
        expected_x = screen.x() + (screen.width() - w) // 2
        expected_y = screen.y() + top_offset if self._style == "Notch" else screen.y() + max(8, 8 + top_offset)
        if self.x() != expected_x or self.y() != expected_y:
            self.move(expected_x, expected_y)

    def _apply_geometry_for_state(self, state: NotchState, animate: bool = True, start_rect: QRect = None):
        if state == NotchState.COLLAPSED:
            self._target_size = (self._collapsed_w, self._collapsed_h)
        elif state == NotchState.PEEK:
            self._target_size = (420, 72)
        elif state == NotchState.ISLAND:
            self._target_size = (420, 64)
        elif state == NotchState.EXPANDED:
            page = self.tab_stack.currentWidget()
            screen = self._get_current_screen_geometry()
            max_height = screen.height() - 56 - max(0, self._top_offset)
            layout = self.view_expanded.layout()
            layout.activate()
            margins = layout.contentsMargins()
            chrome_height = margins.top() + margins.bottom() + layout.spacing() * (layout.count() - 1)
            chrome_height += sum(layout.itemAt(i).minimumSize().height()
                                 for i in range(layout.count()) if layout.itemAt(i).widget() is not self.tab_stack)
            if page in (self.tab_home, self.tab_music):
                page.fit_height(max_height - chrome_height)
            w = max(self._open_w, 780, page.minimumSizeHint().width() + 28)
            h = max(self._open_h, 480, page.minimumSizeHint().height() + chrome_height)
            self._target_size = (min(w, screen.width() - 16), min(h, max_height))
            self.view_expanded.setFixedSize(*self._target_size)

        screen = self._get_current_screen_geometry()
        w, h = self._target_size
        top_offset = getattr(self, "_top_offset", 0)
        x = screen.x() + (screen.width() - w) // 2
        y = screen.y() + top_offset if self._style == "Notch" else screen.y() + max(8, 8 + top_offset)
        target_rect = QRect(x, y, w, h)

        if animate:
            self.anim.stop()
            if hasattr(self, "_anim_opacity"):
                self._anim_opacity.stop()

            # Align start_rect mathematically around target_rect's exact center axis
            target_center_x = target_rect.x() + target_rect.width() // 2
            if start_rect is not None:
                sw = max(1, start_rect.width())
                start_rect = QRect(target_center_x - sw // 2, start_rect.y(), sw, start_rect.height())
                self.setGeometry(start_rect)
            else:
                cur_geo = self.geometry()
                sw = max(1, cur_geo.width())
                start_rect = QRect(target_center_x - sw // 2, cur_geo.y(), sw, cur_geo.height())
                self.setGeometry(start_rect)

            # Organic spring physics matching macOS Dynamic Island & NotchX
            if state == NotchState.COLLAPSED:
                duration = 200
                curve = QEasingCurve(QEasingCurve.Type.OutCubic)
            elif state in (NotchState.PEEK, NotchState.ISLAND):
                duration = 240
                curve = QEasingCurve(QEasingCurve.Type.OutCubic)
            else:  # EXPANDED
                duration = 240
                curve = QEasingCurve(QEasingCurve.Type.OutCubic)
                if hasattr(self, "_expanded_opacity"):
                    self._expanded_opacity.setEnabled(True)
                    self._expanded_opacity.setOpacity(0.0)
                    self._anim_opacity.stop()
                    self._anim_opacity.setDuration(170)
                    self._anim_opacity.setStartValue(0.0)
                    self._anim_opacity.setEndValue(1.0)
                    self._anim_opacity.setEasingCurve(curve)
                    # Smoothly fade content into view as the container blooms outward from center
                    QTimer.singleShot(60, self._anim_opacity.start)

            self.anim.setDuration(duration)
            self.anim.setDuration(self.config.get("notch", {}).get("animation_duration_ms", duration))
            self.anim.setEasingCurve(curve)
            # Clear mask during animation to eliminate SetWindowRgn DWM pipeline stalls
            self.clearMask()
            self.anim.setStartValue(start_rect)
            self.anim.setEndValue(target_rect)
            self.anim.start()
        else:
            self.anim.stop()
            if hasattr(self, "_anim_opacity"):
                self._anim_opacity.stop()
            if hasattr(self, "_expanded_opacity"):
                self._expanded_opacity.setOpacity(1.0)
                self._expanded_opacity.setEnabled(False)
            self.setGeometry(target_rect)
            self._recenter_window()
            self._update_clickthrough_mask()

    def _on_animation_finished(self):
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
                self._switch_to_tab_by_name("Shelf")

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
            if paths:
                self.drop_shelf.add_paths(paths)
                self._switch_to_tab_by_name("Shelf")
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
        bg_col = QColor(surface_colors()["root"] if is_light_theme() else self._theme["bg"])
        grad_col = QColor(surface_colors()["root"] if is_light_theme() else self._theme["gradient"])
        if self._appearance.get("layout") in ("Flat", "Paper", "Instrument"):
            if self._appearance.get("layout") == "Paper" and not is_light_theme():
                bg_col = QColor((bg_col.red() * 3 + 44) // 4, (bg_col.green() * 3 + 40) // 4, (bg_col.blue() * 3 + 32) // 4)
            grad_col = bg_col
        gradient = QLinearGradient(0, 0, 0, h)
        gradient.setColorAt(0.0, grad_col)
        gradient.setColorAt(1.0, bg_col)
        painter.setBrush(QBrush(gradient))

        # Quiet hairline rim highlight
        painter.setPen(QPen(QColor(0, 0, 0, 35) if is_light_theme() else QColor(255, 255, 255, 16), 1.0))
        painter.drawPath(path)

    def closeEvent(self, event):
        if self._shutting_down:
            super().closeEvent(event)
            return
        if not self.tab_home.flush_notes() or not self.tab_notes.flush_notes():
            event.ignore()
            return
        for note in list(self._floating_notes):
            if isinstance(note, FloatingStickyNote) and not note.save_note():
                event.ignore()
                return
        self._shutting_down = True
        for timer in self.findChildren(QTimer):
            timer.stop()
        self.screentime.close()
        self.lyrics_manager.close()
        self.media_manager.stop()
        self.discord_rpc.close()
        self.screenshot_watcher.stop()
        self.bt_manager.close()
        for note in list(self._floating_notes):
            note._closing_with_app = True
            note.close()
        for win in list(self._floating_windows):
            try:
                win.close()
            except Exception:
                pass
        if self._annotation_overlay:
            self._annotation_overlay.close()
        if self._settings_window:
            self._settings_window.close()
        super().closeEvent(event)
