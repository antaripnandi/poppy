"""Compact media preview layout, playback actions and hover transitions."""

import pytest
from PySide6.QtCore import Qt, QRect, QPoint
from PySide6.QtTest import QTest
from poppy.core.window import DynamicNotchWindow, NotchState
from poppy.core.media_manager import MediaManager
from poppy.ui.theme import LAYOUT_THEMES


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
            controls = (window.peek_thumb, window.lbl_peek_title, window.lbl_peek_artist,
                        window.btn_peek_cycle, window.btn_peek_prev, window.btn_peek_play, window.btn_peek_next)
            for widget in controls:
                assert window.view_peek.rect().contains(QRect(widget.mapTo(window.view_peek, QPoint()), widget.size()))
            assert window.lbl_peek_title.mapTo(window.view_peek, QPoint()).y() < window.btn_peek_cycle.mapTo(window.view_peek, QPoint()).y()
    assert window.btn_peek_play.accessibleName() == "Pause"
    assert not window._peek_opacity.isEnabled()
    window._on_media_changed({"title": "No Media Playing"})
    assert window.lbl_peek_title.text() == "Nothing playing"
    assert not window.btn_peek_play.isEnabled()
    window.close()


def test_playback_controls_do_not_open_drawer_but_artwork_does(audit_app, monkeypatch):
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
    assert window.tab_stack.currentWidget() is window.tab_music
    assert not window._peek_opacity.isEnabled()
    window.close()


def test_hover_retries_during_collapse_and_does_not_dismiss_while_pressed(audit_app, monkeypatch):
    import poppy.core.window as module
    window = DynamicNotchWindow()
    window.show()
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
