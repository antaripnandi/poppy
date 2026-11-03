"""Dashboard navigation, appearance modes, resizing and file actions."""

import pytest
from pathlib import Path
from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QLabel, QScrollArea

from poppy.core.drop_shelf import DropShelfManager
from poppy.core.window import DynamicNotchWindow, NotchState
from poppy.ui.settings_window import SettingsWindow
from poppy.ui.styles import get_stylesheet, get_theme, normalize_appearance
from poppy.ui.views import MusicTabView, ShelfItemRow
from poppy.ui.components import CardFrame
from poppy.ui.theme import configure_theme, is_light_theme, refresh_theme, set_widget_style, LAYOUT_THEMES
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QPushButton


@pytest.fixture
def dashboard_window(audit_app, monkeypatch):
    audit_app.setStyleSheet(get_stylesheet())
    window = DynamicNotchWindow()
    monkeypatch.setattr(window, "_get_current_screen_geometry", lambda: QRect(0, 0, 1440, 1000))
    window._is_pinned = True
    window.show()
    window._transition_to(NotchState.EXPANDED, target_tab="Music")
    window.anim.setCurrentTime(window.anim.duration())
    window._anim_opacity.setCurrentTime(window._anim_opacity.duration())
    audit_app.processEvents()
    yield window
    window.close()
    audit_app.setStyleSheet("")


def test_legacy_dimensions_migrate_once_and_custom_sizes_survive():
    assert normalize_appearance({"layout_version": 2, "open_width": 600, "open_height": 400})["open_width"] == 960
    assert normalize_appearance({"open_width": 800, "open_height": 500})["open_width"] == 800
    assert normalize_appearance({"layout_version": 3, "open_width": 960, "open_height": 480})["open_height"] == 480


def test_all_tabs_are_directly_visible_and_home_is_default(dashboard_window, audit_app):
    window = dashboard_window
    assert window._active_tab_names == list(window._tab_name_to_stack_idx)
    assert not hasattr(window, "btn_more")
    for index, name in enumerate(window._active_tab_names):
        window.tab_strip.buttons[index].click()
        audit_app.processEvents()
        assert window.tab_stack.currentIndex() == window._tab_name_to_stack_idx[name]
        assert window.width() == 960
        for button in window.tab_strip.buttons + [window.btn_settings]:
            assert window.view_expanded.rect().contains(QRect(button.mapTo(window.view_expanded, button.rect().topLeft()), button.size()))
    window._collapse_to_pill()
    window._transition_to(NotchState.EXPANDED)
    assert window.tab_stack.currentWidget() is window.tab_home
    assert not window.tab_home.lbl_music_title.isHidden()


def test_battery_polling_cannot_overlay_the_closed_pill(dashboard_window, monkeypatch):
    from types import SimpleNamespace
    window = dashboard_window
    monkeypatch.setattr("poppy.core.window.psutil.sensors_battery", lambda: SimpleNamespace(percent=100, power_plugged=True))
    monkeypatch.setattr("poppy.core.window._get_gpu_utilization", lambda: 14)
    window._collapse_to_pill()
    window.anim.setCurrentTime(window.anim.duration())
    for _ in range(5):
        window._update_system_metrics()
    assert not hasattr(window, "lbl_hdr_bat")
    assert not any("100%" in label.text() for label in window.findChildren(QLabel) if label.isVisible())
    assert window.tab_home.lbl_bat.text() == "Battery 100%"
    monkeypatch.setattr("poppy.core.window.psutil.sensors_battery", lambda: SimpleNamespace(percent=42, power_plugged=False))
    window._update_system_metrics()
    assert window.tab_home.lbl_bat.text() == "Battery 42%"
    window._switch_to_tab_by_name("Home")
    window._transition_to(NotchState.EXPANDED, target_tab="Home")
    assert window.tab_home.lbl_bat.isVisible()


