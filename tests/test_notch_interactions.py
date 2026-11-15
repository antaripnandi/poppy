import ctypes
from ctypes import wintypes

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMenu

from poppy.core.outside_click import WM_INPUT
from poppy.core.window import DynamicNotchWindow, NotchState


def test_drawer_rejects_clicks_while_invisible_and_collapse_fades(audit_app):
    window = DynamicNotchWindow()
    window._is_pinned = True
    window.show()
    window._transition_to(NotchState.EXPANDED, "Home")
    window.anim.setCurrentTime(35)
    window._anim_opacity.setCurrentTime(35)
    timer = window.tab_strip.buttons[window._active_tab_names.index("Timer")]
    point = timer.mapTo(window, timer.rect().center())
    assert window._expanded_opacity.opacity() == 0
    assert window.childAt(point) is not timer
    QTest.mouseClick(window.windowHandle(), Qt.MouseButton.LeftButton, pos=point)
    assert window.tab_stack.currentWidget() is window.tab_home
    window.anim.setCurrentTime(window.anim.duration())
    window._anim_opacity.setCurrentTime(window._anim_opacity.duration())

    window._collapse_to_pill()
    assert window._collapse_snapshot is not None
    assert window._compact_opacity.isEnabled() and window._compact_opacity.opacity() == 0
    window.anim.setCurrentTime(window.anim.duration() // 2)
    assert 0 < window._compact_opacity.opacity() < 1
    window.anim.setCurrentTime(window.anim.duration())
    assert window._collapse_snapshot is None and not window._compact_opacity.isEnabled()


def test_compact_clock_stays_centered_and_accepts_keyboard_activation(audit_app):
    window = DynamicNotchWindow()
    window._is_pinned = True
    window.show()
    window.lbl_clock.setText("2:53 PM")
    audit_app.processEvents()

    def center():
        return window.lbl_clock.mapTo(window, window.lbl_clock.rect().center()).x()

    initial = center()
    window.lbl_coll_pomo.show()
    for text in ("25:00", "24:57", "24:11", "24:00"):
        window.lbl_coll_pomo.setText(text)
        audit_app.processEvents()
        assert center() == initial
    QTest.keyClick(window, Qt.Key.Key_Return)
    assert window.state == NotchState.EXPANDED


def test_hover_uses_visible_shape_and_own_popups(audit_app, monkeypatch):
    window = DynamicNotchWindow({"notifications": {"sound": False}})
    window.show()
    window._transition_to(NotchState.ISLAND, animate=False)
    position = window.geometry().center()
    monkeypatch.setattr("poppy.core.window.QCursor.pos", lambda: position)
    window.trigger_island("Replacement", "Keep open while hovered")
    assert not window._island_timer.isActive()
    position = window.geometry().bottomLeft() + QPoint(1, -1)
    assert window.geometry().contains(position) and not window._point_on_surface(position)
    window.leaveEvent(QEvent(QEvent.Type.Leave))
    assert window._island_timer.isActive()
    window._on_island_timeout()
    assert window.state == NotchState.COLLAPSED

    window.anim.setCurrentTime(window.anim.duration())
    window._transition_to(NotchState.PEEK)
    window.anim.setCurrentTime(window.anim.duration() // 2)
    bounds = window._outline_bounds()
    position = window.mapToGlobal(QPoint(int(bounds.left()) + 1, int(bounds.bottom()) - 2))
    assert window._displayed_geometry().contains(position)
    assert not window._peek_should_stay_open()
    popup = QMenu()
    popup.addAction("Unrelated")
    popup.popup(position)
    assert not window._peek_should_stay_open()
    popup.close()


def test_scroll_steps_and_indicator_agree(audit_app, monkeypatch):
    window = DynamicNotchWindow()
    window.show()
    values = []
    monkeypatch.setattr(window, "_step_volume", lambda step: values.append(("volume", step)))
    monkeypatch.setattr(window, "_step_brightness", lambda step: values.append(("brightness", step)))
    local = window.rect().center()
    scrolls = [(360, Qt.KeyboardModifier.NoModifier)] + [(30, Qt.KeyboardModifier.ShiftModifier)] * 4
    for delta, modifier in scrolls:
        window.wheelEvent(QWheelEvent(QPointF(local), QPointF(window.mapToGlobal(local)), QPoint(),
                                     QPoint(0, delta), Qt.MouseButton.NoButton, modifier,
                                     Qt.ScrollPhase.NoScrollPhase, False))
    assert values == [("volume", 6), ("brightness", 5)]
    window._show_pill_level("Volume", "V", 20, 80)
    assert window.pill_level._value == 20
    assert window.pill_level._label == "20%"
    window.pill_level._motion.setCurrentTime(window.pill_level._motion.duration())
    assert window.pill_level._label == "80%"


def test_display_refresh_fits_each_surface_and_repositions_idle_pill(audit_app, monkeypatch):
    window = DynamicNotchWindow()
    window._is_pinned = True
    window.show()
    screen = QRect(-300, 25, 240, 360)
    monkeypatch.setattr(window, "_get_current_screen_geometry", lambda: screen)
    assert not screen.contains(window.geometry())
    window._schedule_display_refresh()
    audit_app.processEvents()
    assert screen.contains(window.geometry())
    for state in (NotchState.PEEK, NotchState.ISLAND, NotchState.EXPANDED):
        window._transition_to(state, animate=False)
        assert screen.contains(window.geometry())
        if state == NotchState.PEEK:
            button = window.btn_peek_volume
            assert screen.contains(button.mapToGlobal(button.rect().bottomRight()))


def test_drawer_animates_tab_height_changes(audit_app, monkeypatch):
    window = DynamicNotchWindow({"appearance": {"layout": "Instrument"}})
    window._is_pinned = True
    monkeypatch.setattr(window, "_get_current_screen_geometry", lambda: QRect(0, 0, 960, 600))
    window.show()
    window._transition_to(NotchState.EXPANDED, "Home", animate=False)
    before = window.height()
    window._switch_to_tab_by_name("Music")
    assert window.anim.state() == window.anim.State.Running
    assert window._displayed_geometry().height() == before
    window.anim.setCurrentTime(window.anim.duration())
    assert window.height() < before


def test_raw_input_dismisses_on_press_and_stops_when_pinned(audit_app, monkeypatch):
    window = DynamicNotchWindow()
    monkeypatch.setattr(window, "_sync_notch_shadow", lambda *_: None)
    monkeypatch.setattr(type(audit_app), "platformName", lambda: "windows")
    calls = []
    monkeypatch.setattr("poppy.core.window.register_mouse_input", lambda hwnd: calls.append(hwnd) or True)
    monkeypatch.setattr("poppy.core.window.is_mouse_press", lambda handle: handle == 123)
    window.show()
    window._transition_to(NotchState.EXPANDED, animate=False)
    assert window._outside_click_registered and not window._click_outside_timer.isActive()
    window._toggle_pin()
    assert not window._outside_click_registered and calls[-1] is None
    window._toggle_pin()
    position = window.geometry().bottomRight() + QPoint(8, 8)
    monkeypatch.setattr("poppy.core.window.QCursor.pos", lambda: position)
    message = wintypes.MSG()
    message.message = WM_INPUT
    message.lParam = 123
    window.nativeEvent(b"windows_generic_MSG", ctypes.addressof(message))
    audit_app.processEvents()
    assert window.state == NotchState.COLLAPSED
    assert not window._outside_click_registered
