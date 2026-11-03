"""
Poppy Synchronized & Plain Lyrics Manager
Multi-provider lyrics engine supporting:
1. Spotify Color Lyrics (via optional sp_dc cookie from open.spotify.com)
2. LRCLIB API (open crowdsourced synced LRC database)
3. NetEase Cloud Music (time-synced & Romanized lyrics)
4. lyrics.ovh (plain text fallback)
Features thread-safe background fetching, title normalization, and local caching.
Zero external dependencies (pure stdlib).
"""

import json
import os
import re
import urllib.parse
import urllib.request
import threading
import time
from difflib import SequenceMatcher
from contextlib import contextmanager, nullcontext
import urllib.error
from pathlib import Path
from PySide6.QtCore import QObject, Signal, QTimer
from poppy.core.storage import data_path, write_json


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

    def __init__(self, config: dict = None, parent=None):
        super().__init__(parent)
        self.config = config or {}
        self._cache_file = data_path("lyrics_cache.json")
        self._memory_cache: dict[str, dict] = {}
        self._current_request_key: str | None = None
        self._lock = threading.Lock()
        self._pending_request = None
        self._worker_count = 0
        self._pending_key = None
        self._closed = False
        self._inflight = set()
        self._context = threading.local()
        self._cache_write_lock = threading.Lock()
        self._http_lock = threading.Lock()
        self._last_lrclib_request = 0
        self._host_backoff = {}
        self._miss_cache = {}
        self._delivered_key = None
        self._scheduled_request = None
        self._request_timer = QTimer(self)
        self._request_timer.setSingleShot(True)
        self._request_timer.setInterval(200)
        self._request_timer.timeout.connect(self._dispatch_request)
        self._load_disk_cache()

    def update_config(self, config: dict):
        """Update active configuration (e.g. sp_dc cookie)."""
        self.config = config or {}

    def _load_disk_cache(self):
        try:
            if self._cache_file.exists():
                with open(self._cache_file, "r", encoding="utf-8") as f:
                    self._memory_cache = json.load(f)
                    if not isinstance(self._memory_cache, dict):
                        self._memory_cache = {}
        except Exception:
            self._memory_cache = {}

    def _save_disk_cache(self):
        try:
            with self._cache_write_lock:
                with self._lock:
                    snapshot = dict(self._memory_cache)
                write_json(self._cache_file, snapshot)
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
            self.cancel_request()
            return
        if self._closed:
            return

        key = self._make_key(title, artist)
        if key == self._current_request_key and self._delivered_key == key:
            return
        self._current_request_key = key
        self._scheduled_request = (key, title, artist, album)
        with self._lock:
            cached = self._memory_cache.get(key)
            ready = isinstance(cached, dict) and bool(cached.get("plain") or cached.get("synced"))
        if ready:
            self._request_timer.stop()
            self._dispatch_request()
        else:
            self._request_timer.start()

    def _dispatch_request(self):
        request = self._scheduled_request
        self._scheduled_request = None
        if not request or self._closed or request[0] != self._current_request_key:
            return
        key, title, artist, album = request

        # 1. Check in-memory cache
        with self._lock:
            cached = self._memory_cache.get(key)
            if not isinstance(cached, dict):
                cached = None
            if cached is None and (self._pending_key == key or key in self._inflight):
                return
            missed = self._miss_cache.get(key, 0) > time.monotonic()
        if missed:
            self.lyrics_not_found.emit(key)
            return
        if cached is not None:
            plain = cached.get("plain", "")
            raw_lrc = cached.get("synced", "")
            synced = parse_lrc(raw_lrc)
            if plain or synced:
                self._delivered_key = key
                self.lyrics_loaded.emit(key, plain, synced)
                return

        # 2. Fetch in background thread
        with self._lock:
            self._pending_key = key
            self._pending_request = (key, title, artist, album)
            if self._worker_count < 2:
                self._worker_count += 1
                threading.Thread(target=self._drain_requests, daemon=True, name="poppy-lyrics").start()

    def _drain_requests(self):
        while True:
            with self._lock:
                request = self._pending_request
                self._pending_request = None
                if self._closed or request is None:
                    self._worker_count -= 1
                    return
                self._inflight.add(request[0])
            self._context.key = request[0]
            self._context.deadline = time.monotonic() + 12
            self._context.network_failed = False
            try:
                self._fetch_worker(*request)
            except Exception:
                if not self._closed and self._current_request_key == request[0]:
                    self.lyrics_not_found.emit(request[0])
            finally:
                with self._lock:
                    self._inflight.discard(request[0])
                    if self._pending_key == request[0]:
                        self._pending_key = None

    def cancel_request(self):
        self._request_timer.stop()
        self._scheduled_request = None
        self._delivered_key = None
        with self._lock:
            self._current_request_key = None
            self._pending_key = None
            self._pending_request = None

    def close(self):
        self._closed = True
        self.cancel_request()

    def _fetch_worker(self, req_key: str, title: str, artist: str, album: str):
        data = None
        sp_dc = self.config.get("media", {}).get("spotify_sp_dc", "").strip() if self.config else ""
        providers = [(lambda: self._query_lrclib(title, artist, album), 6),
                     (lambda: self._query_netease(title, artist), 4)]
        if sp_dc:
            providers.insert(0, (lambda: self._query_spotify(title, artist, sp_dc), 4))
        providers.append((lambda: self._query_lyrics_ovh(title, artist), 3))
        for provider, budget in providers:
            if self._closed or self._current_request_key != req_key or not self._request_active():
                return
            self._context.provider_deadline = time.monotonic() + budget
            try:
                data = provider()
            except Exception:
                data = None
            if data:
                break

        with self._lock:
            if self._closed:
                return
            if self._pending_key == req_key:
                self._pending_key = None
            if not data:
                if self._current_request_key == req_key:
                    self._miss_cache = {key: expiry for key, expiry in self._miss_cache.items() if expiry > time.monotonic()}
                    if not getattr(self._context, "network_failed", False):
                        self._miss_cache[req_key] = time.monotonic() + 60
                    while len(self._miss_cache) > 128:
                        del self._miss_cache[next(iter(self._miss_cache))]
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
                while len(self._memory_cache) > 128:
                    del self._memory_cache[next(iter(self._memory_cache))]
            if self._current_request_key == req_key:
                if plain or synced:
                    self._delivered_key = req_key
                    self.lyrics_loaded.emit(req_key, plain, synced)
                else:
                    self.lyrics_not_found.emit(req_key)
        if plain or raw_lrc:
            self._save_disk_cache()

    def _request_active(self):
        key = getattr(self._context, "key", None)
        return not self._closed and (key is None or key == self._current_request_key)

    @contextmanager
    def _urlopen(self, request, timeout=4):
        host = urllib.parse.urlsplit(request.full_url).hostname
        # LRCLIB asks clients to serialize requests and leave a short interval.
        with self._http_lock if host == "lrclib.net" else nullcontext():
            if host == "lrclib.net":
                while time.monotonic() - self._last_lrclib_request < 0.2:
                    if not self._request_active():
                        raise RuntimeError("Superseded lyrics request")
                    time.sleep(0.025)
            if not self._request_active():
                raise RuntimeError("Superseded lyrics request")
            remaining = min(getattr(self._context, "deadline", float("inf")),
                            getattr(self._context, "provider_deadline", float("inf"))) - time.monotonic()
            if remaining <= 0 or self._host_backoff.get(host, 0) > time.monotonic():
                self._context.network_failed = True
                raise TimeoutError("Lyrics provider unavailable or lookup budget exhausted")
            try:
                if host == "lrclib.net":
                    self._last_lrclib_request = time.monotonic()
                with urllib.request.urlopen(request, timeout=min(timeout, 4.0, remaining)) as response:
                    yield response
            except urllib.error.HTTPError as error:
                if error.code in (429, 503):
                    try:
                        seconds = max(1, min(300, int(error.headers.get("Retry-After", "2"))))
                    except (ValueError, TypeError):
                        seconds = 2
                    self._host_backoff[host] = time.monotonic() + seconds
                if error.code != 404:
                    self._context.network_failed = True
                raise
            except (OSError, TimeoutError):
                self._context.network_failed = True
                raise

    @staticmethod
    def _clean_title(title):
        title = re.sub(r'\s*[-–—]\s*from\s+["“].*$', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\s*[\[(](?:from\s+|official\s+|lyrics?\b).*?[\])]', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\s+(?:feat\.|ft\.).*|\s*-\s*Single\s*$', '', title, flags=re.IGNORECASE)
        return title.strip()

    @classmethod
    def _best_match(cls, results, title, artist):
        def normalize(value):
            return re.sub(r'[^\w]+', '', value.casefold())
        wanted = normalize(cls._clean_title(title))
        performer = normalize(artist)
        candidates = []
        for record in results if isinstance(results, list) else []:
            if not isinstance(record, dict) or not (record.get("syncedLyrics") or record.get("plainLyrics")):
                continue
            name = normalize(cls._clean_title(record.get("trackName") or record.get("name") or ""))
            actual_artist = normalize(record.get("artistName") or "")
            title_score = SequenceMatcher(None, wanted, name).ratio()
            artist_match = not performer or (actual_artist and (performer in actual_artist or actual_artist in performer))
            if title_score >= 0.8 and artist_match:
                candidates.append((title_score, bool(record.get("syncedLyrics")), record))
        return max(candidates, key=lambda item: item[:2])[2] if candidates else None

    def _query_spotify(self, title: str, artist: str, sp_dc: str) -> dict | None:
        """Fetch official synchronized lyrics from Spotify's internal Color Lyrics endpoint."""
        try:
            # 1. Get access token from sp_dc cookie
            token_url = "https://open.spotify.com/get_access_token?reason=transport&productType=web-player"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Cookie": f"sp_dc={sp_dc.strip()}"
            }
            req = urllib.request.Request(token_url, headers=headers)
            with self._urlopen(req, timeout=4) as res:
                tdata = json.loads(res.read().decode("utf-8"))
                token = tdata.get("accessToken")
                if not token:
                    return None

            clean_title = self._clean_title(title) or title
            clean_artist = re.sub(r'\(.*?\)|\[.*?\]', '', artist).strip() or artist

            # 2. Search track ID
            q = urllib.parse.quote(f"{clean_title} {clean_artist}")
            s_url = f"https://api.spotify.com/v1/search?q={q}&type=track&limit=1"
            s_req = urllib.request.Request(s_url, headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": headers["User-Agent"]
            })
            with self._urlopen(s_req, timeout=4) as s_res:
                s_data = json.loads(s_res.read().decode("utf-8"))
                items = s_data.get("tracks", {}).get("items", [])
                if not items:
                    return None
                track_id = items[0]["id"]

            # 3. Query Color Lyrics
            lyr_url = f"https://spclient.wg.spotify.com/color-lyrics/v2/track/{track_id}?format=json&vocalRemoval=false"
            lyr_req = urllib.request.Request(lyr_url, headers={
                "Authorization": f"Bearer {token}",
                "App-Platform": "WebPlayer",
                "User-Agent": headers["User-Agent"]
            })
            with self._urlopen(lyr_req, timeout=4) as lyr_res:
                lyr_data = json.loads(lyr_res.read().decode("utf-8"))
                lines_data = lyr_data.get("lyrics", {}).get("lines", [])
                if not lines_data:
                    return None

                lrc_lines = []
                plain_lines = []
                for item in lines_data:
                    ms = int(item.get("startTimeMs", 0))
                    words = item.get("words", "").strip()
                    if not words:
                        continue
                    mm = ms // 60000
                    ss = (ms % 60000) / 1000.0
                    lrc_lines.append(f"[{mm:02d}:{ss:05.2f}]{words}")
                    plain_lines.append(words)

                return {
                    "syncedLyrics": "\n".join(lrc_lines),
                    "plainLyrics": "\n".join(plain_lines)
                }
        except Exception:
            return None

    def _query_netease(self, title: str, artist: str) -> dict | None:
        """Fetch synchronized LRC lyrics from NetEase Cloud Music (high quality Romanized text)."""
        clean_title = self._clean_title(title) or title
        clean_artist = re.sub(r'\(.*?\)|\[.*?\]', '', artist).strip() or artist

        queries = dict.fromkeys([
            f"{clean_title} {clean_artist}",
            clean_title
        ])

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Cookie": "NMTID=00OAVK3xqDG726ITU6jopU6jF2yMk0AAAGCO8l1BA;"
        }

        for q in queries:
            if not self._request_active():
                return None
            try:
                s_url = f"https://music.163.com/api/search/pc?limit=5&type=1&offset=0&s={urllib.parse.quote(q)}"
                req = urllib.request.Request(s_url, headers=headers)
                with self._urlopen(req, timeout=4) as res:
                    raw = json.loads(res.read().decode("utf-8"))
                    songs = raw.get("result", {}).get("songs", [])
                    if not songs:
                        continue
                    song_id = songs[0]["id"]

                l_url = f"https://music.163.com/api/song/lyric?id={song_id}&lv=1"
                l_req = urllib.request.Request(l_url, headers=headers)
                with self._urlopen(l_req, timeout=4) as l_res:
                    l_data = json.loads(l_res.read().decode("utf-8"))
                    raw_lyric = l_data.get("lrc", {}).get("lyric", "")
                    if not raw_lyric or "[" not in raw_lyric:
                        continue

                    # Clean credit metadata
                    clean_lines = []
                    for line in raw_lyric.splitlines():
                        if any(marker in line for marker in ("作词", "作曲", "编曲", "制作人")):
                            continue
                        clean_lines.append(line)
                    clean_lrc = "\n".join(clean_lines).strip()
                    if clean_lrc:
                        return {
                            "syncedLyrics": clean_lrc,
                            "plainLyrics": re.sub(r'\[.*?\]', '', clean_lrc).strip()
                        }
            except Exception:
                continue
        return None

    def _query_lrclib(self, title: str, artist: str, album: str) -> dict | None:
        headers = {"User-Agent": "Poppy/dev (https://github.com/antaripnandi/poppy)"}

        clean_title = self._clean_title(title) or title
        clean_artist = re.sub(r'\(.*?\)|\[.*?\]', '', artist).strip() or artist

        # 1. Direct lookup by title + artist, trying normalized metadata first.
        for t, a in list(dict.fromkeys([(clean_title, clean_artist), (title, artist)])):
            if not self._request_active():
                return None
            if not t or not a:
                continue
            params = {"track_name": t, "artist_name": a}
            url = f"https://lrclib.net/api/get?{urllib.parse.urlencode(params)}"
            try:
                req = urllib.request.Request(url, headers=headers)
                with self._urlopen(req, timeout=4.0) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    if data and (data.get("syncedLyrics") or data.get("plainLyrics")):
                        return data
            except Exception:
                pass

        # 2. Targeted search with track_name and artist_name
        for t, a in list(dict.fromkeys([(clean_title, clean_artist), (title, artist)])):
            if not self._request_active():
                return None
            if not t or not a:
                continue
            params = {"track_name": t, "artist_name": a}
            url = f"https://lrclib.net/api/search?{urllib.parse.urlencode(params)}"
            try:
                req = urllib.request.Request(url, headers=headers)
                with self._urlopen(req, timeout=4.0) as resp:
                    results = json.loads(resp.read().decode("utf-8"))
                    match = self._best_match(results, title, clean_artist)
                    if match:
                        return match
            except Exception:
                pass

        # 3. Smart Title-Only Search (handles featured artists, remix/collab credits)
        for t in dict.fromkeys([clean_title, title]):
            if not self._request_active():
                return None
            if not t:
                continue
            url = f"https://lrclib.net/api/search?{urllib.parse.urlencode({'track_name': t})}"
            try:
                req = urllib.request.Request(url, headers=headers)
                with self._urlopen(req, timeout=4.0) as resp:
                    results = json.loads(resp.read().decode("utf-8"))
                    match = self._best_match(results, title, clean_artist)
                    if match:
                        return match
            except Exception:
                pass

        return None

    def _query_lyrics_ovh(self, title: str, artist: str) -> dict | None:
        headers = {"User-Agent": "Poppy/dev (https://github.com/antaripnandi/poppy)"}
        clean_title = self._clean_title(title) or title
        clean_artist = re.sub(r'\(.*?\)|\[.*?\]', '', artist).strip() or artist
        try:
            ovh_url = f"https://api.lyrics.ovh/v1/{urllib.parse.quote(clean_artist)}/{urllib.parse.quote(clean_title)}"
            req = urllib.request.Request(ovh_url, headers=headers)
            with self._urlopen(req, timeout=3.5) as resp:
                odata = json.loads(resp.read().decode("utf-8"))
                txt = (odata.get("lyrics") or "").strip()
                if txt:
                    return {"plainLyrics": txt, "syncedLyrics": None}
        except Exception:
            pass
        return None
