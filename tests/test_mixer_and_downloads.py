"""Protect session targeting, local download detection, and their UI entry points."""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractSlider

from poppy.core.app_mixer import AppVolume
from poppy.core.download_watcher import DownloadWatcher, _snapshot, _writer_closed
from poppy.core.window import DynamicNotchWindow, NotchState
from poppy.ui import app_mixer
from poppy.ui.settings_window import SettingsWindow


def test_download_watch_ignores_existing_partial_and_open_files(tmp_path, monkeypatch):
    old = tmp_path / "existing.zip"
    old.write_bytes(b"old")
    baseline, _ = _snapshot(tmp_path)
    pending = {}
    candidate = tmp_path / "new.zip"
    partial = tmp_path / "new.zip.part"
    candidate.touch()
    partial.write_bytes(b"part")
    open_writer = True
    monkeypatch.setattr("poppy.core.download_watcher._writer_closed", lambda _: not open_writer)

    def scan():
        return DownloadWatcher._scan(tmp_path, *_snapshot(tmp_path), baseline, pending)

    for _ in range(4):
        assert scan() == []
    partial.replace(candidate)
    assert scan() == []
    candidate.write_bytes(b"complete")
    for _ in range(4):
        assert scan() == []
    open_writer = False
    assert scan() == [candidate]
    assert scan() == []
    old.write_bytes(b"an edit to an existing file")
    assert scan() == []


def test_windows_writer_probe_waits_for_open_handle(tmp_path):
    candidate = tmp_path / "file.zip"
    with candidate.open("wb") as writer:
        writer.write(b"partial")
        writer.flush()
        assert not _writer_closed(candidate)
    assert _writer_closed(candidate)


def test_optional_tools_search_and_apply(audit_app, monkeypatch, tmp_path):
    window = DynamicNotchWindow()
    configured = []
    monkeypatch.setattr(window.download_watcher, "configure", lambda *args: configured.append(args))
    settings = SettingsWindow()
    settings.show()
    settings.search_settings.setText("download alerts")
    assert settings.nav_list.currentItem().text() == "Tools"
    assert not settings.stack.isHidden()
    settings.search_settings.setText("no such setting")
    assert settings.stack.isHidden() and settings.no_search_results.isVisible()
    settings.select_page("Behavior")
    assert not settings.stack.isHidden()
    assert settings.nav_list.currentItem().text() == "Behavior"
    settings.chk_app_mixer.setChecked(False, animate=False)
    settings.chk_downloads.setChecked(True, animate=False)
    settings.download_folder.setText(str(tmp_path))
    settings.chk_pill_levels.setChecked(False, animate=False)
    settings.settings_saved.connect(window._on_settings_saved)
    assert settings._save_settings()
    assert window.tab_home.btn_app_mixer.isHidden()
    assert window.btn_peek_app_mixer.isHidden()
    assert configured == [(True, str(tmp_path))]
    assert not window._can_show_pill_level()


def test_mixer_refresh_does_not_retarget_held_slider(audit_app, monkeypatch):
    music = AppVolume("Music", "", ("music-1",), 46, False, False)
    browser = AppVolume("Browser", "", ("browser-1",), 30, False, False)
    snapshot = ["speakers", [music]]
    writes = []
    monkeypatch.setattr(app_mixer, "read_app_volumes", lambda: tuple(snapshot))
    monkeypatch.setattr(app_mixer, "set_app_volume", lambda *args, **kw: writes.append((args, kw)))
    monkeypatch.setattr(app_mixer.AudioEndpointManager, "get_output_endpoints", lambda: [])
    window = DynamicNotchWindow()
    window.show()
    window._transition_to(NotchState.PEEK, animate=False)
    window._open_app_mixer(window.btn_peek_volume)
    menu = window._app_mixer
    _, slider, _, mute = menu._rows[music.sessions]
    assert slider.value() == 46
    slider.setSliderDown(True)
    snapshot[1] = [browser, music]
    menu.refresh()
    assert list(menu._rows) == [music.sessions]
    slider.setSliderDown(False)
    slider.setValue(39)
    assert writes == []
    slider.triggerAction(QAbstractSlider.SliderAction.SliderSingleStepAdd)
    assert writes == [(("speakers", music.sessions), {"level": 40})]
    mute.click()
    assert writes[-1] == (("speakers", music.sessions), {"muted": True})
    snapshot[:] = ["headphones", [music]]
    menu.refresh()
    slider.setValue(100)
    assert len(writes) == 2


