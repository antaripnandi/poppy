"""Spotify account authorization and playback volume, using OAuth PKCE."""

import base64
import hashlib
import json
import math
import re
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlsplit

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QHostAddress, QNetworkAccessManager, QNetworkRequest, QTcpServer, QTcpSocket

from poppy.core.storage import data_path, write_json


REDIRECT_URI = "http://127.0.0.1:43821/callback"
SCOPES = {"user-read-playback-state", "user-modify-playback-state"}
_API = "https://api.spotify.com/v1/me/player"
_TOKEN = "https://accounts.spotify.com/api/token"
_MAX_REPLY = 256 * 1024


class SpotifyPlayback(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.client_id = ""
        self._tokens = {}
        self.status = "Connect Spotify in Settings to control its playback volume."
        self.device = {}
        self._reply = None
        self._pending = None
        self._blocked_until = 0
        self._state = ""
        self._verifier = ""
        self._auth_exchange = False
        self._closed = False
        self._network = QNetworkAccessManager(self)
        self._server = QTcpServer(self)
        self._server.newConnection.connect(self._accept_connection)
        self._auth_timer = QTimer(self, interval=180000, singleShot=True)
        self._auth_timer.timeout.connect(self.cancel_connect)
        self._credentials = data_path("spotify_playback.json")
        try:
            saved = json.loads(self._credentials.read_text(encoding="utf-8"))
            self.client_id = saved.get("client_id", "")
            if saved.get("credentials"):
                import win32crypt
                _, decoded = win32crypt.CryptUnprotectData(base64.b64decode(saved["credentials"], validate=True),
                                                          None, None, None, 1)
                self._tokens = json.loads(decoded.decode("utf-8"))
                if (not isinstance(self._tokens, dict) or not isinstance(self._tokens.get("refresh_token"), str)
                        or not isinstance(self._tokens.get("access_token"), str)
                        or type(self._tokens.get("expires_at")) not in (float, int)
                        or not math.isfinite(self._tokens["expires_at"])):
                    raise ValueError()
        except FileNotFoundError:
            pass
        except Exception:
            self._tokens = {}
            self.status = "Reconnect Spotify to restore playback-volume access."
        if self.connected:
            self.status = "Spotify connected."

    @property
    def connected(self):
        return bool(self._tokens.get("refresh_token"))

    @property
    def busy(self):
        return self._reply is not None

    @property
    def connecting(self):
        return self._auth_timer.isActive() or self._auth_exchange

    def _save(self, client_id, tokens):
        credentials = ""
        if tokens:
            try:
                import win32crypt
                protected = win32crypt.CryptProtectData(json.dumps(tokens).encode("utf-8"),
                                                         "Poppy Spotify playback", None, None, None, 1)
            except Exception:
                raise OSError("Could not protect Spotify credentials.") from None
            credentials = base64.b64encode(protected).decode("ascii")
        write_json(self._credentials, {"client_id": client_id, "credentials": credentials})

    def connect_account(self, client_id):
        if self._closed:
            return
        client_id = client_id.strip()
        if not re.fullmatch(r"[a-fA-F0-9]{32}", client_id):
            self._report("Enter the Client ID from your Spotify Developer app.")
            return
        self.cancel_connect(report=False)
        if not self._server.listen(QHostAddress(QHostAddress.SpecialAddress.LocalHost), 43821):
            self._report("Port 43821 is in use. Close the other connection attempt and try again.")
            return
        self._auth_client_id = client_id
        self._state = secrets.token_urlsafe(32)
        self._verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self._verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
        query = urlencode({"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT_URI,
                           "scope": " ".join(sorted(SCOPES)), "state": self._state,
                           "code_challenge": challenge, "code_challenge_method": "S256"})
        self._auth_timer.start()
        self._report("Finish connecting in your browser.")
        if not QDesktopServices.openUrl(QUrl("https://accounts.spotify.com/authorize?" + query)):
            self.cancel_connect(report=False)
            self._report("Could not open the browser. Try connecting again.")

    def cancel_connect(self, *, report=True):
        if self._auth_exchange:
            self._cancel_request()
        self._auth_exchange = False
        self._server.close()
        self._auth_timer.stop()
        self._state = self._verifier = ""
        for socket in self._server.findChildren(QTcpSocket):
            socket.abort()
        if report:
            self._report("Spotify connection cancelled. You can connect again.")

    def _accept_connection(self):
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.setReadBufferSize(8193)
            socket.readyRead.connect(lambda s=socket: self._read_callback(s))
            socket.disconnected.connect(socket.deleteLater)
            QTimer.singleShot(5000, socket, socket.disconnectFromHost)

    def _read_callback(self, socket):
        if socket.bytesAvailable() > 8192:
            socket.abort()
            return
        if not socket.canReadLine():
            return
        try:
            method, target, version = bytes(socket.readLine(8193)).decode("ascii").strip().split(" ")
            url = urlsplit(target)
            query = parse_qs(url.query, max_num_fields=8)
            valid = (method == "GET" and version in ("HTTP/1.1", "HTTP/1.0") and not url.netloc
                     and url.path == "/callback" and self.connecting
                     and query.get("state") == [self._state])
        except (ValueError, UnicodeError):
            valid = False
        if not valid:
            socket.write(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
            socket.disconnectFromHost()
            return
        code = query.get("code", [])
        body = b"Return to Poppy to see the Spotify connection result."
        socket.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nCache-Control: no-store\r\n"
                     b"Connection: close\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
        socket.disconnectFromHost()
        client_id, verifier = self._auth_client_id, self._verifier
        self._server.close()
        self._auth_timer.stop()
        self._state = self._verifier = ""
        self._cancel_request()
        if len(code) != 1 or "error" in query:
            self._report("Spotify authorization was declined. You can connect again.")
            return
        self._auth_exchange = True
        self._request("POST", _TOKEN, {"grant_type": "authorization_code", "client_id": client_id,
                                      "redirect_uri": REDIRECT_URI, "code": code[0], "code_verifier": verifier},
                      lambda status, data, reply: self._received_tokens(status, data, client_id))

    def disconnect_account(self):
        try:
            self._save(self.client_id, {})
        except OSError:
            self._report("Could not remove the saved connection. Try again.")
            return
        self.cancel_connect(report=False)
        self._cancel_request()
        self._tokens = {}
        self.device = {}
        self._report("Spotify disconnected.")

    def _cancel_request(self):
        self._pending = None
        if self._reply is not None:
            reply, self._reply = self._reply, None
            reply.abort()
            reply.deleteLater()

    def _request(self, method, url, form, callback, *, bearer=False):
        request = QNetworkRequest(QUrl(url))
        request.setTransferTimeout(8000)
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        if bearer:
            request.setRawHeader(b"Authorization", ("Bearer " + self._tokens["access_token"]).encode("ascii"))
        body = b""
        if form is not None:
            request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/x-www-form-urlencoded")
            body = urlencode(form).encode("ascii")
        reply = self._network.sendCustomRequest(request, method.encode("ascii"), body)
        self._reply = reply
        reply.setReadBufferSize(_MAX_REPLY + 1)
        reply.readyRead.connect(lambda: reply.abort() if reply.bytesAvailable() > _MAX_REPLY else None)
        reply.finished.connect(lambda: self._finish(reply, callback))

    def _finish(self, reply, callback):
        reply.deleteLater()
        if reply is not self._reply:
            return
        self._reply = None
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0
        try:
            raw = bytes(reply.read(_MAX_REPLY + 1))
            data = json.loads(raw) if raw else {}
            if len(raw) > _MAX_REPLY or not isinstance(data, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            status, data = 0, {}
        callback(status, data, reply)

    def _received_tokens(self, status, data, client_id):
        self._auth_exchange = False
        if (status != 200 or not isinstance(data.get("access_token"), str) or not data["access_token"]
                or not data["access_token"].isascii() or not data["access_token"].isprintable()):
            self._pending = None
            self.device = {}
            if status in (400, 401):
                try:
                    self._save(self.client_id, {})
                    self._tokens = {}
                except OSError:
                    pass
            self._report("Could not authorize Spotify. Check the Client ID and registered redirect, then connect again.")
            return
        if not isinstance(data.get("scope", ""), str) or ("scope" in data and not SCOPES.issubset(data["scope"].split())):
            self._pending = None
            self._report("Spotify did not grant playback access. Connect again and allow both playback permissions.")
            return
        tokens = dict(data)
        tokens["refresh_token"] = data.get("refresh_token") or self._tokens.get("refresh_token")
        try:
            lifetime = float(data["expires_in"])
            if not math.isfinite(lifetime) or not 0 < lifetime <= 86400:
                raise ValueError()
            tokens["expires_at"] = time.time() + max(0, lifetime - 30)
            if not isinstance(tokens["refresh_token"], str) or not tokens["refresh_token"]:
                raise ValueError()
            self._save(client_id, tokens)
        except (KeyError, OSError, ValueError, TypeError):
            self._pending = None
            self._report("Could not save the Spotify connection with Windows protection. Try connecting again.")
            return
        self.client_id, self._tokens = client_id, tokens
        pending, self._pending = self._pending, None
        if pending:
            self._api(*pending)
        else:
            self._report("Spotify connected.")

    def refresh(self):
        if not self._closed and self.connected and self._reply is None and not self.connecting and time.time() >= self._blocked_until:
            self._api("GET", _API, self._received_playback)

    def _api(self, method, url, callback, retry=True):
        if self._closed or not self.connected or self._reply is not None or self.connecting or time.time() < self._blocked_until:
            return
        if self._tokens.get("expires_at", 0) <= time.time() or not self._tokens.get("access_token"):
            self._pending = (method, url, callback, retry)
            self._request("POST", _TOKEN, {"grant_type": "refresh_token", "client_id": self.client_id,
                                          "refresh_token": self._tokens["refresh_token"]},
                          lambda status, data, reply: self._received_tokens(status, data, self.client_id))
            return

        def complete(status, data, reply):
            if status == 401 and retry:
                self._tokens["expires_at"] = 0
                self._api(method, url, callback, False)
            elif status == 429:
                try:
                    delay = min(86400, max(1, int(bytes(reply.rawHeader("Retry-After")))))
                except ValueError:
                    delay = 30
                self._blocked_until = time.time() + delay
                self.device = {}
                self._report(f"Spotify asked Poppy to wait {delay} seconds. Try again shortly.")
            else:
                callback(status, data)

        self._request(method, url, None, complete, bearer=True)

    def _received_playback(self, status, data):
        self.device = data.get("device", {}) if status == 200 else {}
        if not isinstance(self.device, dict):
            self.device = {}
        if status == 403:
            text = "Spotify playback control requires Premium and access to this Developer app."
        elif status in (200, 204) and not self.device:
            text = "Start playback in Spotify, then reopen the mixer."
        elif status == 200:
            text = self.device.get("name", "Spotify playback")
        else:
            text = "Could not read Spotify playback. Try again."
        self._report(text)

    def set_volume(self, device_id, level):
        if (self._closed or not self.connected or self._reply is not None or self.connecting
                or time.time() < self._blocked_until
                or self.device.get("id") != device_id or not self.can_set_volume):
            return False
        if type(level) is not int or not 0 <= level <= 100:
            return False
        url = _API + "/volume?" + urlencode({"volume_percent": level, "device_id": device_id})

        def written(status, data):
            if status == 204:
                self.device["volume_percent"] = level
                self.changed.emit()
            else:
                self.device = {}
                self._report("Spotify could not change this device's volume. Refresh playback and try again.")

        self._api("PUT", url, written)
        return True

    @property
    def can_set_volume(self):
        level = self.device.get("volume_percent")
        return bool(self.device.get("id") and not self.device.get("is_restricted")
                    and self.device.get("supports_volume", True) and type(level) is int and 0 <= level <= 100)

    def _report(self, text):
        self.status = text
        self.changed.emit()

    def close(self):
        self._closed = True
        self.cancel_connect(report=False)
        self._cancel_request()
