"""Exercise the reported bugs with isolated profiles and Windows service doubles."""

import asyncio
import ctypes
import json
import sys
from datetime import date
from threading import Event, get_ident
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QBuffer, QIODevice, QMimeData, QPoint, QRect, Qt, QUrl
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QPushButton

from poppy import main
from poppy.core import brightness_flyout, screenshot_watcher, screentime_manager, system_controls, window
from poppy.core.discord_rpc import DiscordRPCManager
from poppy.core.media_manager import MediaManager
from poppy.core.storage import data_path
from poppy.core.system_features import ClipboardHistoryManager
from poppy.core.updates import UpdateChecker
from poppy.core.weather_manager import WeatherManager
from poppy.ui.extended_views import CalendarTabView, DocsTabView
from poppy.ui.views import HomeTabView


def test_startup_recovers_invalid_settings_section_without_erasing_profile():
    profile = data_path("config.json")
    profile.parent.mkdir(parents=True, exist_ok=True)
    saved = {"appearance": None, "notifications": {"sound": False}, "custom": ["keep"]}
    profile.write_text(json.dumps(saved), encoding="utf-8")
    config = main.load_config()
    assert config["appearance"]["layout"] == "Classic"
    assert config["notifications"] == {"sound": False}
    assert config["custom"] == ["keep"]
    assert json.loads(profile.read_text(encoding="utf-8")) == saved


def test_alert_has_a_visible_fallback_with_the_tray_hidden(monkeypatch):
    alerts, tray_alerts = [], []
    monkeypatch.setattr(main.QToolTip, "showText", lambda *args, **kwargs: alerts.append(args))
    tray = SimpleNamespace(isVisible=lambda: False, supportsMessages=lambda: True,
                           showMessage=lambda *args: tray_alerts.append(args))
    notch = SimpleNamespace(_displayed_geometry=lambda: QRect(20, 0, 240, 30))
    main.show_notification(notch, tray, "Download ready", "notes & music.zip")
    assert alerts[0][:2] == (QPoint(28, 35), "<b>Download ready</b><br>notes &amp; music.zip")
    assert not tray_alerts
    tray.isVisible = lambda: True
    main.show_notification(notch, tray, "Download ready", "notes & music.zip")
    assert tray_alerts == [("Download ready", "notes & music.zip")]
    assert len(alerts) == 1


def test_media_keeps_selected_browser_session_across_polls():
    class Session:
        source_app_user_model_id = "chrome.exe"

        def __init__(self, title):
            self.title = title

        def get_playback_info(self):
            return None

        async def try_get_media_properties_async(self):
            return SimpleNamespace(title=self.title, artist="", album_title="", thumbnail=None)

        def get_timeline_properties(self):
            return None

    manager = MediaManager()
    titles = ["First", "Second"]
    manager._session_manager = SimpleNamespace(get_sessions=lambda: [Session(title) for title in titles])

    async def refresh():
        await manager._refresh_all_sessions()
        return manager.sessions[manager.get_active_index()].title

    assert asyncio.run(refresh()) == "First"
    manager.select_session(1)
    assert asyncio.run(refresh()) == "Second"
    titles.reverse()
    assert asyncio.run(refresh()) == "Second"
    titles[0] = "Second tab's next track"
    assert asyncio.run(refresh()) == "Second tab's next track"


def test_discord_enable_disable_and_client_change_keep_one_rpc_worker(monkeypatch):
    activity = []
    sent = Event()
    disconnected = Event()

    class Presence:
        def __init__(self, client_id):
            self.client_id = client_id
            self.owner = get_ident()

        def connect(self):
            assert get_ident() == self.owner

        def update(self, **payload):
            assert get_ident() == self.owner
            activity.append((self.client_id, payload["details"], self.owner))
            sent.set()

        def close(self):
            assert get_ident() == self.owner
            disconnected.set()

    monkeypatch.setitem(sys.modules, "pypresence", SimpleNamespace(Presence=Presence))
    rpc = DiscordRPCManager({"enabled": False})
    try:
        for client in ("first", "second"):
            sent.clear()
            rpc.update_config({"enabled": True, "mode": "custom", "client_id": client,
                               "custom_presence": {"details": client}})
            assert sent.wait(2)
        disconnected.clear()
        rpc.update_config({"enabled": False})
        assert disconnected.wait(2) and not rpc._connected
        sent.clear()
        rpc.update_config({"enabled": True, "mode": "custom", "client_id": "third",
                           "custom_presence": {"details": "third"}})
        assert sent.wait(2)
        assert [(client, details) for client, details, _ in activity] == [
            ("first", "first"), ("second", "second"), ("third", "third")]
        assert {owner for _, _, owner in activity} == {rpc._worker_thread.ident}
    finally:
        rpc.close()
        rpc._worker_thread.join(2)
    assert not rpc._worker_thread.is_alive()