def test_layout_and_mode_preview_preserves_notes_and_cancel_restores(dashboard_window, audit_app):
    window = dashboard_window
    window._switch_to_tab_by_name("Home")
    window.tab_home.txt_notes.setPlainText("Keep this unsaved note")
    original_view = window.tab_home
    settings = SettingsWindow(window.config)
    settings.appearance_live_updated.connect(window._apply_live_appearance)
    settings.show()
    settings.combo_mode.setCurrentText("Light")
    settings.combo_layout.setCurrentText("Soft")
    audit_app.processEvents()
    assert is_light_theme()
    assert window.tab_home is original_view
    assert window.tab_home.dashboard_grid.itemAtPosition(0, 1).widget() is window.tab_home.card_notes
    assert window.tab_home.lbl_big_time.palette().color(QPalette.ColorRole.WindowText).lightness() < 100
    assert window.grab().toImage().pixelColor(5, 80).lightness() > 200
    assert window.tab_home.txt_notes.toPlainText() == "Keep this unsaved note"
    settings.close()
    audit_app.processEvents()
    assert not is_light_theme()
    assert window.tab_home.dashboard_grid.itemAtPosition(0, 1).widget() is window.tab_home.card_controls
    assert window.tab_home.txt_notes.toPlainText() == "Keep this unsaved note"


def test_light_mode_preserves_hover_selectors_and_restores_authored_styles(audit_app):
    button = QPushButton("Example")
    source = "QPushButton { color: #ffffff; background: #202329; } QPushButton:hover { background: #414957; }"
    configure_theme({"mode": "Dark"})
    set_widget_style(button, source)
    button.show()
    configure_theme({"mode": "Light"})
    refresh_theme()
    audit_app.processEvents()
    assert "QPushButton:hover" in button.styleSheet()
    assert button.palette().color(QPalette.ColorRole.ButtonText).lightness() < 100
    configure_theme({"mode": "Dark"})
    refresh_theme()
    assert button.styleSheet() == source


def test_layout_selection_changes_visible_arrangements_and_restores(dashboard_window, audit_app):
    """Exercise Settings wiring, rendered geometry and cancellation across pages."""
    window = dashboard_window
    settings = SettingsWindow(window.config)
    settings.appearance_live_updated.connect(window._apply_live_appearance)
    settings.show()
    home, music = window.tab_home, window.tab_music
    home.txt_notes.setPlainText("Keep my note")
    snapshots = {}
    for name in ("Classic", "Minimal", "Soft", "Classic"):
        settings.combo_layout.setCurrentText(name)
        for tab in ("Home", "Music", "Docs"):
            window._switch_to_tab_by_name(tab, animate=False)
            window._apply_geometry_for_state(window.state, animate=False)
            audit_app.processEvents()
            if tab == "Home":
                assert (home.card_notes.y() < home.card_controls.y()) == (name == "Soft")
                if name == "Minimal":
                    assert home.card_clock.width() < home.card_controls.width()
                elif name == "Classic":
                    assert abs(home.card_clock.width() - home.card_controls.width()) <= 1
            elif tab == "Music":
                assert music.player_card.x() < music.lyrics_widget.x()
                if name == "Minimal":
                    assert music.player_card.width() < music.lyrics_widget.width()
                    assert music.lbl_large_art.width() == 96
                snapshots[name] = window.grab().toImage()
            else:
                cards = window.tab_docs.findChildren(CardFrame)
                assert cards
                assert all(card.property("layoutTheme") == name for card in cards)
        preview = settings.layout_preview
        assert (preview.cards["notes"].y() < preview.cards["controls"].y()) == (name == "Soft")
        assert settings.lbl_layout_description.text() == LAYOUT_THEMES[name]["description"]
    assert snapshots["Classic"] != snapshots["Minimal"]
    assert snapshots["Classic"] != snapshots["Soft"]
    settings.combo_layout.setCurrentText("Soft")
    settings.close()
    audit_app.processEvents()
    assert music.player_card.x() < music.lyrics_widget.x()
    assert home.txt_notes.toPlainText() == "Keep my note"
    assert home is window.tab_home and music is window.tab_music


