import io
import json
import urllib.parse
import urllib.request

import pytest

from poppy.core import system_features
from poppy.core.lyrics_manager import LyricsManager
from poppy.core.updates import newer_release
from poppy.core.weather_manager import WeatherManager


def test_spotify_secrets_are_removed_on_redirect(monkeypatch):
    manager = LyricsManager()
    responses = iter(({"accessToken": "test-token"}, {"tracks": {"items": [{"id": "track"}]}}, {}))
    requests = []

    def open_request(request, timeout):
        requests.append(request)
        return io.BytesIO(json.dumps(next(responses)).encode())

    monkeypatch.setattr(manager, "_urlopen", open_request)
    try:
        manager._query_spotify("Track", "Artist", "test-cookie")
        assert requests[0].get_header("Cookie") == "sp_dc=test-cookie"
        assert all(request.get_header("Authorization") == "Bearer test-token" for request in requests[1:])
        assert len(requests) == 3
        handler = urllib.request.HTTPRedirectHandler()
        for request in requests:
            redirect = handler.redirect_request(request, None, 302, "", {}, "https://example.invalid/")
            assert redirect.get_header("Cookie") is None
            assert redirect.get_header("Authorization") is None
    finally:
        manager.close()


@pytest.mark.parametrize(
    "location, hosts",
    [
        ("", []),
        ("London", ["geocoding-api.open-meteo.com"]),
        ("Auto-detect", ["get.geojs.io", "ipapi.co"]),
    ],
)
def test_weather_uses_https_and_requires_location_choice(monkeypatch, location, hosts):
    requests = []

    def offline(request, timeout):
        requests.append(urllib.parse.urlsplit(request.full_url))
        raise OSError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", offline)
    weather = WeatherManager({"weather": {"city": location}})
    messages = []
    weather.weather_updated.connect(messages.append)
    weather._worker()
    assert [url.hostname for url in requests] == hosts
    assert all(url.scheme == "https" for url in requests)
    assert messages and "temp" not in messages[-1]


def test_installed_autostart_uses_the_executable_only(monkeypatch):
    commands = []
    registry = system_features.winreg
    monkeypatch.setattr(registry, "OpenKey", lambda *args: object())
    monkeypatch.setattr(registry, "CloseKey", lambda key: None)
    monkeypatch.setattr(registry, "SetValueEx", lambda *args: commands.append(args[-1]))
    monkeypatch.setattr(system_features.sys, "frozen", True, raising=False)
    monkeypatch.setattr(system_features.sys, "executable", r"C:\App Files\Poppy\Poppy.exe")
    assert system_features.set_autostart_state(True)
    assert commands == [r'"C:\App Files\Poppy\Poppy.exe"']


def test_update_check_requires_a_newer_stable_release_with_a_complete_installer(monkeypatch):
    monkeypatch.setattr("poppy.core.updates.APP_VERSION", "0.9.9")
    name = "Poppy-Setup-0.10.0-x64.exe"
    payload = {"tag_name": "v0.10.0", "assets": [{"name": name}, {"name": f"{name}.sha256"}]}
    assert newer_release(payload) == "0.10.0"
    for changes in ({"draft": True}, {"prerelease": True}, {"tag_name": "v0.9.8"},
                    {"tag_name": "v0.10.0-rc.1"}, {"assets": [{"name": name}]}):
        assert newer_release({**payload, **changes}) == ""
