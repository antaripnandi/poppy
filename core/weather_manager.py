"""
Poppy Dynamic Weather Engine
Fetches real-time weather and automatic geolocation without hardcoded values.
Uses lightweight IP-based location and Open-Meteo free public forecast API.
Zero external dependencies (uses standard library urllib and json).
"""

import threading
import urllib.request
import json

from PySide6.QtCore import QObject, Signal, QTimer
from poppy.ui.icons import Icons


class WeatherManager(QObject):
    """
    Background weather monitor. Resolves client location via IP geolocation,
    fetches live temperature, weather code, and high/low forecasts.
    """
    weather_updated = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cached_data = {}
        self._timer = QTimer(self)
        self._timer.setInterval(20 * 60 * 1000)  # Refresh every 20 minutes
        self._timer.timeout.connect(self.refresh)

    def start(self):
        """Starts periodic weather refresh and triggers initial fetch."""
        self.refresh()
        self._timer.start()

    def refresh(self):
        """Asynchronously queries geolocation and live weather."""
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        city = "Local"
        region = ""
        country = ""
        lat, lon = None, None

        # 1. Geolocation lookup (with multiple fallbacks)
        geo_services = [
            ("http://ip-api.com/json/", lambda d: (d.get("city", "Local"), d.get("regionName", ""), d.get("country", ""), d.get("lat"), d.get("lon")) if d.get("status") == "success" else None),
            ("https://get.geojs.io/v1/ip/geo.json", lambda d: (d.get("city", "Local"), d.get("region", ""), d.get("country", ""), float(d.get("latitude")), float(d.get("longitude"))) if d.get("latitude") else None),
            ("https://ipapi.co/json/", lambda d: (d.get("city", "Local"), d.get("region", ""), d.get("country_name", ""), float(d.get("latitude")), float(d.get("longitude"))) if d.get("latitude") else None),
        ]

        for url, parser in geo_services:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Poppy/1.0"})
                with urllib.request.urlopen(req, timeout=4) as res:
                    raw = json.loads(res.read().decode())
                    parsed = parser(raw)
                    if parsed:
                        city, region, country, lat, lon = parsed
                        break
            except Exception:
                continue

        if lat is None or lon is None:
            lat, lon = 13.08, 80.27  # Default if offline

        # 2. Open-Meteo Weather API
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,weather_code,is_day"
            f"&daily=temperature_2m_max,temperature_2m_min&timezone=auto"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Poppy/1.0"})
            with urllib.request.urlopen(req, timeout=5) as res:
                wdata = json.loads(res.read().decode())
                current = wdata.get("current", {})
                daily = wdata.get("daily", {})

                temp = int(round(current.get("temperature_2m", 25)))
                humidity = int(round(current.get("relative_humidity_2m", 60)))
                code = current.get("weather_code", 0)
                is_day = bool(current.get("is_day", 1))

                high = int(round(daily.get("temperature_2m_max", [temp])[0]))
                low = int(round(daily.get("temperature_2m_min", [temp])[0]))

                cond, icon = self._map_wmo_code(code, is_day)

                data = {
                    "city": city,
                    "region": region,
                    "country": country,
                    "temp": temp,
                    "high": high,
                    "low": low,
                    "humidity": humidity,
                    "condition": cond,
                    "icon": icon,
                    "is_day": is_day,
                    "display_text": f"{temp}° {cond} · H {high}° L {low}° · {city}",
                    "short_text": f"{temp}° {cond} · H {high}° L {low}°"
                }
                self._cached_data = data
                self.weather_updated.emit(data)
        except Exception:
            if self._cached_data:
                self.weather_updated.emit(self._cached_data)

    def _map_wmo_code(self, code: int, is_day: bool) -> tuple[str, str]:
        """Maps WMO Weather Codes to human text and Segoe Fluent glyphs."""
        if code == 0:
            return "Clear", Icons.WEATHER_SUN if is_day else Icons.WEATHER_MOON
        elif code in (1, 2):
            return "Partly Cloudy", Icons.WEATHER_SUN if is_day else Icons.WEATHER_MOON
        elif code == 3:
            return "Overcast", Icons.WEATHER_CLOUD
        elif code in (45, 48):
            return "Foggy", Icons.WEATHER_CLOUD
        elif code in (51, 53, 55, 61, 63, 65, 80, 81, 82):
            return "Rain", Icons.WEATHER_RAIN
        elif code in (71, 73, 75, 77, 85, 86):
            return "Snow", Icons.WEATHER_SNOW
        elif code in (95, 96, 99):
            return "Thunderstorm", Icons.WEATHER_STORM
        return "Fair", Icons.WEATHER_SUN if is_day else Icons.WEATHER_MOON

