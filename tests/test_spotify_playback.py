import hashlib
import base64
import json
import socket
import time
from urllib.parse import parse_qs, urlsplit

from PySide6.QtCore import QObject, QEventLoop, QTimer, Signal

from poppy.core.spotify_playback import REDIRECT_URI, SCOPES, SpotifyPlayback
from poppy.ui.settings_window import SettingsWindow
from poppy.ui.spotify_controls import SpotifyVolumeControls


class Reply(QObject):
    readyRead = Signal()
    finished = Signal()

    def __init__(self, request, method, body):
        super().__init__()
        self.request, self.method, self.body = request, bytes(method), bytes(body)
        self.status, self.data, self.retry_after = 200, b"", b"1"
        self.aborted = False

    def setReadBufferSize(self, size):
        pass

    def attribute(self, attribute):
        return self.status

    def bytesAvailable(self):
        return len(self.data)

    def rawHeader(self, name):
        return self.retry_after

    def read(self, limit):
        return self.data[:limit]

    def abort(self):
        self.aborted = True

    def complete(self, status, data=None):
        self.status = status
        self.data = json.dumps(data).encode() if data is not None else b""
        self.finished.emit()


def network_for(manager, monkeypatch):
    requests = []

    def send(request, method, body):
        reply = Reply(request, method, body)
        requests.append(reply)
        return reply

    monkeypatch.setattr(manager._network, "sendCustomRequest", send)
    return requests


def wait_until(predicate):
    if predicate():
        return
    loop = QEventLoop()
    timer = QTimer(interval=10)
    timer.timeout.connect(lambda: loop.quit() if predicate() else None)
    timer.start()
    QTimer.singleShot(1500, loop, loop.quit)
    loop.exec()
    assert predicate()


def playback_state(device_id="desktop", level=35):
    return {"device": {"id": device_id, "name": "Spotify desktop", "volume_percent": level,
                       "supports_volume": True, "is_restricted": False}}


def authorized(manager):
    manager.client_id = "a" * 32
    manager._tokens = {"access_token": "test-access", "refresh_token": "test-refresh",
                       "expires_at": time.time() + 300}
    manager.device = playback_state()["device"]


def test_oauth_state_pkce_and_encrypted_persistence(audit_app, monkeypatch):
    manager = SpotifyPlayback()
    urls = []
    requests = network_for(manager, monkeypatch)
    monkeypatch.setattr("poppy.core.spotify_playback.QDesktopServices.openUrl", lambda url: urls.append(url) or True)
    try:
        manager.connect_account("a" * 32)
        assert manager._server.serverAddress().toString() == "127.0.0.1"
        query = parse_qs(urlsplit(urls[0].toString()).query)
        assert query["redirect_uri"] == [REDIRECT_URI]
        assert set(query["scope"][0].split()) == SCOPES
        challenge = base64.urlsafe_b64encode(hashlib.sha256(manager._verifier.encode()).digest()).rstrip(b"=").decode()
        assert query["code_challenge"] == [challenge] and query["code_challenge_method"] == ["S256"]

        with socket.create_connection(("127.0.0.1", 43821), timeout=1) as client:
            client.sendall(b"GET /callback?state=wrong&code=bad HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            audit_app.processEvents()
            audit_app.processEvents()
            assert manager.connecting and not requests

        state = query["state"][0]
        client = socket.create_connection(("127.0.0.1", 43821), timeout=1)
        client.sendall(f"GET /callback?state={state}&code=sample-code HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".encode())
        wait_until(lambda: bool(requests))
        client.close()
        reply = requests[-1]
        form = parse_qs(reply.body.decode())
        assert form["code"] == ["sample-code"]
        assert form["code_verifier"][0] and "client_secret" not in form
        assert not reply.request.rawHeader("Authorization")
        reply.complete(200, {"access_token": "test-access", "refresh_token": "test-refresh", "expires_in": 3600,
                             "scope": " ".join(SCOPES)})
        assert manager.connected
        stored = manager._credentials.read_text()
        assert "test-access" not in stored and "test-refresh" not in stored
        reopened = SpotifyPlayback()
        assert reopened.connected and reopened.client_id == "a" * 32
        reopened.disconnect_account()
        assert not SpotifyPlayback().connected
    finally:
        manager.close()


def test_mixer_reads_without_writes_and_gestures_target_device(audit_app, monkeypatch):
    manager = SpotifyPlayback()
    authorized(manager)
    requests = network_for(manager, monkeypatch)
    control = SpotifyVolumeControls(manager, lambda: None)
    control.show()
    audit_app.processEvents()
    assert [request.method for request in requests] == [b"GET"]
    requests[-1].complete(200, playback_state())
    assert control.slider.value() == 35
    requests.clear()
    control.slider.setValue(70)
    assert not requests  # A polling or programmatic update must never become an audio write.

    control.slider.setSliderPosition(52)
    control._volume_gesture(7)
    control._write_volume()
    put, = requests
    assert put.method == b"PUT"
    assert parse_qs(urlsplit(put.request.url().toString()).query) == {"volume_percent": ["52"], "device_id": ["desktop"]}
    assert bytes(put.request.rawHeader("Authorization")) == b"Bearer test-access"
    put.complete(204)
    assert manager.device["volume_percent"] == 52 and control.readout.text() == "52%"

    control.slider.setSliderPosition(63)
    control._volume_gesture(7)
    manager._received_playback(200, playback_state("phone", 20))
    count = len(requests)
    control._write_volume()
    assert len(requests) == count and control.slider.value() == 20
    control.hide()
    assert not control._timer.isActive() and control._pending is None
    manager.close()


def test_refresh_rotation_401_once_and_rate_limit(audit_app, monkeypatch):
    manager = SpotifyPlayback()
    authorized(manager)
    requests = network_for(manager, monkeypatch)
    manager.refresh()
    requests[-1].complete(401)
    refresh = requests[-1]
    assert refresh.method == b"POST"
    assert parse_qs(refresh.body.decode())["grant_type"] == ["refresh_token"]
    refresh.complete(200, {"access_token": "new-access", "expires_in": 3600, "scope": " ".join(SCOPES)})
    assert manager._tokens["refresh_token"] == "test-refresh"
    requests[-1].complete(200, playback_state())
    assert manager.can_set_volume
    assert manager.set_volume("other-device", 100) is False
    assert manager.set_volume("desktop", 40)
    requests[-1].complete(429)
    assert not manager.can_set_volume
    count = len(requests)
    manager.refresh()
    manager.set_volume("desktop", 100)
    assert len(requests) == count
    manager.close()


def test_account_controls_use_shared_connection_and_reject_unsupported_device(audit_app, monkeypatch):
    manager = SpotifyPlayback()
    settings = SettingsWindow(spotify=manager)
    assert settings.spotify_account.playback is manager
    authorized(manager)
    requests = network_for(manager, monkeypatch)
    manager._received_playback(200, {"device": {**manager.device, "supports_volume": False}})
    assert manager.set_volume("desktop", 50) is False and not requests
    manager._received_playback(204, {})
    assert not manager.can_set_volume
    manager.close()
