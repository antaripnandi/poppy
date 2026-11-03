"""Real design changes and the user-facing Home arrangement editor."""

from itertools import permutations

import pytest
from PySide6.QtCore import Qt, QRect, QPoint
from PySide6.QtTest import QTest

from poppy.core.window import DynamicNotchWindow, NotchState
from poppy.ui.settings_window import SettingsWindow
from poppy.ui.theme import LAYOUT_THEMES, HOME_CARDS, home_order, configure_theme, refresh_theme, set_widget_style
from poppy.ui.styles import normalize_appearance


@pytest.fixture
def editor(audit_app, monkeypatch):
    window = DynamicNotchWindow({"appearance": {"layout_version": 3, "layout": "Classic"}})
    monkeypatch.setattr(window, "_get_current_screen_geometry", lambda: QRect(0, 0, 1440, 1000))
    window._is_pinned = True
    window.show()
    window._transition_to(NotchState.EXPANDED, target_tab="Home")
    window.anim.setCurrentTime(window.anim.duration())
    window._anim_opacity.setCurrentTime(window._anim_opacity.duration())
    settings = SettingsWindow(window.config)
    settings.appearance_live_updated.connect(window._apply_live_appearance)
    settings.settings_saved.connect(window._on_settings_saved)
    settings.show()
    audit_app.processEvents()
    yield window, settings
    settings.close()
    window.close()


def actual_order(home):
    keys = {home.card_clock: "clock", home.card_controls: "controls",
            home.card_notes: "notes", home.card_shelf: "shelf"}
    return [keys[home.dashboard_grid.itemAtPosition(row, column).widget()]
            for row in range(2) for column in range(2)]


def test_drag_changes_home_and_outside_drop_and_escape_leave_it_alone(editor, audit_app):
    window, settings = editor
    preview = settings.layout_preview
    source, target = preview.cards["clock"], preview.cards["shelf"]
    origin = source.rect().center()
    destination = source.mapFromGlobal(target.mapToGlobal(target.rect().center()))
    QTest.mousePress(source, Qt.MouseButton.LeftButton, pos=origin)
    QTest.mouseMove(source, destination)
    assert preview._ghost.isVisible()
    QTest.mouseRelease(source, Qt.MouseButton.LeftButton, pos=destination)
    audit_app.processEvents()
    expected = ["controls", "notes", "shelf", "clock"]
    assert preview.order == actual_order(window.tab_home) == expected
    assert preview._ghost.isHidden()
    assert source.hasFocus()
    for cancel in (False, True):
        QTest.mousePress(source, Qt.MouseButton.LeftButton, pos=source.rect().center())
        QTest.mouseMove(source, QPoint(-100, -100))
        if cancel:
            QTest.keyClick(source, Qt.Key.Key_Escape)
        QTest.mouseRelease(source, Qt.MouseButton.LeftButton, pos=QPoint(-100, -100))
        assert preview.order == expected


