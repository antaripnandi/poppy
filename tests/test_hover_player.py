"""Compact media preview layout, playback actions and hover transitions."""

import pytest
from PySide6.QtCore import Qt, QRect, QPoint, QPointF, QBuffer, QIODevice
from PySide6.QtGui import QColor, QImage, QContextMenuEvent
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


def test_hover_metadata_and_controls_fit_all_themes(audit_app, monkeypatch):
    window = DynamicNotchWindow()
    monkeypatch.setattr(window.lyrics_manager, "request_lyrics", lambda *args: None)
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
    assert window._leave_timer.isActive()
    monkeypatch.setattr(module.QApplication, "mouseButtons", lambda: Qt.MouseButton.NoButton)
    window._on_leave_timeout()
    assert window.state == NotchState.COLLAPSED
    assert not window._peek_opacity.isEnabled()
    window.close()


def test_idle_pill_shows_only_clock_before_and_after_a_media_session(audit_app, monkeypatch):
    from poppy.core.window import QCursor
    window = DynamicNotchWindow()
    window.show()
    monkeypatch.setattr(QCursor, "pos", lambda: window.geometry().center())
    media_widgets = (window.coll_thumb, window.coll_visualizer, window.coll_status_dot)
    assert all(widget.isHidden() for widget in media_widgets)
    assert window.lbl_clock.isVisible()
    window._on_hover_peek_timeout()
    assert window.state == NotchState.COLLAPSED
    window._on_media_changed({"title": "Video"})
    assert all(widget.isVisible() for widget in media_widgets)
    window._transition_to(NotchState.PEEK)
    window._on_media_changed({"title": "No Media Playing"})
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
    anchor = button.mapToGlobal(QPoint(button.width() // 2, 0))
    assert popup.bottom() < anchor.y()
    assert abs(popup.center().x() - anchor.x()) <= 1
    assert popup.top() >= window._get_current_screen_geometry().top()
    skip = window.btn_peek_next
    assert not popup.intersects(QRect(skip.mapToGlobal(QPoint()), skip.size()))
    assert window.peek_volume.orientation() == Qt.Orientation.Vertical
    assert window.lbl_peek_volume.text() == "45%"
    slider = window.peek_volume
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
