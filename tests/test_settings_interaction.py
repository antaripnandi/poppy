"""Settings input, scrolling and avoiding expensive work during geometry previews."""

import pytest
from PySide6.QtCore import Qt, QPoint, QPointF, QEvent
from PySide6.QtGui import QWheelEvent, QMouseEvent
from PySide6.QtTest import QTest

from poppy.core.window import DynamicNotchWindow
from poppy.ui.settings_window import SettingsWindow

_sync_hardware = DynamicNotchWindow._sync_system_controls


@pytest.fixture
def connected_settings(audit_app):
    window = DynamicNotchWindow()
    settings = SettingsWindow(window.config)
    window._settings_window = settings
    settings.appearance_live_updated.connect(window._apply_live_appearance)
    settings.show()
    audit_app.processEvents()
    yield window, settings
    settings.close()
    window.close()


def wheel(widget, angle=-120, pixels=0):
    position = widget.rect().center()
    event = QWheelEvent(QPointF(position), QPointF(widget.mapToGlobal(position)),
        QPoint(0, pixels), QPoint(0, angle), Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    from PySide6.QtWidgets import QApplication
    QApplication.sendEvent(widget, event)


def test_wheel_scrolls_settings_instead_of_changing_hovered_fields(connected_settings, audit_app):
    _, settings = connected_settings
    page = settings.stack.currentWidget()
    bar = page.verticalScrollBar()
    assert bar.maximum() > 0
    for field, getter in ((settings.combo_layout, settings.combo_layout.currentIndex),
                          (settings.slider_col_w, settings.slider_col_w.value),
                          (settings.lbl_val_col_w, settings.lbl_val_col_w.value)):
        page.ensureWidgetVisible(field)
        audit_app.processEvents()
        before_scroll, before_value = bar.value(), getter()
        wheel(field, angle=-120 if before_scroll < bar.maximum() else 120)
        assert getter() == before_value
        assert bar.value() != before_scroll


def test_slider_track_drag_keyboard_and_exact_numeric_entry(connected_settings, audit_app):
    _, settings = connected_settings
    slider = settings.slider_col_w
    page = settings.stack.currentWidget()
    page.ensureWidgetVisible(slider)
    audit_app.processEvents()
    y = slider.height() // 2
    QTest.mouseClick(slider, Qt.MouseButton.LeftButton, pos=QPoint(105, y))
    assert slider.value() > 300  # Clicking the track jumps rather than advancing one page.
    QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=QPoint(20, y))
    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(129, y), QPointF(129, y),
                       Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    audit_app.sendEvent(slider, event)
    QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=QPoint(129, y))
    assert slider.value() == slider.maximum()
    exact = settings.lbl_val_col_w
    exact.setText("203")
    QTest.keyClick(exact, Qt.Key.Key_Return)
    assert slider.value() == exact.value() == 203
    assert exact.contentsRect().width() > exact.fontMetrics().horizontalAdvance("1200")
    QTest.keyClick(slider, Qt.Key.Key_Right)
    assert slider.value() == exact.value() == 204
    exact.setText("999")
    QTest.keyClick(exact, Qt.Key.Key_Return)
    assert exact.text() == "204"
    assert slider.value() == 204


def test_pixel_wheel_input_scrolls_settings(connected_settings):
    _, settings = connected_settings
    page = settings.stack.currentWidget()
    page.ensureWidgetVisible(settings.slider_col_w)
    before = page.verticalScrollBar().value()
    wheel(settings.slider_col_w, angle=0, pixels=-35)
    assert page.verticalScrollBar().value() > before


def test_drag_previews_are_coalesced_and_do_not_restyle_or_rebuild(connected_settings, monkeypatch):
    window, settings = connected_settings
    previews = []
    settings.appearance_live_updated.connect(previews.append)
    expensive_calls = []
    def unwanted(*args, **kwargs):
        expensive_calls.append(True)
    monkeypatch.setattr("poppy.core.window.refresh_theme", unwanted)
    monkeypatch.setattr("poppy.ui.settings_window.refresh_theme", unwanted)
    monkeypatch.setattr(window.tab_home, "apply_layout", unwanted)
    for value in range(210, 230):
        settings.slider_col_w.setValue(value)
    assert previews == []
    QTest.qWait(80)
    assert len(previews) == 1
    assert window._collapsed_w == 229
    settings.slider_col_w.setValue(231)
    settings.slider_col_w.sliderReleased.emit()
    assert window._collapsed_w == 231
    QTest.qWait(80)
    assert len(previews) == 2
    assert expensive_calls == []


def test_close_cancels_pending_preview(connected_settings):
    window, settings = connected_settings
    previews = []
    settings.appearance_live_updated.connect(previews.append)
    settings.slider_col_w.setValue(203)
    assert settings._preview_timer.isActive()
    settings.close()
    QTest.qWait(80)
    assert not settings._preview_timer.isActive()
    assert window._collapsed_w == 240
    assert len(previews) == 1  # Restore saved settings, with no late draft update.


def test_geometry_preview_keeps_scroll_position(connected_settings, audit_app):
    window, settings = connected_settings
    page = settings.stack.currentWidget()
    page.ensureWidgetVisible(settings.slider_open_w)
    audit_app.processEvents()
    before = page.verticalScrollBar().value()
    for value in range(900, 925):
        settings.slider_open_w.setValue(value)
    QTest.qWait(80)
    assert page.verticalScrollBar().value() == before
    assert window._open_w == 924


def test_mode_change_performs_one_global_theme_refresh(connected_settings, monkeypatch):
    import poppy.core.window as window_module
    import poppy.ui.settings_window as settings_module
    _, settings = connected_settings
    refreshes = []
    original = window_module.refresh_theme
    monkeypatch.setattr(window_module, "refresh_theme", lambda: (refreshes.append("window"), original()))
    monkeypatch.setattr(settings_module, "refresh_theme", lambda: (refreshes.append("settings"), original()))
    settings.combo_mode.setCurrentText("Light")
    assert refreshes == ["window"]


def test_hidden_panels_do_not_query_hardware(connected_settings, monkeypatch):
    window, _ = connected_settings
    queries = []
    for controller, method in ((window.audio_ctrl, "get_volume"), (window.audio_ctrl, "get_mute"),
                               (window.audio_ctrl, "get_mic_mute"), (window.bright_ctrl, "get_brightness")):
        monkeypatch.setattr(controller, method, lambda: queries.append(True))
    _sync_hardware(window)
    assert queries == []


def test_settings_dialog_and_done_fit_on_short_monitor(audit_app, monkeypatch):
    from PySide6.QtCore import QRect
    window = DynamicNotchWindow()
    screen = QRect(0, 0, 800, 600)
    monkeypatch.setattr(window, "_get_current_screen_geometry", lambda: screen)
    window.open_settings()
    audit_app.processEvents()
    settings = window._settings_window
    assert screen.contains(settings.geometry())
    assert settings.y() >= window._collapsed_h + 12
    assert settings.rect().contains(QRect(settings.btn_done.mapTo(settings,
        settings.btn_done.rect().topLeft()), settings.btn_done.size()))
    settings.close()
    window.close()
