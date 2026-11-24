"""
Tests for Screen Time Manager, Settings integration, and Centered Pop-Out Animation.
"""

from datetime import datetime

import pytest
from PySide6.QtWidgets import QApplication, QLayout
from PySide6.QtCore import QAbstractAnimation, QEvent, QObject, QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from poppy.core.screentime_manager import ScreenTimeManager, format_duration
from poppy.core.window import DynamicNotchWindow, NotchState
from poppy.ui.components import ToggleSwitch
from poppy.ui.settings_window import SettingsWindow
from poppy.ui.styles import get_stylesheet
from poppy.ui.theme import set_widget_style


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if not app:
        app = QApplication([])
    return app


def test_screentime_duration_formatting():
    assert format_duration(0) == "0m"
    assert format_duration(59) == "0m"
    assert format_duration(60) == "1m"
    assert format_duration(3600) == "1h 00m"
    assert format_duration(3665) == "1h 01m"
    assert format_duration(7500) == "2h 05m"


def test_clock_updates_seconds_only_when_home_shows_them(qapp, monkeypatch):
    class FixedClock(datetime):
        @classmethod
        def now(cls):
            return cls(2026, 11, 11, 14, 20, 15, 250000)

    monkeypatch.setattr("poppy.core.window.datetime", FixedClock)
    window = DynamicNotchWindow({"appearance": {"layout": "Paper"}})
    window.show()
    assert window.lbl_clock.text() == "2:20 PM"
    assert window._clock_timer.interval() == 44750

    window._transition_to(NotchState.EXPANDED, "Home", animate=False)
    assert window.tab_home.lbl_big_time.text() == "2:20:15 PM"
    assert window._clock_timer.interval() == 750

    window._switch_to_tab_by_name("Music", animate=False)
    assert window._clock_timer.interval() == 44750


def test_screentime_manager_tracking_and_reset(qapp):
    config = {
        "screentime": {
            "enabled": True,
            "daily_goal_hours": 4.0,
            "idle_threshold_seconds": 120,
            "track_apps": True
        }
    }
    sm = ScreenTimeManager(config)
    sm._today_seconds = 7200  # 2 hours
    sm._continuous_seconds = 1800  # 30 mins
    sm._today_apps = {"Code": 4800, "Brave": 2400}

    assert sm.get_formatted_today() == "2h 00m"
    assert sm.get_goal_progress() == pytest.approx(0.5, 0.01)

    top = sm.get_top_apps(2)
    assert len(top) == 2
    assert top[0][0] == "Code"
    assert top[0][2] == "1h 20m"
    assert top[1][0] == "Brave"
    assert top[1][2] == "40m"

    sm.reset_today()
    assert sm.get_today_seconds() == 0
    assert sm.get_goal_progress() == 0.0
    assert sm.get_top_apps() == []


@pytest.mark.parametrize("tab", ["Home", "Music"])
def test_expand_animation_smooth_center(qapp, tab):
    """
    Ensure the window pops out symmetrically from center with zero right-to-left drift.
    """
    w = DynamicNotchWindow()
    w.setMinimumSize(1, 1)
    w.show()

    # Initial collapsed state
    init_g = w.geometry()
    expected_center_x = init_g.x() + init_g.width() / 2.0

    # Expand to EXPANDED
    w._transition_to(NotchState.EXPANDED, target_tab=tab)

    start_v = w.anim.startValue()
    end_v = w.anim.endValue()

    start_center_x = start_v.x() + start_v.width() / 2.0
    end_center_x = end_v.x() + end_v.width() / 2.0

    # The start and end centers must be identical (perfectly centered popup)
    assert abs(start_center_x - end_center_x) < 1.0
    assert abs(start_center_x - expected_center_x) < 1.0

    # Check the visible outline and the drawer content separately.
    host = w.geometry()
    duration = w.anim.duration()
    for pct in [0.0, 0.25, 0.5, 0.75, 1.0]:
        t = int(duration * pct)
        w.anim.setCurrentTime(t)
        qapp.processEvents()
        frame_g = w._displayed_geometry()
        requested = w.anim.currentValue()
        assert QLayout.closestAcceptableSize(w, requested.size()) == requested.size()
        assert frame_g.size() == requested.size()
        frame_center = frame_g.x() + frame_g.width() / 2.0
        assert abs(frame_center - expected_center_x) <= 1.0
        assert w.view_expanded.mapToGlobal(QPoint()) == end_v.topLeft()
        assert w.geometry() == (host if w.anim.state() == QAbstractAnimation.State.Running else end_v)


