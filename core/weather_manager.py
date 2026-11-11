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
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal, QTimer
from poppy.ui.icons import Icons


@dataclass(frozen=True)
class WeatherLocation:
    city: str
    latitude: float
    longitude: float
    region: str = ""
    country: str = ""
    district: str = ""

    @property
    def label(self):
        return ", ".join(dict.fromkeys(part for part in (self.city, self.district, self.region, self.country) if part))

    @classmethod
    def from_data(cls, data):
        if not isinstance(data, dict) or not isinstance(data.get("city"), str) or not data["city"].strip():
            return None
        try:
            latitude, longitude = float(data["latitude"]), float(data["longitude"])
        except (KeyError, TypeError, ValueError, OverflowError):
            return None
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return None
        details = {key: data[key].strip() for key in ("region", "country", "district") if isinstance(data.get(key), str)}
        return cls(data["city"].strip(), latitude, longitude, **details)


def city_search_url(query, count=8):
    params = urllib.parse.urlencode({"name": query, "count": count})
    return f"https://geocoding-api.open-meteo.com/v1/search?{params}"


def city_search_results(payload):
    results = payload.get("results", []) if isinstance(payload, dict) else None
    if not isinstance(results, list):
        raise ValueError("Invalid city search response")
    cities = {}
    for result in results:
        if not isinstance(result, dict):
            continue
        location = WeatherLocation.from_data({
            "city": result.get("name"), "latitude": result.get("latitude"), "longitude": result.get("longitude"),
            "region": result.get("admin1"), "country": result.get("country"), "district": result.get("admin2"),
        })
        if location:
            cities.setdefault(location.label, location)
    return cities


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
        """Refresh when the forecast location or units change."""
        previous = self._preferences()
        self.config = config or {}
        if previous != self._preferences():
            self._cached_data = {}
            if self._preferences()[0]:
                self.weather_updated.emit({"display_text": "Updating weather…"})
            self.refresh()

    def start(self):
        """Starts periodic weather refresh and triggers initial fetch."""
        self.refresh()

    def refresh(self):
        """Asynchronously queries geolocation and live weather."""
        self._request += 1
        preferences = self._preferences()
        if not preferences[0]:
            self._timer.stop()
            self._publish(self._request, preferences, self._fetch(*preferences))
            return
        if not self._timer.isActive():
            self._timer.start()
        threading.Thread(target=self._worker, args=(self._request, preferences), daemon=True).start()

    def _preferences(self):
        weather = self.config.get("weather", {})
        city = str(weather.get("city") or "").strip()
        unit = str(weather.get("unit") or "celsius").lower()
        location = WeatherLocation.from_data(weather.get("location"))
        return city, unit, location if location and city == location.city else None

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

    def _fetch(self, target_city, unit, location=None):
        if not target_city:
            return {"display_text": "Set a weather location in Settings"}

        city = "Local"
        region = ""
        country = ""
        lat, lon = None, None

        if location is not None:
            city, region, country = location.city, location.region, location.country
            lat, lon = location.latitude, location.longitude
        elif target_city.lower() != "auto-detect":
            # Older profiles may have a city name without a selected location.
            try:
                req = urllib.request.Request(city_search_url(target_city, count=1), headers={"User-Agent": "Poppy/1.0"})
                with urllib.request.urlopen(req, timeout=4) as res:
                    match = next(iter(city_search_results(json.load(res)).values()), None)
                    if match:
                        city, region, country = match.city, match.region, match.country
                        lat, lon = match.latitude, match.longitude
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

