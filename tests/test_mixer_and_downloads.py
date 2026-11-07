"""Protect session targeting, local download detection, and their UI entry points."""

from PySide6.QtCore import QPoint

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
    slider.setValue(40)
    assert writes == [(("speakers", music.sessions), {"level": 40})]
    mute.click()
    assert writes[-1] == (("speakers", music.sessions), {"muted": True})
    snapshot[:] = ["headphones", [music]]
    menu.refresh()
    slider.setValue(100)
    assert len(writes) == 2


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
