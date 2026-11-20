import base64
import json
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtNetwork import QNetworkRequest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from poppy.core import dictation_api
from poppy.core.dictation_live import GeminiLiveDictation
from poppy.ui.dictation import DictationController, native
from poppy.core.window import DynamicNotchWindow
from poppy.ui.settings_window import SettingsWindow


class Reply(QObject):
    readyRead = Signal()
    finished = Signal()

    def __init__(self, request, body):
        super().__init__()
        self.request = request
        self.body = body
        self.host = urlsplit(request.url().toString()).hostname
        self.status = 0
        self.response = b""
        self.aborted = False

    def setReadBufferSize(self, size):
        pass

    def attribute(self, attribute):
        return self.status

    def rawHeader(self, name):
        return b"5"

    def isOpen(self):
        return True

    def bytesAvailable(self):
        return len(self.response)

    def readAll(self):
        return self.response

    def complete(self, status, response=None):
        self.status = status
        self.response = json.dumps(response or {}).encode()
        self.finished.emit()

    def abort(self):
        self.aborted = True
        self.finished.emit()


def mock_network(api, monkeypatch):
    replies = []

    def post(request, body):
        reply = Reply(request, body)
        replies.append(reply)
        return reply

    monkeypatch.setattr(api._network, "post", post)
    return replies


def gemini_text(text):
    return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": text}]}}]}


def start(api, cleanup=True):
    api.start(b"RIFFsample-data", cleanup=cleanup, vocabulary=["Poppy"],
              snippets={"my link": "https://example.test"}, style="technical")


def test_rate_limited_provider_cools_down_and_cleanup_only_gets_text(monkeypatch):
    api = dictation_api.DictationApi()
    api.set_keys({"groq": ["first", "backup"], "gemini": ["google"], "openrouter": ["router"]})
    moment = [100.0]
    monkeypatch.setattr(dictation_api.time, "monotonic", lambda: moment[0])
    replies = mock_network(api, monkeypatch)
    results = []
    api.finished.connect(lambda *result: results.append(result))
    start(api)
    assert replies[-1].host == "api.groq.com" and b"whisper-large-v3-turbo" in replies[-1].body
    replies[-1].complete(429)
    assert replies[-1].host == "generativelanguage.googleapis.com" and len(replies) == 2
    assert "inlineData" in json.loads(replies[-1].body)["contents"][0]["parts"][0]
    replies[-1].complete(200, gemini_text("Um, please see my link."))
    assert json.loads(replies[-1].body)["contents"][0]["parts"] == [{"text": "Um, please see my link."}]
    assert b"example.test" not in replies[-1].body
    replies[-1].complete(429)
    assert replies[-1].host == "openrouter.ai"
    assert json.loads(replies[-1].body)["model"] == "openrouter/free"
    replies[-1].complete(200, {"choices": [{"finish_reason": "stop", "message": {"content": "See my link."}}]})
    assert results == [("See https://example.test.", "")]
    moment[0] += 6
    start(api)
    assert replies[-1].host == "api.groq.com"
    api.cancel()


def test_failed_key_uses_backup_and_failed_cleanup_keeps_transcript(monkeypatch):
    api = dictation_api.DictationApi()
    api.set_keys({"gemini": ["invalid", "valid"]})
    replies = mock_network(api, monkeypatch)
    results = []
    api.finished.connect(lambda *result: results.append(result))
    start(api)
    replies[-1].complete(400, {"error": {"details": [{"reason": "API_KEY_INVALID"}]}})
    assert bytes(replies[-1].request.rawHeader("x-goog-api-key")) == b"valid"
    assert "gemini-3.8-flash" in replies[-1].request.url().toString()
    replies[-1].complete(200, gemini_text("Spoken text."))
    replies[-1].complete(503)
    assert "gemini-3.8-flash" in replies[-1].request.url().toString()
    replies[-1].complete(503)
    assert results == [("Spoken text.", "Cleanup unavailable")]
    start(api)
    api.cancel()
    assert replies[-1].aborted and len(results) == 1


def test_settings_save_keys_encrypted_and_reopen_with_voice_options(audit_app, tmp_path):
    window = SettingsWindow()
    window.select_page("Voice typing")
    assert window.stack.currentWidget().widget() is window.voice_typing
    voice = window.voice_typing
    voice.keys["groq"].setText("demo-groq-key, demo-groq-key")
    voice.keys["gemini"].setText("demo-gemini-key")
    voice.enabled.setChecked(True)
    voice.snippets.setPlainText("my link = https://example.test/?a=b")
    assert window._save_settings()
    saved = (tmp_path / "data" / "config.json").read_text()
    assert "demo-groq-key" not in saved and "demo-gemini-key" not in saved
    config = json.loads(saved)["dictation"]
    assert dictation_api.read_keys(config) == {"groq": ["demo-groq-key"], "gemini": ["demo-gemini-key"]}
    assert config["enabled"] and config["snippets"] == {"my link": "https://example.test/?a=b"}


