"""
Poppy Dynamic Notch Window
Faithfully inspired by NotchX (by Navneet Kaur / Raho Osman) and macOS Dynamic Island.
Features animated notch transitions, deep Windows GSMTC media
integration, Discord RPC, Pomodoro focus tracking, and dedicated settings app.

States:
- Collapsed: Sleek top-bezel pill (Audio visualizer + Tabular Clock + Pomodoro badge)
- Peek: Blooms into Spotify / YouTube Media HUD on mouse hover
- Expanded: Full Productivity Drawer with Tab bar (Home, Music, Timer, Shelf, Notes)
"""

import os
import ctypes
from ctypes import wintypes
import psutil
import atexit
from enum import Enum
from datetime import datetime
from fractions import Fraction

from PySide6.QtCore import (
    Qt, QRect, QRectF, QSize, QPoint, QPointF, Property, QPropertyAnimation, QVariantAnimation, QEasingCurve, QTimer, QEvent, Signal
)
from PySide6.QtGui import (
    QPainter, QColor, QBrush, QPainterPath, QRegion, QPixmap, QImage, QKeyEvent, QLinearGradient, QGuiApplication, QCursor,
    QShortcut, QKeySequence, QIcon, QPen
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QApplication,
    QStackedWidget, QPushButton, QFrame, QGraphicsOpacityEffect, QMenu, QLayout, QSizePolicy, QMessageBox, QDialog, QWidgetAction
)