def test_open_and_switch_tabs_without_snapping(qapp, monkeypatch):
    class ResizeLog(QObject):
        def __init__(self):
            super().__init__()
            self.sizes = []

        def eventFilter(self, obj, event):
            if event.type() == QEvent.Type.Resize:
                self.sizes.append(event.size())
            return False

    w = DynamicNotchWindow({"notch": {"animation_duration_ms": 500}})
    monkeypatch.setattr(w, "_get_current_screen_geometry", lambda: QRect(0, 0, 1440, 900))
    w._is_pinned = True
    w.show()
    qapp.processEvents()
    log = ResizeLog()
    w.installEventFilter(log)
    compact = w.geometry()
    w._transition_to(NotchState.EXPANDED, target_tab="Home")
    assert log.sizes == [w.geometry().size()]
    assert w._displayed_geometry() == compact

    w.anim.setCurrentTime(90)
    w._anim_opacity.setCurrentTime(90)
    mid = w._displayed_geometry()
    opacity = w._expanded_opacity.opacity()
    previous_target = w.anim.endValue()
    w._open_w += 60
    music_index = w._active_tab_names.index("Music")
    w.tab_strip.buttons[music_index].click()
    assert w.tab_stack.currentWidget() is w.tab_music
    assert w._displayed_geometry() == mid
    assert w.anim.startValue() == mid and w.anim.endValue() != previous_target
    assert w.view_expanded.mapToGlobal(QPoint()) == w.anim.endValue().topLeft()
    assert w.anim.duration() == 410
    assert w._expanded_opacity.opacity() == opacity
    assert w._anim_opacity.state() == QAbstractAnimation.State.Running
    assert [i for i, button in enumerate(w.tab_strip.buttons) if button.isChecked()] == [music_index]


def test_drawer_fade_ends_with_geometry_and_cancels_on_close(qapp):
    w = DynamicNotchWindow({"notch": {"animation_duration_ms": 80, "auto_hover_peek": False}})
    w._is_pinned = True
    w.show()
    w._transition_to(NotchState.EXPANDED)
    assert w._anim_opacity.duration() == w.anim.duration() == 80
    w.anim.setCurrentTime(10)
    w._anim_opacity.setCurrentTime(10)
    assert w._expanded_opacity.opacity() == 0.0
    mid = w._displayed_geometry()
    outline = w._notch_path()
    w._transition_to(NotchState.COLLAPSED)
    assert w._displayed_geometry() == mid
    assert w._notch_path() == outline
    QTest.qWait(75)
    assert w._anim_opacity.state() == QAbstractAnimation.State.Stopped
    assert not w._expanded_opacity.isEnabled()


def test_pill_reveal_and_collapse_use_shorter_timings(qapp):
    w = DynamicNotchWindow({"notch": {"animation_duration_ms": 240}})
    w._is_pinned = True
    w.show()
    w._transition_to(NotchState.PEEK)
    assert w.anim.duration() == w._peek_fade.duration() == 180
    assert w._peek_opacity.opacity() == 0
    w.anim.setCurrentTime(w.anim.duration())
    w._transition_to(NotchState.EXPANDED)
    assert w.anim.duration() == w._anim_opacity.duration() == 240
    w._anim_opacity.setCurrentTime(30)
    assert w._expanded_opacity.opacity() == 0
    w.anim.setCurrentTime(w.anim.duration())
    w._collapse_to_pill()
    assert w.anim.duration() < 180


