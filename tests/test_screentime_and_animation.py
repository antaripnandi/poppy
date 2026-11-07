"""
Tests for Screen Time Manager, Settings integration, and Centered Pop-Out Animation.
"""

import pytest
from PySide6.QtWidgets import QApplication, QLayout
from PySide6.QtCore import QAbstractAnimation, QEvent, QObject, QRect, QEasingCurve
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from poppy.core.screentime_manager import ScreenTimeManager, format_duration
from poppy.core.window import DynamicNotchWindow, NotchState
from poppy.ui.components import ToggleSwitch
from poppy.ui.settings_window import SettingsWindow


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

    # Check intermediate frames during animation
    duration = w.anim.duration()
    for pct in [0.0, 0.25, 0.5, 0.75, 1.0]:
        t = int(duration * pct)
        w.anim.setCurrentTime(t)
        qapp.processEvents()
        frame_g = w.geometry()
        requested = w.anim.currentValue()
        assert QLayout.closestAcceptableSize(w, requested.size()) == requested.size()
        assert frame_g.size() == requested.size()
        frame_center = frame_g.x() + frame_g.width() / 2.0
        assert abs(frame_center - expected_center_x) <= 1.0


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
    w._transition_to(NotchState.EXPANDED, target_tab="Home")
    assert log.sizes == []

    w.anim.setCurrentTime(90)
    w._anim_opacity.setCurrentTime(90)
    mid = w.geometry()
    opacity = w._expanded_opacity.opacity()
    previous_target = w.anim.endValue()
    w._open_w += 60
    music_index = w._active_tab_names.index("Music")
    w.tab_strip.buttons[music_index].click()
    assert w.tab_stack.currentWidget() is w.tab_music
    assert w.geometry() == mid
    assert w.anim.startValue() == mid and w.anim.endValue() != previous_target
    assert w.anim.duration() == 410
    assert w._expanded_opacity.opacity() == opacity
    assert w._anim_opacity.state() == QAbstractAnimation.State.Running
    indicator = w.tab_strip._anim
    assert indicator.state() == QAbstractAnimation.State.Running
    indicator.setCurrentTime(indicator.duration())
    assert w.tab_strip.indicator.geometry() == w.tab_strip.buttons[music_index].geometry()


def test_drawer_fade_ends_with_geometry_and_cancels_on_close(qapp):
    w = DynamicNotchWindow({"notch": {"animation_duration_ms": 80, "auto_hover_peek": False}})
    w._is_pinned = True
    w.show()
    w._transition_to(NotchState.EXPANDED)
    assert w._anim_opacity.duration() == w.anim.duration() == 80
    w.anim.setCurrentTime(10)
    w._anim_opacity.setCurrentTime(10)
    assert w._expanded_opacity.opacity() == 0.0
    mid = w.geometry()
    w._transition_to(NotchState.COLLAPSED)
    assert w.geometry() == mid
    QTest.qWait(75)
    assert w._anim_opacity.state() == QAbstractAnimation.State.Stopped
    assert not w._expanded_opacity.isEnabled()


def test_screenshot_replacement_preserves_in_flight_opacity(qapp, monkeypatch, tmp_path):
    w = DynamicNotchWindow({"notifications": {"sound": False}})
    monkeypatch.setattr(w.drop_shelf, "add_paths", lambda paths: None)
    w.show()
    image = QImage(40, 30, QImage.Format.Format_RGB32)
    image.fill(0xFF223344)
    w._on_screenshot_captured(str(tmp_path / "first.png"), image)
    w._thumb_anim.setCurrentTime(75)
    opacity = w._thumb_opacity_fx.opacity()
    assert 0.0 < opacity < 1.0
    w._on_screenshot_captured(str(tmp_path / "second.png"), image)
    assert w._thumb_opacity_fx.opacity() == opacity
    assert w._thumb_anim.currentTime() == 75
    w.trigger_island("Reminder", "Check the shelf")
    assert w._thumb_anim.state() == QAbstractAnimation.State.Stopped
    assert not w._thumb_opacity_fx.isEnabled()


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
    assert w.tab_strip.indicator.geometry() == w.tab_strip.buttons[music_index].geometry()


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