def test_mixer_applies_drag_before_release_and_cancels_pending_on_output_change(audit_app, monkeypatch):
    music = AppVolume("Music", "", ("music",), 55, False, False)
    snapshot = ["speakers", [music]]
    writes = []
    monkeypatch.setattr(app_mixer, "read_app_volumes", lambda: tuple(snapshot))
    monkeypatch.setattr(app_mixer, "set_app_volume", lambda *args, **kwargs: writes.append((args, kwargs)))
    monkeypatch.setattr(app_mixer.AudioEndpointManager, "get_output_endpoints", lambda: [])
    window = DynamicNotchWindow()
    window.show()
    window._transition_to(NotchState.PEEK, animate=False)
    window._open_app_mixer(window.btn_peek_volume)
    menu = window._app_mixer
    _, slider, _, _ = menu._rows[music.sessions]
    left = QPoint(2, slider.height() // 2)
    right = QPoint(slider.width() - 3, slider.height() // 2)
    QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=left)
    assert slider.isSliderDown() and menu._level_timer.isActive()
    menu._level_timer.timeout.emit()
    assert writes == [(("speakers", music.sessions), {"level": 0})]
    QTest.mouseMove(slider, right)
    assert menu._pending_level is not None
    snapshot[0] = "headphones"
    menu.refresh()
    assert menu._pending_level is None and not menu._level_timer.isActive()
    menu._level_timer.timeout.emit()
    assert len(writes) == 1


def test_mixer_pin_survives_reopening_without_an_audio_write(audit_app, monkeypatch):
    browser = AppVolume("Browser", r"C:\Program Files\Browser\browser.exe", ("browser",), 46, False, False)
    music = AppVolume("Music", r"C:\Program Files\Music\music.exe", ("music",), 30, False, False)
    monkeypatch.setattr(app_mixer, "read_app_volumes", lambda: ("speakers", [browser, music]))
    monkeypatch.setattr(app_mixer.AudioEndpointManager, "get_output_endpoints", lambda: [])
    writes = []
    monkeypatch.setattr(app_mixer, "set_app_volume", lambda *args, **kwargs: writes.append(args))
    window = DynamicNotchWindow()
    first = app_mixer.AppMixerMenu(window)
    first.refresh()
    row = first._rows[music.sessions][0]
    row.findChild(app_mixer.IconButton, "mixerPin").click()
    second = app_mixer.AppMixerMenu(window)
    second.refresh()
    assert second.rows.itemAt(0).widget() is second._rows[music.sessions][0]
    assert not writes


def test_download_activity_is_scoped_to_current_watch(audit_app, tmp_path):
    from threading import Event

    window = DynamicNotchWindow()
    watcher = window.download_watcher
    watcher.folder = tmp_path
    token = Event()
    watcher._stop = token
    window._show_download_activity(QPoint(0, 0))
    activity = window._download_activity
    assert activity.items.item(0).text() == "No new files in this session."
    bounds = activity.size()
    watcher._deliver(token, [tmp_path / "Ready.zip"], (("Receiving.zip", 4096),))
    audit_app.processEvents()
    assert activity.size() == bounds
    assert activity.items.isVisible()
    assert activity.items.item(0).text().startswith("Receiving.zip\nPartial file")
    assert activity.items.item(1).text() == "Ready.zip\nReady"
    watcher.close()
    watcher._deliver(token, [tmp_path / "Stale.zip"], ())
    assert not watcher.recent and not watcher.partials


def test_timed_awake_releases_request_and_updates_controls(audit_app, monkeypatch):
    from poppy.core import system_tools

    calls = []
    monkeypatch.setattr(system_tools.ctypes.windll.kernel32, "SetThreadExecutionState",
                        lambda state: calls.append(state) or 1)
    window = DynamicNotchWindow()
    window._set_awake(True, 15)
    assert window.caffeine.is_active and window.caffeine._timer.isActive()
    assert window.tab_home.btn_act_caffeine.isChecked()
    window.caffeine._timer.timeout.emit()
    assert not window.caffeine.is_active and not window.caffeine._timer.isActive()
    assert not window.tab_home.btn_act_caffeine.isChecked()
    assert calls == [0x80000003, 0x80000000]


def test_countdown_and_stopwatch_run_independently(audit_app, monkeypatch):
    window = DynamicNotchWindow()
    countdown, stopwatch = window.tab_timer.countdown, window.tab_timer.stopwatch
    now = [100.0]
    monkeypatch.setattr(countdown, "_clock", lambda: now[0])
    monkeypatch.setattr(stopwatch, "_clock", lambda: now[0])
    finished = []
    countdown.finished.connect(lambda: finished.append(True))
    countdown.duration.setValue(1)
    countdown._toggle()
    stopwatch._toggle()
    now[0] += 20
    stopwatch._toggle()
    now[0] += 40
    countdown._update_time()
    countdown._update_time()
    assert countdown.readout.text() == "00:00" and finished == [True]
    assert stopwatch.readout.text() == "00:20"


def test_clipboard_link_cleanup_preserves_query_encoding_and_signed_links():
    from poppy.ui.extended_views import clean_clipboard_link

    assert clean_clipboard_link("https://example.com/?utm_source=share&file=a%2Bb&fbclid=1#part") == (
        "https://example.com/?file=a%2Bb#part"
    )
    assert clean_clipboard_link("https://example.com/?signature=xyz&utm_source=share") is None
    assert clean_clipboard_link("Look at https://example.com/?utm_source=share") is None


def test_download_alert_anchors_content_and_opens_folder(audit_app, monkeypatch, tmp_path):
    window = DynamicNotchWindow({"notifications": {"sound": False}})
    window.show()
    opened = []
    monkeypatch.setattr(window, "_open_download_folder", opened.append)
    window._on_downloads_ready([tmp_path / "music.zip"])
    assert window.state == NotchState.ISLAND
    assert window.lbl_isl_sub.text() == "music.zip"
    assert window.btn_isl_shelf.text() == "Open folder"
    host = window.geometry()
    target = window.anim.endValue()
    window.anim.setCurrentTime(window.anim.duration() // 2)
    assert window.geometry() == host
    assert window.view_island.mapToGlobal(QPoint()) == target.topLeft()
    window.btn_isl_shelf.click()
    assert window.state == NotchState.COLLAPSED
    assert opened == [tmp_path]
