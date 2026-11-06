import json
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QPoint, QCoreApplication, QEvent
from PySide6.QtGui import QColor, QImage, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton

from poppy.core.instance import SingleInstance
from poppy.core.pomodoro import PomodoroManager, PomoState
from poppy.core.storage import data_dir, spotify_cookie, write_json, write_text
from poppy.core.system_features import ClipboardHistoryManager
from poppy.core.screenshot_watcher import ScreenshotWatcher
from poppy.core.window import DynamicNotchWindow, NotchState
from poppy.main import load_config
from poppy.ui.components import ClickableSlider, ToggleSwitch
from poppy.ui.extended_views import ClipboardTabView, DocsTabView
from poppy.ui.sticky_note import FloatingStickyNote
from poppy.ui.views import NotesTabView


def test_second_instance_activates_first_without_replacing_it(audit_app):
    first, second = SingleInstance(), SingleInstance()
    activations = []
    first.activation_requested.connect(lambda: activations.append(True))
    try:
        assert first.acquire()
        assert not second.acquire()
        audit_app.processEvents()
        assert activations == [True]
    finally:
        second.close()
        first.close()
    third = SingleInstance()
    assert third.acquire()
    third.close()


def test_atomic_save_failure_keeps_previous_content(tmp_path, monkeypatch):
    from poppy.core import storage
    path = tmp_path / "saved.txt"
    write_text(path, "original")
    class FailedSave:
        def __init__(self, path): pass
        def open(self, mode): return False
        def errorString(self): return "Read-only folder"
    monkeypatch.setattr(storage, "QSaveFile", FailedSave)
    with pytest.raises(OSError):
        write_text(path, "replacement")
    assert path.read_text() == "original"


def test_scratchpad_preserves_literal_markup_and_pending_save():
    text = "  <b>literal markup</b>\n"
    view = NotesTabView()
    view.editor.setPlainText(text)
    assert view.flush_notes()
    reopened = NotesTabView()
    assert reopened.editor.toPlainText() == text


def test_floating_copy_keeps_source_and_saves_on_close():
    view = NotesTabView()
    view.editor.setPlainText("  keep this\n")
    copies = []
    view.tear_off_requested.connect(copies.append)
    view._tear_off()
    assert copies == ["  keep this\n"]
    assert view.editor.toPlainText() == "  keep this\n"
    note = FloatingStickyNote(initial_text=copies[0])
    note.editor.setPlainText("Edited before the debounce fires")
    assert note.close()
    saved = json.loads(note._note_file.read_text())
    assert saved["text"] == "Edited before the debounce fires"
    assert not saved["open"]
    reopened = FloatingStickyNote(note_id=note.note_id)
    assert reopened.editor.toPlainText() == saved["text"]


def test_failed_note_save_does_not_close_or_clear_text(monkeypatch):
    def fail(*args): raise OSError("disk full")
    with monkeypatch.context() as scoped:
        scoped.setattr("poppy.ui.sticky_note.write_json", fail)
        note = FloatingStickyNote("keep this")
        assert not note.close()
        assert note.editor.toPlainText() == "keep this"
        assert "Not saved" in note.lbl_stats.text()
    assert note.close()


def test_filtered_clipboard_actions_use_original_identity():
    manager = ClipboardHistoryManager()
    manager.add_clip("wanted")
    manager.add_clip("other")
    view = ClipboardTabView(manager)
    view.input_search.setText("wanted")
    pin = [b for b in view.findChildren(QPushButton) if b.toolTip() == "Pin to top"][-1]
    pin.click()
    assert next(c for c in manager.history if c["text"] == "wanted")["pinned"]
    delete = [b for b in view.findChildren(QPushButton) if b.toolTip() == "Delete Clip"][-1]
    delete.click()
    assert [c["text"] for c in manager.history] == ["other"]


