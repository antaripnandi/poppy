"""
Tests for Screen Time Manager, Settings integration, and Centered Pop-Out Animation.
"""

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QRect, QEasingCurve
from poppy.core.screentime_manager import ScreenTimeManager, format_duration
from poppy.core.window import DynamicNotchWindow, NotchState
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


def test_expand_animation_smooth_center(qapp):
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
    w._transition_to(NotchState.EXPANDED)

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
        frame_center = frame_g.x() + frame_g.width() / 2.0
        assert abs(frame_center - expected_center_x) <= 1.0


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