def test_saved_layout_applies_to_music_and_other_pages_on_startup(audit_app, monkeypatch):
    monkeypatch.setattr("poppy.ui.settings_window.set_autostart_state", lambda *args: None)
    settings = SettingsWindow({"appearance": {"layout": "Classic", "layout_version": 3}})
    settings.combo_layout.setCurrentText("Soft")
    assert settings._save_settings()
    settings.close()
    from poppy.main import load_config
    window = DynamicNotchWindow(load_config())
    window.show()
    window._is_pinned = True
    window._transition_to(NotchState.EXPANDED, target_tab="Music")
    window.anim.setCurrentTime(window.anim.duration())
    window._anim_opacity.setCurrentTime(window._anim_opacity.duration())
    audit_app.processEvents()
    assert window.tab_music.player_card.x() < window.tab_music.lyrics_widget.x()
    assert window.tab_home.dashboard_grid.itemAtPosition(0, 1).widget() is window.tab_home.card_notes
    assert window.tab_docs.layout().spacing() == LAYOUT_THEMES["Soft"]["spacing"]
    window.close()


def test_follow_windows_updates_without_restarting(dashboard_window, monkeypatch):
    preference = [False]
    monkeypatch.setattr("poppy.ui.theme.windows_uses_light_theme", lambda: preference[0])
    monkeypatch.setattr("poppy.core.window._get_gpu_utilization", lambda: None)
    dashboard_window._apply_live_appearance({"mode": "System"})
    assert not is_light_theme()
    preference[0] = True
    dashboard_window._update_system_metrics()
    assert is_light_theme()
    preference[0] = False
    dashboard_window._update_system_metrics()
    assert not is_light_theme()


def test_loaded_dashboard_fits_without_scrolling(dashboard_window, audit_app, tmp_path, monkeypatch):
    window = dashboard_window
    window._switch_to_tab_by_name("Home")
    paths = []
    for index in range(8):
        path = tmp_path / f"Screenshot_2026-11-03_{index}.txt"
        path.write_text("Test file")
        paths.append(str(path))
    window.drop_shelf.add_paths(paths)
    window._on_sessions_updated([
        {"index": 0, "display_name": "Spotify"},
        {"index": 1, "display_name": "Brave"},
    ], 0)
    assert window.tab_home.findChildren(QScrollArea) == []

    for screen in (QRect(0, 0, 1440, 1000), QRect(0, 0, 800, 600)):
        monkeypatch.setattr(window, "_get_current_screen_geometry", lambda screen=screen: screen)
        for mode in ("Dark", "Light"):
            for layout in LAYOUT_THEMES:
                window._apply_live_appearance({"mode": mode, "layout": layout,
                    "open_width": 780, "open_height": 480, "layout_version": 3})
                audit_app.processEvents()
                home = window.tab_home
                assert window.height() <= screen.height() - 56
                assert home.height() >= home.minimumSizeHint().height(), (layout, mode, screen)
                for widget in (home.card_clock, home.card_controls, home.card_notes,
                               home.card_shelf, home.shelf_preview_frame, home.input_calc,
                               home.txt_notes, *home._source_pills):
                    assert home.rect().contains(QRect(widget.mapTo(home, widget.rect().topLeft()), widget.size()))


def test_lyrics_share_the_desktop_view_without_resizing(dashboard_window, audit_app, monkeypatch):
    window = dashboard_window
    original = window.size()
    assert window.tab_music.lyrics_widget.isVisible()
    window.tab_music.btn_lyrics.click()
    audit_app.processEvents()
    assert window.tab_music.lyrics_widget.isHidden()
    assert window.size() == original
    window.tab_music.btn_lyrics.click()
    assert window.tab_music.lyrics_widget.isVisible()
    monkeypatch.setattr(window, "_get_current_screen_geometry", lambda: QRect(0, 0, 800, 600))
    window._resize_expanded_panel()
    assert window.height() <= 544
    assert window.width() <= 784