from poppy.ui.theme import set_widget_style, configure_theme, refresh_theme, surface_colors, is_light_theme, resolve_light_mode, LAYOUT_THEMES, home_order, contrast_ink
from poppy.ui.components import (
    IconButton, TabButton, AudioVisualizerBars, DraggableThumbnail, PillLevel,
    AnimatedTabStrip, AnimatedStackedWidget, CardFrame, ClickableSlider, PlaybackSlider
)
from poppy.ui.icons import Icons, get_fluent_font_family
from poppy.ui.views import (
    HomeTabView, MusicTabView, TimerTabView, ShelfTabView, NotesTabView
)
from poppy.ui.extended_views import (
    CalendarTabView, ClipboardTabView, DocsTabView,
    DesktopsTabView, ScreenAnnotationOverlay, LauncherTabView
)
from poppy.ui.sticky_note import FloatingStickyNote, FloatingStickyImage
from poppy.ui.settings_window import SettingsWindow
from poppy.ui.app_mixer import AppMixerMenu
from poppy.ui.download_activity import DownloadActivityMenu
from poppy.ui.styles import DEFAULT_THEME, get_theme, get_stylesheet, normalize_appearance
from poppy.core.pomodoro import PomodoroManager
from poppy.core.media_manager import MediaManager
from poppy.core.lyrics_manager import LyricsManager
from poppy.core.drop_shelf import DropShelfManager
from poppy.core.download_watcher import DownloadWatcher
from poppy.core.discord_rpc import DiscordRPCManager
from poppy.core.screenshot_watcher import ScreenshotWatcher
from poppy.core.system_controls import SystemAudioController, SystemBrightnessController, system_animations_enabled
from poppy.core.brightness_flyout import BrightnessFlyout
from poppy.core.system_features import (
    PrivacyMonitor, ScreenCaptureShield, BluetoothManager,
    ClipboardHistoryManager, AudioEndpointManager, AppLauncherIndexer, clipboard_allows_history
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
    PEEK_SIZE = (316, 108)
    # Relative to the drawer duration. The second value is the initial speed
    # as a multiple of the average speed over the transition.
    MOTION_PROFILES = {
        NotchState.COLLAPSED: (0.72, 0.8),
        NotchState.PEEK: (0.75, 1.1),
        NotchState.ISLAND: (0.85, 1.2),
        NotchState.EXPANDED: (1.0, 1.4),
    }
    message_requested = Signal(str, str)
    quit_requested = Signal()
    settings_applied = Signal()
    update_check_requested = Signal()

    def __init__(self, config: dict = None):
        super().__init__()
        self.config = config or {}
        self._current_media = {}
        self._has_media = False
        self._brightness_flyout = None
        self._manage_native_levels = False
        self._native_brightness_feedback = False
        self._brightness_level = None
        self._pending_brightness_step = 0
        self._volume_scroll_delta = 0

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
        self.download_watcher = DownloadWatcher(parent=self)
        self.download_watcher.files_ready.connect(self._on_downloads_ready)
        self._island_download_folder = None
        self._download_activity = None
        self._app_mixer = None
        rpc_cfg = self.config.get("discord_rpc", {})
        self.discord_rpc = DiscordRPCManager(config=rpc_cfg, parent=self)
        self.audio_ctrl = SystemAudioController()
        self.bright_ctrl = SystemBrightnessController()
        self.caffeine = CaffeineManager(self)
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
        self._peek_timeline = (0.0, 0.0)
        self._peek_bg = QColor("#242f4a")
        self._compact_art_key = None
        self.setMinimumSize(1, 1)
        self.screentime = ScreenTimeManager(self.config, parent=self)

        # State & Animation
        self.state = NotchState.COLLAPSED
        self._target_size = (self._collapsed_w, self._collapsed_h)
        self._start_corner_radius = 14
        self._start_outline_center = 0.0
        self._transition_frame: QRect | None = None
        self.anim = QPropertyAnimation(self, b"notchGeometry", self)
        self.anim.finished.connect(self._on_animation_finished)

        # Registries
        self._floating_notes = []
        self._settings_window = None
        self._command_palette = None

        # Smooth leave timer (350ms grace period)
        self._leave_timer = QTimer(self)
        self._leave_timer.setSingleShot(True)
        self._leave_timer.setInterval(350)
        self._leave_timer.timeout.connect(self._on_leave_timeout)

        # Native popups and a moving window can suppress the final Leave event.
        self._peek_presence_timer = QTimer(self)
        self._peek_presence_timer.setInterval(120)
        self._peek_presence_timer.timeout.connect(self._check_peek_presence)

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
        self._sys_timer.timeout.connect(lambda: self._update_system_metrics(visible_only=True))

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._update_clock)

        self._init_views()
        self._connect_signals()
        self.caffeine.changed.connect(self._update_caffeine_ui)
        for button in (self.tab_home.btn_act_caffeine, self.btn_hdr_caffeine):
            button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            button.customContextMenuRequested.connect(lambda pos, b=button: self._show_awake_menu(b.mapToGlobal(pos)))
        self._update_caffeine_ui(False)
        self._apply_optional_features()
        self._commands_shortcut = QShortcut(QKeySequence("Ctrl+Shift+Space"), self)
        self._commands_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._commands_shortcut.activated.connect(self.open_commands)
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
        self._theme = get_theme(self._theme_name, app_cfg["layout"])
        self._style = app_cfg.get("style", "Notch")  # "Notch" or "Pill"
        self._collapsed_w = app_cfg.get("collapsed_width", 240)
        self._collapsed_h = app_cfg.get("collapsed_height", 30)
        self._open_w = max(app_cfg["open_width"], 480)
        self._open_h = max(app_cfg["open_height"], 360)
        self._corner_radius = app_cfg.get("corner_radius", 22)
        self._top_offset = app_cfg.get("top_offset", 0)
        self._display = app_cfg.get("display", "Primary")

    def minimumSizeHint(self) -> QSize:
        return QSize(self._collapsed_w, self._collapsed_h)

    def sizeHint(self) -> QSize:
        return QSize(self._target_size[0], self._target_size[1])

    def _init_views(self):
        # =====================================================================
        # 1. Collapsed View: Minimalist Top Pill (pill-v2.png)
        # Symmetrical 3-zone architecture: Left (Media icon) - Center (Time) - Right (Visualizer)
        # =====================================================================
        self._surface_clip = QWidget(self)
        self.view_collapsed = QWidget(self._surface_clip)
        self.view_collapsed.setFixedSize(self._collapsed_w, self._collapsed_h)
        v_coll_layout = QHBoxLayout(self.view_collapsed)
        v_coll_layout.setContentsMargins(20, 0, 20, 0)
        v_coll_layout.setSpacing(0)
        v_coll_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Left zone artwork scales with the configured pill dimensions.
        left_box = QWidget(self)
        l_layout = QHBoxLayout(left_box)
        l_layout.setContentsMargins(0, 0, 0, 0)
        l_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.coll_thumb = QLabel()
        self._size_collapsed_art()
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

        # Right zone: equalizer bars.
        right_box = QWidget(self)
        r_layout = QHBoxLayout(right_box)
        r_layout.setContentsMargins(0, 0, 0, 0)
        r_layout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.coll_visualizer = AudioVisualizerBars(self)
        r_layout.addWidget(self.coll_visualizer)

        v_coll_layout.addWidget(right_box, 1)
        for widget in (self.coll_thumb, self.coll_visualizer):
            widget.hide()

        self._collapsed_contents = (left_box, center_box, right_box)
        self.pill_level = PillLevel(self.view_collapsed)
        self.pill_level.hide()
        self._pill_level_timer = QTimer(self)
        self._pill_level_timer.setSingleShot(True)
        self._pill_level_timer.setInterval(1000)
        self._pill_level_timer.timeout.connect(self._dismiss_pill_level)

        # =====================================================================
        # 2. Peek View (Hover HUD: Spotify / YouTube Media HUD)
        # =====================================================================
        self.view_peek = QWidget(self._surface_clip)
        self.view_peek.setFixedSize(*self.PEEK_SIZE)
        self.view_peek.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        layout = QHBoxLayout(self.view_peek)
        layout.setContentsMargins(21, 7, 21, 7)
        layout.setSpacing(13)
        self.peek_thumb = QLabel(Icons.MUSIC)
        self.peek_thumb.setFixedSize(82, 82)
        self.peek_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.peek_thumb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.peek_thumb.setToolTip("Open Poppy. Right-click for sound options.")
        layout.addWidget(self.peek_thumb, 0, Qt.AlignmentFlag.AlignVCenter)

        player = QVBoxLayout()
        player.setSpacing(1)
        header = QHBoxLayout()
        header.setSpacing(8)
        metadata = QVBoxLayout()
        metadata.setSpacing(0)
        self.lbl_peek_title = QLabel("Nothing playing")
        self.lbl_peek_artist = QLabel()
        for label in (self.lbl_peek_title, self.lbl_peek_artist):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            metadata.addWidget(label)
        header.addLayout(metadata, 1)
        self.peek_visualizer = AudioVisualizerBars(self.view_peek)
        self.peek_visualizer.hide()
        header.addWidget(self.peek_visualizer, 0, Qt.AlignmentFlag.AlignTop)
        player.addLayout(header)

        controls = QHBoxLayout()
        controls.setSpacing(0)
        self.btn_peek_prev = IconButton("", "Previous track", size=28)
        self.btn_peek_play = IconButton("", "Play", size=32)
        self.btn_peek_next = IconButton("", "Next track", size=28)
        for button, callback in (
            (self.btn_peek_prev, self.media_manager.previous_track),
            (self.btn_peek_play, self.media_manager.toggle_play_pause),
            (self.btn_peek_next, self.media_manager.next_track),
        ):
            button.clicked.connect(callback)
            button.setEnabled(False)
            button.setFixedHeight(26)
            controls.addWidget(button, 1, Qt.AlignmentFlag.AlignCenter)
        player.addLayout(controls)

        playback = QHBoxLayout()
        playback.setSpacing(7)
        self.peek_seek = PlaybackSlider(Qt.Orientation.Horizontal, time_ruler=False)
        self.peek_seek.setAccessibleName("Playback position")
        self.peek_seek.setFixedHeight(16)
        self.peek_seek.setEnabled(False)
        self.peek_seek.seek_clicked.connect(self._seek_peek)
        self.peek_seek.seek_cancelled.connect(self._show_peek_timeline)
        self.peek_seek.sliderMoved.connect(self._set_peek_elapsed)
        playback.addWidget(self.peek_seek, 1, Qt.AlignmentFlag.AlignVCenter)
        self._peek_volume_muted = False
        self.btn_peek_volume = IconButton("", "Show volume slider", size=20)
        self.btn_peek_volume.clicked.connect(self._toggle_peek_volume)
        playback.addWidget(self.btn_peek_volume, 0, Qt.AlignmentFlag.AlignVCenter)
        controls.setContentsMargins(0, 0, self.btn_peek_volume.width() + playback.spacing(), 0)
        player.addLayout(playback)
        self.lbl_peek_time = QLabel()
        self.lbl_peek_time.setFixedHeight(13)
        self.lbl_peek_time.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        player.addWidget(self.lbl_peek_time)
        layout.addLayout(player, 1)

        self.peek_volume_menu = QMenu(self)
        self.peek_volume_menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.peek_volume_menu.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
        volume_action = QWidgetAction(self.peek_volume_menu)
        volume = QWidget()
        volume.setFixedWidth(48)
        volume_layout = QVBoxLayout(volume)
        volume_layout.setContentsMargins(5, 6, 5, 6)
        volume_layout.setSpacing(4)
        self.lbl_peek_volume = QLabel("0%")
        self.lbl_peek_volume.setAlignment(Qt.AlignmentFlag.AlignCenter)
        volume_layout.addWidget(self.lbl_peek_volume)
        self.peek_volume = ClickableSlider(Qt.Orientation.Vertical)
        self.peek_volume.setAccessibleName("System volume")
        self.peek_volume.setRange(0, 100)
        self.peek_volume.setFixedSize(30, 144)
        self.peek_volume.actionTriggered.connect(lambda _: self._on_volume_slider_action(self.peek_volume))
        volume_layout.addWidget(self.peek_volume, 0, Qt.AlignmentFlag.AlignHCenter)
        self.btn_peek_app_mixer = QPushButton("Apps")
        self.btn_peek_app_mixer.setToolTip("Open app mixer")
        self.btn_peek_app_mixer.setAccessibleName("Open app mixer")
        self.btn_peek_app_mixer.clicked.connect(lambda: self._open_app_mixer(self.btn_peek_volume))
        volume_layout.addWidget(self.btn_peek_app_mixer)
        volume_action.setDefaultWidget(volume)
        self.peek_volume_menu.addAction(volume_action)
        self._peek_volume_opacity = QGraphicsOpacityEffect(self.peek_volume_menu)
        self._peek_volume_opacity.setEnabled(False)
        self.peek_volume_menu.setGraphicsEffect(self._peek_volume_opacity)
        self._peek_volume_fade = QPropertyAnimation(self._peek_volume_opacity, b"opacity", self)
        self._peek_volume_fade.setDuration(110)
        self._peek_volume_fade.setStartValue(0.35)
        self._peek_volume_fade.setEndValue(1.0)
        self._peek_volume_fade.finished.connect(lambda: self._peek_volume_opacity.setEnabled(False))
        self.peek_volume_menu.aboutToHide.connect(self._finish_peek_volume)

        # Position the full-size child explicitly so it can be clipped equally
        # on both sides while the native window is narrower during the reveal.
        self.view_peek.hide()
        self._peek_opacity = QGraphicsOpacityEffect(self.view_peek)
        self.view_peek.setGraphicsEffect(self._peek_opacity)
        self._peek_opacity.setEnabled(False)
        self._peek_fade = QPropertyAnimation(self._peek_opacity, b"opacity", self)
        self._peek_fade.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._peek_fade.finished.connect(lambda: self._peek_opacity.setEnabled(False))

        # =====================================================================
        # 2b. Island View (Dynamic Island HUD for Screenshot & Staging)
        # =====================================================================
        self.view_island = QWidget(self._surface_clip)
        self.view_island.setFixedSize(420, 64)
        self.view_island.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        v_isl_layout = QHBoxLayout(self.view_island)
        v_isl_layout.setContentsMargins(22, 8, 22, 8)
        v_isl_layout.setSpacing(6)

        # Draggable Thumbnail Preview (44x44, rounded 8px)
        self.island_thumb = DraggableThumbnail(size=44, border_radius=8, parent=self)
        self._thumb_opacity_fx = QGraphicsOpacityEffect(self.island_thumb)
        self._thumb_opacity_fx.setEnabled(False)
        self.island_thumb.setGraphicsEffect(self._thumb_opacity_fx)
        self._thumb_anim = QPropertyAnimation(self._thumb_opacity_fx, b"opacity", self)
        self._thumb_anim.setDuration(240)
        self._thumb_anim.setStartValue(0.0)
        self._thumb_anim.setEndValue(1.0)
        self._thumb_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._thumb_anim.finished.connect(lambda: self._thumb_opacity_fx.setEnabled(False))
        v_isl_layout.addWidget(self.island_thumb, alignment=Qt.AlignmentFlag.AlignVCenter)

        isl_meta = QVBoxLayout()
        isl_meta.setContentsMargins(0, 0, 0, 0)
        isl_meta.setSpacing(2)
        isl_meta.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.lbl_isl_title = QLabel()
        self.lbl_isl_sub = QLabel()
        for label, name in ((self.lbl_isl_title, "islandTitle"), (self.lbl_isl_sub, "islandDetail")):
            label.setObjectName(name)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            isl_meta.addWidget(label)
        set_widget_style(self.view_island, """
            QLabel#islandTitle {
                font-family: 'Segoe UI'; font-size: 14px; font-weight: 600;
                color: #f1f3f5; background: transparent; border: none;
            }
            QLabel#islandDetail {
                font-family: 'Segoe UI'; font-size: 12px; font-weight: 400;
                color: #b0b7bd; background: transparent; border: none;
            }
            QPushButton#islandAction {
                font-family: 'Segoe UI'; font-size: 12px; padding: 4px 8px;
            }
        """)
        v_isl_layout.addLayout(isl_meta, stretch=1)

        # Action Buttons
        self.btn_isl_chat = QPushButton("Copy")
        self.btn_isl_chat.setObjectName("islandAction")
        self.btn_isl_chat.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_isl_chat.setToolTip("Copy screenshot to clipboard")
        self.btn_isl_chat.setMinimumWidth(64)
        self.btn_isl_chat.clicked.connect(self._copy_island_for_chat)
        v_isl_layout.addWidget(self.btn_isl_chat)

        self.btn_isl_pin = QPushButton("Pin")
        self.btn_isl_pin.setObjectName("islandAction")
        self.btn_isl_pin.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_isl_pin.setToolTip("Pin screenshot as a floating sticky note on screen")
        self.btn_isl_pin.clicked.connect(lambda: self._pin_screenshot_to_screen(self._last_screenshot_path))
        v_isl_layout.addWidget(self.btn_isl_pin)

        self.btn_isl_shelf = QPushButton("Shelf")
        self.btn_isl_shelf.setObjectName("islandAction")
        self.btn_isl_shelf.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_isl_shelf.setToolTip("Open temporary file shelf")
        self.btn_isl_shelf.clicked.connect(self._activate_island)
        v_isl_layout.addWidget(self.btn_isl_shelf)

        self.btn_isl_close = IconButton(Icons.CLOSE, "Dismiss notification", size=28, font_size=11, is_fluent=True)
        self.btn_isl_close.clicked.connect(self._collapse_to_pill)
        v_isl_layout.addWidget(self.btn_isl_close, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.view_island.setVisible(False)

        # =====================================================================
        # 3. Expanded View (NotchX Navigation & Full Tabbed Suite)
        # =====================================================================
        self.view_expanded = QWidget(self._surface_clip)
        self.view_expanded.setFixedSize(self._open_w, self._open_h)
        self.view_expanded.setMinimumSize(0, 0)
        self._expanded_opacity = QGraphicsOpacityEffect(self.view_expanded)
        self.view_expanded.setGraphicsEffect(self._expanded_opacity)
        self._expanded_opacity.setOpacity(1.0)
        self._expanded_opacity.setEnabled(False)
        self._anim_opacity = QPropertyAnimation(self._expanded_opacity, b"opacity", self)
        self._anim_opacity.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._anim_opacity.finished.connect(lambda: self._expanded_opacity.setEnabled(False))
        v_exp_layout = QVBoxLayout(self.view_expanded)
        v_exp_layout.setContentsMargins(14, 12, 14, 12)
        v_exp_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        v_exp_layout.setSpacing(8)

        # Header Bar: Tabs on the Left, Clock & Controls Capsule on the Right
        header_bar = QHBoxLayout()
        self._expanded_header = header_bar
        header_bar.setSpacing(6)
        header_bar.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Direct tab navigation with a text-only selection.
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
        self.tab_strip = AnimatedTabStrip([(name, "") for name in self._active_tab_names], parent=self)
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
        self.tab_home.slider_vol.actionTriggered.connect(lambda _: self._on_volume_slider_action(self.tab_home.slider_vol))
        self.tab_home.btn_vol_mute.clicked.connect(self._on_mute_clicked)
        self.tab_home.btn_app_mixer.clicked.connect(lambda: self._open_app_mixer(self.tab_home.btn_app_mixer))
        self.tab_home.slider_bright.valueChanged.connect(self._on_brightness_slider_changed)
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
        self.bright_ctrl.brightness_changed.connect(self._on_brightness_read)
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
        self.tab_music.vol_slider.actionTriggered.connect(lambda _: self._on_volume_slider_action(self.tab_music.vol_slider))
        self.tab_music.btn_vol_music.clicked.connect(self._on_mute_clicked)
        self.tab_music.seek_requested.connect(self.media_manager.seek)
        self.tab_music.sound_settings_requested.connect(lambda: self._show_audio_device_dropdown(self.tab_music.btn_output))
        self.tab_music.layout_changed.connect(self._resize_expanded_panel)
        self.tab_music.btn_lyrics.toggled.connect(self._on_lyrics_visibility_changed)
        self.tab_stack.addWidget(self.tab_music)

        # 2: Calendar Tab
        self.tab_calendar = CalendarTabView(self, accent=self._theme["accent"])
        self.tab_stack.addWidget(self.tab_calendar)

        # 3: Clipboard Tab
        self.tab_clipboard = ClipboardTabView(self.clip_mgr, parent=self,
                                              recording_enabled=self.config.get("clipboard", {}).get("enabled", False))
        self.tab_stack.addWidget(self.tab_clipboard)

        # 4: Docs Tab
        self.tab_docs = DocsTabView(self)
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
        self.tab_timer.countdown.finished.connect(lambda: self.trigger_island("Timer finished", "Your countdown is complete."))
        self.tab_stack.addWidget(self.tab_timer)

        # 7: Shelf Tab
        self.tab_shelf = ShelfTabView(self.drop_shelf, screenshot_watcher=self.screenshot_watcher, parent=self)
        self.tab_shelf.pin_requested.connect(self._pin_screenshot_to_screen)
        self.tab_shelf.btn_downloads.clicked.connect(
            lambda: self._show_download_activity(self.tab_shelf.btn_downloads.mapToGlobal(
                self.tab_shelf.btn_downloads.rect().bottomLeft()))
        )
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
        commands = QPushButton("Commands")
        commands.setToolTip("Search tabs, actions, and installed apps (Ctrl+Shift+Space)")
        set_widget_style(commands, "QPushButton { background: transparent; border: none; color: #a7adab; padding: 4px 7px; } QPushButton:hover { color: #edf1f0; } QPushButton:focus { border: 1px solid #a7adab; }")
        commands.clicked.connect(self.open_commands)
        tools.addWidget(commands)
        tools.addStretch()
        for name, _, _, _ in window_tools:
            tools.addWidget(getattr(self, name))
        v_exp_layout.addLayout(tools)
        self.view_expanded.setVisible(False)

        # Activate initial tab (Home)
        self._switch_tab(0)
        self.tab_home.slider_vol.set_accent(self._theme["accent"])
        self.tab_home.slider_bright.set_accent(self._theme["accent"])
        self._apply_layout_theme(self._appearance.get("layout", "Classic"))
        refresh_theme()
        self._refresh_peek_surface()

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
        if self.state != NotchState.EXPANDED:
            return
        if self.anim.state() != QPropertyAnimation.State.Running:
            self._apply_geometry_for_state(self.state, animate=False)
            return
        target = self._geometry_for_state(self.state)
        if target != self.anim.endValue():
            remaining = self.anim.duration() - self.anim.currentTime()
            self._animate_geometry(target, remaining)

    def _on_lyrics_visibility_changed(self, visible):
        data = self._current_media
        title = data.get("title", "")
        detached = self.tab_music.window() is not self
        showing = self.tab_music.isVisible() and self.tab_music.btn_lyrics.isChecked()
        if showing and (visible or detached) and title not in ("", "No Media Playing", "Unknown Title"):
            track = (title, data.get("artist", ""), data.get("album", ""), data.get("duration_sec", 0))
            self.tab_music.set_lyrics_loading(*track)
            self.lyrics_manager.request_lyrics(*track)
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
        self.media_manager.timeline_changed.connect(self._on_media_timeline)

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
        self.tab_home.customize_requested.connect(lambda: self.open_settings("Appearance"))
        self._apply_home_sections()

    def _apply_home_sections(self):
        hidden = self.config.get("appearance", {}).get("hidden_home_sections", [])
        hidden = [key for key in hidden if isinstance(key, str)] if isinstance(hidden, list) else []
        st_cfg = self.config.get("screentime", {})
        show_screen_time = st_cfg.get("enabled", True) and st_cfg.get("show_in_main_menu", True)
        if show_screen_time:
            self.tab_home.screentime_widget.update_stats(
                self.screentime.get_today_seconds(), self.screentime.get_top_apps(5),
                st_cfg.get("track_apps", True),
            )
        self.tab_home.set_sections(hidden, show_screen_time)

    def _on_screentime_stats_updated(self, total_sec: int, streak_sec: int, top_apps: list, active_app: str):
        st_cfg = self.config.get("screentime", {})
        panel = self.tab_home.screentime_widget
        if not panel.isHidden() and panel.update_stats(total_sec, top_apps, st_cfg.get("track_apps", True)):
            self._resize_expanded_panel()
        if self._settings_window and self._settings_window.isVisible():
            self._settings_window.update_screentime_display(
                total_sec, streak_sec, top_apps, active_app, self.screentime.get_goal_hours()
            )

    def _on_screentime_break_reminder(self, streak_min: int):
        unit = "minute" if streak_min == 1 else "minutes"
        self.trigger_island("Time for a break", f"You've been active for {streak_min} {unit}.")

    def _on_screentime_goal_reached(self, goal_hours: float):
        unit = "hour" if goal_hours == 1 else "hours"
        self.trigger_island("Screen time goal reached", f"You've used {goal_hours:g} {unit} today.")

    def _alerts_allowed(self):
        preferences = self.config.get("notifications", {})
        quiet = preferences.get("mute_in_focus", True) and self.pomodoro.is_running and self.pomodoro.state.value == "focus"
        return preferences.get("enabled", True) and not quiet

    def _present_island(self, duration=4500):
        if self.config.get("notifications", {}).get("sound", True):
            QApplication.beep()
        opening = self.state != NotchState.ISLAND
        self._transition_to(NotchState.ISLAND)
        if opening:
            self.view_island.setFocus(Qt.FocusReason.OtherFocusReason)
        self.view_island.layout().activate()
        for label in (self.lbl_isl_title, self.lbl_isl_sub):
            text = label.text()
            label.setAccessibleName(text)
            fitted = label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, label.contentsRect().width())
            if fitted != text:
                if not label.toolTip():
                    label.setToolTip(text)
                label.setText(fitted)
        self._island_timer.start(duration)

    def trigger_island(self, title: str, text: str, *, download_folder=None):
        preferences = self.config.get("notifications", {})
        if not self._alerts_allowed():
            return
        if not preferences.get("preview_text", True):
            text = "Open Poppy for details."
        if self.state == NotchState.EXPANDED or not preferences.get("show_island_on_notify", True):
            self.message_requested.emit(title, text)
            return
        self.lbl_isl_title.setText(title)
        self.lbl_isl_title.setToolTip("")
        self.lbl_isl_sub.setText(text)
        self.lbl_isl_sub.setToolTip("")
        self._island_download_folder = download_folder
        for control in (self.island_thumb, self.btn_isl_chat, self.btn_isl_pin, self.btn_isl_shelf):
            control.hide()
        if download_folder is not None:
            self.btn_isl_shelf.setText("Open folder")
            self.btn_isl_shelf.setToolTip("Open the watched download folder")
            self.btn_isl_shelf.show()
        self._thumb_anim.stop()
        self._thumb_opacity_fx.setEnabled(False)
        self._present_island()

    def _on_downloads_ready(self, paths):
        if len(paths) == 1:
            self.trigger_island("Download ready", paths[0].name, download_folder=paths[0].parent)
        elif paths:
            self.trigger_island("Downloads ready", f"{len(paths)} new files", download_folder=paths[0].parent)

    def _open_download_folder(self, folder=None):
        folder = folder or self.download_watcher.folder
        try:
            if folder is not None and folder.is_dir():
                os.startfile(folder)
        except OSError:
            self.message_requested.emit("Downloads", "Windows could not open the download folder.")

    def _show_download_activity(self, position):
        if self.download_watcher.folder is None:
            return
        if self._download_activity is None:
            self._download_activity = DownloadActivityMenu(self.download_watcher, self._open_download_folder, self)
        self._download_activity.popup(position)

    def _update_clock(self):
        now = datetime.now()
        time_12 = now.strftime("%I:%M:%S %p").lstrip("0")
        time_short = now.strftime("%I:%M %p").lstrip("0")
        date_str = now.strftime("%A, %d %B")
        self.lbl_clock.setText(time_short)
        self.tab_home.lbl_big_time.setText(time_short if self._appearance.get("layout") == "Classic" else time_12)
        self.tab_home.lbl_date.setText(date_str)

    def _update_system_metrics(self, *, visible_only=False):
        if self._appearance.get("mode") == "System" and is_light_theme() != resolve_light_mode("System"):
            self._apply_live_appearance(self._appearance)
        self._sync_system_controls()
        if self._brightness_flyout:
            self._brightness_flyout.refresh_volume()
        if visible_only and not self.tab_home.card_clock.isVisible():
            return
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

    def _sync_system_controls(self, force: bool = False):
        """Synchronizes UI volume and brightness sliders with actual Windows hardware levels."""
        home_visible = self.tab_home.isVisible()
        if not force and not (home_visible or self.tab_music.isVisible() or self.view_peek.isVisible()):
            return
        try:
            # Volume sync
            if not any(slider.isSliderDown() for slider in
                       (self.tab_home.slider_vol, self.tab_music.vol_slider, self.peek_volume)):
                volume = self.audio_ctrl.read_volume()
                if volume is not None:
                    self._show_volume(*volume)

            # Brightness sync
            if (force or home_visible) and not self.tab_home.slider_bright.isSliderDown():
                self.bright_ctrl.request_brightness()

            # Mic mute sync
            if force or home_visible:
                mic_muted = self.audio_ctrl.get_mic_mute()
                self._update_mic_button_ui(mic_muted)
        except Exception:
            pass

    def _on_volume_slider_action(self, slider):
        value = slider.sliderPosition()
        if slider.isVisible() and slider.isEnabled() and value != slider.value():
            self._on_volume_slider_changed(value, source=slider)

    def _on_volume_slider_changed(self, value: int, *, source=None):
        self.audio_ctrl.set_volume(value)
        muted = self.audio_ctrl.get_mute()
        if muted and value > 0:
            self.audio_ctrl.set_mute(False)
            muted = False
        self._show_volume(value, muted, source=source)
        return muted

    def _on_mute_clicked(self):
        new_muted = self.audio_ctrl.toggle_mute()
        vol = self.audio_ctrl.get_volume()
        if vol is None:
            return
        self._show_volume(vol, new_muted)
        self._show_pill_level("Volume", Icons.MUTE if new_muted else Icons.VOLUME,
                              vol if new_muted else 0, vol, muted=new_muted)

    def _step_volume(self, step):
        previous = self.audio_ctrl.get_volume()
        if previous is None:
            return
        was_muted = self.audio_ctrl.get_mute()
        value = max(0, min(100, previous + step))
        muted = self._on_volume_slider_changed(value) if value != previous or was_muted else False
        icon = Icons.MUTE if muted or value == 0 else Icons.VOLUME
        self._show_pill_level("Volume", icon, 0 if was_muted else previous, value, muted=muted)

    def start_system_level_controls(self):
        self._manage_native_levels = True
        if not self.config.get("notch", {}).get("pill_levels", True):
            return
        if self._brightness_flyout is None:
            self._brightness_flyout = BrightnessFlyout(
                self._can_show_pill_level, self._show_native_brightness,
                read_volume=self.audio_ctrl.read_volume, show_volume=self._show_native_volume,
            )
            self._brightness_flyout.start(wintypes.HWND(int(self.winId())))

    def _stop_system_level_controls(self):
        if self._brightness_flyout:
            self._brightness_flyout.close()
            self._brightness_flyout = None

    def nativeEvent(self, event_type, message):
        if event_type == b"windows_generic_MSG" and self._brightness_flyout:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x218 and msg.wParam == 0x8013:  # WM_POWERBROADCAST
                if self._brightness_flyout.power_setting_changed(msg.lParam):
                    return True, 1
        return super().nativeEvent(event_type, message)

    def _can_show_pill_level(self):
        if not self.config.get("notch", {}).get("pill_levels", True) or not self.isVisible():
            return False
        return self.state == NotchState.COLLAPSED or (
            self.state == NotchState.PEEK and QApplication.activePopupWidget() is None
        )

    def _show_native_brightness(self, previous, value):
        self._native_brightness_feedback = True
        self._brightness_level = value
        self._show_pill_level("Brightness", Icons.BRIGHTNESS, previous, value)

    def _show_native_volume(self, previous, value):
        old_volume, old_mute = previous
        volume, muted = value
        self._show_volume(volume, muted)
        icon = Icons.MUTE if muted or volume == 0 else Icons.VOLUME
        self._show_pill_level("Volume", icon, 0 if old_mute else old_volume, volume, muted=muted)

    def _sync_brightness_flyout(self):
        if self._brightness_flyout:
            self._brightness_flyout.sync()

    def _show_pill_level(self, name, icon, previous, value, *, muted=False):
        if not self._can_show_pill_level():
            return
        if self.state == NotchState.PEEK:
            self._transition_to(NotchState.COLLAPSED)
        self._hover_peek_timer.stop()
        already_visible = self.pill_level.isVisible()
        duration = min(120, self._transition_duration())
        self.pill_level.show_level(name, icon, previous, value, duration, muted=muted)
        if not already_visible:
            self._update_pill_level_ink()
            for widget in self._collapsed_contents:
                widget.hide()
            self.pill_level.setGeometry(self.view_collapsed.rect())
            self.pill_level.show()
        self._pill_level_timer.start()

    def _update_pill_level_ink(self):
        color = surface_colors()["root"] if is_light_theme() else self._theme["bg"]
        self.pill_level.set_ink(contrast_ink(QColor(color)))

    def _dismiss_pill_level(self):
        self._native_brightness_feedback = False
        self.pill_level.hide()
        for widget in self._collapsed_contents:
            widget.show()
        if self.state == NotchState.COLLAPSED and self._displayed_geometry().contains(QCursor.pos()):
            self._hover_peek_timer.start(140)

    def _show_volume(self, volume, muted, *, source=None):
        self.tab_home.set_volume_display(volume, muted, sync_slider=source is not self.tab_home.slider_vol)
        self.tab_music.set_volume_display(volume, muted, sync_slider=source is not self.tab_music.vol_slider)
        self.coll_visualizer.set_muted(muted or volume == 0)
        self.peek_visualizer.set_muted(muted or volume == 0)
        if source is not self.peek_volume and not self.peek_volume.isSliderDown():
            self.peek_volume.blockSignals(True)
            self.peek_volume.setValue(volume)
            self.peek_volume.blockSignals(False)
        self.lbl_peek_volume.setText(f"{volume}%")
        if self._peek_volume_muted != muted:
            self._peek_volume_muted = muted
            self.btn_peek_volume.setIcon(self._peek_icons["Muted" if muted else "Volume"])
            self.btn_peek_volume.setAccessibleDescription("Muted" if muted else "")

    def _toggle_peek_volume(self):
        menu = self.peek_volume_menu
        if menu.isVisible():
            menu.hide()
            return
        self._sync_system_controls()
        button = self.btn_peek_volume
        anchor = button.mapToGlobal(button.rect().center())
        screen = QGuiApplication.screenAt(anchor)
        bounds = screen.availableGeometry() if screen else self._get_current_screen_geometry()
        y = self._displayed_geometry().bottom() + 5
        chrome = menu.sizeHint().height() - self.peek_volume.height()
        track_height = max(30, min(144, bounds.bottom() + 1 - y - chrome))
        self.peek_volume.setFixedHeight(track_height)
        menu.setFixedHeight(chrome + track_height)
        size = menu.sizeHint()
        x = max(bounds.left(), min(anchor.x() - size.width() // 2, bounds.right() - size.width() + 1))
        y = max(bounds.top(), min(y, bounds.bottom() - menu.height() + 1))
        animate = system_animations_enabled()
        if animate:
            self._peek_volume_opacity.setOpacity(0.35)
        self._peek_volume_opacity.setEnabled(animate)
        menu.popup(QPoint(x, y))
        self._sync_brightness_flyout()
        self.peek_volume.setFocus(Qt.FocusReason.PopupFocusReason)
        if animate:
            self._peek_volume_fade.start()

    def _finish_peek_volume(self):
        self._peek_volume_fade.stop()
        self._peek_volume_opacity.setEnabled(False)
        self.peek_volume_menu.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
        if self._brightness_flyout:
            QTimer.singleShot(0, self, self._sync_brightness_flyout)

    def _open_app_mixer(self, anchor):
        if not self.config.get("mixer", {}).get("enabled", True):
            return
        self.peek_volume_menu.hide()
        if self._app_mixer is None:
            self._app_mixer = AppMixerMenu(self)
            self._app_mixer.aboutToHide.connect(lambda: QTimer.singleShot(0, self, self._sync_brightness_flyout))
        menu = self._app_mixer
        menu.prepare()
        center = anchor.mapToGlobal(anchor.rect().bottomLeft()) + QPoint(anchor.width() // 2, 5)
        menu.popup(center - QPoint(menu.sizeHint().width() // 2, 0))
        self._sync_brightness_flyout()

    def _on_brightness_slider_changed(self, value: int):
        self._brightness_level = value
        self.bright_ctrl.set_brightness(value)
        self.tab_home.set_brightness_display(value)

    def _step_brightness(self, step):
        if (self._brightness_level is not None and self.pill_level.isVisible()
                and self.pill_level.accessibleName() == "Brightness"):
            self._apply_brightness_step(self._brightness_level, step)
        else:
            self._pending_brightness_step += step
            self.bright_ctrl.request_brightness()

    def _apply_brightness_step(self, previous, step):
        self._native_brightness_feedback = False
        value = max(0, min(100, previous + step))
        if value != previous:
            self._on_brightness_slider_changed(value)
        self._show_pill_level("Brightness", Icons.BRIGHTNESS, previous, value)

    def _on_brightness_read(self, value):
        if self._native_brightness_feedback and not self._pending_brightness_step:
            return  # A background WMI read can arrive after a newer hardware level.
        previous = self._brightness_level
        self._brightness_level = value
        step, self._pending_brightness_step = self._pending_brightness_step, 0
        slider = self.tab_home.slider_bright
        slider.setEnabled(value is not None)
        slider.setToolTip("Brightness" if value is not None else "Brightness control is unavailable on this display.")
        if value is not None and not slider.isSliderDown():
            self.tab_home.set_brightness_display(value)
            if step:
                self._apply_brightness_step(value, step)
            elif (value != previous and self.pill_level.isVisible()
                    and self.pill_level.accessibleName() == "Brightness"):
                self._show_pill_level("Brightness", Icons.BRIGHTNESS, previous, value)

    def _on_weather_updated(self, data: dict):
        self.tab_home.update_weather(data)

    def _toggle_caffeine(self):
        if self.caffeine.is_active:
            self._set_awake(False)
        else:
            self._set_awake(True)

    def _set_awake(self, enabled, minutes=None):
        success = self.caffeine.start(minutes) if enabled else self.caffeine.stop()
        if not success:
            self._update_caffeine_ui(self.caffeine.is_active)
            self.message_requested.emit("Keep awake", "Windows could not change the power request.")

    def _show_awake_menu(self, position):
        menu = QMenu(self)
        for minutes in (15, 30, 60, 120):
            menu.addAction(f"Keep awake for {minutes} minutes",
                           lambda checked=False, duration=minutes: self._set_awake(True, duration))
        menu.addAction("Keep awake until turned off", lambda: self._set_awake(True))
        if self.caffeine.is_active:
            menu.addAction("Turn off", lambda: self._set_awake(False))
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(position)

    def _update_caffeine_ui(self, is_on: bool):
        if is_on:
            duration = self.caffeine.minutes
            tip = f"Keep awake for {duration} minutes. Click to stop." if duration else "Keeping the PC awake. Click to stop."
            style = """
                background: rgba(245, 158, 11, 0.22);
                border: none;
                border-radius: 6px;
                color: #fbbf24;
                font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets';
                font-size: 11px;
            """
        else:
            tip = "Click to keep the PC awake. Right-click for timed options."
            style = """
                background: transparent;
                border: none;
                border-radius: 6px;
                color: #94a3b8;
                font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets';
                font-size: 11px;
            """
        self.tab_home.btn_act_caffeine.setChecked(is_on)
        self.tab_home.btn_act_caffeine.setToolTip(tip)
        if hasattr(self, 'btn_hdr_caffeine') and self.btn_hdr_caffeine:
            set_widget_style(self.btn_hdr_caffeine, style)
            self.btn_hdr_caffeine.setToolTip(tip)

    def _toggle_mic_mute(self):
        new_state = self.audio_ctrl.toggle_mic_mute()
        self._update_mic_button_ui(new_state)

    def _update_mic_button_ui(self, is_muted: bool):
        button = self.tab_home.btn_act_mic
        button.setChecked(is_muted)
        button.setToolTip("Microphone muted. Click to unmute." if is_muted else "Mute microphone")

    def _toggle_focus_shield(self):
        if self.pomodoro.is_running:
            self.pomodoro.pause()
        else:
            self.pomodoro.start()
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

    def open_commands(self):
        if self._command_palette is not None:
            self._command_palette.raise_()
            self._command_palette.activateWindow()
            return
        dialog = QDialog(self, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        dialog.setWindowTitle("Poppy commands")
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.resize(480, 360)
        actions = [
            ("Settings", self.open_settings), ("Start or pause focus timer", self.pomodoro.toggle),
            ("New floating note", lambda: self._tear_off_sticky_note("")),
            ("Open calculator", self._trigger_quick_search),
            ("Take a screen snip", self._trigger_screen_snip),
            ("Pick a screen color", self._trigger_color_eyedropper),
            ("Toggle keep awake", self._toggle_caffeine),
            ("Windows sound settings", lambda: os.startfile("ms-settings:sound")),
            ("Windows Bluetooth settings", lambda: os.startfile("ms-settings:bluetooth")),
        ]
        for name in self._active_tab_names:
            actions.append((f"Open {name}", lambda tab=name: self._transition_to(NotchState.EXPANDED, target_tab=tab)))
        view = LauncherTabView(AppLauncherIndexer, commands=actions)
        QVBoxLayout(dialog).addWidget(view)
        view.launched.connect(dialog.accept)
        dialog.finished.connect(lambda _: setattr(self, "_command_palette", None))
        self._command_palette = dialog
        dialog.show()
        dialog.activateWindow()

    def contextMenuEvent(self, event):
        position = event.globalPos()
        menu = QMenu(self)
        if self.state == NotchState.PEEK:
            menu.addAction("Toggle mute", self._on_mute_clicked)
            if self.config.get("mixer", {}).get("enabled", True):
                menu.addAction("App mixer", lambda: self._open_app_mixer(self.btn_peek_volume))
            if len(self.media_manager.get_sessions()) > 1:
                self._add_media_session_actions(menu.addMenu("Media player"))
            outputs = menu.addMenu("Sound output")
            outputs.aboutToShow.connect(lambda: self._add_audio_endpoint_actions(outputs))
            menu.addSeparator()
        menu.addAction("Open commands", self.open_commands)
        if self.download_watcher.folder is not None:
            menu.addAction("Download activity", lambda: self._show_download_activity(position))
            menu.addAction("Open download folder", self._open_download_folder)
        menu.addAction("Keep awake options", lambda: self._show_awake_menu(position))
        menu.addAction("Settings", self.open_settings)
        menu.addSeparator()
        menu.addAction("Exit Poppy", self.quit_requested.emit)
        menu.aboutToHide.connect(menu.deleteLater)
        if self.state == NotchState.PEEK and self._brightness_flyout:
            menu.aboutToHide.connect(lambda: QTimer.singleShot(0, self, self._sync_brightness_flyout))
        menu.popup(position)
        self._sync_brightness_flyout()
        event.accept()

    def _lock_workstation(self):
        lock_workstation()

    def _show_player_dropdown(self):
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
        self._add_media_session_actions(menu)
        btn = self.tab_home.btn_player_drop
        pos = btn.mapToGlobal(QPoint(0, btn.height() + 2))
        try:
            menu.exec(pos)
        finally:
            menu.deleteLater()

    def _add_media_session_actions(self, menu):
        sessions = self.media_manager.get_sessions()
        active_idx = self.media_manager.get_active_index()
        for s in sessions:
            idx = s["index"]
            name = s["display_name"]
            action = menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(idx == active_idx)
            action.triggered.connect(lambda checked=False, i=idx: self.media_manager.select_session(i))

        if not sessions:
            act = menu.addAction("No active media sessions")
            act.setEnabled(False)

    def _show_audio_device_dropdown(self, anchor=None):
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
        self._add_audio_endpoint_actions(menu)
        btn = anchor or self.tab_home.btn_audio_drop
        pos = btn.mapToGlobal(QPoint(0, btn.height() + 2))
        try:
            menu.exec(pos)
        finally:
            menu.deleteLater()

    def _add_audio_endpoint_actions(self, menu):
        menu.clear()
        endpoints = AudioEndpointManager.get_output_endpoints()
        for ep in endpoints:
            name = ep["name"]
            action = menu.addAction(name)
            action.setEnabled(bool(ep.get("id")))
            action.setCheckable(True)
            action.setChecked(ep.get("default", False))
            action.triggered.connect(lambda checked=False, device=ep: self._on_audio_endpoint_selected(device))

        if not endpoints:
            act = menu.addAction("No active audio endpoints")
            act.setEnabled(False)

        menu.addSeparator()
        act_settings = menu.addAction("Sound Settings...")
        act_settings.triggered.connect(lambda: os.startfile("ms-settings:sound"))

    def _on_audio_endpoint_selected(self, device: dict):
        try:
            AudioEndpointManager.set_default_output(device["id"])
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Could not switch sound output", f"{error}\nChoose an output in Windows Sound Settings.")
            return
        self.tab_home.btn_audio_drop.setToolTip(f"Sound output: {device['name']}")
        self.tab_music.btn_output.setToolTip(f"Sound output: {device['name']}")
        self._sync_system_controls(force=True)

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
        enabled = not self._is_screen_shielded
        if not ScreenCaptureShield.set_shield(int(self.winId()), enabled):
            self.message_requested.emit("Screen Capture Shield", "Windows could not change capture protection.")
            return
        self._is_screen_shielded = enabled
        if enabled:
            set_widget_style(self.btn_hdr_shield, """
                background: rgba(34, 197, 94, 0.25);
                border: none;
                border-radius: 6px;
                color: #4ade80;
                font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets';
                font-size: 11px;
            """)
            self.btn_hdr_shield.setToolTip("Capture protection is on for the Poppy drawer and pill.")
        else:
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
        self.tab_home.btn_act_shield.setChecked(self.pomodoro.is_running)
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
        track_fields = ("index", "source_app", "title", "artist", "album")
        if self.peek_seek.isSliderDown() and (
            not data.get("can_seek") or any(self._current_media.get(key) != data.get(key) for key in track_fields)
        ):
            self.peek_seek.cancel_drag()
        self._current_media = dict(data)
        if unchanged:
            self._on_media_timeline(data.get("position_sec", 0), data.get("duration_sec", 0), data.get("is_playing", False))
            self._on_playback_changed(data.get("is_playing", False))
            return
        title = data.get("title", "No Media Playing")
        artist = data.get("artist", "")
        is_playing = data.get("is_playing", False)

        # Fit metadata to actual pixels, leaving transport controls a stable width.
        available = title not in ("No Media Playing", "Unknown Title", "")
        self._has_media = available
        for widget in (self.coll_thumb, self.coll_visualizer):
            widget.setVisible(available)
        self.peek_visualizer.setVisible(available)
        self.lbl_peek_title.setToolTip(title if available else "")
        self.lbl_peek_artist.setToolTip(artist if available else "")
        for button in (self.btn_peek_prev, self.btn_peek_play, self.btn_peek_next):
            button.setEnabled(available)
        self._set_peek_playing(is_playing)
        self._elide_peek_metadata()
        QTimer.singleShot(0, self, self._elide_peek_metadata)

        # Home keeps full metadata for tooltips and elides it to the card width.
        self.tab_home.update_track_info(title, artist)

        # Music Tab update
        self.tab_music.update_media(data)
        self._peek_timeline = (data.get("position_sec", 0), data.get("duration_sec", 0))
        if self.state == NotchState.PEEK:
            self._show_peek_timeline()

        # Synchronized & Plain Lyrics (LRCLIB asynchronous fetch)
        if title and title not in ("No Media Playing", "Unknown Title", ""):
            self.tab_music.set_lyrics_loading(title, artist, data.get("album", ""), data.get("duration_sec", 0))
            self._on_lyrics_visibility_changed(self.tab_music.btn_lyrics.isChecked())
        else:
            self.lyrics_manager.cancel_request()
            self.tab_music.set_lyrics_not_found(title)

        artwork = self.tab_music._artwork_pixmap
        if artwork.isNull():
            self.peek_thumb.setText(Icons.MUSIC)
            self.tab_home.lbl_music_art.setText(Icons.MUSIC)
        else:
            self.peek_thumb.setPixmap(self.tab_music._rounded_art(artwork, self.peek_thumb.width(), 6))
            self.tab_home.lbl_music_art.setPixmap(self.tab_music._rounded_art(
                artwork, self.tab_home.lbl_music_art.width(), min(6, self.tab_music._art_radius())))
        self._refresh_collapsed_art()
        self._refresh_peek_surface()

        if is_playing and not self.pomodoro.is_running:
            self.discord_rpc.update_media(title, artist, data.get("album", ""), is_playing)

    def _on_playback_changed(self, is_playing: bool):
        self.coll_visualizer.set_playing(is_playing)
        if hasattr(self.tab_music, "set_playback_state"):
            self.tab_music.set_playback_state(is_playing)

        play_symbol = Icons.PAUSE if is_playing else Icons.PLAY
        self._set_peek_playing(is_playing)
        self.tab_home.btn_ctrl_play.setText(play_symbol)
        self.tab_home.btn_ctrl_play.setAccessibleName("Pause" if is_playing else "Play")
        self.tab_home.btn_ctrl_play.setToolTip("Pause" if is_playing else "Play")

    def _set_peek_playing(self, playing):
        playing = playing and self._has_media
        self.peek_visualizer.set_playing(playing)
        label = "Pause" if playing else "Play"
        self.btn_peek_play.setAccessibleName(label)
        self.btn_peek_play.setToolTip(label)
        self.btn_peek_play.setIcon(self._peek_icons[label])

    @staticmethod
    def _peek_icon(action, ink):
        pixmap = QPixmap(36, 36)
        pixmap.setDevicePixelRatio(2)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(ink))
        if action in ("Volume", "Muted"):
            speaker = QPainterPath(QPointF(2.5, 6.6))
            for x, y in ((5.2, 6.6), (9.6, 3.4), (9.6, 14.6), (5.2, 11.4), (2.5, 11.4)):
                speaker.lineTo(x, y)
            speaker.closeSubpath()
            painter.drawPath(speaker)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(ink), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            if action == "Muted":
                painter.drawLine(QPointF(12, 7.2), QPointF(15, 10.8))
                painter.drawLine(QPointF(12, 10.8), QPointF(15, 7.2))
            else:
                wave = QPainterPath(QPointF(11.8, 5))
                wave.quadTo(17.8, 9, 11.8, 13)
                painter.drawPath(wave)
        elif action == "Pause":
            for x in (4, 10):
                painter.drawRoundedRect(QRectF(x, 2, 4, 14), 1, 1)
        else:
            if action == "Previous":
                painter.translate(18, 0)
                painter.scale(-1, 1)
            shape = QPainterPath()
            shape.moveTo(4, 2.5)
            shape.lineTo(15, 9)
            shape.lineTo(4, 15.5)
            shape.closeSubpath()
            painter.drawPath(shape)
            if action != "Play":
                painter.drawRoundedRect(QRectF(14, 2.5, 2.5, 13), 0.6, 0.6)
        painter.end()
        disabled = QPixmap(pixmap.size())
        disabled.setDevicePixelRatio(pixmap.devicePixelRatio())
        disabled.fill(Qt.GlobalColor.transparent)
        painter = QPainter(disabled)
        painter.setOpacity(0.32)
        painter.drawPixmap(0, 0, pixmap)
        painter.end()
        icon = QIcon(pixmap)
        icon.addPixmap(disabled, QIcon.Mode.Disabled)
        return icon

    def _size_collapsed_art(self):
        size = max(12, min(round(self._collapsed_h * 2 / 3), round(self._collapsed_w * 0.11)))
        radius = max(3, round(size * 0.24))
        self.coll_thumb.setFixedSize(size, size)
        self.coll_thumb.setStyleSheet(f"background: rgba(128,128,128,0.16); border-radius: {radius}px; color: #9ca8b7; font-family: '{get_fluent_font_family()}'; font-size: {max(9, size // 2)}px;")

    def _refresh_collapsed_art(self):
        artwork = self.tab_music._artwork_pixmap
        size = self.coll_thumb.width()
        key = (artwork.cacheKey(), size)
        if key == self._compact_art_key:
            return
        self._compact_art_key = key
        if artwork.isNull():
            self.coll_thumb.setText(Icons.MUSIC)
        else:
            self.coll_thumb.setPixmap(self.tab_music._rounded_art(artwork, size, max(3, round(size * 0.24))))

    def _on_media_timeline(self, position, duration, playing):
        self.tab_music.update_timeline(position, duration, playing)
        self._peek_timeline = (position, duration)
        if self.state == NotchState.PEEK:
            self._show_peek_timeline()

    def _show_peek_timeline(self):
        position, duration = self._peek_timeline if self._has_media else (0, 0)
        seekable = bool(duration > 0 and self._current_media.get("can_seek"))
        if self.peek_seek.isSliderDown():
            if not seekable:
                self.peek_seek.cancel_drag()
            return
        self.peek_seek.setEnabled(seekable)
        self.peek_seek.setRange(0, max(1, round(duration)))
        self.peek_seek.setValue(round(position) if duration > 0 else 0)
        self._set_peek_elapsed(position if duration > 0 else None)

    def _set_peek_elapsed(self, position):
        duration = self._peek_timeline[1]
        text = (f"{self.tab_music._format_time(position)} / {self.tab_music._format_time(duration)}"
                if position is not None and duration > 0 else "")
        if self.lbl_peek_time.text() != text:
            self.lbl_peek_time.setText(text)
        self.peek_seek.setAccessibleDescription(text or "Playback position unavailable")

    def _seek_peek(self, position):
        self._set_peek_elapsed(position)
        self.media_manager.seek(position)

    def _refresh_peek_surface(self):
        source = self._appearance["peek_color_source"]
        theme_color = QColor(surface_colors()["root"] if is_light_theme() else self._theme["bg"])
        if source == "fixed":
            color = QColor(self._appearance["peek_color"])
        elif source == "artwork" and not self.tab_music._artwork_pixmap.isNull():
            hue, saturation, _, _ = self.tab_music._artwork_surface.getHsl()
            color = QColor.fromHsl(max(0, hue), min(105, round(saturation * 1.4)), 215 if is_light_theme() else 36)
        else:
            color = theme_color
        if color == getattr(self, "_styled_peek_bg", None):
            return
        self._styled_peek_bg = self._peek_bg = color

        ink = contrast_ink(color)
        dark_ink = ink == "#000000"
        rgb = "0,0,0" if dark_ink else "255,255,255"
        muted = f"rgba({rgb},0.78)"
        self.lbl_peek_title.setStyleSheet(f"color: {ink}; font-family: 'Segoe UI'; font-size: 13px; font-weight: 600;")
        self.lbl_peek_artist.setStyleSheet(f"color: {muted}; font-family: 'Segoe UI'; font-size: 10px;")
        self.lbl_peek_time.setStyleSheet(f"color: {muted}; font-family: 'Segoe UI'; font-size: 10px;")
        self.peek_visualizer.set_ink(QColor(ink))
        font = get_fluent_font_family()
        self.peek_thumb.setStyleSheet(
            f"color: {ink}; background: rgba({rgb},0.07); border-radius: 6px; "
            f"font-family: '{font}'; font-size: 24px;")
        self._peek_icons = {action: self._peek_icon(action, ink)
                            for action in ("Previous", "Play", "Pause", "Next", "Volume", "Muted")}
        self.btn_peek_prev.setIcon(self._peek_icons["Previous"])
        action = "Pause" if self._has_media and self._current_media.get("is_playing") else "Play"
        self.btn_peek_play.setIcon(self._peek_icons[action])
        self.btn_peek_next.setIcon(self._peek_icons["Next"])
        self.btn_peek_volume.setIcon(self._peek_icons["Muted" if self._peek_volume_muted else "Volume"])
        for button in (self.btn_peek_prev, self.btn_peek_next, self.btn_peek_volume, self.btn_peek_play):
            size = 18 if button is self.btn_peek_play else 14
            button.setIconSize(QSize(size, size))
            button.setProperty("poppyStyleSource", None)
            button.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {ink};
                    border: 1px solid transparent;
                    border-radius: 5px;
                    padding: 0;
                    font-family: '{font}';
                    font-size: 11px;
                }}
                QPushButton:hover {{ background: rgba({rgb},0.10); }}
                QPushButton:focus {{ border-color: {muted}; }}
                QPushButton:disabled {{ color: {muted}; }}
            """)
        self.peek_seek.setStyleSheet(f"""
            QSlider:focus {{ border: none; outline: none; }}
            QSlider::groove:horizontal {{ height: 2px; background: rgba({rgb},0.23); border-radius: 1px; }}
            QSlider::sub-page:horizontal {{ background: {muted}; border-radius: 1px; }}
            QSlider::handle:horizontal {{
                background: {ink}; border: 1px solid {ink}; width: 6px; margin: -3px 0; border-radius: 4px;
            }}
            QSlider::handle:horizontal:focus {{ background: {color.name()}; }}
            QSlider::handle:horizontal:disabled {{ background: transparent; border-color: transparent; }}
        """)
        self.peek_volume_menu.setStyleSheet(f"""
            QMenu {{ background: {color.name()}; border: none; border-radius: 8px; padding: 2px; }}
        """)
        self.lbl_peek_volume.setStyleSheet(f"color: {ink}; font: 11px 'Segoe UI';")
        self.peek_volume.setStyleSheet(f"""
            QSlider::groove:vertical {{ width: 4px; background: rgba({rgb},0.23); border-radius: 2px; }}
            QSlider::add-page:vertical {{ background: {muted}; border-radius: 2px; }}
            QSlider::handle:vertical {{
                height: 8px; margin: 0 -3px; background: {ink}; border: 1px solid {ink}; border-radius: 5px;
            }}
            QSlider:focus {{ border: none; outline: none; }}
            QSlider::handle:vertical:focus {{ background: {color.name()}; }}
        """)
        if self.state == NotchState.PEEK:
            self.update()

    def _elide_peek_metadata(self):
        data = self._current_media
        title = data.get("title", "")
        artist = data.get("artist", "") if self._has_media else "Play media to start"
        if self._has_media and not artist:
            artist = data.get("display_name", "")
        for label, text in ((self.lbl_peek_title, title if self._has_media else "Nothing playing"),
                            (self.lbl_peek_artist, artist)):
            label.setText(label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, max(1, label.width())))

    def _on_sessions_updated(self, sessions_list: list, active_index: int):
        signature = (tuple((session["index"], session["display_name"]) for session in sessions_list), active_index)
        if signature == getattr(self, "_session_ui_signature", None):
            self.tab_music._sessions = sessions_list
            return
        self._session_ui_signature = signature
        accent = self._theme["accent"]
        self.tab_home.update_sessions_list(sessions_list, active_index)
        self.tab_music.update_sessions_list(sessions_list, active_index, accent=accent)


    def _on_shelf_updated(self):
        self.tab_home.update_shelf_display(self.drop_shelf.staged_items)

    def _on_screenshot_captured(self, file_path: str, qimage: QImage):
        self._last_screenshot_path = file_path
        self.drop_shelf.add_paths([file_path])
        if not self._alerts_allowed():
            return
        preferences = self.config.get("notifications", {})
        if self.state == NotchState.EXPANDED or not preferences.get("show_island_on_notify", True) or not preferences.get("preview_text", True):
            self.trigger_island("Screenshot staged", "Ready in Shelf.")
            return

        preview_visible = self.state == NotchState.ISLAND and self.island_thumb.isVisible()
        self._island_download_folder = None
        self.lbl_isl_title.setText("Screenshot staged")
        self.lbl_isl_title.setToolTip("")
        for control in (self.island_thumb, self.btn_isl_chat, self.btn_isl_pin, self.btn_isl_shelf):
            control.show()
        self.btn_isl_shelf.setText("Shelf")
        self.btn_isl_shelf.setToolTip("Open temporary file shelf")
        pix = QPixmap.fromImage(qimage)
        self.island_thumb.set_image(file_path, pix)
        self.lbl_isl_sub.setText(f"{qimage.width()} × {qimage.height()}")
        self.lbl_isl_sub.setToolTip("Drag the preview to another app or use Copy")
        self.btn_isl_chat.setText("Copy")

        if not system_animations_enabled():
            self._thumb_anim.stop()
            self._thumb_opacity_fx.setEnabled(False)
        elif not preview_visible:
            self._thumb_anim.stop()
            self._thumb_opacity_fx.setOpacity(0.0)
            self._thumb_opacity_fx.setEnabled(True)
            self._thumb_anim.start()

        # If drawer is not already expanded, expand to Island
        self._present_island()

    def _copy_island_for_chat(self):
        if self._last_screenshot_path:
            ok = self.screenshot_watcher.copy_image_for_chat(self._last_screenshot_path)
            if ok:
                self.btn_isl_chat.setText("Copied")
                QTimer.singleShot(1800, self._reset_island_chat_btn)

    def _reset_island_chat_btn(self):
        self.btn_isl_chat.setText("Copy")

    def _copy_latest_shelf_for_chat(self):
        if self.drop_shelf.staged_items:
            latest = self.drop_shelf.staged_items[-1]
            ok = self.screenshot_watcher.copy_image_for_chat(latest.path)
            if ok:
                self.tab_home.btn_home_shelf_chat.setText("Copied")
                QTimer.singleShot(1800, self._reset_home_shelf_chat_btn)

    def _reset_home_shelf_chat_btn(self):
        self.tab_home.btn_home_shelf_chat.setText("Copy")

    def _open_shelf_from_island(self):
        self._island_timer.stop()
        self._transition_to(NotchState.EXPANDED, target_tab="Shelf")

    def _activate_island(self):
        folder = self._island_download_folder
        if folder is None:
            self._open_shelf_from_island()
        else:
            self._collapse_to_pill()
            self._open_download_folder(folder)

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
        self._transition_to(NotchState.COLLAPSED, animate=False)
        self.clearFocus()

        if self._settings_window is None:
            self._settings_window = SettingsWindow(config=self.config)
            self._settings_window.settings_saved.connect(self._on_settings_saved)
            self._settings_window.appearance_live_updated.connect(self._apply_live_appearance)
            self._settings_window.screentime_reset_requested.connect(self.screentime.reset_today)
            self._settings_window.update_check_requested.connect(self.update_check_requested)

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
        self.tab_docs.apply_layout(name)
        expanded = self.view_expanded.layout()
        index = 2 if name == "Daily" else 0
        if expanded.itemAt(index) is not self._expanded_header:
            expanded.removeItem(self._expanded_header)
            expanded.insertLayout(index, self._expanded_header)
        if not self.tab_music._artwork_pixmap.isNull():
            self.tab_home.lbl_music_art.setPixmap(self.tab_music._rounded_art(
                self.tab_music._artwork_pixmap, self.tab_home.lbl_music_art.width(), min(6, self.tab_music._art_radius())))
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
        self._theme = get_theme(self._theme_name, app_cfg["layout"])
        self._style = app_cfg.get("style", "Notch")
        self._collapsed_w = app_cfg.get("collapsed_width", 240)
        self._collapsed_h = app_cfg.get("collapsed_height", 30)
        self._open_w = max(app_cfg["open_width"], 480)
        self._open_h = max(app_cfg["open_height"], 360)
        self._corner_radius = app_cfg.get("corner_radius", 22)
        self._top_offset = app_cfg.get("top_offset", 0)
        self._display = app_cfg.get("display", "Primary")

        if palette_changed or layout_changed:
            set_widget_style(QApplication.instance(), get_stylesheet(self._theme_name, app_cfg["layout"]))
            accent = self._theme["accent"]
            set_widget_style(self.lbl_coll_pomo, f"color: {accent}; font-size: 11px; font-weight: 600; min-width: 44px;")
            self.tab_music.set_accent(accent)
            self.tab_timer.set_accent(accent)
            self.tab_calendar.set_accent(accent)
            self.tab_home.slider_vol.set_accent(accent)
            self.tab_home.slider_bright.set_accent(accent)
        if palette_changed or layout_changed or light_changed or media_changed:
            self.tab_music.configure_appearance(self.config.get("media", {}), self._theme)
            self._applied_media_appearance = media_values
        if layout_changed:
            self._apply_layout_theme(app_cfg.get("layout", "Classic"))
        elif order_changed:
            self.tab_home.apply_layout(app_cfg["layout"], home_order(app_cfg["layout"], app_cfg.get("home_orders")))
        if light_changed or layout_changed:
            refresh_theme()
            self.tab_strip.apply_design()
        if palette_changed or layout_changed or light_changed:
            for dialog in self._floating_windows:
                set_widget_style(dialog, f"QDialog {{ background-color: {self._theme['bg']}; color: #f1f5f9; }}")
                self._fit_floating_window(dialog)

        if self.view_collapsed.size() != QSize(self._collapsed_w, self._collapsed_h):
            self.view_collapsed.setFixedSize(self._collapsed_w, self._collapsed_h)
            self._size_collapsed_art()
            self._refresh_collapsed_art()
        self._refresh_peek_surface()
        if self.pill_level.isVisible():
            self.pill_level.setGeometry(self.view_collapsed.rect())
            self._update_pill_level_ink()
        self._apply_geometry_for_state(self.state, animate=False)
        self.update()

    def _on_settings_saved(self, new_config: dict):
        self.config = new_config or {}
        self._apply_live_appearance(self.config.get("appearance", {}))
        self._rebuild_tabs()
        self.tab_clipboard.set_recording_enabled(self.config.get("clipboard", {}).get("enabled", False))

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

        rpc_cfg = self.config.get("discord_rpc", {})
        if rpc_cfg:
            self.discord_rpc.update_config(rpc_cfg)

        if hasattr(self, "screentime"):
            self.screentime.update_config(self.config)
            self._apply_home_sections()

        capture_enabled = self.config.get("capture", {}).get("enabled", False)
        self.screenshot_watcher.enabled = capture_enabled
        if capture_enabled:
            self.screenshot_watcher.start()
        else:
            self.screenshot_watcher.stop()
        self._apply_optional_features()
        self.settings_applied.emit()

    def _apply_optional_features(self):
        mixer_enabled = self.config.get("mixer", {}).get("enabled", True)
        self.tab_home.btn_app_mixer.setVisible(mixer_enabled)
        self.btn_peek_app_mixer.setVisible(mixer_enabled)
        if not mixer_enabled and self._app_mixer:
            self._app_mixer.hide()
        downloads = self.config.get("downloads", {})
        self.download_watcher.configure(downloads.get("enabled", False), downloads.get("folder", ""))
        self.tab_shelf.btn_downloads.setVisible(downloads.get("enabled", False))
        if self._download_activity and not downloads.get("enabled", False):
            self._download_activity.hide()
        if not self.config.get("notch", {}).get("pill_levels", True):
            self._stop_system_level_controls()
            if self._pill_level_timer.isActive():
                self._pill_level_timer.stop()
                self._dismiss_pill_level()
        elif self._manage_native_levels:
            self.start_system_level_controls()

    # --- Mouse & State Transitions ---
    def enterEvent(self, event):
        self._leave_timer.stop()
        if self.state == NotchState.ISLAND:
            self._island_timer.stop()
        if self.state in (NotchState.PEEK, NotchState.EXPANDED):
            super().enterEvent(event)
            return
        auto_peek = self.config.get("notch", {}).get("auto_hover_peek", True)
        if self.state == NotchState.COLLAPSED and auto_peek and not self._pill_level_timer.isActive():
            self._hover_peek_timer.start(140)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_peek_timer.stop()
        if self._is_pinned and self.state == NotchState.EXPANDED:
            super().leaveEvent(event)
            return
        from PySide6.QtGui import QCursor
        # If cursor is STILL geometrically within the window, ignore child switch events
        if self._displayed_geometry().contains(QCursor.pos()):
            return
        self._volume_scroll_delta = 0
        if self.state == NotchState.ISLAND:
            self._island_timer.start(1800)
        elif self.state == NotchState.PEEK:
            self._leave_timer.start()
        super().leaveEvent(event)

    def _on_hover_peek_timeout(self):
        auto_peek = self.config.get("notch", {}).get("auto_hover_peek", True)
        if (self.state == NotchState.COLLAPSED and auto_peek and not self._pill_level_timer.isActive()
                and self._displayed_geometry().contains(QCursor.pos())):
            if self.anim.state() == QPropertyAnimation.State.Running:
                self._hover_peek_timer.start(70)
                return
            self._transition_to(NotchState.PEEK)

    def _on_leave_timeout(self):
        if self.state == NotchState.PEEK and not self._peek_should_stay_open():
            self._transition_to(NotchState.COLLAPSED)

    def _check_peek_presence(self):
        if self.state != NotchState.PEEK:
            return
        if self._peek_should_stay_open():
            self._leave_timer.stop()
        elif not self._leave_timer.isActive():
            self._leave_timer.start()

    def _peek_should_stay_open(self):
        if QApplication.mouseButtons() != Qt.MouseButton.NoButton:
            return True
        pointer = QCursor.pos()
        local = self.mapFromGlobal(pointer)
        mask = self.mask()
        if self._displayed_geometry().contains(pointer) and (mask.isEmpty() or mask.contains(local)):
            return True
        if self.peek_volume_menu.isVisible() and self.peek_volume_menu.geometry().contains(pointer):
            return True
        # Leave context menus open until the user dismisses them. The speaker
        # popup is part of the hover surface and follows its leave grace period.
        popup = QApplication.activePopupWidget()
        return popup is not None and popup is not self.peek_volume_menu

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
                self._activate_island()
                event.accept()
                return

        super().mousePressEvent(event)

    def wheelEvent(self, event):
        if self.state in (NotchState.COLLAPSED, NotchState.PEEK):
            delta = event.angleDelta().y()
            phase = event.phase()
            if phase in (Qt.ScrollPhase.ScrollBegin, Qt.ScrollPhase.ScrollEnd):
                self._volume_scroll_delta = 0
            if phase == Qt.ScrollPhase.ScrollMomentum:
                event.accept()
                return
            if delta and event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
                self._volume_scroll_delta = 0
                self._step_brightness(5 if delta > 0 else -5)
                event.accept()
                return
            if delta and event.modifiers() == Qt.KeyboardModifier.NoModifier and self.config.get("notch", {}).get("scroll_volume", True):
                if self._volume_scroll_delta * delta < 0:
                    self._volume_scroll_delta = 0
                self._volume_scroll_delta += delta
                if abs(self._volume_scroll_delta) >= 120:
                    direction = 1 if self._volume_scroll_delta > 0 else -1
                    self._volume_scroll_delta = direction * (abs(self._volume_scroll_delta) % 120)
                    self._step_volume(2 * direction)
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
        if not self._shutting_down and self.state == NotchState.EXPANDED:
            self._click_outside_timer.start()

    def _check_click_outside(self):
        if self._is_pinned or self._command_palette is not None:
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
        if self._displayed_geometry().contains(cursor_pos):
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

    def _transition_to(self, new_state: NotchState, target_tab: str = None, *, animate: bool = True):
        if self.state == new_state:
            if target_tab:
                self._switch_to_tab_by_name(target_tab, animate=False)
            if not animate:
                self._apply_geometry_for_state(new_state, animate=False)
            return

        start_radius = self._outline_radius()
        start_center = self._outline_bounds().center().x() + self.x()
        velocity = self._geometry_velocity()
        self.anim.stop()
        self._peek_presence_timer.stop()
        self._leave_timer.stop()
        self._click_outside_timer.stop()
        self.peek_volume_menu.hide()
        if self.state == NotchState.ISLAND:
            self._island_download_folder = None
            self._island_timer.stop()
            self._thumb_anim.stop()
            self._thumb_opacity_fx.setEnabled(False)

        self.view_collapsed.setVisible(new_state == NotchState.COLLAPSED)
        self.view_peek.setVisible(new_state == NotchState.PEEK)
        self.view_island.setVisible(new_state == NotchState.ISLAND)
        self.view_expanded.setVisible(new_state == NotchState.EXPANDED)

        if new_state == NotchState.EXPANDED:
            # Select the page before enabling expanded layout resize requests.
            default_tab = self.config.get("notch", {}).get("default_tab", "Home")
            selected_tab = target_tab or (default_tab if default_tab in self._tab_name_to_stack_idx else "Home")
            if selected_tab not in self._enabled_tab_names:
                selected_tab = self._active_tab_names[0]
            self._switch_to_tab_by_name(selected_tab, animate=False)

        self.state = new_state
        if new_state not in (NotchState.COLLAPSED, NotchState.PEEK):
            self._volume_scroll_delta = 0
        self._sync_brightness_flyout()
        if new_state != NotchState.COLLAPSED and self._pill_level_timer.isActive():
            self._pill_level_timer.stop()
            self._dismiss_pill_level()
        if new_state == NotchState.PEEK:
            self._show_peek_timeline()
            self._sync_system_controls()
            self.view_peek.layout().activate()
            self._elide_peek_metadata()
        self._apply_geometry_for_state(new_state, animate=animate, start_radius=start_radius,
                                       start_center=start_center, velocity=velocity)
        self.update()

        if new_state == NotchState.EXPANDED:
            self._sync_system_controls(force=True)
            self.raise_()
            self.activateWindow()
            QTimer.singleShot(220, self, self._start_click_outside_timer)
        elif new_state == NotchState.PEEK:
            self.view_peek.setFocus(Qt.FocusReason.OtherFocusReason)
            self._peek_presence_timer.start()

    def _get_current_screen_geometry(self) -> QRect:
        """Multi-monitor aware screen lookup using configured display or cursor fallback."""
        target_disp = getattr(self, "_display", "Primary")
        screens = QGuiApplication.screens()
        if target_disp == "Primary" and (primary := QGuiApplication.primaryScreen()):
            return primary.geometry()
        if target_disp and screens:
            display_number = target_disp.split(" (", 1)[0]
            for idx, scr in enumerate(screens):
                if display_number == f"Display {idx + 1}" or target_disp == scr.name():
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

    def _geometry_for_state(self, state: NotchState) -> QRect:
        screen = self._get_current_screen_geometry()
        if state == NotchState.COLLAPSED:
            self._target_size = (self._collapsed_w, self._collapsed_h)
        elif state == NotchState.PEEK:
            self._target_size = self.PEEK_SIZE
        elif state == NotchState.ISLAND:
            self._target_size = (420, 64)
        elif state == NotchState.EXPANDED:
            page = self.tab_stack.currentWidget()
            max_height = screen.height() - 56 - max(0, self._top_offset)
            layout = self.view_expanded.layout()
            layout.activate()
            margins = layout.contentsMargins()
            chrome_height = margins.top() + margins.bottom() + layout.spacing() * (layout.count() - 1)
            chrome_height += sum(layout.itemAt(i).minimumSize().height()
                                 for i in range(layout.count()) if layout.itemAt(i).widget() is not self.tab_stack)
            preferred_height = min(max(self._open_h, 480), max_height)
            w = min(max(self._open_w, 780, page.minimumSizeHint().width() + 28), screen.width() - 16)
            home_height = 0
            if page is self.tab_home:
                home_height = page.fit_height(preferred_height - chrome_height, w, max_height=max_height - chrome_height)
            elif page is self.tab_music:
                page.fit_height(preferred_height - chrome_height)
            h = max(preferred_height, max(home_height, page.minimumSizeHint().height()) + chrome_height)
            self._target_size = (w, min(h, max_height))
            self.view_expanded.setFixedSize(*self._target_size)

        w, h = self._target_size
        top_offset = getattr(self, "_top_offset", 0)
        x = screen.x() + (screen.width() - w) // 2
        y = screen.y() + top_offset if self._style == "Notch" else screen.y() + max(8, 8 + top_offset)
        return QRect(x, y, w, h)

    def _transition_duration(self) -> int:
        if not system_animations_enabled():
            return 0
        return max(0, self.config.get("notch", {}).get("animation_duration_ms", 200))

    def _apply_geometry_for_state(self, state: NotchState, animate: bool = True, *,
                                  start_radius: float | None = None, start_center: float | None = None,
                                  velocity: tuple[float, float] | None = None):
        self._anim_opacity.stop()
        self._expanded_opacity.setEnabled(False)
        self._peek_fade.stop()
        self._peek_opacity.setEnabled(False)

        target = self._geometry_for_state(state)
        duration = round(self._transition_duration() * self.MOTION_PROFILES[state][0]) if animate else 0
        reveal = None
        if duration and target != self._displayed_geometry():
            if state == NotchState.EXPANDED:
                reveal = self._anim_opacity, self._expanded_opacity, min(56, duration / 4)
            elif state == NotchState.PEEK:
                reveal = self._peek_fade, self._peek_opacity, min(20, duration / 8)
        if reveal:
            fade, opacity, delay = reveal
            fade.setDuration(duration)
            key = fade.easingCurve().valueForProgress(delay / duration)
            fade.setKeyValues([(0.0, 0.0), (key, 0.0), (1.0, 1.0)])
            # Hide the anchored content before the native host changes size.
            opacity.setOpacity(0.0)
            opacity.setEnabled(True)
        self._animate_geometry(target, duration, start_radius=start_radius, start_center=start_center,
                               velocity=velocity)
        if reveal:
            fade.start()

    def _geometry_velocity(self) -> tuple[float, float] | None:
        if self.anim.state() != QPropertyAnimation.State.Running:
            return None
        start, end = self.anim.startValue(), self.anim.endValue()
        duration, time = self.anim.duration(), self.anim.currentTime()
        left, right = max(0, time - 1), min(duration, time + 1)
        curve = self.anim.easingCurve()
        speed = (curve.valueForProgress(right / duration) - curve.valueForProgress(left / duration)) / (right - left)
        return (end.width() - start.width()) * speed, (end.height() - start.height()) * speed

    def _motion_curve(self, start, target, host, duration, velocity):
        slope = self.MOTION_PROFILES[self.state][1]
        width = target.width() - start.width()
        height = target.height() - start.height()
        distance_squared = width * width + height * height
        if velocity is not None and distance_squared:
            # Project the current size velocity onto the new size change.
            slope = duration * (velocity[0] * width + velocity[1] * height) / distance_squared
            slope = max(-0.75, min(2.5, slope))
        if slope < 0:
            # A reversal briefly brakes in the old direction. Use the
            # cubic's extremum to keep that movement inside the reserved host.
            t = -slope / (6 - 3 * slope)
            travel = t * (1 - t) * (1 - t) * slope + t * t * (3 - 2 * t)
            edge = QRectF(start.x() + travel * (target.x() - start.x()),
                          start.y() + travel * (target.y() - start.y()),
                          start.width() + travel * width, start.height() + travel * height)
            if not QRectF(host).contains(edge):
                slope = 0
        curve = QEasingCurve(QEasingCurve.Type.BezierSpline)
        curve.addCubicBezierSegment(QPointF(1 / 3, slope / 3), QPointF(2 / 3, 1), QPointF(1, 1))
        return curve

    def _displayed_geometry(self) -> QRect:
        return self.geometry() if self._transition_frame is None else self._transition_frame

    def _set_displayed_geometry(self, rect: QRect):
        if self._transition_frame is None:
            self.setGeometry(rect)
        else:
            dirty = self._transition_frame.united(rect).translated(-self.pos())
            self._transition_frame = rect
            self._position_surface_view()
            self.update(dirty.adjusted(-2, -2, 2, 2))

    notchGeometry = Property(QRect, _displayed_geometry, _set_displayed_geometry)

    def _animate_geometry(self, target: QRect, duration: int, *,
                          start_radius: float | None = None, start_center: float | None = None,
                          velocity: tuple[float, float] | None = None):
        self._start_corner_radius = self._outline_radius() if start_radius is None else start_radius
        self._start_outline_center = (
            self._outline_bounds().center().x() + self.x() if start_center is None else start_center
        )
        if velocity is None:
            velocity = self._geometry_velocity()
        self.anim.stop()
        start = self._displayed_geometry()
        if duration <= 0 or start == target:
            self._release_transition_host()
            self.setGeometry(target)
            self._position_surface_view()
            self._update_clickthrough_mask()
            return
        # Clear the native region while resizing to avoid repeated DWM stalls.
        self.clearMask()
        self.anim.setDuration(duration)
        self.anim.setStartValue(start)
        self.anim.setEndValue(target)
        # Anchor the incoming view while its outline changes size.
        host = self.geometry() if self._transition_frame is not None else start
        self._transition_frame = start
        host = host.united(target)
        self.anim.setEasingCurve(self._motion_curve(start, target, host, duration, velocity))
        # Start on a whole physical pixel so Qt's child and window
        # coordinates round the same way when the surface is released.
        quantum = Fraction(self.devicePixelRatioF()).limit_denominator(100).denominator
        screen_x = self._get_current_screen_geometry().x()
        host.setLeft(host.left() - (host.left() - screen_x) % quantum)
        self.setGeometry(host)
        self._position_surface_view()
        self.anim.start()

    def _release_transition_host(self):
        if self._transition_frame is not None:
            rect, self._transition_frame = self._transition_frame, None
            self._surface_clip.clearMask()
            self.setGeometry(rect)
            self._position_surface_view()

    def _on_animation_finished(self):
        self._release_transition_host()
        self._update_clickthrough_mask()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_surface_view()
        # NEVER call SetWindowRgn during a live animation frame
        if self._transition_frame is None and self.anim.state() != QPropertyAnimation.State.Running:
            self._recenter_window()
            self._update_clickthrough_mask()

    def _position_surface_view(self):
        self._surface_clip.setGeometry(self.rect())
        view = {
            NotchState.COLLAPSED: self.view_collapsed,
            NotchState.PEEK: self.view_peek,
            NotchState.ISLAND: self.view_island,
            NotchState.EXPANDED: self.view_expanded,
        }[self.state]
        if self._transition_frame is None:
            view.move((self.width() - view.width()) // 2, 0)
            return
        anchor = self.anim.endValue().topLeft() - self.geometry().topLeft()
        view.move(anchor)
        # Clip the parent so opacity effects still paint the view at full size.
        self._surface_clip.setMask(QRegion(self._notch_path().toFillPolygon().toPolygon()))

    def _update_clickthrough_mask(self):
        region = QRegion(self._notch_path().toFillPolygon().toPolygon())
        # Allow for polygon rounding and the painter's partially covered pixels.
        region |= region.translated(-2, 0) | region.translated(2, 0)
        region |= region.translated(0, -2) | region.translated(0, 2)
        self.setMask(region.intersected(self.rect()))

    def _outline_radius(self):
        target = self._corner_radius if self.state == NotchState.EXPANDED else 14
        if self.anim.state() == QPropertyAnimation.State.Running:
            progress = self._outline_progress()
            return self._start_corner_radius + (target - self._start_corner_radius) * progress
        return target

    def _outline_progress(self):
        # Size can coast briefly on reversal. Keep the anchor and radius
        # within their endpoints, including half-pixel display rounding.
        return max(0.0, self.anim.easingCurve().valueForProgress(self.anim.currentTime() / self.anim.duration()))

    def _outline_bounds(self) -> QRectF:
        bounds = QRectF(self._displayed_geometry())
        if self._transition_frame is not None and self.anim.state() == QPropertyAnimation.State.Running:
            start = self._start_outline_center
            end = QRectF(self.anim.endValue()).center().x()
            progress = self._outline_progress()
            bounds.moveLeft(start + (end - start) * progress - bounds.width() / 2)
        return bounds.translated(-self.geometry().topLeft())

    def _notch_path(self):
        bounds = self._outline_bounds()
        w, h = float(bounds.width()), float(bounds.height())
        radius = min(w / 2, h / 2, self._outline_radius())
        path = QPainterPath()
        if self._style == "Notch":
            # Leave room within the window for reverse curves at the bezel.
            flare = min(10.0, h * 0.27, w * 0.12)
            radius = min(radius, (w - 2 * flare) / 2)
            path.moveTo(0, 0)
            path.lineTo(w, 0)
            path.quadTo(w - flare, 0, w - flare, flare)
            path.lineTo(w - flare, h - radius)
            path.quadTo(w - flare, h, w - flare - radius, h)
            path.lineTo(flare + radius, h)
            path.quadTo(flare, h, flare, h - radius)
            path.lineTo(flare, flare)
            path.quadTo(flare, 0, 0, 0)
            path.closeSubpath()
        else:
            path.addRoundedRect(0, 0, w, h, radius, radius)
        return path.translated(bounds.x(), bounds.y())

    # --- Drag & Drop Handlers ---
    def dragEnterEvent(self, event):
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
            if self.state != NotchState.EXPANDED:
                self._transition_to(NotchState.EXPANDED, target_tab="Shelf")
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
            if paths:
                self.drop_shelf.add_paths(paths)
                self._switch_to_tab_by_name("Shelf")
                event.acceptProposedAction()
                return
        event.ignore()

    def paintEvent(self, event):
        painter = QPainter(self)
        if self._transition_frame is not None:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.fillRect(event.rect(), Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        bounds = self._outline_bounds()
        path = self._notch_path()

        # Gradient / Surface Fill from active theme
        bg_col = QColor(surface_colors()["root"] if is_light_theme() else self._theme["bg"])
        grad_col = QColor(surface_colors()["root"] if is_light_theme() else self._theme["gradient"])
        if self.state == NotchState.PEEK:
            bg_col = grad_col = self._peek_bg
            if self._appearance["peek_color_source"] == "artwork" and not self.tab_music._artwork_pixmap.isNull():
                grad_col = bg_col.lighter(108) if is_light_theme() else bg_col.darker(155)
        if self.state != NotchState.PEEK and self._appearance.get("layout") in ("Flat", "Paper", "Instrument"):
            if self._appearance.get("layout") == "Paper" and not is_light_theme():
                bg_col = QColor((bg_col.red() * 3 + 44) // 4, (bg_col.green() * 3 + 40) // 4, (bg_col.blue() * 3 + 32) // 4)
            grad_col = bg_col
        dx = bounds.width() if self.state == NotchState.PEEK else 0
        gradient = QLinearGradient(bounds.x(), bounds.y(), bounds.x() + dx, bounds.y() + bounds.height())
        gradient.setColorAt(0.0, grad_col)
        gradient.setColorAt(1.0, bg_col)
        painter.fillPath(path, QBrush(gradient))

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
        self._stop_system_level_controls()
        self.download_watcher.close()
        self.caffeine.stop()
        if self._app_mixer:
            self._app_mixer.hide()
        for timer in self.findChildren(QTimer):
            timer.stop()
        for animation in self.findChildren(QVariantAnimation):
            animation.stop()
        self.screentime.close()
        self.lyrics_manager.close()
        self.media_manager.stop()
        self.bright_ctrl.close()
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
