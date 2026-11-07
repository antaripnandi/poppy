"""Compact media preview layout, playback actions and hover transitions."""

import pytest
from PySide6.QtCore import Qt, QRect, QPoint, QPointF, QBuffer, QIODevice
from PySide6.QtGui import QColor, QImage, QContextMenuEvent, QEnterEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMenu
from poppy.core.window import DynamicNotchWindow, NotchState
from poppy.core.media_manager import MediaManager
from poppy.ui.theme import LAYOUT_THEMES
from poppy.ui.settings_window import SettingsWindow


def settle(window, app):
    window.anim.setCurrentTime(window.anim.duration())
    if window._peek_fade.state() == window._peek_fade.State.Running:
        window._peek_fade.setCurrentTime(window._peek_fade.duration())
    app.processEvents()


def test_level_gestures_retarget_the_pill_and_restore_the_clock(audit_app, monkeypatch):
    window = DynamicNotchWindow()
    volume = [46]
    brightness = []
    brightness_reads = []
    monkeypatch.setattr(window.audio_ctrl, "get_volume", lambda: volume[-1])
    monkeypatch.setattr(window.audio_ctrl, "get_mute", lambda: False)
    monkeypatch.setattr(window.audio_ctrl, "set_volume", volume.append)
    monkeypatch.setattr(window.bright_ctrl, "set_brightness", brightness.append)
    monkeypatch.setattr(window.bright_ctrl, "request_brightness", lambda: brightness_reads.append(True))
    window.show()
    window._on_brightness_read(60)
    size = window.size()
    center = QPointF(window.rect().center())
    pointer = QPointF(window.geometry().center())

    def scroll(delta, modifiers=Qt.KeyboardModifier.NoModifier):
        event = QWheelEvent(center, pointer, QPoint(), QPoint(0, delta),
                            Qt.MouseButton.NoButton, modifiers, Qt.ScrollPhase.NoScrollPhase, False)
        audit_app.sendEvent(window, event)
        assert event.isAccepted()

    scroll(120)
    assert volume[-1] == 48
    assert window.pill_level.isVisible() and not window.lbl_clock.isVisible()
    assert window.pill_level.accessibleDescription() == "48%"
    window.pill_level._motion.setCurrentTime(60)
    intermediate = window.pill_level._value
    assert 46 < intermediate < 48
    scroll(-120)
    assert volume[-1] == 46
    assert window.pill_level._motion.startValue() == intermediate
    window.pill_level._motion.setCurrentTime(window.pill_level._motion.duration())
    assert window.pill_level._value == 46

    scroll(-120, Qt.KeyboardModifier.ShiftModifier)
    assert brightness_reads and not brightness
    window._on_brightness_read(70)
    assert brightness == [65] and volume == [46, 48, 46]
    assert window.pill_level.accessibleName() == "Brightness"
    assert window.pill_level.accessibleDescription() == "65%"
    assert window.size() == size and window.state == NotchState.COLLAPSED
    monkeypatch.setattr("poppy.core.window.QCursor.pos", lambda: pointer.toPoint())
    window._on_hover_peek_timeout()
    assert window.state == NotchState.COLLAPSED

    monkeypatch.setattr("poppy.core.window.QCursor.pos", lambda: QPoint(-100, -100))
    window._pill_level_timer.start(1)
    QTest.qWait(30)
    assert window.lbl_clock.isVisible() and not window.pill_level.isVisible()
    window.close()


