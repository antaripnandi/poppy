"""Screen drawing input, rendering and overlay lifecycle."""

import pytest
from PySide6.QtCore import Qt, QEvent, QPoint, QPointF, QRect
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtTest import QTest

from poppy.ui.extended_views import ScreenAnnotationOverlay
from poppy.core.window import DynamicNotchWindow, NotchState


@pytest.fixture
def canvas(audit_app):
    overlay = ScreenAnnotationOverlay(screen_geometry=QRect(0, 0, 800, 600))
    overlay.show()
    audit_app.processEvents()
    yield overlay
    overlay.close()


def stroke(app, overlay, points):
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=points[0])
    for point in points[1:-1]:
        app.sendEvent(overlay, QMouseEvent(QEvent.Type.MouseMove, QPointF(point),
            QPointF(overlay.mapToGlobal(point)), Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=points[-1])
    app.processEvents()


def _pixel(image, x, y):
    scale = image.devicePixelRatio()
    return image.pixelColor(round(x * scale), round(y * scale))


def test_empty_canvas_has_an_input_layer_and_clear_preserves_it(canvas, audit_app):
    # Alpha zero is the Windows click-through case that direct Qt input tests miss.
    image = canvas.grab().toImage()
    assert 0 < _pixel(image, 100, 200).alpha() <= 2
    stroke(audit_app, canvas, [QPoint(100, 200), QPoint(120, 200), QPoint(150, 200)])
    assert len(canvas._paths) == 1
    drawn = _pixel(canvas.grab().toImage(), 120, 200)
    assert drawn.red() > 200 and drawn.alpha() == 255
    canvas.btn_clear.click()
    cleared = _pixel(canvas.grab().toImage(), 120, 200)
    assert canvas._paths == []
    assert 0 < cleared.alpha() <= 2


def test_clicks_draw_dots_and_release_keeps_the_last_segment(canvas, audit_app):
    stroke(audit_app, canvas, [QPoint(100, 200), QPoint(100, 200)])
    assert _pixel(canvas.grab().toImage(), 100, 200).alpha() == 255
    stroke(audit_app, canvas, [QPoint(200, 200), QPoint(250, 200)])
    assert canvas._paths[-1][0].currentPosition() == QPointF(250, 200)
    assert _pixel(canvas.grab().toImage(), 230, 200).red() > 200


def test_color_controls_do_not_add_marks_or_recolor_old_strokes(canvas, audit_app):
    stroke(audit_app, canvas, [QPoint(100, 200), QPoint(150, 200)])
    QTest.mouseClick(canvas.color_buttons[2], Qt.MouseButton.LeftButton)
    assert len(canvas._paths) == 1
    assert canvas._pen_color == QColor(56, 189, 248)
    assert canvas.color_buttons[2].isChecked()
    stroke(audit_app, canvas, [QPoint(100, 250), QPoint(150, 250)])
    assert canvas._paths[0][1] == QColor(239, 68, 68)
    assert canvas._paths[1][1] == QColor(56, 189, 248)


def test_shift_preserves_ink_and_toolbar_while_canvas_passes_input(canvas, audit_app, monkeypatch):
    stroke(audit_app, canvas, [QPoint(100, 200), QPoint(150, 200)])
    toggle = Qt.WindowType.WindowTransparentForInput
    shift = False
    monkeypatch.setattr(canvas, "_shift_down", lambda: shift)
    monkeypatch.setattr(canvas, "_mouse_down", lambda: False)

    shift = True
    canvas._sync_input_mode()
    assert canvas.windowHandle().flags() & toggle
    assert not canvas.toolbar.windowHandle().flags() & toggle
    image = canvas.grab().toImage()
    assert _pixel(image, 120, 200).alpha() == 255
    assert _pixel(image, 120, 240).alpha() == 0
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=QPoint(100, 250))
    assert len(canvas._paths) == 1

    shift = False
    canvas._sync_input_mode()
    assert not canvas.windowHandle().flags() & toggle
    stroke(audit_app, canvas, [QPoint(100, 250), QPoint(150, 250)])
    assert len(canvas._paths) == 2


def test_switches_without_splitting_a_mouse_gesture(canvas, monkeypatch):
    shift = False
    mouse_down = False
    monkeypatch.setattr(canvas, "_shift_down", lambda: shift)
    monkeypatch.setattr(canvas, "_mouse_down", lambda: mouse_down)
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(100, 200))
    shift = True
    canvas._sync_input_mode()
    assert not canvas._passing_input
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(150, 200))
    assert canvas._paths[-1][0].currentPosition() == QPointF(150, 200)
    assert canvas._passing_input

    shift = False
    mouse_down = True
    canvas._sync_input_mode()
    assert canvas._passing_input
    mouse_down = False
    canvas._sync_input_mode()
    assert not canvas._passing_input
    QTest.mouseClick(canvas.btn_interact, Qt.MouseButton.LeftButton)
    assert canvas._passing_input
    QTest.mouseClick(canvas.btn_interact, Qt.MouseButton.LeftButton)
    assert not canvas._passing_input


def test_button_uses_selected_monitor_and_escape_from_toolbar_cleans_up(audit_app, monkeypatch):
    window = DynamicNotchWindow()
    screen = QRect(-1280, 0, 1280, 720)
    monkeypatch.setattr(window, "_get_current_screen_geometry", lambda: screen)
    window._is_pinned = True
    window.show()
    window._transition_to(NotchState.EXPANDED)
    window.btn_hdr_pencil.click()
    overlay = window._annotation_overlay
    assert overlay is not None
    audit_app.processEvents()
    assert overlay.geometry() == screen
    assert screen.contains(overlay.toolbar.geometry())
    assert window.state == NotchState.COLLAPSED
    assert not window._hover_peek_timer.isActive()
    closed = []
    overlay.closed.connect(lambda: closed.append(True))
    overlay.btn_clear.setFocus()
    QTest.keyClick(overlay.btn_clear, Qt.Key.Key_Escape)
    assert closed == [True]
    assert window._annotation_overlay is None
    window._toggle_annotation()
    assert window._annotation_overlay is not overlay
    window._annotation_overlay.btn_close.click()
    assert window._annotation_overlay is None
    window._toggle_annotation()
    window.close()
    assert window._annotation_overlay is None
