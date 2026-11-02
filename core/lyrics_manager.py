"""
Poppy Synchronized & Plain Lyrics Manager
Multi-provider lyrics engine supporting:
1. Spotify Color Lyrics (via optional sp_dc cookie from open.spotify.com)
2. NetEase Cloud Music (high-accuracy time-synced & Romanized lyrics)
3. LRCLIB API (open crowdsourced synced LRC database)
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

    def __init__(self, config: dict = None, parent=None):
        super().__init__(parent)
        self.config = config or {}
        self._cache_file = Path(os.path.expanduser("~/.poppy/lyrics_cache.json"))
        self._memory_cache: dict[str, dict] = {}
        self._current_request_key: str | None = None
        self._lock = threading.Lock()
        self._load_disk_cache()

    def update_config(self, config: dict):
        """Update active configuration (e.g. sp_dc cookie)."""
        self.config = config or {}

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
        data = None

        # 1. Spotify Color Lyrics (if sp_dc is provided in config)
        sp_dc = self.config.get("media", {}).get("spotify_sp_dc", "").strip() if self.config else ""
        if sp_dc:
            data = self._query_spotify(title, artist, sp_dc)

        # 2. NetEase Cloud Music (high-accuracy Romanized / synced lyrics)
        if not data:
            data = self._query_netease(title, artist)

        # 3. LRCLIB (open crowdsourced database)
        if not data:
            data = self._query_lrclib(title, artist, album)

        # 4. lyrics.ovh (plain text fallback)
        if not data:
            data = self._query_lyrics_ovh(title, artist)

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
            with urllib.request.urlopen(req, timeout=4) as res:
                tdata = json.loads(res.read().decode("utf-8"))
                token = tdata.get("accessToken")
                if not token:
                    return None

            clean_title = re.sub(r'\(.*?\)|\[.*?\]|feat\..*|ft\..*|- Single|- Remastered.*|- Live.*', '', title, flags=re.IGNORECASE).strip() or title
            clean_artist = re.sub(r'\(.*?\)|\[.*?\]', '', artist).strip() or artist

            # 2. Search track ID
            q = urllib.parse.quote(f"{clean_title} {clean_artist}")
            s_url = f"https://api.spotify.com/v1/search?q={q}&type=track&limit=1"
            s_req = urllib.request.Request(s_url, headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": headers["User-Agent"]
            })
            with urllib.request.urlopen(s_req, timeout=4) as s_res:
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
            with urllib.request.urlopen(lyr_req, timeout=4) as lyr_res:
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
        clean_title = re.sub(r'\(.*?\)|\[.*?\]|feat\..*|ft\..*|- Single|- Remastered.*|- Live.*', '', title, flags=re.IGNORECASE).strip() or title
        clean_artist = re.sub(r'\(.*?\)|\[.*?\]', '', artist).strip() or artist

        queries = [
            f"{clean_title} {clean_artist}",
            clean_title
        ]

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Cookie": "NMTID=00OAVK3xqDG726ITU6jopU6jF2yMk0AAAGCO8l1BA;"
        }

        for q in queries:
            try:
                s_url = f"https://music.163.com/api/search/pc?limit=5&type=1&offset=0&s={urllib.parse.quote(q)}"
                req = urllib.request.Request(s_url, headers=headers)
                with urllib.request.urlopen(req, timeout=4) as res:
                    raw = json.loads(res.read().decode("utf-8"))
                    songs = raw.get("result", {}).get("songs", [])
                    if not songs:
                        continue
                    song_id = songs[0]["id"]

                l_url = f"https://music.163.com/api/song/lyric?id={song_id}&lv=1"
                l_req = urllib.request.Request(l_url, headers=headers)
                with urllib.request.urlopen(l_req, timeout=4) as l_res:
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
                with urllib.request.urlopen(req, timeout=4.0) as resp:
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
                with urllib.request.urlopen(req, timeout=4.0) as resp:
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
                with urllib.request.urlopen(req, timeout=4.0) as resp:
                    results = json.loads(resp.read().decode("utf-8"))
                    if results and isinstance(results, list):
                        art_low = artist.lower()
                        clean_a_low = clean_artist.lower()
                        for r in results:
                            rn = (r.get("trackName") or "").lower()
                            ra = (r.get("artistName") or "").lower()
                            if r.get("syncedLyrics") and (art_low in ra or art_low in rn or clean_a_low in ra or ra in title.lower()):
                                return r
                        for r in results:
                            rn = (r.get("trackName") or "").lower()
                            ra = (r.get("artistName") or "").lower()
                            if (art_low in ra or art_low in rn or clean_a_low in ra or ra in title.lower()) and r.get("plainLyrics"):
                                return r
                        for r in results:
                            if (r.get("trackName") or "").strip().lower() == clean_title.lower() and r.get("syncedLyrics"):
                                return r
            except Exception:
                pass

        return None

    def _query_lyrics_ovh(self, title: str, artist: str) -> dict | None:
        headers = {"User-Agent": "PoppyNotch/1.0 (Windows)"}
        clean_title = re.sub(r'\(.*?\)|\[.*?\]|feat\..*|ft\..*|- Single|- Remastered.*|- Live.*', '', title, flags=re.IGNORECASE).strip() or title
        clean_artist = re.sub(r'\(.*?\)|\[.*?\]', '', artist).strip() or artist
        try:
            ovh_url = f"https://api.lyrics.ovh/v1/{urllib.parse.quote(clean_artist)}/{urllib.parse.quote(clean_title)}"
            req = urllib.request.Request(ovh_url, headers=headers)
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                odata = json.loads(resp.read().decode("utf-8"))
                txt = (odata.get("lyrics") or "").strip()
                if txt:
                    return {"plainLyrics": txt, "syncedLyrics": None}
        except Exception:
            pass
        return None