def test_hover_metadata_and_controls_fit_all_themes(audit_app, monkeypatch):
    window = DynamicNotchWindow()
    monkeypatch.setattr(window.lyrics_manager, "request_lyrics", lambda *args: None)
    monkeypatch.setattr("poppy.core.window.QCursor.pos", lambda: window.geometry().center())
    window.show()
    title = "A long track title with <literal text> " * 8
    artist = "An artist with a long name " * 6
    window._on_media_changed({"title": title, "artist": artist, "is_playing": True})
    window._on_sessions_updated([{"index": 0, "display_name": "An unusually long player name"},
                                 {"index": 1, "display_name": "Another player"}], 0)
    window._transition_to(NotchState.PEEK)
    settle(window, audit_app)
    for mode in ("Dark", "Light"):
        for layout in LAYOUT_THEMES:
            window._apply_live_appearance({"layout": layout, "mode": mode, "layout_version": 3})
            audit_app.processEvents()
            window._elide_peek_metadata()
            assert window.size() == window.view_peek.size()
            assert window.lbl_peek_title.textFormat() == Qt.TextFormat.PlainText
            assert window.lbl_peek_title.toolTip() == title
            assert window.lbl_peek_artist.toolTip() == artist
            assert window.lbl_peek_title.fontMetrics().horizontalAdvance(window.lbl_peek_title.text()) <= window.lbl_peek_title.width()
            assert window.lbl_peek_artist.fontMetrics().horizontalAdvance(window.lbl_peek_artist.text()) <= window.lbl_peek_artist.width()
            controls = (window.peek_thumb, window.lbl_peek_title, window.lbl_peek_artist, window.peek_visualizer,
                        window.btn_peek_prev, window.btn_peek_play, window.btn_peek_next,
                        window.peek_seek, window.btn_peek_volume)
            for widget in controls:
                assert window.view_peek.rect().contains(QRect(widget.mapTo(window.view_peek, QPoint()), widget.size()))
            assert window.peek_thumb.width() > window.btn_peek_play.width() * 2
            assert window.peek_thumb.geometry().right() < window.lbl_peek_title.mapTo(window.view_peek, QPoint()).x()
            buttons = (window.btn_peek_prev, window.btn_peek_play, window.btn_peek_next)
            centers = [button.mapTo(window.view_peek, button.rect().center()) for button in buttons]
            assert centers[0].x() < centers[1].x() < centers[2].x()
            assert max(point.y() for point in centers) - min(point.y() for point in centers) <= 1
            assert not window.peek_volume.isVisible()
    assert window.btn_peek_play.accessibleName() == "Pause"
    assert not window._peek_opacity.isEnabled()
    window._on_media_changed({"title": "No Media Playing"})
    assert window.lbl_peek_title.text() == "Nothing playing"
    assert not window.btn_peek_play.isEnabled()
    window.close()


def test_playback_controls_keep_peek_open_and_artwork_opens_home(audit_app, monkeypatch):
    calls = []
    monkeypatch.setattr(MediaManager, "toggle_play_pause", lambda self: calls.append("play"))
    monkeypatch.setattr(MediaManager, "next_track", lambda self: calls.append("next"))
    monkeypatch.setattr(MediaManager, "previous_track", lambda self: calls.append("previous"))
    window = DynamicNotchWindow()
    monkeypatch.setattr(window.lyrics_manager, "request_lyrics", lambda *args: None)
    window._is_pinned = True
    window.show()
    window._on_media_changed({"title": "Track", "artist": "Artist"})
    window._transition_to(NotchState.PEEK)
    settle(window, audit_app)
    for button in (window.btn_peek_play, window.btn_peek_next, window.btn_peek_prev):
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        assert window.state == NotchState.PEEK
    assert calls == ["play", "next", "previous"]
    QTest.mouseClick(window.peek_thumb, Qt.MouseButton.LeftButton)
    assert window.state == NotchState.EXPANDED
    assert window.tab_stack.currentWidget() is window.tab_home
    assert not window._peek_opacity.isEnabled()
    window.close()


def test_hover_retries_during_collapse_and_does_not_dismiss_while_pressed(audit_app, monkeypatch):
    import poppy.core.window as module
    window = DynamicNotchWindow()
    window.show()
    window._on_media_changed({"title": "Track"})
    window._transition_to(NotchState.PEEK)
    settle(window, audit_app)
    window._collapse_to_pill()
    monkeypatch.setattr(module.QCursor, "pos", lambda: window.geometry().center())
    window._on_hover_peek_timeout()
    assert window._hover_peek_timer.isActive()
    window.anim.setCurrentTime(window.anim.duration())
    window._on_hover_peek_timeout()
    assert window.state == NotchState.PEEK
    monkeypatch.setattr(module.QCursor, "pos", lambda: window.geometry().bottomRight() + QPoint(100, 100))
    monkeypatch.setattr(module.QApplication, "mouseButtons", lambda: Qt.MouseButton.LeftButton)
    window._on_leave_timeout()
    assert window.state == NotchState.PEEK
    assert window._peek_presence_timer.isActive()
    monkeypatch.setattr(module.QApplication, "mouseButtons", lambda: Qt.MouseButton.NoButton)
    window._on_leave_timeout()
    assert window.state == NotchState.COLLAPSED
    assert not window._peek_opacity.isEnabled()
    window.close()


@pytest.mark.parametrize("volume_popup", [False, True])
def test_peek_collapses_if_windows_misses_the_leave_event(audit_app, monkeypatch, volume_popup):
    from poppy.core.window import QCursor
    window = DynamicNotchWindow()
    window.show()
    window._on_media_changed({"title": "Track"})
    window._transition_to(NotchState.PEEK)
    settle(window, audit_app)
    pointer = window.geometry().center()
    monkeypatch.setattr(QCursor, "pos", lambda: pointer)
    if volume_popup:
        window.btn_peek_volume.click()
        pointer = window.peek_volume_menu.geometry().center()
        QTest.qWait(500)
        assert window.state == NotchState.PEEK
        assert window.peek_volume_menu.isVisible()

    # Only the cursor position changes. Qt never receives a Leave event.
    pointer = window.geometry().topLeft() - QPoint(80, 80)
    for _ in range(20):
        if window.state == NotchState.COLLAPSED:
            break
        QTest.qWait(40)
    assert window.state == NotchState.COLLAPSED
    assert not window.peek_volume_menu.isVisible()
    assert not window._peek_presence_timer.isActive()
    window.close()