@pytest.mark.parametrize("layout", list(LAYOUT_THEMES))
def test_music_controls_fit_without_an_outer_scroll_area(dashboard_window, audit_app, monkeypatch, layout):
    window = dashboard_window
    view = window.tab_music
    window._switch_to_tab_by_name("Music")
    view.update_sessions_list([{"index": i, "display_name": f"Player {i}"} for i in range(4)], 0)
    view.lyrics_widget.set_synced_lyrics([(i * 5, f"Lyric line {i}") for i in range(60)])
    view.update_media({"title": "A very long title " * 12, "artist": "Artist name " * 10,
                       "position_sec": 65, "duration_sec": 200, "can_seek": True})
    assert view.findChildren(QScrollArea) == [view.lyrics_widget.scroll_area]
    for screen in (QRect(0, 0, 1440, 1000), QRect(0, 0, 800, 600)):
        monkeypatch.setattr(window, "_get_current_screen_geometry", lambda screen=screen: screen)
        for mode in ("Dark", "Light"):
            window._apply_live_appearance({"mode": mode, "layout": layout, "open_width": 780, "open_height": 480, "layout_version": 3})
            audit_app.processEvents()
            assert window.height() <= screen.height() - 56
            assert view.player_card.x() < view.lyrics_widget.x()
            for control in (view.lbl_large_art, view.lbl_title, view.scrubber, view.btn_prev,
                            view.btn_play, view.btn_next, view.vol_slider, view.btn_output,
                            *view._source_pills):
                assert view.rect().contains(QRect(control.mapTo(view, control.rect().topLeft()), control.size()))
            assert view.lyrics_widget.scroll_area.verticalScrollBar().maximum() > 0


