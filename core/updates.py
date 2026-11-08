"""Check published Poppy releases and leave installation to the user."""

import json
import re

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from poppy.core import APP_VERSION


RELEASES_URL = "https://github.com/antaripnandi/poppy/releases"
_LATEST_URL = "https://api.github.com/repos/antaripnandi/poppy/releases/latest"
_MAX_REPLY = 512 * 1024
_CHECK_INTERVAL = 24 * 60 * 60 * 1000
_TAG = re.compile(r"v(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})")


def newer_release(payload: dict) -> str:
    tag = payload.get("tag_name")
    match = _TAG.fullmatch(tag) if isinstance(tag, str) else None
    if not match or payload.get("draft") or payload.get("prerelease"):
        return ""
    if tuple(map(int, match.groups())) <= tuple(map(int, APP_VERSION.split("."))):
        return ""
    version = tag[1:]
    assets = payload.get("assets")
    if not isinstance(assets, list):
        return ""
    names = {asset["name"] for asset in assets if isinstance(asset, dict) and isinstance(asset.get("name"), str)}
    installer = f"Poppy-Setup-{version}-x64.exe"
    return version if {installer, f"{installer}.sha256"} <= names else ""


class UpdateChecker(QObject):
    checked = Signal(str, str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._network = QNetworkAccessManager(self)
        self._network.finished.connect(self._finish)
        self._reply = None
        self._manual = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._check_periodically)

    def configure(self, automatic: bool):
        if not automatic:
            self._timer.stop()
            if self._reply is not None and not self._manual:
                reply, self._reply = self._reply, None
                reply.abort()
        elif not self._timer.isActive():
            self._timer.start(15_000)

    def _check_periodically(self):
        if self._timer.interval() != _CHECK_INTERVAL:
            self._timer.start(_CHECK_INTERVAL)
        self.check()

    def check(self, *, manual=False):
        self._manual |= manual
        if self._reply is not None:
            return
        request = QNetworkRequest(QUrl(_LATEST_URL))
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(b"User-Agent", f"Poppy/{APP_VERSION}".encode("ascii"))
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute, QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        request.setTransferTimeout(8000)
        reply = self._network.get(request)
        self._reply = reply
        reply.setReadBufferSize(_MAX_REPLY + 1)
        reply.readyRead.connect(lambda: self._limit_reply(reply))

    @staticmethod
    def _limit_reply(reply):
        if reply.bytesAvailable() > _MAX_REPLY:
            reply.abort()

    def _finish(self, reply):
        if reply is not self._reply:
            reply.deleteLater()
            return
        manual, self._manual = self._manual, False
        self._reply = None
        version = ""
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if status == 404:
            message = "A stable Poppy release has not been published yet."
        elif status == 200 and reply.error() == QNetworkReply.NetworkError.NoError:
            try:
                payload = json.loads(bytes(reply.read(_MAX_REPLY)))
                if not isinstance(payload, dict):
                    raise ValueError("Invalid release metadata")
                version = newer_release(payload)
                message = "You're on the latest available version."
            except (ValueError, UnicodeError):
                message = "Poppy could not read the release information."
        else:
            message = "Poppy could not check for updates. Try again later."
        reply.deleteLater()
        self.checked.emit(version, message, manual)
