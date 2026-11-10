"""Weather location searches save the selected match and ignore stale replies."""

import io
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from PySide6.QtCore import Qt
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtTest import QTest

from poppy.core.storage import data_path
from poppy.core.weather_manager import WeatherManager
from poppy.ui.settings_window import SettingsWindow


def test_city_dropdown_saves_selected_coordinates(audit_app, monkeypatch):
    class Reply:
        readyRead = SimpleNamespace(connect=lambda _: None)

        def __init__(self, query):
            self.query = query
            self.aborted = False
            self.body = b""

        def abort(self):
            self.aborted = True

        def setReadBufferSize(self, _):
            pass

        def deleteLater(self):
            pass

        def attribute(self, _):
            return 200

        def error(self):
            return QNetworkReply.NetworkError.NoError

        def bytesAvailable(self):
            return len(self.body)

        def readAll(self):
            return self.body

    settings = SettingsWindow()
    settings.select_page("Weather")
    settings.show()
    field = settings.txt_weather_city
    field.setFocus()
    audit_app.processEvents()
    requests = []

    def get(request):
        url = urlsplit(request.url().toString())
        assert (url.scheme, url.hostname) == ("https", "geocoding-api.open-meteo.com")
        reply = Reply(parse_qs(url.query)["name"][0])
        requests.append(reply)
        return reply

    monkeypatch.setattr(field._network, "get", get)
    QTest.keyClicks(field, "Spr")
    assert not requests
    QTest.qWait(300)
    old, = requests
    assert old.query == "Spr"
    QTest.keyClicks(field, "ingfield")
    assert old.aborted
    QTest.qWait(300)
    current = requests[-1]
    assert current.query == "Springfield"
    field._finish_search(old)
    assert field._reply is current
    assert not settings._save_settings()
    assert not data_path("config.json").exists()

    current.body = json.dumps({"results": [
        {"name": "Springfield", "admin1": "Illinois", "country": "United States", "latitude": 39.8, "longitude": -89.6},
        {"name": "Springfield", "admin1": "Massachusetts", "country": "United States", "latitude": 42.1, "longitude": -72.6},
    ]}).encode()
    field._finish_search(current)
    popup = field.completer().popup()
    assert popup.isVisible()
    assert popup.model().index(1, 0).data() == "Springfield, Massachusetts, United States"
    popup.setCurrentIndex(popup.model().index(1, 0))
    QTest.keyClick(popup, Qt.Key.Key_Return)
    assert field.text() == "Springfield, Massachusetts, United States"
    assert settings._save_settings()
    config = json.loads(data_path("config.json").read_text(encoding="utf-8"))
    assert config["weather"]["city"] == "Springfield"
    assert config["weather"]["location"]["longitude"] == -72.6

    reopened = SettingsWindow(config)
    assert reopened.txt_weather_city.text() == field.text()
    urls = []

    def forecast(request, timeout):
        url = urlsplit(request.full_url)
        urls.append(url)
        return io.BytesIO(b'{"current":{"temperature_2m":19}}')

    monkeypatch.setattr("poppy.core.weather_manager.urllib.request.urlopen", forecast)
    manager = WeatherManager(config)
    data = manager._fetch(*manager._preferences())
    url, = urls
    assert url.hostname == "api.open-meteo.com"
    assert parse_qs(url.query)["latitude"] == ["42.1"]
    assert data["region"] == "Massachusetts"


def test_weather_location_preserves_legacy_and_explicit_modes():
    settings = SettingsWindow({"weather": {"city": "Chennai"}})
    field = settings.txt_weather_city
    assert field.selection() == {"city": "Chennai", "location": None}
    field.setText("Random text")
    assert field.selection() is None
    field.setText(" auto-detect ")
    assert field.selection() == {"city": "Auto-detect", "location": None}
    field.clear()
    assert field.selection() == {"city": "", "location": None}
