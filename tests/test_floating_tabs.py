"""Live content must remain visible and functional after moving between windows."""

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QLabel, QPushButton

from poppy.core.window import DynamicNotchWindow, NotchState
from poppy.ui.components import CardFrame


@pytest.fixture
def window(audit_app, monkeypatch):
    window = DynamicNotchWindow()
    monkeypatch.setattr(window, "_get_current_screen_geometry", lambda: QRect(0, 0, 1440, 1000))
    monkeypatch.setattr(window.lyrics_manager, "request_lyrics", lambda *args: None)
    window._is_pinned = True
    window.show()
    window._transition_to(NotchState.EXPANDED)
    window.anim.setCurrentTime(window.anim.duration())
    window._anim_opacity.setCurrentTime(window._anim_opacity.duration())
    audit_app.processEvents()
    yield window
    window.close()


@pytest.mark.parametrize("name", ["Home", "Music", "Calendar", "Clipboard", "Docs", "Desktops", "Timer", "Shelf", "Notes"])
def test_float_shows_live_content_and_close_keeps_current_tab(window, audit_app, name):
    window._switch_to_tab_by_name(name, animate=False)
    view = window.tab_stack.currentWidget()
    index = window.tab_stack.currentIndex()
    window._pop_out_current_tab()
    audit_app.processEvents()
    dialog = window._floating_windows[0]
    assert view.window() is dialog
    assert view.isVisible() and not view.isHidden()
    assert any(widget.isVisible() for widget in view.findChildren(QLabel) + view.findChildren(QPushButton))
    assert dialog.rect().contains(view.geometry())
    # Repeating the action raises the existing window rather than making a copy.
    window._pop_out_current_tab()
    assert window._floating_windows == [dialog]
    other = "Timer" if name == "Home" else "Home"
    window._switch_to_tab_by_name(other, animate=False)
    selected = window.tab_stack.currentWidget()
    dialog.close()
    audit_app.processEvents()
    assert window.tab_stack.widget(index) is view
    assert window.tab_stack.currentWidget() is selected
    assert window._floating_windows == []
    window._switch_to_tab_by_name(name, animate=False)
    assert view.isVisible()


def test_floating_music_keeps_lyrics_and_notes_survive_round_trip(window, audit_app, monkeypatch):
    requested = []
    monkeypatch.setattr(window.lyrics_manager, "request_lyrics", lambda *args: requested.append(args))
    window._switch_to_tab_by_name("Music", animate=False)
    window._on_media_changed({"title": "First track", "artist": "Artist"})
    window._pop_out_current_tab()
    dialog = window._floating_windows[0]
    window._switch_to_tab_by_name("Home", animate=False)
    window._on_media_changed({"title": "Next track", "artist": "Another artist"})
    assert requested[-1] == ("Next track", "Another artist", "", 0)
    assert window.tab_music.lbl_title.toolTip() == "Next track"
    dialog.close()
    window._switch_to_tab_by_name("Notes", animate=False)
    editor = window.tab_notes.editor
    editor.setPlainText("Keep this note")
    window._pop_out_current_tab()
    audit_app.processEvents()
    assert editor.isVisible()
    window._floating_windows[0].close()
    assert window.tab_notes.editor is editor
    assert editor.toPlainText() == "Keep this note"


def test_floating_music_fits_short_screen_and_theme_changes(window, audit_app, monkeypatch):
    screen = QRect(0, 0, 800, 600)
    monkeypatch.setattr(window, "_get_current_screen_geometry", lambda: screen)
    window._switch_to_tab_by_name("Music", animate=False)
    window.tab_music.update_sessions_list([{"index": i, "display_name": f"Player {i}"} for i in range(4)], 0)
    window._pop_out_current_tab()
    dialog = window._floating_windows[0]
    for name in ("Classic", "Soft", "Instrument", "Paper"):
        window._apply_live_appearance({"layout": name, "mode": "Light", "layout_version": 3})
        audit_app.processEvents()
        assert screen.contains(dialog.geometry())
        assert window.tab_music.isVisible()
        for control in (window.tab_music.btn_play, window.tab_music.scrubber, window.tab_music.vol_slider):
            assert dialog.rect().contains(QRect(control.mapTo(dialog, control.rect().topLeft()), control.size()))
    dialog.close()
