"""One Gemini Live transcription turn for a user-started recording."""

import base64
import json
import re

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkRequest
from PySide6.QtWebSockets import QWebSocket

from poppy.core.dictation_api import transcript_needs_recovery


_URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
_MODEL = "models/gemini-3.5-transcribe-live"
_CHUNK_BYTES = 3200  # 100 ms of 16 kHz mono PCM16.
_MAX_BUFFER = 128000
_SETTLE_MS = 200


class GeminiLiveDictation(QObject):
    preview = Signal(str)
    finalized = Signal(str, str)
    checkpointed = Signal(str)
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
        self._timeout.timeout.connect(self._timed_out)
        self._settle = QTimer(self, interval=_SETTLE_MS, singleShot=True, timerType=Qt.TimerType.PreciseTimer)
        self._settle.timeout.connect(self._settled)
        self._drain = QTimer(self, interval=20, singleShot=True)
        self._drain.timeout.connect(self._flush)
        self._active = False
        self._ready = False
        self._ended = False
        self._turn_closed = False
        self._checkpointing = False
        self._replaying = False
        self._audio_bytes = 0
        self._sent_bytes = 0
        self._last_voice = 0
        self._final_offset = 0
        self.unconfirmed_ending = False
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

    def feed(self, pcm, *, voiced=True):
        if not self._active or self._ended:
            return
        self._audio_bytes += len(pcm)
        if voiced and pcm:
            self._last_voice = self._audio_bytes
        self._buffer.extend(pcm)
        if len(self._buffer) > (91 * 32000 if self._replaying else _MAX_BUFFER):
            self._fail()
        elif self._ready:
            self._flush()

    def replay(self, pcm):
        """Queue captured audio when a connection or a new turn becomes ready."""
        self._replaying = True
        self.feed(pcm, voiced=bool(pcm))

    @property
    def has_offsets(self):
        return self._final_offset > 0

    @property
    def ready(self):
        return self._ready

    @property
    def has_transcript(self):
        return bool(self._parts or self._last_preview)

    def checkpoint(self):
        self._checkpointing = True
        self.finish()

    def finish(self):
        if self._active and self._ended and self._checkpointing:
            if self._timeout.remainingTime() > 3200:
                self._timeout.start(3200)
            return
        if not self._active or self._ended:
            return
        self._ended = True
        self._timeout.start(10000 if self._checkpointing else 3200)
        if self._ready:
            self._flush()

    def _flush(self):
        if not self._active or not self._ready:
            return
        packets = 0
        while self._buffer and (self._ended or len(self._buffer) >= _CHUNK_BYTES):
            if self._replaying and (packets >= 8 or self._socket.bytesToWrite() > _MAX_BUFFER):
                self._drain.start()
                return
            chunk = self._buffer[:_CHUNK_BYTES]
            data = base64.b64encode(chunk).decode("ascii")
            del self._buffer[:_CHUNK_BYTES]
            if not self._send({"realtimeInput": {"audio": {"mimeType": "audio/pcm;rate=16000", "data": data}}}):
                return
            self._sent_bytes += len(chunk)
            packets += 1
        self._replaying = False
        if self._ended and not self._turn_closed:
            self._turn_closed = True
            if self._send({"realtimeInput": {"activityEnd": {}}}) and self._covers_voice():
                self._complete()

    def _covers_voice(self):
        return self._last_voice > 0 and self._final_offset >= self._last_voice

    def _settled(self):
        if self._active and self._timeout.remainingTime() > 0:
            self._complete()

    def _timed_out(self):
        self._fail(unconfirmed_ending=self._turn_closed)

    def _complete(self):
        result = " ".join(self._parts).strip()
        if not result or (self.has_offsets and not self._covers_voice()):
            self._fail()
            return
        reference = self._last_preview if transcript_needs_recovery(result, self._last_preview) else ""
        if self._checkpointing:
            if reference:
                self._fail(unconfirmed_ending=True)
                return
            self.cancel()
            self.checkpointed.emit(result)
        else:
            self.cancel()
            self.finalized.emit(result, reference)

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
                self._fail(status if status in (400, 401, 403, 404, 429) else 0)
            elif "error" in message or "goAway" in message:
                self._fail()
            return
        if content.get("interrupted"):
            self._fail()
            return
        final = content.get("inputTranscription")
        interim = content.get("interimInputTranscription")
        new_final = False
        if isinstance(final, dict):
            text = final.get("text")
            if isinstance(text, str) and text.strip():
                text = text.replace("\x00", "").strip()
                offset = final.get("endOffset")
                if isinstance(offset, str) and re.fullmatch(r"[0-9]{1,4}(?:\.[0-9]{1,9})?s", offset):
                    position = round(float(offset[:-1]) * 16000) * 2
                    if position < self._final_offset or position > self._sent_bytes:
                        self._fail()
                        return
                    if position > 0 and position == self._final_offset and self._parts:
                        if text != self._parts[-1]:
                            self._fail()
                            return
                        text = ""
                    self._final_offset = position
                if text:
                    self._parts.append(text)
                    new_final = self._turn_closed
        live = interim.get("text", "") if isinstance(interim, dict) else ""
        if isinstance(live, str) and live.strip():
            self._last_preview = " ".join([*self._parts, live]).strip()
            self.preview.emit(self._last_preview)
        if self._turn_closed and self._covers_voice():
            self._complete()
            return
        if self.has_offsets:
            self._settle.stop()
        elif new_final:
            # Input captions arrive independently of turn and generation markers.
            self._settle.start()
        if isinstance(final, dict) and not live:
            confirmed = " ".join(self._parts).strip()
            if self._turn_closed and transcript_needs_recovery(confirmed, self._last_preview):
                self.preview.emit(self._last_preview)
            else:
                self.preview.emit(confirmed)

    def cancel(self):
        if self._active:
            self._active = False
            self._timeout.stop()
            self._settle.stop()
            self._drain.stop()
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

    def _fail(self, status=0, *, unconfirmed_ending=False):
        if self._active:
            self.unconfirmed_ending = unconfirmed_ending
            self.cancel()
            self.failed.emit(status)