def test_idle_hover_opens_and_stays_open_when_a_media_session_ends(audit_app, monkeypatch):
    from poppy.core.window import QCursor
    window = DynamicNotchWindow({"notch": {"auto_hover_peek": False}})
    window.show()
    pointer = window.geometry().center()
    monkeypatch.setattr(QCursor, "pos", lambda: pointer)
    media_widgets = (window.coll_thumb, window.coll_visualizer, window.coll_status_dot)
    transport = (window.btn_peek_prev, window.btn_peek_play, window.btn_peek_next, window.peek_seek)
    assert all(widget.isHidden() for widget in media_widgets)
    assert window.lbl_clock.isVisible()

    local = QPointF(window.mapFromGlobal(pointer))
    enter = QEnterEvent(local, local, QPointF(pointer))
    window.enterEvent(enter)
    assert not window._hover_peek_timer.isActive()
    window._on_hover_peek_timeout()
    assert window.state == NotchState.COLLAPSED

    window.config["notch"]["auto_hover_peek"] = True
    window.enterEvent(enter)
    assert window._hover_peek_timer.isActive()
    window._on_hover_peek_timeout()
    settle(window, audit_app)
    assert window.state == NotchState.PEEK
    assert window.lbl_peek_title.text() == "Nothing playing"
    assert window.peek_visualizer.isHidden()
    assert all(not button.isEnabled() for button in transport)
    window.btn_peek_volume.click()
    assert window.peek_volume_menu.isVisible()

    window._on_media_changed({"title": "Video", "can_seek": True, "position_sec": 15, "duration_sec": 45})
    assert window.lbl_peek_title.text() == "Video"
    assert all(button.isEnabled() for button in transport)
    window._on_media_changed({"title": "No Media Playing"})
    assert window.state == NotchState.PEEK
    assert window.peek_volume_menu.isVisible()
    assert window.lbl_peek_title.text() == "Nothing playing"
    assert all(not button.isEnabled() for button in transport)
    assert window.peek_seek.value() == 0

    window.peek_volume_menu.hide()
    pointer = window.geometry().topLeft() - QPoint(100, 100)
    window._on_leave_timeout()
    settle(window, audit_app)
    assert window.state == NotchState.COLLAPSED
    assert all(widget.isHidden() for widget in media_widgets)
    assert window.lbl_clock.isVisible()
    QTest.mouseClick(window.lbl_clock, Qt.MouseButton.LeftButton)
    assert window.state == NotchState.EXPANDED
    assert window.tab_stack.currentWidget() is window.tab_home
    window.close()


