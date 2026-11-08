"""
Poppy Dynamic Weather Engine
Fetches real-time weather and automatic geolocation without hardcoded values.
Uses lightweight IP-based location and Open-Meteo free public forecast API.
Zero external dependencies (uses standard library urllib and json).
"""

import threading
import urllib.request
import urllib.parse
import json

from PySide6.QtCore import QObject, Signal, QTimer
from poppy.ui.icons import Icons


class WeatherManager(QObject):
    """
    Background weather monitor. Resolves client location via custom city or IP geolocation,
    fetches live temperature, weather code, and high/low forecasts via Open-Meteo.
    """
    weather_updated = Signal(dict)
    _received = Signal(int, object, dict)

    def __init__(self, config: dict = None, parent=None):
        super().__init__(parent)
        self.config = config or {}
        self._cached_data = {}
        self._request = 0
        self._received.connect(self._publish)
        self._timer = QTimer(self)
        self._timer.setInterval(20 * 60 * 1000)  # Refresh every 20 minutes
        self._timer.timeout.connect(self.refresh)

    def update_config(self, config: dict):
        """Update weather preferences and trigger immediate background fetch."""
        previous = self._preferences()
        self.config = config or {}
        if previous != self._preferences():
            self._cached_data = {}
            self.weather_updated.emit({"display_text": "Updating weather…"})
        self.refresh()

    def start(self):
        """Starts periodic weather refresh and triggers initial fetch."""
        self.refresh()
        self._timer.start()

    def refresh(self):
        """Asynchronously queries geolocation and live weather."""
        self._request += 1
        threading.Thread(target=self._worker, args=(self._request, self._preferences()), daemon=True).start()

    def _preferences(self):
        weather = self.config.get("weather", {})
        return str(weather.get("city") or "").strip(), str(weather.get("unit") or "celsius").lower()

    def _worker(self, request=None, preferences=None):
        request = self._request if request is None else request
        preferences = self._preferences() if preferences is None else preferences
        data = self._fetch(*preferences)
        try:
            self._received.emit(request, preferences, data)
        except RuntimeError:
            pass  # The window closed before the fetch finished.

    def _publish(self, request, preferences, data):
        if request != self._request or preferences != self._preferences():
            return
        if "temp" in data:
            self._cached_data = data
        elif not data and self._cached_data:
            data = self._cached_data
        self.weather_updated.emit(data or {"display_text": "Weather unavailable"})

    def _fetch(self, target_city, unit):
        if not target_city:
            return {"display_text": "Set a weather location in Settings"}

        city = "Local"
        region = ""
        country = ""
        lat, lon = None, None

        # 1a. If user supplied a specific city, geocode with Open-Meteo
        if target_city.lower() != "auto-detect":
            try:
                enc_city = urllib.parse.quote(target_city)
                geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={enc_city}&count=1"
                req = urllib.request.Request(geo_url, headers={"User-Agent": "Poppy/1.0"})
                with urllib.request.urlopen(req, timeout=4) as res:
                    gdata = json.loads(res.read().decode())
                    results = gdata.get("results")
                    if results and isinstance(results, list):
                        r = results[0]
                        city = r.get("name", target_city)
                        region = r.get("admin1", "")
                        country = r.get("country", "")
                        lat = float(r.get("latitude"))
                        lon = float(r.get("longitude"))
            except Exception:
                pass

        # IP-based lookup is only used when the user chooses it.
        else:
            geo_services = [
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
            return {"display_text": "Weather location unavailable"}

        # 2. Open-Meteo Weather API
        temp_unit_param = "&temperature_unit=fahrenheit" if unit == "fahrenheit" else ""
        unit_sym = "°F" if unit == "fahrenheit" else "°C"
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,weather_code,is_day"
            f"&daily=temperature_2m_max,temperature_2m_min&timezone=auto{temp_unit_param}"
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

                return {
                    "city": city,
                    "region": region,
                    "country": country,
                    "temp": temp,
                    "unit": unit_sym,
                    "high": high,
                    "low": low,
                    "humidity": humidity,
                    "condition": cond,
                    "icon": icon,
                    "is_day": is_day,
                    "display_text": f"{temp}{unit_sym} {cond} · H {high}° L {low}° · {city}",
                    "short_text": f"{temp}{unit_sym} {cond} · H {high}° L {low}°"
                }
        except Exception:
            return {}

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

