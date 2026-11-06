"""Regression checks for repeated updates, rapid skips and lyrics cancellation."""

import threading
import time
import asyncio
import urllib.error
from email.message import Message
from types import SimpleNamespace

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage, QColor
from PySide6.QtTest import QTest

from poppy.core.window import DynamicNotchWindow
from poppy.core.lyrics_manager import LyricsManager
from poppy.core.media_manager import MediaManager, SessionData


def wait_for(predicate, timeout=2000):
    end = time.monotonic() + timeout / 1000
    while not predicate() and time.monotonic() < end:
        QTest.qWait(10)
    assert predicate()


def test_repeated_media_updates_reuse_artwork_and_session_buttons(audit_app, monkeypatch):
    window = DynamicNotchWindow()
    image = QImage(240, 240, QImage.Format.Format_ARGB32)
    image.fill(QColor("#123456"))
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    data = {"title": "Track", "artist": "Artist", "thumbnail_bytes": bytes(buffer.data()), "is_playing": False}
    sessions = [{"index": i, "display_name": f"Player {i}"} for i in range(2)]
    window._on_sessions_updated(sessions, 0)
    window._on_media_changed(data)
    music = window.tab_music
    original_buttons = list(music._source_pills)
    calls = []
    monkeypatch.setattr(music, "update_media", lambda *args: calls.append("media"))
    monkeypatch.setattr(music, "_rounded_art", lambda *args: calls.append("art"))
    music.fit_height(music.height())
    calls.clear()
    for index in range(100):
        window._on_media_changed(dict(data, position_sec=index))
        window._on_sessions_updated(sessions, 0)
        music.fit_height(music.height())
    assert calls == []
    assert music._source_pills == original_buttons
    window.close()


def test_duplicate_lyrics_do_not_recreate_rows_or_modify_the_source(audit_app):
    window = DynamicNotchWindow()
    view = window.tab_music
    view.set_lyrics_loading("Track", "Artist")
    key = LyricsManager._make_key("Track", "Artist")
    lines = [(i * 5, f"Line {i}") for i in range(60)]
    view.set_lyrics(key, "", lines)
    rows = list(view.lyrics_widget._line_buttons)
    for _ in range(20):
        view.set_lyrics(key, "", lines)
    assert view.lyrics_widget._line_buttons == rows
    view.set_lyrics_loading("Another track", "Artist")
    assert len(lines) == 60
    assert all(row.isHidden() for row in rows)
    window.close()


def test_fast_skips_only_query_the_final_track_and_cache_reopen_is_offline(audit_app, monkeypatch):
    manager = LyricsManager()
    queries, loaded = [], []
    manager.lyrics_loaded.connect(lambda *args: loaded.append(args))
    def query(title, artist, album, duration):
        queries.append(title)
        return {"syncedLyrics": "[00:01.00]A line"}
    monkeypatch.setattr(manager, "_query_lrclib", query)
    for index in range(30):
        manager.request_lyrics(f"Track {index}", "Artist")
    assert queries == []
    wait_for(lambda: len(loaded) == 1)
    wait_for(lambda: manager._worker_count == 0)
    assert queries == ["Track 29"]
    manager.cancel_request()
    manager.request_lyrics("Track 29", "Artist")
    assert len(loaded) == 2
    assert queries == ["Track 29"]
    manager.close()


def test_superseded_lookup_stops_before_its_next_http_attempt(audit_app, monkeypatch):
    manager = LyricsManager()
    started, release = threading.Event(), threading.Event()
    calls, loaded = [], []
    manager.lyrics_loaded.connect(lambda *args: loaded.append(args))
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self):
            started.set()
            assert release.wait(2)
            return b'{}'
    def open_request(request, timeout):
        calls.append(request.full_url)
        assert timeout <= 4.0
        return Response()
    monkeypatch.setattr("poppy.core.lyrics_manager.urllib.request.urlopen", open_request)
    manager.request_lyrics("Old track", "Artist")
    manager._request_timer.stop()
    manager._dispatch_request()
    assert started.wait(1)
    manager.request_lyrics("New track", "Artist")
    manager._request_timer.stop()
    release.set()
    wait_for(lambda: manager._worker_count == 0)
    assert len(calls) == 1
    assert loaded == []
    manager.close()


