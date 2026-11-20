import json
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QNetworkRequest
from PySide6.QtWidgets import QWidget

from poppy.core import dictation_api
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
