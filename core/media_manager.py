"""
Poppy Windows GSMTC Media Manager
Interacts with Windows 11/10 Global System Media Transport Controls
for Spotify, YouTube, Chrome, Edge, Apple Music, etc.
Supports multi-session tracking, seeking, and live playback timeline telemetry.
"""

import asyncio
import threading
import time
from collections import OrderedDict
from PySide6.QtCore import QObject, Signal


def format_source_name(app_id: str, title: str = "") -> str:
    """Format Windows App ID into a human-friendly name with app emoji/icon."""
    app_lower = (app_id or "").lower()
    title_lower = (title or "").lower()

    if "spotify" in app_lower:
        return "Spotify"
    elif "applemusic" in app_lower:
        return "Apple Music"
    elif "brave" in app_lower:
        if "youtube music" in title_lower or "music.youtube" in title_lower:
            return "YouTube Music"
        elif "youtube" in title_lower:
            return "YouTube"
        return "Brave"
    elif "chrome" in app_lower:
        if "youtube music" in title_lower or "music.youtube" in title_lower:
            return "YouTube Music"
        elif "youtube" in title_lower:
            return "YouTube"
        return "Chrome"
    elif "msedge" in app_lower or "edge" in app_lower:
        if "youtube" in title_lower:
            return "YouTube (Edge)"
        return "Edge"
    elif "firefox" in app_lower:
        return "Firefox"
    elif "wmplayer" in app_lower or "zune" in app_lower:
        return "Media Player"
    elif "discord" in app_lower:
        return "Discord"

    cleaned = app_id.replace(".exe", "").replace("Microsoft.", "").replace("_8wekyb3d8bbwe", "")
    return cleaned[:16] if cleaned else "Desktop Audio"


class SessionData:
    def __init__(
        self, index: int, session_obj, app_id: str, title: str,
        artist: str, album: str, is_playing: bool, thumbnail_bytes: bytes = None,
        position_sec: float = 0.0, duration_sec: float = 0.0,
        last_updated_ts: float = 0.0, can_seek: bool = False
    ):
        self.index = index
        self.session_obj = session_obj
        self.app_id = app_id
        self.display_name = format_source_name(app_id, title)
        self.title = title or "Unknown Title"
        self.artist = artist or "Desktop Audio"
        self.album = album or ""
        self.is_playing = is_playing
        self.thumbnail_bytes = thumbnail_bytes
        self.position_sec = position_sec
        self.duration_sec = duration_sec
        self.last_updated_ts = last_updated_ts
        self.can_seek = can_seek

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "source_app": self.app_id,
            "display_name": self.display_name,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "is_playing": self.is_playing,
            "thumbnail_bytes": self.thumbnail_bytes,
            "position_sec": self.position_sec,
            "duration_sec": self.duration_sec,
            "last_updated_ts": self.last_updated_ts,
            "can_seek": self.can_seek
        }