def test_recording_lifecycle_and_cancel_without_audio_upload(audit_app, monkeypatch):
    class Mic:
        def read(self):
            return b"\x00\x10" * 3200

        def close(self, *, keep_audio=False):
            return b""

    parent = QWidget()
    manager = DictationController(parent)
    monkeypatch.setattr(manager, "_start_live", lambda: None)
    copies = []
    monkeypatch.setattr(native, "Microphone", Mic)
    monkeypatch.setattr(native, "focused_target", lambda: None)
    monkeypatch.setattr(native, "modifiers_down", lambda: False)
    monkeypatch.setattr(native, "copy_text", lambda hwnd, text, *, history: copies.append((text, history)))
    manager.configure({"enabled": True, "protected_keys": dictation_api.protect_keys({"gemini": ["test"]})})
    assert manager._indicator is None
    manager.toggle()
    assert manager._indicator.isVisible() and manager._indicator.listening
    manager._read_mic()
    manager.cancel()
    assert manager._mic is None and manager._api is None and not manager._indicator.isVisible()
    manager.toggle()
    manager._read_mic()
    api = dictation_api.DictationApi(manager)
    api.set_keys({"gemini": ["test"]})
    api.phase_changed.connect(manager._processing)
    api.finished.connect(manager._finished)
    manager._api = api
    replies = mock_network(api, monkeypatch)
    manager.toggle()
    assert manager._indicator.title.text() == "Transcribing"
    replies[-1].complete(200, gemini_text("Hello, Poppy."))
    replies[-1].complete(200, gemini_text("Hello, Poppy."))
    assert manager.last_text == "Hello, Poppy."
    assert manager._indicator.title.text() == "Copied to clipboard"
    assert copies == [("Hello, Poppy.", True)]
    manager.close()


def test_check_keys_batches_requests_and_reports_each_slot(monkeypatch):
    page = SettingsWindow().voice_typing
    replies = []

    def get(request):
        reply = Reply(request, None)
        reply.readAll = lambda: b""
        replies.append(reply)
        return reply

    monkeypatch.setattr(page._checker._network, "get", get)
    page.keys["gemini"].setText("one, two, three, four, five")
    page.keys["openrouter"].setText("router")
    page.check_button.click()
    assert len(replies) == 4
    assert not page.check_button.isEnabled()
    assert all(reply.body is None and reply.request.attribute(QNetworkRequest.Attribute.RedirectPolicyAttribute)
               == QNetworkRequest.RedirectPolicy.ManualRedirectPolicy for reply in replies)
    replies[1].complete(401)
    assert len(replies) == 5 and replies[4].host == "generativelanguage.googleapis.com"
    replies[0].complete(200)
    assert len(replies) == 6 and replies[5].host == "openrouter.ai"
    for index in (2, 3, 4, 5):
        replies[index].complete(200)
    assert page.check_button.isEnabled()
    label = page._key_rows["gemini"][0]
    assert label.text().startswith("4/5 accepted")
    assert "Key 2 · Rejected" in label.toolTip()
    assert page.status.text().startswith("5 of 6 keys accepted")
    page.check_button.click()
    page.keys["openrouter"].setText("replacement")
    assert all(reply.aborted for reply in replies[6:])


def test_drawer_mic_opens_idle_pill_then_previews_speech_without_copying(audit_app, monkeypatch):
    class Mic:
        def read(self):
            return b"\x00\x0a" * 1600

        def close(self, *, keep_audio=False):
            return b""

    keys = dictation_api.protect_keys({"gemini": ["fixture"]})
    window = DynamicNotchWindow({"dictation": {"enabled": True, "protected_keys": keys, "cleanup": False}})
    monkeypatch.setattr(native, "focused_target", lambda: None)
    monkeypatch.setattr(native, "Microphone", Mic)
    monkeypatch.setattr(native, "modifiers_down", lambda: False)
    copies = []
    monkeypatch.setattr(native, "copy_text", lambda hwnd, text, **kwargs: copies.append(text))
    controller = window.dictation
    monkeypatch.setattr(controller, "_start_live", lambda: None)
    window.btn_hdr_dictation.click()
    assert controller._indicator.isVisible() and window.btn_hdr_dictation.isChecked()
    assert controller._mic is None
    controller._indicator.action.click()
    assert controller._indicator.listening
    replies = mock_network(controller._pipeline(), monkeypatch)
    for _ in range(36):
        controller._read_mic()
    assert any(controller._indicator.levels)
    assert len(replies) == 1
    replies[-1].complete(200, gemini_text("The first few words."))
    assert "first few words" in controller._indicator.preview.text()
    assert controller._indicator.listening and not copies
    controller._indicator.action.click()
    assert len(replies) == 2
    replies[-1].complete(200, gemini_text("The full recording."))
    assert copies == ["The full recording."]
    controller.cancel()
    assert not window.btn_hdr_dictation.isChecked()