def test_display_primary_ignores_window_position_and_display_numbers_are_exact(monkeypatch):
    screens = [SimpleNamespace(geometry=lambda i=i: QRect(i * 1000, 0, 1000, 800),
                               name=lambda i=i: str(i)) for i in range(10)]
    monkeypatch.setattr(window.QGuiApplication, "screens", lambda: screens)
    monkeypatch.setattr(window.QGuiApplication, "primaryScreen", lambda: screens[0])
    monkeypatch.setattr(window.QGuiApplication, "screenAt", lambda _: screens[1])
    notch = SimpleNamespace(_display="Primary", geometry=screens[1].geometry)
    assert window.DynamicNotchWindow._get_current_screen_geometry(notch) == screens[0].geometry()
    notch._display = "Display 10 (1000x800)"
    assert window.DynamicNotchWindow._get_current_screen_geometry(notch) == screens[9].geometry()


@pytest.mark.parametrize("channels", [1, 2, 6])
def test_audio_meter_reads_the_actual_channel_count(channels):
    from ctypes import POINTER, c_float, c_void_p, wintypes

    @ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, POINTER(c_float))
    def master(_, result):
        result[0] = 0.75
        return 0

    @ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, POINTER(wintypes.UINT))
    def count(_, result):
        result[0] = channels
        return 0

    @ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, wintypes.UINT, POINTER(c_float))
    def peaks(_, requested, result):
        if requested != channels:
            return -2147024809
        for index in range(channels):
            result[index] = 0.25 if index == 0 else 0.5
        return 0

    table = (c_void_p * 6)()
    for index, callback in enumerate((master, count, peaks), 3):
        table[index] = ctypes.cast(callback, c_void_p).value
    instance = ctypes.pointer(ctypes.cast(table, POINTER(c_void_p)))
    meter = system_controls.AudioPeakMeter.__new__(system_controls.AudioPeakMeter)
    meter._pMeter = ctypes.cast(instance, c_void_p)
    meter._release = lambda _: None
    assert meter.get_peaks() == (0.75, 0.25, 0.25 if channels == 1 else 0.5)


@pytest.mark.parametrize("key, level", [(0xAE, 0), (0xAF, 100)])
def test_volume_limit_feedback_requires_matching_passthrough_key(monkeypatch, key, level):
    displayed, passed = [], []
    current = (level, False)
    flyout = brightness_flyout.BrightnessFlyout(
        lambda: True, lambda *_: None, read_volume=lambda: current,
        show_volume=lambda *args: displayed.append(args),
    )
    monkeypatch.setattr(brightness_flyout, "monotonic", lambda: 10.0)
    flyout._user32 = SimpleNamespace(CallNextHookEx=lambda *args: passed.append(args) or 7)
    flyout._volume = current
    flyout._volume_window = (42, 10.0)
    flyout._clipped = (42, None)
    flyout._poll_volume()
    assert not displayed
    value = ctypes.c_uint32(key)
    assert flyout._keyboard_event(0, 0x100, ctypes.addressof(value)) == 7
    flyout._poll_volume()
    flyout._poll_volume()
    assert len(passed) == 1 and displayed == [(current, current)]


def test_capture_shield_retains_state_when_windows_rejects_toggle(monkeypatch):
    notices = []
    notch = SimpleNamespace(_is_screen_shielded=True, winId=lambda: 1, btn_hdr_shield=QPushButton(),
                            message_requested=SimpleNamespace(emit=lambda *args: notices.append(args)))
    notch.btn_hdr_shield.setToolTip("Active")
    monkeypatch.setattr(window.ScreenCaptureShield, "set_shield", lambda *args: False)
    window.DynamicNotchWindow._toggle_screen_shield(notch)
    assert notch._is_screen_shielded and notch.btn_hdr_shield.toolTip() == "Active"
    assert notices[0][0] == "Screen Capture Shield"


def test_calendar_navigation_schedules_in_the_visible_month():
    calendar = CalendarTabView()
    calendar.current_year, calendar.current_month = 2026, 1
    calendar.selected_date = date(2026, 1, 31)
    calendar._next_month()
    calendar.input_event.setText("February event")
    calendar.input_event.returnPressed.emit()
    assert calendar.selected_date == date(2026, 2, 28)
    assert calendar.events["2026-02-28"][0]["title"] == "February event"
    assert calendar._day_buttons[calendar.selected_date].isChecked()


def test_clipboard_recopy_retries_unsaved_history(monkeypatch):
    history = ClipboardHistoryManager()
    with monkeypatch.context() as scoped:
        def fail(*args):
            raise OSError("transient write failure")

        scoped.setattr("poppy.core.system_features.write_json", fail)
        assert history.add_clip("Saved once")
    original = history.history[0]
    assert history.last_save_error
    assert history.add_clip("Saved once")
    assert not history.last_save_error
    assert json.loads(history.store_file.read_text(encoding="utf-8")) == [original]