def test_keyboard_orders_are_independent_per_design_and_cancel_restores(editor, audit_app):
    window, settings = editor
    home, music = window.tab_home, window.tab_music
    home.txt_notes.setPlainText("Keep this text")
    music.update_timeline(42, 180, False)
    preview = settings.layout_preview
    for name in LAYOUT_THEMES:
        settings.combo_layout.setCurrentText(name)
        audit_app.processEvents()
        assert preview.order == list(LAYOUT_THEMES[name]["home_order"])
        first = preview.cards[preview.order[0]]
        QTest.keyClick(first, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
        assert actual_order(home) == preview.order
        assert actual_order(home) != list(LAYOUT_THEMES[name]["home_order"])
    settings.combo_layout.setCurrentText("Classic")
    assert preview.order == ["controls", "notes", "clock", "shelf"]
    assert home.txt_notes.toPlainText() == "Keep this text"
    assert music._pos_sec == 42
    settings.close()
    assert actual_order(home) == list(HOME_CARDS)
    assert home is window.tab_home and music is window.tab_music


def test_orders_save_reload_and_reset_only_the_selected_design(editor, audit_app, monkeypatch):
    from poppy.main import load_config
    monkeypatch.setattr("poppy.ui.settings_window.get_autostart_state", lambda: False)
    window, settings = editor
    preview = settings.layout_preview
    preview.move_card("shelf", 0)
    settings.combo_layout.setCurrentText("Paper")
    preview.move_card("notes", 0)
    paper = list(preview.order)
    assert settings._save_settings()
    settings.close()
    saved = load_config()
    assert saved["appearance"]["home_orders"]["Paper"] == paper
    reloaded = SettingsWindow(saved)
    assert reloaded.layout_preview.order == paper
    reloaded.btn_reset_order.click()
    assert reloaded.layout_preview.order == list(HOME_CARDS)
    reloaded.combo_layout.setCurrentText("Classic")
    assert reloaded.layout_preview.order[0] == "shelf"
    reloaded.close()
    restored_window = DynamicNotchWindow(saved)
    assert actual_order(restored_window.tab_home) == paper
    restored_window.close()


@pytest.mark.parametrize("bad", [None, "clock", [], ["notes"] * 4,
                                ["clock", "controls", "notes", "unknown"], [[], {}, None, 1]])
def test_invalid_order_cannot_hide_or_duplicate_a_section(bad):
    config = normalize_appearance({"layout": "Paper", "home_orders": {"Paper": bad}})
    assert home_order("Paper", config["home_orders"]) == HOME_CARDS


@pytest.mark.parametrize("mode", ["Dark", "Light"])
def test_new_designs_change_controls_and_restore_the_original(editor, audit_app, mode):
    window, settings = editor
    assert [settings.combo_layout.itemText(i) for i in range(settings.combo_layout.count())] == list(LAYOUT_THEMES)
    settings.combo_mode.setCurrentText(mode)
    snapshots = {}
    for name in ("Classic", "Flat", "Paper", "Instrument", "Classic"):
        settings.combo_layout.setCurrentText(name)
        audit_app.processEvents()
        snapshots[name] = window.tab_home.slider_vol.grab().toImage()
        assert (window.tab_music.identity_layout.direction().name == "LeftToRight") == (name in ("Flat", "Paper"))
        if name == "Paper":
            assert window.tab_home.lbl_big_time.font().family() == "Cambria"
        if name == "Instrument":
            assert window.tab_home.lbl_big_time.font().family() == "Consolas"
            assert all(label.isVisible() for label in window.tab_home._design_headers)
        if name == "Classic":
            assert all(label.isHidden() for label in window.tab_home._design_headers)
            assert window.tab_home.lbl_big_time.font().family() != "Cambria"
    assert snapshots["Classic"] != snapshots["Flat"] != snapshots["Paper"] != snapshots["Instrument"]


@pytest.mark.parametrize("name", ["Flat", "Paper", "Instrument"])
def test_redesigned_slider_hit_area_matches_the_visible_track(editor, audit_app, name):
    window, settings = editor
    settings.combo_layout.setCurrentText(name)
    slider = window.tab_home.slider_vol
    for x, expected in ((32, 0), (round(slider.width() / 2 - 8), 50), (slider.width() - 48, 100)):
        QTest.mouseClick(slider, Qt.MouseButton.LeftButton, pos=QPoint(x, slider.height() // 2))
        assert abs(slider.value() - expected) <= 1


def test_design_compilation_preserves_focus_and_restores_authored_controls(audit_app):
    from PySide6.QtWidgets import QPushButton
    button = QPushButton("Action")
    original = "QPushButton { background: #202329; border: none; border-radius: 10px; } QPushButton:hover { background: #414957; } QPushButton:focus { border: 1px solid #a7bbc7; }"
    configure_theme({"mode": "Dark", "layout": "Classic"})
    set_widget_style(button, original)
    for mode in ("Dark", "Light"):
        for name in ("Flat", "Paper", "Instrument"):
            configure_theme({"mode": mode, "layout": name})
            refresh_theme()
            assert "QPushButton:hover" in button.styleSheet()
            assert "QPushButton:focus" in button.styleSheet()
            assert button.property("poppyStyleSource") == original
    configure_theme({"mode": "Dark", "layout": "Classic"})
    refresh_theme()
    assert button.styleSheet() == original


@pytest.mark.parametrize("name", list(LAYOUT_THEMES))
def test_every_home_order_fits_on_a_short_screen(editor, audit_app, monkeypatch, name):
    window, settings = editor
    monkeypatch.setattr(window, "_get_current_screen_geometry", lambda: QRect(0, 0, 800, 600))
    settings.combo_layout.setCurrentText(name)
    for order in permutations(HOME_CARDS):
        settings._on_home_order_changed(list(order))
        audit_app.processEvents()
        home = window.tab_home
        assert actual_order(home) == list(order)
        assert window.height() <= 544
        for widget in (home.card_clock, home.card_controls, home.card_notes, home.card_shelf,
                       home.lbl_big_time, home.slider_vol, home.txt_notes, home.input_calc):
            assert home.rect().contains(QRect(widget.mapTo(home, widget.rect().topLeft()), widget.size()))
