import json
from zipfile import ZipFile

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QFontInfo

from poppy.core.storage import data_path, resource_path
from poppy.core.window import DynamicNotchWindow
from poppy.ui.notch_shadow import NotchShadow
from poppy.ui.pill_fonts import DEFAULT_PILL_FONT, PILL_FONT_RESOURCE, pill_font_path
from poppy.ui.settings_window import SettingsWindow
from poppy.ui.styles import get_stylesheet


def test_pill_font_preview_only_changes_compact_text_and_cancel_restores(audit_app):
    old_style = audit_app.styleSheet()
    audit_app.setStyleSheet(get_stylesheet())
    try:
        window = DynamicNotchWindow()
        window.show()
        settings = SettingsWindow()
        settings.appearance_live_updated.connect(window._apply_live_appearance)
        settings.show()
        home_font = QFontInfo(window.tab_home.lbl_big_time.font()).family()
        assert QFontInfo(window.lbl_clock.font()).family() == DEFAULT_PILL_FONT
        assert QFontInfo(window.lbl_coll_pomo.font()).family() == DEFAULT_PILL_FONT
        assert window.pill_level._text_font.family() == DEFAULT_PILL_FONT
        assert home_font != DEFAULT_PILL_FONT

        settings.combo_pill_font.setCurrentIndex(settings.combo_pill_font.findData("Segoe UI"))
        settings.slider_pill_font_size.setValue(17)
        settings._on_live_appearance_change()
        assert QFontInfo(window.lbl_clock.font()).family() == "Segoe UI"
        assert QFontInfo(window.tab_home.lbl_big_time.font()).family() == home_font
        settings.close()
        assert QFontInfo(window.lbl_clock.font()).family() == DEFAULT_PILL_FONT
    finally:
        audit_app.setStyleSheet(old_style)


def test_font_import_export_and_settings_persistence(monkeypatch, tmp_path):
    source = resource_path(PILL_FONT_RESOURCE)
    settings = SettingsWindow()
    archive = tmp_path / "font.zip"
    monkeypatch.setattr("poppy.ui.settings_window.QFileDialog.getSaveFileName", lambda *_: (str(archive), ""))
    settings._export_pill_font()
    with ZipFile(archive) as exported:
        assert exported.read(source.name) == source.read_bytes()
        assert b"SIL OPEN FONT LICENSE" in exported.read("OFL.txt")

    monkeypatch.setattr("poppy.ui.settings_window.QFileDialog.getOpenFileName", lambda *_: (str(source), ""))
    settings._import_pill_font()
    selection = settings.combo_pill_font.currentData()
    assert pill_font_path(selection).read_bytes() == source.read_bytes()
    settings.slider_pill_font_size.setValue(17)
    settings.chk_notch_shadow.setChecked(False)
    assert settings._save_settings()

    saved = json.loads(data_path("config.json").read_text(encoding="utf-8"))
    reopened = SettingsWindow(saved)
    assert reopened.combo_pill_font.currentData() == selection
    assert reopened.slider_pill_font_size.value() == 17
    assert not reopened.chk_notch_shadow.isChecked()
    copy = tmp_path / "exported.ttf"
    monkeypatch.setattr("poppy.ui.settings_window.QFileDialog.getSaveFileName", lambda *_: (str(copy), ""))
    reopened._export_pill_font()
    assert copy.read_bytes() == source.read_bytes()


def test_shadow_extends_past_the_panel_without_covering_its_face(audit_app):
    window = DynamicNotchWindow()
    shadow = NotchShadow(window)
    bounds = QRect(100, 30, 240, 30)
    shadow.follow(bounds, window._notch_path(), screen_top=0)
    shadow.show()
    assert shadow.windowFlags() & Qt.WindowType.WindowTransparentForInput
    assert shadow.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    pixmap = shadow.grab()
    image = pixmap.toImage()
    center = bounds.center() - shadow.pos()
    below = QPoint(center.x(), bounds.bottom() - shadow.y() + 4)

    def alpha(point):
        ratio = pixmap.devicePixelRatio()
        return image.pixelColor(round(point.x() * ratio), round(point.y() * ratio)).alpha()

    assert alpha(center) == 0
    assert alpha(below) > 0
    shadow.hide()