def test_fitted_album_art_survives_appearance_mode_changes(dashboard_window, audit_app):
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QImage, QPainter, QColor
    image = QImage(240, 240, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#123456"))
    painter = QPainter(image)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#cdbda8"))
    painter.drawEllipse(44, 24, 144, 144)
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    view = dashboard_window.tab_music
    dashboard_window._switch_to_tab_by_name("Music")
    view.update_media({"title": "Test track", "thumbnail_bytes": bytes(buffer.data())})
    for mode in ("Dark", "Light", "Dark"):
        dashboard_window._apply_live_appearance({"mode": mode, "open_width": 780,
            "open_height": 480, "layout_version": 3})
        audit_app.processEvents()
        rendered = view.lbl_large_art.pixmap().toImage()
        assert rendered.pixelColor(rendered.width() // 2, round(rendered.height() * 0.17)).name() == "#cdbda8"


def test_music_keyboard_and_wheel_changes_commit_real_seeks(dashboard_window, audit_app):
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest
    view = dashboard_window.tab_music
    view.update_media({"title": "Test track", "position_sec": 60, "duration_sec": 200, "can_seek": True})
    seeks = []
    view.seek_requested.connect(seeks.append)
    QTest.keyClick(view.scrubber, Qt.Key.Key_Right)
    assert seeks == [61.0]
    point = view.scrubber.rect().center()
    event = QWheelEvent(QPointF(point), QPointF(view.scrubber.mapToGlobal(point)), QPoint(), QPoint(0, 120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    audit_app.sendEvent(view.scrubber, event)
    assert len(seeks) == 2
    assert seeks[-1] == view.scrubber.value()
    QTest.mouseClick(view.scrubber, Qt.MouseButton.LeftButton, pos=QPoint(0, point.y()))
    assert seeks[-1] == 0.0
    QTest.mouseClick(view.scrubber, Qt.MouseButton.LeftButton,
                     pos=QPoint(view.scrubber.width() - 1, point.y()))
    assert seeks[-1] == 200.0


@pytest.mark.parametrize("layout", list(LAYOUT_THEMES))
def test_all_tabs_keep_static_controls_visible_with_loaded_lists(dashboard_window, audit_app, tmp_path, monkeypatch, layout):
    from PySide6.QtWidgets import QPushButton
    window = dashboard_window
    files = []
    for index in range(20):
        path = tmp_path / f"Example_{index}.txt"
        path.write_text("Example content")
        files.append(str(path))
        window.tab_docs._add_recent(str(path))
        window.clip_mgr.add_clip(f"Clipboard item {index}: " + "Example words " * 10)
    window.drop_shelf.add_paths(files)
    calendar = window.tab_calendar
    calendar.events[calendar.selected_date.isoformat()] = [{"title": f"Event {i}"} for i in range(20)]
    calendar._render_agenda()
    monkeypatch.setattr(window, "_get_current_screen_geometry", lambda: QRect(0, 0, 800, 600))
    window._apply_live_appearance({"layout": layout, "open_width": 780, "open_height": 480, "layout_version": 3})
    for name in window._active_tab_names:
        window._switch_to_tab_by_name(name)
        audit_app.processEvents()
        page = window.tab_stack.currentWidget()
        for button in page.findChildren(QPushButton):
            if not button.isVisible():
                continue
            parent = button.parentWidget()
            while parent is not page and parent is not None and not isinstance(parent, QScrollArea):
                parent = parent.parentWidget()
            if isinstance(parent, QScrollArea):
                continue  # Collection rows can move through their own viewport.
            assert page.rect().contains(QRect(button.mapTo(page, button.rect().topLeft()), button.size()))
        for area in page.findChildren(QScrollArea):
            assert area.horizontalScrollBar().maximum() == 0
    for area in (calendar.events_scroll, window.tab_clipboard.scroll,
                 window.tab_docs.recent_scroll, window.tab_shelf.scroll_area):
        assert area.widget().minimumSizeHint().height() > 0


def test_session_tiles_are_bounded_and_select_the_real_session(audit_app):
    view = MusicTabView()
    selected = []
    view.session_select_requested.connect(selected.append)
    sessions = [{"index": i, "display_name": f"Player {i}"} for i in range(8)]
    view.update_sessions_list(sessions, 7)
    assert len(view._source_pills) == 4
    assert view._source_pills[-1].accessibleName() == "Switch to Player 7"
    view._source_pills[-1].click()
    assert selected == [7]
    view.update_media({"title": "A long title " * 30, "artist": "Artist " * 40,
                       "position_sec": 65, "duration_sec": 200, "can_seek": True, "is_playing": True})
    view.resize(700, 450)
    view.show()
    audit_app.processEvents()
    assert view.width() == 700
    assert view.lbl_remaining.text() == "03:20"
    assert view.scrubber.isEnabled()
    assert view.btn_play.accessibleName() == "Pause"
    assert view.lbl_title.toolTip() == "A long title " * 30
    view.update_media({"title": "No Media Playing"})
    assert not view.btn_play.isEnabled()
    assert not view.scrubber.isEnabled()


def test_settings_plain_labels_theme_and_size_persist(monkeypatch):
    monkeypatch.setattr("poppy.ui.settings_window.get_autostart_state", lambda: False)
    monkeypatch.setattr("poppy.ui.settings_window.set_autostart_state", lambda *args: None)
    settings = SettingsWindow({"appearance": {"open_width": 960, "open_height": 480}})
    assert settings.slider_open_w.value() == 960
    assert settings.slider_open_h.value() == 560
    text = [settings.nav_list.item(i).text() for i in range(settings.nav_list.count())]
    text.extend(label.text() for label in settings.findChildren(QLabel))
    assert not any(ord(char) >= 0x1F000 or char == "\ufe0f" for string in text for char in string)
    settings.select_page("Tabs Manager")
    assert settings.nav_list.currentRow() == 1
    settings.combo_theme.setCurrentText("Graphite")
    settings.combo_layout.setCurrentText("Soft")
    settings.combo_mode.setCurrentText("Light")
    settings.combo_media_background.setCurrentText("Theme")
    settings.chk_media_players.setChecked(False)
    assert settings._save_settings()
    assert settings.config["appearance"]["theme"] == "Graphite"
    assert settings.config["appearance"]["layout_version"] == 3
    assert settings.config["appearance"]["layout"] == "Soft"
    assert settings.config["appearance"]["mode"] == "Light"
    assert settings.config["media"]["background"] == "theme"
    assert not settings.config["media"]["show_player_tiles"]
    reloaded = SettingsWindow(settings.config)
    assert reloaded.combo_layout.currentText() == "Soft"
    assert reloaded.combo_mode.currentText() == "Light"


def test_media_appearance_options_apply_without_losing_players(dashboard_window):
    view = dashboard_window.tab_music
    view.update_sessions_list([{"index": i, "display_name": f"Player {i}"} for i in range(2)], 0)
    expanded_height = dashboard_window.height()
    view.configure_appearance({"background": "theme", "show_player_tiles": False}, get_theme("Sage"))
    assert get_theme("Sage")["bg"] in view.player_card.styleSheet()
    assert view.sessions_widget.isHidden()
    assert len(view._sessions) == 2
    assert dashboard_window.height() == expanded_height
    view.configure_appearance({"background": "artwork", "show_player_tiles": True}, get_theme("Sage"))
    assert view.sessions_widget.isVisible()
    assert dashboard_window.height() == expanded_height


def test_lyrics_are_requested_only_when_opened(dashboard_window, monkeypatch):
    window = dashboard_window
    requests = []
    monkeypatch.setattr(window.lyrics_manager, "request_lyrics", lambda *args: requests.append(args))
    window._switch_to_tab_by_name("Home")
    window._on_media_changed({"title": "Test song", "artist": "Test artist", "album": "Test album"})
    assert requests == []
    window._switch_to_tab_by_name("Music")
    assert requests == [("Test song", "Test artist", "Test album")]
    window.tab_music.btn_lyrics.click()
    window._on_media_changed({"title": "Next song", "artist": "Another artist"})
    assert len(requests) == 1


def test_follow_playback_can_be_disabled(dashboard_window, audit_app):
    view = dashboard_window.tab_music
    lyrics = view.lyrics_widget
    lyrics.set_synced_lyrics([(i * 5, f"Line {i}") for i in range(30)])
    audit_app.processEvents()
    view.configure_appearance({"auto_scroll_lyrics": False}, get_theme("Pure black"))
    lyrics.update_playback_time(120)
    assert lyrics._current_line_idx == 24
    assert not lyrics._scroll_anim.state() == lyrics._scroll_anim.State.Running
    view.configure_appearance({"auto_scroll_lyrics": True}, get_theme("Pure black"))
    assert lyrics._scroll_anim.state() == lyrics._scroll_anim.State.Running


def test_shelf_copy_of_document_uses_file_url_and_keeps_original(tmp_path, monkeypatch):
    path = tmp_path / "document.txt"
    path.write_text("Keep this file")
    manager = DropShelfManager()
    manager.add_paths([str(path)])
    class ImageOnlyWatcher:
        def copy_image_for_chat(self, path):
            pytest.fail("Documents must not use the image-only copy path")
    copied = []
    class Clipboard:
        def setMimeData(self, mime):
            copied.extend(url.toLocalFile() for url in mime.urls())
    monkeypatch.setattr("poppy.ui.views.QApplication.clipboard", lambda: Clipboard())
    row = ShelfItemRow(manager.staged_items[0], ImageOnlyWatcher(), manager)
    row._copy_for_chat()
    assert [Path(item) for item in copied] == [path]
    assert row.btn_pin.text() == "Open"
    manager.clear_shelf()
    assert path.read_text() == "Keep this file"