def test_weather_ignores_old_requests_and_displays_the_configured_unit(monkeypatch):
    weather = WeatherManager({"weather": {"city": "London", "unit": "celsius"}})
    messages = []
    weather.weather_updated.connect(messages.append)
    london = weather._preferences()
    weather._publish(0, london, {"temp": 18, "city": "London", "unit": "°C"})
    weather.update_config({"weather": {"city": "Mumbai", "unit": "fahrenheit"}})
    weather._publish(0, london, {"temp": 19, "city": "London", "unit": "°C"})
    weather._publish(weather._request, weather._preferences(), {})
    assert messages[-1] == {"display_text": "Weather unavailable"}
    home = HomeTabView()
    home.update_weather({"temp": 77, "unit": "°F", "city": "Mumbai", "high": 81, "low": 69})
    assert all(value in home.lbl_weather_text.toolTip() for value in ("77°F", "81°F", "69°F"))


def test_docs_open_reports_a_missing_recent_pdf(monkeypatch, tmp_path):
    view = DocsTabView()
    view._add_recent(str(tmp_path / "removed.pdf"))
    def missing(_):
        raise FileNotFoundError

    monkeypatch.setattr("poppy.ui.extended_views.os.startfile", missing)
    next(button for button in view.findChildren(QPushButton) if button.text() == "Open").click()
    assert view.doc_status.text() == "This PDF was moved or deleted."


def test_screentime_clears_the_active_label_for_excluded_apps(monkeypatch):
    manager = screentime_manager.ScreenTimeManager({"screentime": {"excluded_apps": ["Private"]}})
    active = iter(("Editor", "Private"))
    monkeypatch.setattr(screentime_manager, "_get_idle_seconds", lambda: 0)
    monkeypatch.setattr(screentime_manager, "_get_active_app_name", lambda: next(active))
    manager._on_tick()
    assert manager._current_app == "Editor"
    manager._on_tick()
    assert not manager._current_app and manager.get_top_apps() == [("Editor", 1, "0m")]
    manager.close()


def test_only_local_urls_open_shelf_during_drag():
    transitions = []
    notch = SimpleNamespace(state=window.NotchState.COLLAPSED,
                            _transition_to=lambda *args, **kwargs: transitions.append((args, kwargs)))
    mime = QMimeData()
    accepted = []
    event = SimpleNamespace(mimeData=lambda: mime, ignore=lambda: accepted.append(False),
                            acceptProposedAction=lambda: accepted.append(True))
    mime.setUrls([QUrl("https://example.invalid/file")])
    window.DynamicNotchWindow.dragEnterEvent(notch, event)
    assert accepted == [False] and not transitions
    mime.setUrls([QUrl.fromLocalFile("C:/download.zip")])
    window.DynamicNotchWindow.dragEnterEvent(notch, event)
    assert accepted[-1] and transitions == [((window.NotchState.EXPANDED,), {"target_tab": "Shelf"})]


def test_turning_off_automatic_updates_cancels_only_automatic_reply():
    class Reply:
        def __init__(self, checker):
            self.checker = checker
            self.aborted = self.deleted = False

        def abort(self):
            self.aborted = True
            self.checker._finish(self)

        def deleteLater(self):
            self.deleted = True

    checker = UpdateChecker()
    results = []
    checker.checked.connect(lambda *args: results.append(args))
    automatic = checker._reply = Reply(checker)
    checker.configure(False)
    assert automatic.aborted and automatic.deleted and not results
    manual = checker._reply = Reply(checker)
    checker.check(manual=True)
    checker.configure(False)
    assert checker._reply is manual and not manual.aborted


def test_screenshot_staging_retries_busy_clipboard_and_accepts_windows_png(monkeypatch, audit_app):
    watcher = screenshot_watcher.ScreenshotWatcher()
    watcher.enabled = True
    image = QImage(32, 32, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.red)
    png = QBuffer()
    png.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(png, "PNG")
    mime = QMimeData()
    mime.setData('application/x-qt-windows-mime;value="PNG"', png.data())
    assert not mime.hasImage()
    permission = iter((None, False, True))
    clipboard = SimpleNamespace(mimeData=lambda: mime)
    monkeypatch.setattr(screenshot_watcher, "clipboard_history_permission", lambda: next(permission))
    monkeypatch.setattr(screenshot_watcher, "GetClipboardSequenceNumber", lambda: 1)
    monkeypatch.setattr(screenshot_watcher.QApplication, "clipboard", lambda: clipboard)
    captured = []
    watcher.screenshot_captured.connect(lambda path, image: captured.append((path, image)))
    watcher._on_clipboard_data_changed()
    watcher._debounce_timer.stop()
    watcher._process_clipboard()
    assert watcher._debounce_timer.isActive() and not captured
    watcher._debounce_timer.stop()
    watcher._process_clipboard()
    assert not watcher._debounce_timer.isActive() and not captured
    watcher._process_clipboard()
    from PySide6.QtTest import QTest
    for _ in range(100):
        if captured:
            break
        QTest.qWait(10)
    watcher.stop()
    assert len(captured) == 1
    path, staged_image = captured[0]
    assert QImage(path).pixelColor(0, 0) == staged_image.pixelColor(0, 0) == image.pixelColor(0, 0)