def test_clipboard_preserves_whitespace_long_text_and_pins():
    manager = ClipboardHistoryManager()
    text = "  " + "x" * 5000 + "\n"
    manager.add_clip(text)
    identity = manager.history[0]["id"]
    manager.toggle_pin(identity)
    manager.add_clip("another")
    manager.add_clip(text)
    assert manager.history[0]["text"] == text
    assert manager.history[0]["pinned"]
    assert manager.history[0]["id"] == identity
    for index in range(80): manager.add_clip(str(index))
    assert len(manager.history) == manager.MAX_RECENT + 1
    assert ClipboardHistoryManager().history == manager.history


def test_legacy_spotify_cookie_is_migrated_in_place():
    path = data_dir() / "config.json"
    write_json(path, {"media": {"spotify_sp_dc": "synthetic-cookie"}})
    load_config()
    media = json.loads(path.read_text())["media"]
    assert "spotify_sp_dc" not in media
    assert spotify_cookie(media) == "synthetic-cookie"


def test_capture_paths_are_unique_and_pixels_survive(tmp_path):
    watcher = ScreenshotWatcher(shelf_dir=str(tmp_path))
    paths = []
    for color in ("red", "blue"):
        image = QImage(32, 32, QImage.Format.Format_ARGB32)
        image.fill(QColor(color))
        paths.append(watcher._save_image(image))
    assert paths[0] != paths[1]
    assert QImage(paths[0]).pixelColor(0, 0) == QColor("red")
    assert QImage(paths[1]).pixelColor(0, 0) == QColor("blue")


