"""
Poppy Synchronized & Plain Lyrics Manager
Fetches high-accuracy synchronized (LRC) and plain lyrics using LRCLIB API.
Features thread-safe background fetching, title normalization, and local caching.
Zero external dependencies (pure stdlib).
"""

import json
import os
import re
import urllib.parse
import urllib.request
import threading
from pathlib import Path
from PySide6.QtCore import QObject, Signal


def parse_lrc(lrc_text: str) -> list[tuple[float, str]]:
    """Parse LRC timestamped lyrics into sorted (timestamp_seconds, text) tuples."""
    if not lrc_text:
        return []
    lines = []
    pattern = re.compile(r'\[(\d+):(\d+(?:\.\d+)?)\](.*)')
    for raw_line in lrc_text.splitlines():
        match = pattern.match(raw_line.strip())
        if match:
            mins = int(match.group(1))
            secs = float(match.group(2))
            text = match.group(3).strip()
            if text:
                lines.append((mins * 60.0 + secs, text))
    lines.sort(key=lambda x: x[0])
    return lines


class LyricsManager(QObject):
    """
    Asynchronous lyrics fetcher and cache manager.
    Emits `lyrics_loaded(track_key, plain_lyrics, synced_lines)` when lyrics arrive.
    """
    lyrics_loaded = Signal(str, str, list)  # track_key, plain_lyrics, synced_lines [(time_sec, text), ...]
    lyrics_not_found = Signal(str)          # track_key

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache_file = Path(os.path.expanduser("~/.poppy/lyrics_cache.json"))
        self._memory_cache: dict[str, dict] = {}
        self._current_request_key: str | None = None
        self._lock = threading.Lock()
        self._load_disk_cache()

    def _load_disk_cache(self):
        try:
            if self._cache_file.exists():
                with open(self._cache_file, "r", encoding="utf-8") as f:
                    self._memory_cache = json.load(f)
        except Exception:
            self._memory_cache = {}

    def _save_disk_cache(self):
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump(self._memory_cache, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    @staticmethod
    def _make_key(title: str, artist: str) -> str:
        t = (title or "").strip().lower()
        a = (artist or "").strip().lower()
        return f"{t}::: {a}"

    def request_lyrics(self, title: str, artist: str, album: str = ""):
        """Request lyrics asynchronously for the given track."""
        if not title or title.lower() in ("no media playing", "unknown title", "system audio"):
            self._current_request_key = None
            return

        key = self._make_key(title, artist)
        self._current_request_key = key

        # 1. Check in-memory cache
        with self._lock:
            cached = self._memory_cache.get(key)
        if cached is not None:
            plain = cached.get("plain", "")
            raw_lrc = cached.get("synced", "")
            synced = parse_lrc(raw_lrc)
            if plain or synced:
                self.lyrics_loaded.emit(key, plain, synced)
                return

        # 2. Fetch in background thread
        threading.Thread(target=self._fetch_worker, args=(key, title, artist, album), daemon=True).start()

    def _fetch_worker(self, req_key: str, title: str, artist: str, album: str):
        data = self._query_lrclib(title, artist, album)

        with self._lock:
            if not data:
                if self._current_request_key == req_key:
                    self.lyrics_not_found.emit(req_key)
                return

            plain = data.get("plainLyrics") or ""
            raw_lrc = data.get("syncedLyrics") or ""
            synced = parse_lrc(raw_lrc)

            if plain or raw_lrc:
                self._memory_cache[req_key] = {
                    "plain": plain,
                    "synced": raw_lrc
                }
                self._save_disk_cache()

            if self._current_request_key == req_key:
                if plain or synced:
                    self.lyrics_loaded.emit(req_key, plain, synced)
                else:
                    self.lyrics_not_found.emit(req_key)

    def _query_lrclib(self, title: str, artist: str, album: str) -> dict | None:
        headers = {"User-Agent": "PoppyNotch/1.0 (Windows)"}

        clean_title = re.sub(r'\(.*?\)|\[.*?\]|feat\..*|ft\..*|- Single|- Remastered.*|- Live.*', '', title, flags=re.IGNORECASE).strip() or title
        clean_artist = re.sub(r'\(.*?\)|\[.*?\]', '', artist).strip() or artist

        # 1. Direct GET by exact title + artist (fast index lookup, no 503 errors)
        for t, a in [(title, artist), (clean_title, clean_artist)]:
            if not t or not a:
                continue
            params = {"track_name": t, "artist_name": a}
            url = f"https://lrclib.net/api/get?{urllib.parse.urlencode(params)}"
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=3.5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    if data and (data.get("syncedLyrics") or data.get("plainLyrics")):
                        return data
            except Exception:
                pass

        # 2. Targeted search with track_name and artist_name
        for t, a in [(title, artist), (clean_title, clean_artist)]:
            if not t or not a:
                continue
            params = {"track_name": t, "artist_name": a}
            url = f"https://lrclib.net/api/search?{urllib.parse.urlencode(params)}"
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=3.5) as resp:
                    results = json.loads(resp.read().decode("utf-8"))
                    if results and isinstance(results, list):
                        for r in results:
                            if r.get("syncedLyrics"):
                                return r
                        for r in results:
                            if r.get("plainLyrics"):
                                return r
            except Exception:
                pass

        # 3. Smart Title-Only Search (handles featured artists, remix/collab credits)
        for t in [clean_title, title]:
            if not t:
                continue
            url = f"https://lrclib.net/api/search?{urllib.parse.urlencode({'track_name': t})}"
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=3.5) as resp:
                    results = json.loads(resp.read().decode("utf-8"))
                    if results and isinstance(results, list):
                        art_low = artist.lower()
                        clean_a_low = clean_artist.lower()
                        # Pass 3a: Synced lyrics matching artist or featured artist
                        for r in results:
                            rn = (r.get("trackName") or "").lower()
                            ra = (r.get("artistName") or "").lower()
                            if r.get("syncedLyrics") and (art_low in ra or art_low in rn or clean_a_low in ra or ra in title.lower()):
                                return r
                        # Pass 3b: Plain lyrics matching artist or featured artist
                        for r in results:
                            rn = (r.get("trackName") or "").lower()
                            ra = (r.get("artistName") or "").lower()
                            if (art_low in ra or art_low in rn or clean_a_low in ra or ra in title.lower()) and r.get("plainLyrics"):
                                return r
                        # Pass 3c: Exact title match with synced lyrics
                        for r in results:
                            if (r.get("trackName") or "").strip().lower() == clean_title.lower() and r.get("syncedLyrics"):
                                return r
            except Exception:
                pass

        # 4. Fallback: Secondary plain text lyrics provider (lyrics.ovh)
        try:
            ovh_url = f"https://api.lyrics.ovh/v1/{urllib.parse.quote(clean_artist)}/{urllib.parse.quote(clean_title)}"
            req = urllib.request.Request(ovh_url, headers=headers)
            with urllib.request.urlopen(req, timeout=3) as resp:
                odata = json.loads(resp.read().decode("utf-8"))
                txt = (odata.get("lyrics") or "").strip()
                if txt:
                    return {"plainLyrics": txt, "syncedLyrics": None}
        except Exception:
            pass

        return None