def test_reversing_pill_motion_brakes_inside_the_original_host(qapp):
    w = DynamicNotchWindow({"appearance": {"collapsed_width": 239}})
    w._is_pinned = True
    w.show()
    resting = w.geometry()
    w._transition_to(NotchState.EXPANDED)
    host = w.geometry()
    w.anim.setCurrentTime(w.anim.duration() // 2)
    before = w._displayed_geometry()
    w._collapse_to_pill()
    assert w._displayed_geometry() == before
    assert w.geometry() == host
    assert w._geometry_velocity()[0] > 0
    widths = []
    for tick in range(0, w.anim.duration() + 1):
        w.anim.setCurrentTime(tick)
        outline = w._outline_bounds().translated(w.pos())
        assert QRectF(host).contains(outline)
        assert abs(outline.center().x() - QRectF(resting).center().x()) <= 0.5
        widths.append(outline.width())
    turn = widths.index(max(widths))
    assert max(widths) > before.width()
    assert widths[turn:] == sorted(widths[turn:], reverse=True)
    assert w.geometry() == resting


def test_screenshot_replacement_preserves_in_flight_opacity(qapp, monkeypatch, tmp_path):
    w = DynamicNotchWindow({"notifications": {"sound": False}})
    monkeypatch.setattr(w.drop_shelf, "add_paths", lambda paths: None)
    w.show()
    image = QImage(40, 30, QImage.Format.Format_RGB32)
    image.fill(0xFF223344)
    w._on_screenshot_captured(str(tmp_path / "first.png"), image)
    assert w.lbl_isl_title.text() == "Screenshot staged"
    w._thumb_anim.setCurrentTime(75)
    opacity = w._thumb_opacity_fx.opacity()
    assert 0.0 < opacity < 1.0
    w._on_screenshot_captured(str(tmp_path / "second.png"), image)
    assert w._thumb_opacity_fx.opacity() == opacity
    assert w._thumb_anim.currentTime() == 75
    w.trigger_island("Reminder", "Check the shelf")
    assert w._thumb_anim.state() == QAbstractAnimation.State.Stopped
    assert not w._thumb_opacity_fx.isEnabled()


@pytest.mark.parametrize("layout, mode", [("Daily", "Dark"), ("Console", "Light")])
def test_screen_time_alerts_keep_native_type_and_aligned_controls(qapp, layout, mode):
    style, source = qapp.styleSheet(), qapp.property("poppyStyleSource")
    try:
        w = DynamicNotchWindow({"appearance": {"layout": layout, "mode": mode},
                                "notifications": {"sound": False}})
        set_widget_style(qapp, get_stylesheet("Pure black", layout))
        w.show()
        w._on_screentime_break_reminder(60)
        w.anim.setCurrentTime(w.anim.duration())
        qapp.processEvents()
        title, detail, dismiss = w.lbl_isl_title, w.lbl_isl_sub, w.btn_isl_close
        assert title.text() == "Time for a break"
        assert detail.text() == "You've been active for 60 minutes."
        assert title.font().family() == detail.font().family() == "Segoe UI"
        assert (title.font().pixelSize(), detail.font().pixelSize()) == (14, 12)
        assert title.x() == detail.x() == w.view_island.width() - dismiss.geometry().right() - 1
        text_bounds = title.geometry().united(detail.geometry())
        assert abs(text_bounds.center().y() - dismiss.geometry().center().y()) <= 1
        assert qapp.focusWidget() is w.view_island
        QTest.keyClick(w.view_island, Qt.Key.Key_Tab)
        assert dismiss.hasFocus()

        w._on_screentime_goal_reached(1.5)
        assert title.text() == "Screen time goal reached"
        assert detail.text() == "You've used 1.5 hours today."
        assert dismiss.hasFocus()
        QTest.keyClick(dismiss, Qt.Key.Key_Space)
        assert w.state == NotchState.COLLAPSED
    finally:
        qapp.setProperty("poppyStyleSource", source)
        qapp.setStyleSheet(style)


def test_immediate_toggle_update_cancels_previous_motion(qapp):
    toggle = ToggleSwitch()
    toggle.show()
    toggle.setChecked(True)
    toggle._anim.setCurrentTime(50)
    assert 2.0 < toggle.thumb_position < 18.0
    toggle.setChecked(False, animate=False)
    assert toggle._anim.state() == QAbstractAnimation.State.Stopped
    assert not toggle.isChecked()
    assert toggle.thumb_position == 2.0


def test_windows_reduced_motion_keeps_controls_functional(qapp, monkeypatch):
    monkeypatch.setattr("poppy.core.window.system_animations_enabled", lambda: False)
    monkeypatch.setattr("poppy.ui.components.system_animations_enabled", lambda: False)
    w = DynamicNotchWindow()
    w._is_pinned = True
    w.show()
    w._transition_to(NotchState.PEEK)
    assert w.size().toTuple() == w.PEEK_SIZE
    assert w.anim.state() == QAbstractAnimation.State.Stopped
    assert not w._peek_opacity.isEnabled()
    w.btn_peek_volume.click()
    assert w.peek_volume_menu.isVisible()
    assert not w._peek_volume_opacity.isEnabled()
    w.peek_volume_menu.hide()
    w._show_native_brightness(60, 55)
    assert w.state == NotchState.COLLAPSED
    assert w.pill_level._value == 55.0
    w._transition_to(NotchState.EXPANDED)
    assert w.anim.state() == QAbstractAnimation.State.Stopped
    assert not w._expanded_opacity.isEnabled()
    music_index = w._active_tab_names.index("Music")
    w.tab_strip.buttons[music_index].click()
    assert w.tab_stack.currentWidget() is w.tab_music
    assert w.tab_strip.buttons[music_index].isChecked()


def test_settings_window_screentime_page(qapp):
    """
    Verify Screen Time settings page exists, has all reliable controls, and updates correctly.
    """
    cfg = {
        "screentime": {
            "enabled": True,
            "show_in_main_menu": True,
            "track_apps": True,
            "idle_threshold_seconds": 120,
            "daily_goal_hours": 8,
            "goal_alert_enabled": True,
            "break_reminders_enabled": True,
            "break_interval_minutes": 45,
            "excluded_apps": ["keepass"]
        }
    }
    sw = SettingsWindow(cfg)
    sw.select_page("Screen Time")

    assert sw.chk_st_enabled.isChecked() is True
    assert sw.chk_st_show_main_menu.isChecked() is True
    assert sw.slider_st_goal.value() == 8
    assert sw.combo_st_break_interval.currentData() == 45
    assert "keepass" in sw.txt_st_excluded.text()

    # Test live stats update method
    sw.update_screentime_display(5400, 2700, [("Code", 3600, "1h 00m")], "Code", 8.0)
    assert "1h 30m" in sw.lbl_st_today_time.text()
    assert "Goal: 18%" in sw.lbl_st_goal_pct.text()
    assert "45m" in sw.lbl_st_streak.text()


def test_open_settings_collapses_notch_and_focuses_front(qapp):
    """
    Ensure opening settings immediately collapses the notch so it never obscures the settings window.
    """
    w = DynamicNotchWindow()
    w.setMinimumSize(1, 1)
    w.show()
    w._transition_to(NotchState.EXPANDED)
    assert w.state == NotchState.EXPANDED

    # Open settings
    w.open_settings("Notifications")
    assert w.state == NotchState.COLLAPSED
    assert w.size().toTuple() == (w._collapsed_w, w._collapsed_h)
    assert w.anim.state() == QAbstractAnimation.State.Stopped
    assert w._settings_window is not None
    assert w._settings_window.isVisible() is True
    w._settings_window.close()
    w.close()


def test_spotify_lyrics_word_wrap_and_style(qapp):
    """
    Ensure lyric rows wrap naturally and match Spotify desktop typography.
    """
    from poppy.ui.components import LyricLineWidget
    row = LyricLineWidget(12.5, "tuje scene main dikhaa ke film Golmaal ke (ke-ke-ke-ke)")
    assert row.time_sec == 12.5
    assert row._lbl.wordWrap() is True
    assert row._is_active is False

    row.set_active(True)
    assert row._is_active is True
    assert "font-weight: 800" in row._lbl.styleSheet()
    assert "#ffffff" in row._lbl.styleSheet()

    row.set_active(False)
    assert row._is_active is False
    assert "font-weight: 700" in row._lbl.styleSheet()