def test_dragged_pill_keeps_its_anchor_through_resize_and_reopen(audit_app, monkeypatch):
    monkeypatch.setattr("poppy.ui.dictation.system_animations_enabled", lambda: False)
    parent = QWidget()
    manager = DictationController(parent)
    manager._status("Ready to dictate", "Click to start")
    pill = manager._indicator
    old = pill.pos()
    clicks = []
    pill.clicked.connect(lambda: clicks.append(True))
    start = QPoint(110, 23)
    QTest.mousePress(pill, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(pill, start + QPoint(52, -103))
    QTest.mouseRelease(pill, Qt.MouseButton.LeftButton, pos=start)
    assert pill.pos() != old and not clicks
    anchor = (pill.x(), pill.y() + pill.height())
    manager._status("Listening", "Recording")
    assert (pill.x(), pill.y() + pill.height()) == anchor
    manager._status("Copied to clipboard", "Ctrl+V to paste")
    assert (pill.x(), pill.y() + pill.height()) == anchor
    manager.close()
    reopened = DictationController(parent)
    reopened._status("Ready to dictate", "Click to start")
    pill = reopened._indicator
    assert (pill.x(), pill.y() + pill.height()) == anchor
    reopened._reset_position()
    assert pill.pos() == old
    bounds = pill.screen().availableGeometry()
    near_top = QPoint(bounds.left() + 10, bounds.top() + 2)
    pill.place(near_top, pill.screen())
    reopened._status("Listening", "Recording")
    assert pill.y() == bounds.top()
    reopened._status("Text sent", "Complete")
    assert pill.pos() == near_top
    reopened.close()


def test_live_protocol_flushes_tail_and_only_finalizes_after_stop(monkeypatch):
    class Socket(QObject):
        connected = Signal()
        textMessageReceived = Signal(str)
        binaryMessageReceived = Signal(bytes)
        disconnected = Signal()
        errorOccurred = Signal()

        def setMaxAllowedIncomingMessageSize(self, size):
            pass

        def abort(self):
            self.disconnected.emit()

    monkeypatch.setattr("poppy.core.dictation_live.QWebSocket", Socket)
    live = GeminiLiveDictation()
    packets, preview, completed = [], [], []
    monkeypatch.setattr(live, "_send", lambda packet: packets.append(packet) or True)
    live.preview.connect(preview.append)
    live.finalized.connect(completed.append)
    live._active = True
    live.feed(b"\x01\x02" * 1800)
    assert not packets
    live._message('{"setupComplete":{}}')
    assert packets[0] == {"realtimeInput": {"activityStart": {}}}
    assert len(packets) == 2 and len(live._buffer) == 400
    live._message('{"serverContent":{"inputTranscription":{"text":"First phrase."}}}')
    live._message('{"serverContent":{"interimInputTranscription":{"text":"Sec"}}}')
    assert preview[-1] == "First phrase. Sec" and not completed
    live.finish()
    assert "audio" in packets[-2]["realtimeInput"]
    assert packets[-1] == {"realtimeInput": {"activityEnd": {}}}
    live._message('{"serverContent":{"inputTranscription":{"text":"Second phrase."}}}')
    live._message('{"serverContent":{"inputTranscription":{"text":"Late reply."}}}')
    assert completed == ["First phrase. Second phrase."]


def test_stream_success_reuses_text_and_failure_uses_full_capture(audit_app, monkeypatch):
    class Mic:
        def read(self):
            return b"\x00\x10" * 3200

        def close(self, *, keep_audio=False):
            return b"\x00\x10" * 800 if keep_audio else b""

    class Live(QObject):
        preview = Signal(str)
        finalized = Signal(str)
        failed = Signal()

        def start(self, key, vocabulary):
            self.audio = bytearray()

        def feed(self, pcm):
            self.audio.extend(pcm)

        def finish(self):
            pass

        def cancel(self):
            pass

    monkeypatch.setattr("poppy.ui.dictation.GeminiLiveDictation", Live)
    monkeypatch.setattr(native, "Microphone", Mic)
    monkeypatch.setattr(native, "focused_target", lambda: None)
    monkeypatch.setattr(native, "modifiers_down", lambda: False)
    copies = []
    monkeypatch.setattr(native, "copy_text", lambda hwnd, text, **kwargs: copies.append(text))
    parent = QWidget()
    manager = DictationController(parent)
    manager.configure({"enabled": True, "protected_keys": dictation_api.protect_keys({"gemini": ["test"]})})
    replies = mock_network(manager._pipeline(), monkeypatch)
    manager.toggle()
    live = manager._live
    manager._read_mic()
    live.preview.emit("Preview fragment")
    assert "Preview fragment" in manager._indicator.preview.text() and not copies
    manager.toggle()
    assert len(live.audio) == 8000 and not replies
    live.finalized.emit("Final recognized words.")
    assert len(replies) == 1 and b"Final recognized words." in replies[-1].body
    assert b"inlineData" not in replies[-1].body
    replies[-1].complete(200, gemini_text("Final words."))
    assert copies == ["Final words."]

    manager.toggle()
    live = manager._live
    manager._read_mic()
    manager.toggle()
    live.failed.emit()
    payload = json.loads(replies[-1].body)
    audio = base64.b64decode(payload["contents"][0]["parts"][0]["inlineData"]["data"])
    assert audio[44:] == live.audio
    assert copies == ["Final words."]
    manager.cancel()
    manager.close()
