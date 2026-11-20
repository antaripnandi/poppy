"""One Gemini Live transcription turn for a user-started recording."""

import base64
import json

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkRequest
from PySide6.QtWebSockets import QWebSocket

from poppy.core.dictation_api import transcript_has_missing_tail


_URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
_MODEL = "models/gemini-3.5-transcribe-live"
_CHUNK_BYTES = 3200  # 100 ms of 16 kHz mono PCM16.
_MAX_BUFFER = 128000


class GeminiLiveDictation(QObject):
    preview = Signal(str)
    finalized = Signal(str, str)
    failed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._socket = QWebSocket(parent=self)
        self._socket.setMaxAllowedIncomingMessageSize(128 * 1024)
        self._socket.connected.connect(self._setup)
        self._socket.textMessageReceived.connect(self._message)
        self._socket.binaryMessageReceived.connect(lambda data: self._message(bytes(data)))
        self._socket.disconnected.connect(self._disconnected)
        self._socket.errorOccurred.connect(lambda _: self._disconnected())
        self._timeout = QTimer(self, singleShot=True)
        self._timeout.timeout.connect(self._fail)
        self._active = False
        self._ready = False
        self._ended = False
        self._turn_closed = False
        self._buffer = bytearray()
        self._parts = []
        self._last_preview = ""

    def start(self, key, vocabulary, *, language_codes=()):
        self._active = True
        self._vocabulary = vocabulary[:100]
        self._language_codes = language_codes
        request = QNetworkRequest(QUrl(_URL))
        request.setRawHeader(b"x-goog-api-key", key.encode("ascii"))
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        self._timeout.start(3600)
        self._socket.open(request)

    def _send(self, payload):
        if (self._socket.bytesToWrite() > 2 * _MAX_BUFFER
                or self._socket.sendTextMessage(json.dumps(payload, ensure_ascii=False)) <= 0):
            self._fail()
            return False
        return True

    def _setup(self):
        if self._active:
            self._send({"setup": {
                "model": _MODEL,
                "generationConfig": {"responseModalities": ["TEXT"]},
                "realtimeInputConfig": {"automaticActivityDetection": {"disabled": True}},
                "inputAudioTranscription": {"mode": "VERBATIM", "customVocabulary": self._vocabulary,
                                            "languageCodes": self._language_codes},
            }})

    def feed(self, pcm):
        if not self._active or self._ended:
            return
        self._buffer.extend(pcm)
        if len(self._buffer) > _MAX_BUFFER:
            self._fail()
        elif self._ready:
            self._flush()

    def finish(self):
        if not self._active or self._ended:
            return
        self._ended = True
        self._timeout.start(3200)
        if self._ready:
            self._flush()

    def _flush(self):
        while self._buffer and (self._ended or len(self._buffer) >= _CHUNK_BYTES):
            data = base64.b64encode(self._buffer[:_CHUNK_BYTES]).decode("ascii")
            del self._buffer[:_CHUNK_BYTES]
            if not self._send({"realtimeInput": {"audio": {"mimeType": "audio/pcm;rate=16000", "data": data}}}):
                return
        if self._ended and not self._turn_closed:
            self._turn_closed = True
            self._send({"realtimeInput": {"activityEnd": {}}})

    def _message(self, raw):
        if not self._active:
            return
        try:
            message = json.loads(raw)
        except (ValueError, UnicodeError):
            self._fail()
            return
        if not isinstance(message, dict):
            return
        if "setupComplete" in message and not self._ready:
            self._ready = True
            if not self._ended:
                self._timeout.stop()
            if self._send({"realtimeInput": {"activityStart": {}}}):
                self._flush()
            return
        content = message.get("serverContent")
        if not isinstance(content, dict):
            error = message.get("error")
            if isinstance(error, dict):
                name = error.get("status")
                codes = {"UNAUTHENTICATED": 401, "PERMISSION_DENIED": 403, "RESOURCE_EXHAUSTED": 429}
                status = codes.get(name, error.get("code")) if isinstance(name, str) else error.get("code")
                self._fail(status if status in (401, 403, 429) else 0)
            elif "error" in message or "goAway" in message:
                self._fail()
            return
        if content.get("interrupted"):
            self._fail()
            return
        final = content.get("inputTranscription")
        interim = content.get("interimInputTranscription")
        if isinstance(final, dict):
            text = final.get("text")
            if isinstance(text, str) and text.strip():
                self._parts.append(text.replace("\x00", "").strip())
        live = interim.get("text", "") if isinstance(interim, dict) else ""
        if isinstance(live, str) and live.strip():
            self._last_preview = " ".join([*self._parts, live]).strip()
            self.preview.emit(self._last_preview)
        if self._turn_closed and (content.get("generationComplete") or content.get("turnComplete")):
            result = " ".join(self._parts).strip()
            if result:
                reference = self._last_preview if transcript_has_missing_tail(result, self._last_preview) else ""
                self.cancel()
                self.finalized.emit(result, reference)
            elif content.get("turnComplete"):
                self._fail()
            return
        if isinstance(final, dict) and not live:
            preview = self._last_preview if self._turn_closed else ""
            self.preview.emit(preview or " ".join(self._parts).strip())

    def cancel(self):
        if self._active:
            self._active = False
            self._timeout.stop()
            self._buffer.clear()
            self._parts.clear()
            self._last_preview = ""
            self._socket.abort()

    def _disconnected(self):
        if not self._active:
            return
        reason = self._socket.closeReason().casefold()
        if "api key not valid" in reason or "api_key_invalid" in reason:
            self._fail(401)
        elif "quota" in reason or "resource_exhausted" in reason:
            self._fail(429)
        else:
            self._fail()

    def _fail(self, status=0):
        if self._active:
            self.cancel()
            self.failed.emit(status)
