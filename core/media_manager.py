"""
Poppy Windows GSMTC Media Manager
Interacts with Windows 11/10 Global System Media Transport Controls
for Spotify, YouTube, Chrome, Edge, Apple Music, etc.
Supports multi-session tracking and switching between active media sources.
"""

import asyncio
import threading
from PySide6.QtCore import QObject, Signal, QByteArray
from PySide6.QtGui import QPixmap, QImage


def format_source_name(app_id: str, title: str = "") -> str:
    """Format Windows App ID into a human-friendly name with app emoji/icon."""
    app_lower = (app_id or "").lower()
    title_lower = (title or "").lower()

    if "spotify" in app_lower:
        return "Spotify"
    elif "applemusic" in app_lower:
        return "Apple Music"
    elif "brave" in app_lower:
        if "music" in title_lower or "music.youtube" in title_lower:
            return "YouTube Music"
        elif "youtube" in title_lower or "circle of curvature" in title_lower or "part" in title_lower:
            return "YouTube"
        return "Brave"
    elif "chrome" in app_lower:
        if "music" in title_lower or "music.youtube" in title_lower:
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
    def __init__(self, index: int, session_obj, app_id: str, title: str, artist: str, album: str, is_playing: bool, thumbnail_bytes: bytes = None):
        self.index = index
        self.session_obj = session_obj
        self.app_id = app_id
        self.display_name = format_source_name(app_id, title)
        self.title = title or "Unknown Title"
        self.artist = artist or "Desktop Audio"
        self.album = album or ""
        self.is_playing = is_playing
        self.thumbnail_bytes = thumbnail_bytes

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "source_app": self.app_id,
            "display_name": self.display_name,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "is_playing": self.is_playing,
            "thumbnail_bytes": self.thumbnail_bytes
        }


class MediaManager(QObject):
    media_changed = Signal(dict)
    playback_changed = Signal(bool)
    sessions_updated = Signal(list, int)  # (list of session dicts, active_index)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sessions: list[SessionData] = []
        self._selected_index = 0
        self._loop = None
        self._thread = None
        self._running = False
        self._session_manager = None
        self._thumb_cache = {}  # (app_id, title) -> bytes

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
            except Exception as e:
                # Silently catch transient session errors
                pass
            await asyncio.sleep(1.0)

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

                # Cache and load thumbnail
                cache_key = (app_id, title)
                thumb_bytes = self._thumb_cache.get(cache_key)
                if thumb_bytes is None and props and props.thumbnail:
                    thumb_bytes = await self._read_stream(props.thumbnail)
                    if thumb_bytes:
                        self._thumb_cache[cache_key] = thumb_bytes

                data = SessionData(
                    index=idx,
                    session_obj=s,
                    app_id=app_id,
                    title=title,
                    artist=artist,
                    album=album,
                    is_playing=is_playing,
                    thumbnail_bytes=thumb_bytes
                )
                new_sessions.append(data)
            except Exception:
                continue

        # Clamp selected index
        if not new_sessions:
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
                "thumbnail_bytes": None
            }
            self.media_changed.emit(empty_data)
            self.playback_changed.emit(False)
            self.sessions_updated.emit([], 0)
            return

        # Auto-prioritize actively playing session if the user hasn't explicitly locked one
        if self._selected_index >= len(new_sessions):
            self._selected_index = 0

        self.sessions = new_sessions

        # Emit sessions list
        sessions_summary = [s.to_dict() for s in self.sessions]
        self.sessions_updated.emit(sessions_summary, self._selected_index)

        # Emit current selected session details
        curr = self.sessions[self._selected_index]
        self.media_changed.emit(curr.to_dict())
        self.playback_changed.emit(curr.is_playing)

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
        if 0 <= index < len(self.sessions):
            self._selected_index = index
            curr = self.sessions[index]
            self.media_changed.emit(curr.to_dict())
            self.playback_changed.emit(curr.is_playing)
            sessions_summary = [s.to_dict() for s in self.sessions]
            self.sessions_updated.emit(sessions_summary, self._selected_index)

    def next_session(self):
        """Cycle to next active media session."""
        if self.sessions:
            next_idx = (self._selected_index + 1) % len(self.sessions)
            self.select_session(next_idx)

    def previous_session(self):
        """Cycle to previous active media session."""
        if self.sessions:
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