class MediaManager(QObject):
    media_changed = Signal(dict)
    playback_changed = Signal(bool)
    sessions_updated = Signal(list, int)           # (list of session dicts, active_index)
    timeline_changed = Signal(float, float, bool)   # position_sec, duration_sec, is_playing

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sessions: list[SessionData] = []
        self._selected_index = 0
        self._lock = threading.RLock()
        self._loop = None
        self._thread = None
        self._running = False
        self._session_manager = None
        self._thumb_cache: OrderedDict = OrderedDict()  # (app_id, title, artist, album) -> bytes
        self._max_cache_size = 30
        self._last_state_hash = None

    def start(self):
        """Start media monitoring background event loop."""
        self._running = True
        self._thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self._thread.start()

    def _run_event_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._media_loop())
        except Exception as e:
            print(f"[Poppy Media] Loop error: {e}")
        finally:
            self._loop.close()

    async def _media_loop(self):
        try:
            from winsdk.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as SessionManager
            )
            self._session_manager = await SessionManager.request_async()
        except Exception as e:
            print(f"[Poppy Media] GSMTC not available: {e}")
            return

        while self._running:
            try:
                await self._refresh_all_sessions()
            except Exception:
                pass
            await asyncio.sleep(0.75)

    async def _refresh_all_sessions(self):
        if not self._session_manager:
            return

        raw_sessions = self._session_manager.get_sessions()
        new_sessions: list[SessionData] = []

        for idx, s in enumerate(raw_sessions):
            try:
                app_id = s.source_app_user_model_id or ""
                pinfo = s.get_playback_info()
                is_playing = (pinfo.playback_status == 4) if pinfo else False

                props = await s.try_get_media_properties_async()
                title = props.title if props and props.title else "Unknown Title"
                artist = props.artist if props and props.artist else ""
                album = props.album_title if props and props.album_title else ""

                # Query timeline properties (position, duration, seeking)
                pos_sec = 0.0
                dur_sec = 0.0
                last_up = 0.0
                can_seek = False
                try:
                    timeline = s.get_timeline_properties()
                    if timeline and timeline.end_time and timeline.end_time.total_seconds() > 0:
                        raw_pos = max(0.0, timeline.position.total_seconds())
                        dur_sec = max(0.0, timeline.end_time.total_seconds())
                        last_up = timeline.last_updated_time.timestamp() if timeline.last_updated_time else time.time()
                        # GSMTC positions are snapshots as of last_updated_time; extrapolate live time if playing
                        if is_playing and last_up > 0:
                            elapsed = max(0.0, time.time() - last_up)
                            pos_sec = min(dur_sec, raw_pos + elapsed)
                        else:
                            pos_sec = raw_pos
                        can_seek = bool(pinfo and pinfo.controls.is_playback_position_enabled)
                except Exception:
                    pass

                # Cache and load thumbnail with bounded LRU eviction
                cache_key = (app_id, title, artist, album)
                thumb_bytes = self._thumb_cache.get(cache_key)
                if thumb_bytes is None and props and props.thumbnail:
                    thumb_bytes = await self._read_stream(props.thumbnail)
                    if thumb_bytes:
                        if len(self._thumb_cache) >= self._max_cache_size:
                            self._thumb_cache.popitem(last=False)
                        self._thumb_cache[cache_key] = thumb_bytes

                data = SessionData(
                    index=len(new_sessions),
                    session_obj=s,
                    app_id=app_id,
                    title=title,
                    artist=artist,
                    album=album,
                    is_playing=is_playing,
                    thumbnail_bytes=thumb_bytes,
                    position_sec=pos_sec,
                    duration_sec=dur_sec,
                    last_updated_ts=last_up,
                    can_seek=can_seek
                )
                new_sessions.append(data)
            except Exception:
                continue

        with self._lock:
            # Handle empty session list
            if not new_sessions:
                if self._last_state_hash != "empty":
                    self.sessions = []
                    self._selected_index = 0
                    empty_data = {
                        "index": 0,
                        "source_app": "",
                        "display_name": "Desktop Audio",
                        "title": "No Media Playing",
                        "artist": "System Audio",
                        "album": "",
                        "is_playing": False,
                        "thumbnail_bytes": None,
                        "position_sec": 0.0,
                        "duration_sec": 0.0,
                        "last_updated_ts": 0.0,
                        "can_seek": False
                    }
                    self.media_changed.emit(empty_data)
                    self.playback_changed.emit(False)
                    self.sessions_updated.emit([], 0)
                    self.timeline_changed.emit(0.0, 0.0, False)
                    self._last_state_hash = "empty"
                return

            # Clamp selected index
            selected_app = self.sessions[self._selected_index].app_id if self.sessions and self._selected_index < len(self.sessions) else None
            if selected_app:
                self._selected_index = next((i for i, item in enumerate(new_sessions) if item.app_id == selected_app), self._selected_index)
            if self._selected_index >= len(new_sessions):
                self._selected_index = 0

            self.sessions = new_sessions
            curr = self.sessions[self._selected_index]

            # Compute fingerprint for track/session changes
            state_fingerprint = self._fingerprint(curr)

            if state_fingerprint != self._last_state_hash:
                self._last_state_hash = state_fingerprint
                sessions_summary = [s.to_dict() for s in self.sessions]
                self.sessions_updated.emit(sessions_summary, self._selected_index)
                self.media_changed.emit(curr.to_dict())
                self.playback_changed.emit(curr.is_playing)

            # Always emit fresh timeline progress
            self.timeline_changed.emit(curr.position_sec, curr.duration_sec, curr.is_playing)

    async def _read_stream(self, stream_ref) -> bytes:
        try:
            from winsdk.windows.storage.streams import DataReader
            stream = await stream_ref.open_read_async()
            size = stream.size
            if size == 0 or size > 10 * 1024 * 1024:
                return None
            reader = DataReader(stream)
            await reader.load_async(size)
            buf = bytearray(size)
            reader.read_bytes(buf)
            return bytes(buf)
        except Exception:
            return None

    def select_session(self, index: int):
        """Switch active media session by index."""
        with self._lock:
            if 0 <= index < len(self.sessions):
                if index == self._selected_index and self._last_state_hash == self._fingerprint(self.sessions[index]):
                    return
                self._selected_index = index
                curr = self.sessions[index]
                self._last_state_hash = self._fingerprint(curr)
                self.media_changed.emit(curr.to_dict())
                self.playback_changed.emit(curr.is_playing)
                self.timeline_changed.emit(curr.position_sec, curr.duration_sec, curr.is_playing)
                sessions_summary = [s.to_dict() for s in self.sessions]
                self.sessions_updated.emit(sessions_summary, self._selected_index)

    def _fingerprint(self, session):
        return (len(self.sessions), self._selected_index, session.app_id, session.title,
                session.artist, session.album, session.thumbnail_bytes, session.is_playing, session.can_seek)

    def get_sessions(self) -> list[dict]:
        """Returns list of currently active media sessions as dicts."""
        with self._lock:
            return [s.to_dict() for s in self.sessions]

    def get_active_index(self) -> int:
        """Returns the current active session index."""
        with self._lock:
            return self._selected_index

    def get_timeline(self) -> tuple[float, float, bool]:
        """Returns (current_position_seconds, total_duration_seconds, is_playing)."""
        with self._lock:
            if not self.sessions or self._selected_index >= len(self.sessions):
                return (0.0, 0.0, False)
            s = self.sessions[self._selected_index]
            pos = s.position_sec
            dur = s.duration_sec
            is_playing = s.is_playing
            # position_sec already includes extrapolation in _refresh_all_sessions.
            return (pos, dur, is_playing)

    def seek(self, position_seconds: float):
        """Seek active media session to position in seconds."""
        with self._lock:
            if not self._loop or not self.sessions or self._selected_index >= len(self.sessions):
                return
            target_session = self.sessions[self._selected_index].session_obj
            curr = self.sessions[self._selected_index]
            if not curr.can_seek:
                return
            position_seconds = max(0.0, min(curr.duration_sec, position_seconds))
            curr.position_sec = position_seconds
            curr.last_updated_ts = time.time()

        async def _do_seek():
            try:
                ticks = int(position_seconds * 10_000_000)
                await target_session.try_change_playback_position_async(ticks)
            except Exception as e:
                print(f"[Poppy Media] Seek error: {e}")

        asyncio.run_coroutine_threadsafe(_do_seek(), self._loop)
        self.timeline_changed.emit(position_seconds, curr.duration_sec, curr.is_playing)

    def next_session(self):
        """Cycle to next active media session."""
        with self._lock:
            if not self.sessions:
                return
            next_idx = (self._selected_index + 1) % len(self.sessions)
        self.select_session(next_idx)

    def previous_session(self):
        """Cycle to previous active media session."""
        with self._lock:
            if not self.sessions:
                return
            prev_idx = (self._selected_index - 1) % len(self.sessions)
        self.select_session(prev_idx)

    def toggle_play_pause(self):
        self._dispatch_command("toggle")

    def next_track(self):
        self._dispatch_command("next")

    def previous_track(self):
        self._dispatch_command("previous")

    def _dispatch_command(self, cmd: str):
        VK_MEDIA_NEXT_TRACK = 0xB0
        VK_MEDIA_PREV_TRACK = 0xB1
        VK_MEDIA_PLAY_PAUSE = 0xB3

        def _fallback_key(code):
            try:
                import ctypes
                ctypes.windll.user32.keybd_event(code, 0, 1, 0)
                ctypes.windll.user32.keybd_event(code, 0, 1 | 2, 0)
            except Exception as ex:
                print(f"[Poppy Media] Keybd fallback error: {ex}")

        with self._lock:
            if not self._loop or not self.sessions or self._selected_index >= len(self.sessions):
                if cmd == "toggle":
                    _fallback_key(VK_MEDIA_PLAY_PAUSE)
                elif cmd == "next":
                    _fallback_key(VK_MEDIA_NEXT_TRACK)
                elif cmd == "previous":
                    _fallback_key(VK_MEDIA_PREV_TRACK)
                return

            target_session = self.sessions[self._selected_index].session_obj

        async def _exec():
            try:
                success = False
                if cmd == "toggle":
                    success = await target_session.try_toggle_play_pause_async()
                    if not success:
                        _fallback_key(VK_MEDIA_PLAY_PAUSE)
                elif cmd == "next":
                    success = await target_session.try_skip_next_async()
                    if not success:
                        _fallback_key(VK_MEDIA_NEXT_TRACK)
                elif cmd == "previous":
                    success = await target_session.try_skip_previous_async()
                    if not success:
                        _fallback_key(VK_MEDIA_PREV_TRACK)
            except Exception as e:
                print(f"[Poppy Media] Session command {cmd} error: {e}")
                if cmd == "toggle":
                    _fallback_key(VK_MEDIA_PLAY_PAUSE)
                elif cmd == "next":
                    _fallback_key(VK_MEDIA_NEXT_TRACK)
                elif cmd == "previous":
                    _fallback_key(VK_MEDIA_PREV_TRACK)

        asyncio.run_coroutine_threadsafe(_exec(), self._loop)

    def stop(self):
        self._running = False