def test_cache_writes_do_not_hold_the_lock_used_by_the_ui(audit_app, monkeypatch):
    manager = LyricsManager()
    writing, release = threading.Event(), threading.Event()
    monkeypatch.setattr(manager, "_query_lrclib", lambda *args: {"plainLyrics": "A line"})
    def write(*args):
        writing.set()
        release.wait(2)
    monkeypatch.setattr("poppy.core.lyrics_manager.write_json", write)
    manager.request_lyrics("Track", "Artist")
    manager._request_timer.stop()
    manager._dispatch_request()
    assert writing.wait(1)
    acquired = manager._lock.acquire(blocking=False)
    if acquired:
        manager._lock.release()
    release.set()
    assert acquired
    wait_for(lambda: manager._worker_count == 0)
    manager.close()


def test_clean_queries_are_not_repeated_and_movie_credits_are_removed(audit_app, monkeypatch):
    manager = LyricsManager()
    urls = []
    def not_found(request, timeout):
        urls.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, 404, "Not found", {}, None)
    monkeypatch.setattr("poppy.core.lyrics_manager.urllib.request.urlopen", not_found)
    assert manager._query_lrclib("Track", "Artist", "") is None
    assert len(urls) == len(set(urls)) == 3
    assert manager._clean_title('Chhalakata Hamro Jawaniya - From "Bhojpuriya Raja"') == "Chhalakata Hamro Jawaniya"
    assert manager._clean_title("Mind Over Matter (Reprise)") == "Mind Over Matter (Reprise)"
    manager.close()


def test_matching_rejects_wrong_song_and_rate_limits_are_honored(audit_app, monkeypatch):
    manager = LyricsManager()
    wrong = {"trackName": "Completely different", "artistName": "Artist", "syncedLyrics": "[00:01]Wrong"}
    right = {"trackName": "Track", "artistName": "Artist", "plainLyrics": "Right"}
    assert manager._best_match([wrong, right], "Track", "Artist") is right
    calls = []
    headers = Message()
    headers["Retry-After"] = "10"
    def limited(request, timeout):
        calls.append(True)
        raise urllib.error.HTTPError(request.full_url, 429, "Rate limited", headers, None)
    monkeypatch.setattr("poppy.core.lyrics_manager.urllib.request.urlopen", limited)
    manager._query_lrclib("Track", "Artist", "")
    assert calls == [True]
    manager.close()


def test_reselecting_active_media_session_does_not_emit_duplicate_updates(audit_app):
    manager = MediaManager()
    session = SessionData(0, None, "spotify", "Track", "Artist", "Album", False)
    manager.sessions = [session]
    manager._last_state_hash = manager._fingerprint(session)
    received = []
    manager.media_changed.connect(received.append)
    manager.select_session(0)
    assert received == []


def test_session_reordering_keeps_the_selected_player(audit_app):
    manager = MediaManager()
    manager.sessions = [SessionData(0, None, "spotify", "Track", "Artist", "", False),
                        SessionData(1, None, "browser", "Video", "Artist", "", False)]
    manager._selected_index = 1

    class RawSession:
        def __init__(self, app_id):
            self.source_app_user_model_id = app_id
        def get_playback_info(self):
            return SimpleNamespace(playback_status=3)
        def get_timeline_properties(self):
            return None
        async def try_get_media_properties_async(self):
            return SimpleNamespace(title="Track", artist="Artist", album_title="", thumbnail=None)

    manager._session_manager = SimpleNamespace(get_sessions=lambda: [RawSession("browser"), RawSession("spotify")])
    asyncio.run(manager._refresh_all_sessions())
    assert manager.get_active_index() == 0
    assert manager.sessions[0].app_id == "browser"
    roster, tracks = [], []
    manager.sessions_updated.connect(lambda sessions, index: roster.append((sessions, index)))
    manager.media_changed.connect(tracks.append)
    manager._session_manager.get_sessions = lambda: [RawSession("browser"), RawSession("brave")]
    asyncio.run(manager._refresh_all_sessions())
    assert roster[-1][1] == 0
    assert roster[-1][0][1]["display_name"] == "Brave"
    assert tracks == []


def test_unexpected_provider_failure_does_not_leak_a_worker_slot(audit_app, monkeypatch):
    manager = LyricsManager()
    def fail(*args):
        raise ValueError("Invalid provider response")
    monkeypatch.setattr(manager, "_fetch_worker", fail)
    manager.request_lyrics("Track", "Artist")
    manager._request_timer.stop()
    manager._dispatch_request()
    wait_for(lambda: manager._worker_count == 0)
    manager.close()