def test_capture_cleanup_keeps_staged_files(tmp_path):
    watcher = ScreenshotWatcher(shelf_dir=str(tmp_path))
    image = QImage(32, 32, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    protected = watcher._save_image(image)
    watcher.protected_paths = lambda: {protected}
    for i in range(3): watcher._save_image(image)
    watcher._clean_shelf_cap(max_items=1)
    assert Path(protected).exists()
    assert len(list(tmp_path.glob("*.png"))) == 2


def test_capture_worker_stages_without_showing_disabled_alerts(tmp_path):
    window = DynamicNotchWindow()
    window.config["notifications"] = {"enabled": False}
    window.screenshot_watcher.enabled = True
    image = QImage(32, 32, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    window.screenshot_watcher._enqueue_capture("clipboard", image)
    for _ in range(100):
        if window.drop_shelf.staged_items:
            break
        QTest.qWait(20)
    assert len(window.drop_shelf.staged_items) == 1
    assert window.state == NotchState.COLLAPSED

    window.config["notifications"] = {"enabled": True, "preview_text": False, "sound": False}
    window._on_screenshot_captured(window.drop_shelf.staged_items[0].path, image)
    assert window.state == NotchState.ISLAND
    assert window.island_thumb.isHidden()
    assert window.lbl_isl_sub.text() == "Open Poppy for details."


def test_pdf_conversion_preserves_existing_output(tmp_path, monkeypatch):
    source, existing = tmp_path / "report.txt", tmp_path / "report.pdf"
    source.write_text("Synthetic text")
    existing.write_bytes(b"original")
    monkeypatch.setattr("poppy.ui.extended_views.QFileDialog.getOpenFileName", lambda *args: (str(source), ""))
    view = DocsTabView()
    view._convert_to_pdf()
    from PySide6.QtTest import QTest
    for _ in range(100):
        if view._recent_files:
            break
        QTest.qWait(20)
    assert existing.read_bytes() == b"original"
    assert len(view._recent_files) == 1
    assert Path(view._recent_files[0]).read_bytes().startswith(b"%PDF")


def test_repeated_clear_recent_does_not_delete_placeholder():
    view = DocsTabView()
    for _ in range(3):
        view._clear_recent()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert view.lbl_empty_recent.text()


def test_timer_uses_elapsed_time_and_does_not_award_skips():
    now = [100.0]
    timer = PomodoroManager(work_duration=25, break_duration=5, clock=lambda: now[0])
    timer.sound_enabled = False
    timer.start()
    now[0] += 9.4
    timer._tick()
    assert timer.remaining_seconds == 16
    timer.pause()
    now[0] += 60
    timer.resume()
    assert timer.remaining_seconds == 16
    timer.skip()
    assert timer.state == PomoState.SHORT_BREAK
    assert timer.completed_cycles == 0
    timer.set_phase_focus()
    now[0] += 25
    timer._tick()
    assert timer.completed_cycles == 1
    assert timer.completed_focus_seconds == 25
    timer.pause()


def test_timer_buttons_and_explicit_shelf_navigation():
    window = DynamicNotchWindow({"pomodoro": {"sound_enabled": False}})
    window.pomodoro.start()
    assert window.tab_timer.btn_toggle.text() == "Pause"
    window.pomodoro.pause()
    assert window.lbl_coll_pomo.isHidden()
    window.tab_timer.btn_phase_long.click()
    assert window.pomodoro.state == PomoState.LONG_BREAK
    window._open_shelf_from_island()
    assert window.tab_stack.currentWidget() is window.tab_shelf
    window.close()


def test_popout_reuses_live_view_and_returns_it():
    window = DynamicNotchWindow()
    window.tab_stack.setCurrentIndex(6)
    window._pop_out_current_tab()
    dialog = window._floating_windows[0]
    assert window.tab_timer.window() is dialog
    window.tab_timer.btn_toggle.click()
    assert window.pomodoro.is_running
    dialog.close()
    assert window.tab_stack.widget(6) is window.tab_timer
    window.close()


def test_scrubber_has_a_real_drag_lifecycle(audit_app):
    slider = ClickableSlider(Qt.Orientation.Horizontal)
    slider.setRange(0, 100)
    slider.resize(200, 30)
    pressed, released = [], []
    slider.sliderPressed.connect(lambda: pressed.append(True))
    slider.sliderReleased.connect(lambda: released.append(True))
    QTest.mousePress(slider, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(20, 15))
    assert slider.isSliderDown()
    event = QMouseEvent(QEvent.Type.MouseMove, QPoint(160, 15), QPoint(160, 15), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    audit_app.sendEvent(slider, event)
    QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(160, 15))
    assert abs(slider.value() - 80) <= 3
    assert pressed == released == [True]


def test_toggle_is_keyboard_operable():
    toggle = ToggleSwitch()
    QTest.keyClick(toggle, Qt.Key.Key_Space)
    assert toggle.isChecked()
    assert toggle.focusPolicy() == Qt.FocusPolicy.StrongFocus


def test_settings_failure_does_not_apply_or_close(monkeypatch):
    from poppy.ui.settings_window import SettingsWindow
    monkeypatch.setattr("poppy.ui.settings_window.get_autostart_state", lambda: False)
    monkeypatch.setattr("poppy.ui.settings_window.QMessageBox.warning", lambda *args: None)
    settings = SettingsWindow({"custom_setting": {"preserve": True}})
    settings.chk_clipboard_history.setChecked(True)
    applied = []
    settings.settings_saved.connect(applied.append)
    def fail(*args): raise OSError("disk full")
    with monkeypatch.context() as scoped:
        scoped.setattr("poppy.ui.settings_window.write_json", fail)
        assert not settings._save_settings()
    assert applied == []
    assert settings._save_settings()
    saved = json.loads((data_dir() / "config.json").read_text())
    assert saved["clipboard"]["enabled"]
    assert saved["custom_setting"] == {"preserve": True}


def test_windows_clipboard_exclusion_is_respected(monkeypatch):
    import win32clipboard
    from poppy.core.system_features import clipboard_allows_history
    closed = []
    monkeypatch.setattr(win32clipboard, "OpenClipboard", lambda: None)
    monkeypatch.setattr(win32clipboard, "CloseClipboard", lambda: closed.append(True))
    monkeypatch.setattr(win32clipboard, "RegisterClipboardFormat", lambda name: name)
    monkeypatch.setattr(win32clipboard, "IsClipboardFormatAvailable", lambda fmt: fmt == "ExcludeClipboardContentFromMonitorProcessing")
    assert not clipboard_allows_history()
    monkeypatch.setattr(win32clipboard, "IsClipboardFormatAvailable", lambda fmt: fmt == "CanIncludeInClipboardHistory")
    monkeypatch.setattr(win32clipboard, "GetClipboardData", lambda fmt: bytes(4))
    assert not clipboard_allows_history()
    assert len(closed) == 2


def test_recording_is_opt_in(monkeypatch):
    window = DynamicNotchWindow()
    observed = []
    monkeypatch.setattr(window.clip_mgr, "add_clip", observed.append)
    window._on_clipboard_data_changed()
    assert observed == []
    assert not window.screenshot_watcher.enabled
    window.close()


def test_propvariant_matches_native_pointer_size():
    import ctypes
    from poppy.core.system_features import PROPVARIANT
    assert ctypes.sizeof(PROPVARIANT) == (24 if ctypes.sizeof(ctypes.c_void_p) == 8 else 16)


def test_slow_bluetooth_driver_does_not_block_ui_or_overlap_scans(monkeypatch):
    import threading
    from poppy.core.system_features import BluetoothManager
    started, release = threading.Event(), threading.Event()
    calls = []
    def slow_scan():
        calls.append(True)
        started.set()
        release.wait(2)
        return [{"name": "Test device", "connected": True}]
    monkeypatch.setattr(BluetoothManager, "_get_devices", staticmethod(slow_scan))
    manager = BluetoothManager()
    try:
        manager.refresh()
        assert started.wait(1)
        manager.refresh()
        assert calls == [True]
        assert manager.devices == []
        release.set()
        for _ in range(50):
            QTest.qWait(10)
            if manager.devices:
                break
        assert manager.devices[0]["name"] == "Test device"
        assert not manager._scanning
    finally:
        release.set()
        manager.close()


def test_break_reminders_follow_configured_interval(monkeypatch):
    from poppy.core.screentime_manager import ScreenTimeManager
    monkeypatch.setattr("poppy.core.screentime_manager._get_idle_seconds", lambda: 0)
    monkeypatch.setattr("poppy.core.screentime_manager._get_active_app_name", lambda: "Synthetic")
    manager = ScreenTimeManager({"screentime": {"break_interval_minutes": 60}})
    alerts = []
    manager.break_reminder_triggered.connect(alerts.append)
    for elapsed in (3599, 3659, 7199):
        manager._continuous_seconds = elapsed
        manager._on_tick()
    assert alerts == [60, 120]
    manager.close()


def test_lyrics_cannot_replace_a_different_or_stopped_track():
    from poppy.ui.views import MusicTabView
    from poppy.core.lyrics_manager import LyricsManager
    view = MusicTabView()
    view.set_lyrics_loading("new song", "artist")
    view.set_lyrics(LyricsManager._make_key("old song", "artist"), "old lyrics", [])
    assert view.lyrics_widget.content_stack.currentIndex() == 1
    view.set_lyrics_not_found("No Media Playing")
    view.set_lyrics(LyricsManager._make_key("new song", "artist"), "late lyrics", [])
    assert view.lyrics_widget.content_stack.currentIndex() == 1


def test_migration_copies_legacy_data_without_removing_it(tmp_path, monkeypatch):
    from poppy.core import storage
    legacy, destination = tmp_path / "legacy", tmp_path / "destination"
    legacy.mkdir()
    (legacy / "scratchpad.txt").write_text("Old notes", encoding="utf-8")
    monkeypatch.delenv("POPPY_DATA_DIR")
    monkeypatch.setattr(storage, "data_dir", lambda: destination)
    monkeypatch.setattr(storage.os.path, "expanduser", lambda path: str(legacy))
    new_path = storage.data_path("scratchpad.txt")
    assert new_path.read_text() == "Old notes"
    assert (legacy / "scratchpad.txt").read_text() == "Old notes"
    write_text(new_path, "New notes")
    assert storage.data_path("scratchpad.txt").read_text() == "New notes"