def test_peek_seeks_and_fixed_color_survives_layout_changes(audit_app, monkeypatch):
    calls = []
    monkeypatch.setattr(MediaManager, "seek", lambda self, value: calls.append(value))
    window = DynamicNotchWindow()
    window.show()
    window._on_media_changed({"title": "Track", "position_sec": 25, "duration_sec": 100, "can_seek": True})
    window._transition_to(NotchState.PEEK)
    settle(window, audit_app)
    assert window.peek_seek.value() == 25
    assert window.peek_seek.toolTip() == "00:25 / 01:40"
    assert window.peek_seek.isVisible()
    QTest.mouseClick(window.peek_seek, Qt.MouseButton.LeftButton, pos=window.peek_seek.rect().center())
    assert 48 <= calls[-1] <= 52
    assert window.state == NotchState.PEEK
    point = window.rect().center()
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, window.mapToGlobal(point))
    window.contextMenuEvent(event)
    menu = audit_app.activePopupWidget()
    assert isinstance(menu, QMenu)
    actions = {action.text(): action for action in menu.actions()}
    assert actions["Sound output"].menu() is not None
    assert "Toggle mute" in actions
    menu.hide()
    for layout, mode in (("Deck", "Dark"), ("Daily", "Light"), ("Console", "Dark")):
        window._apply_live_appearance({"layout": layout, "mode": mode, "peek_color_source": "fixed", "peek_color": "#244f58"})
        assert window.grab().toImage().pixelColor(window.width() // 2, 6) == QColor("#244f58")
        assert "background: transparent" in window.btn_peek_play.styleSheet()
        assert not window.btn_peek_play.icon().isNull()
    window.close()


def test_volume_opens_a_vertical_slider_and_applies_drag_values(audit_app, monkeypatch):
    window = DynamicNotchWindow()
    levels = []
    monkeypatch.setattr(window.audio_ctrl, "set_volume", levels.append)
    monkeypatch.setattr(window.audio_ctrl, "get_mute", lambda: False)
    window.show()
    window._on_media_changed({"title": "Track"})
    window._transition_to(NotchState.PEEK)
    settle(window, audit_app)
    window._show_volume(45, False)
    assert not window.peek_volume_menu.isVisible()
    QTest.mouseClick(window.btn_peek_volume, Qt.MouseButton.LeftButton)
    assert window.peek_volume_menu.isVisible()
    button = window.btn_peek_volume
    popup = window.peek_volume_menu.geometry()
    anchor = button.mapToGlobal(button.rect().center())
    assert popup.top() > window.geometry().bottom()
    assert abs(popup.center().x() - anchor.x()) <= 1
    assert popup.top() >= window._get_current_screen_geometry().top()
    skip = window.btn_peek_next
    assert not popup.intersects(QRect(skip.mapToGlobal(QPoint()), skip.size()))
    assert window.peek_volume.orientation() == Qt.Orientation.Vertical
    assert window.lbl_peek_volume.text() == "45%"
    slider = window.peek_volume
    assert slider.height() >= 128
    x = slider.width() // 2
    top = QPoint(x, round(slider.height() * 0.15))
    bottom = QPoint(x, round(slider.height() * 0.85))
    QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=bottom)
    QTest.mouseMove(slider, QPoint(x, slider.height() // 2))
    QTest.mouseMove(slider, top)
    QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=top)
    assert len(levels) >= 3
    assert levels == sorted(levels)
    assert levels[0] < 25 and levels[-1] > 80
    assert window.lbl_peek_volume.text() == f"{levels[-1]}%"
    assert window.state == NotchState.PEEK
    QTest.keyClick(slider, Qt.Key.Key_Escape)
    assert not window.peek_volume_menu.isVisible()
    window.btn_peek_volume.click()
    assert window.peek_volume_menu.isVisible()
    assert window.peek_volume_menu.geometry() == popup
    window._collapse_to_pill()
    assert not window.peek_volume_menu.isVisible()
    window.close()


@pytest.mark.parametrize("style", ["Notch", "Pill"])
def test_hover_reveal_keeps_window_and_content_centered(audit_app, style):
    window = DynamicNotchWindow({"appearance": {"style": style, "collapsed_width": 239}})
    window.show()
    window._on_media_changed({"title": "Track"})
    center = window.x() + window.width() / 2
    window._transition_to(NotchState.PEEK)
    widths = []
    for fraction in (0, 0.15, 0.35, 0.6, 1):
        window.anim.setCurrentTime(round(window.anim.duration() * fraction))
        audit_app.processEvents()
        widths.append(window.width())
        assert abs(window.x() + window.width() / 2 - center) <= 1
        assert abs(window.view_peek.x() + window.view_peek.width() / 2 - window.width() / 2) <= 1
    assert widths[0] < widths[1] < widths[-1]
    window.close()


def test_collapsed_artwork_resizes_and_notch_flare_matches_the_mask(audit_app):
    window = DynamicNotchWindow()
    window.show()
    artwork = QImage(64, 48, QImage.Format.Format_ARGB32)
    artwork.fill(QColor("#337799"))
    encoded = QBuffer()
    encoded.open(QIODevice.OpenModeFlag.WriteOnly)
    assert artwork.save(encoded, "PNG")
    window._on_media_changed({"title": "Track", "thumbnail_bytes": bytes(encoded.data())})
    sizes = []
    for width, height in ((180, 24), (340, 44)):
        window._apply_live_appearance({"collapsed_width": width, "collapsed_height": height})
        sizes.append(window.coll_thumb.width())
        pixmap = window.coll_thumb.pixmap()
        assert pixmap.deviceIndependentSize().width() == window.coll_thumb.width()
        assert pixmap.toImage().pixelColor(0, 0).alpha() == 0
        assert window._notch_path().contains(QPointF(8, 1))
        assert not window._notch_path().contains(QPointF(2, height / 2))
        assert not window.mask().contains(QPoint(2, height // 2))
    assert sizes[1] > sizes[0]
    window.close()


def test_settings_round_trip_fixed_hover_color(audit_app, monkeypatch):
    monkeypatch.setattr("poppy.ui.settings_window.QColorDialog.getColor", lambda *_: QColor("#93beb2"))
    settings = SettingsWindow({})
    saved = []
    settings.settings_saved.connect(saved.append)
    settings.combo_peek_color.setCurrentIndex(settings.combo_peek_color.findData("fixed"))
    settings.btn_peek_color.click()
    assert settings._save_settings()
    restored = SettingsWindow(saved[-1])
    assert restored.combo_peek_color.currentData() == "fixed"
    assert restored.btn_peek_color.text() == "#93BEB2"
