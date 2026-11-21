import base64
import json
import sys
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtNetwork import QNetworkRequest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit, QWidget

from poppy.core import dictation_api
from poppy.core.dictation_live import GeminiLiveDictation
from poppy.ui.dictation import DictationController, DictationIndicator, native
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
    replies[-1].complete(200, {"choices": [{"finish_reason": "stop", "message": {"content": "Please see my link."}}]})
    assert results == [("Please see https://example.test.", "")]
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


def test_mixed_audio_finishes_in_one_pass_and_keeps_live_text_on_failure(monkeypatch):
    api = dictation_api.DictationApi()
    api.set_keys({"gemini": ["google"], "groq": ["groq"]})
    replies = mock_network(api, monkeypatch)
    results = []
    api.finished.connect(lambda *result: results.append(result))
    options = dict(cleanup=False, vocabulary=[], snippets={}, style="natural", language_mode="hi-bn-en",
                   romanize=True, live_text="Abe, what?")
    api.start(b"RIFFsample-data", **options)
    payload = json.loads(replies[-1].body)
    assert replies[-1].host == "generativelanguage.googleapis.com"
    prompt = payload["systemInstruction"]["parts"][0]["text"]
    assert "Hindi, Bengali and English" in prompt and "every phrase" in prompt
    assert "Roman letters" in prompt and "obvious fillers" not in prompt
    assert payload["contents"][0]["parts"][1]["text"] == "Partial transcript: Abe, what?"
    replies[-1].complete(200, gemini_text("Abe, what? Ami Banglay bolchi."))
    assert len(replies) == 1 and results[-1] == ("Abe, what? Ami Banglay bolchi.", "")

    api.start(b"RIFFsample-data", **dict(options, cleanup=True))
    replies[-1].complete(503)
    assert "gemini-3.5-flash-lite" in replies[-1].request.url().toString()
    replies[-1].complete(503)
    payload = json.loads(replies[-1].body)
    assert replies[-1].host == "api.groq.com"
    assert payload["messages"][-1]["content"] == options["live_text"]
    replies[-1].complete(200, {"choices": [{"finish_reason": "stop", "message": {"content": "Abe, what?"}}]})
    assert results[-1] == ("Abe, what?", "")


def test_roman_writing_has_local_fallback(monkeypatch):
    api = dictation_api.DictationApi()
    api.set_keys({"gemini": ["google"]})
    replies = mock_network(api, monkeypatch)
    results = []
    api.finished.connect(lambda *result: results.append(result))
    api.start(b"RIFFsample-data", cleanup=False, vocabulary=[], snippets={}, style="natural", romanize=True)
    replies[-1].complete(200, gemini_text("अबे, what? আমি বাংলায় বলছি। Café 👋"))
    assert len(replies) == 2 and b"inlineData" not in replies[-1].body
    assert "gemini-3.1-flash-lite" in replies[-1].request.url().toString()
    replies[-1].complete(503)
    replies[-1].complete(503)
    text, message = results[-1]
    assert message == "Cleanup unavailable"
    assert text.startswith("abe, what? ami ") and text.endswith("Café 👋")
    assert not dictation_api._has_non_latin_letters(text)


def test_roman_output_also_formats_groq_transcripts_when_cleanup_is_off(monkeypatch):
    api = dictation_api.DictationApi()
    api.set_keys({"groq": ["groq"]})
    replies = mock_network(api, monkeypatch)
    results = []
    api.finished.connect(lambda *result: results.append(result))
    api.start(b"RIFFsample-data", cleanup=False, vocabulary=[], snippets={}, style="natural", romanize=True)
    assert replies[-1].request.url().path().endswith("/audio/transcriptions")
    replies[-1].complete(200, {"text": "আমি বাংলায় বলছি।"})
    payload = json.loads(replies[-1].body)
    assert "Preserve wording" in payload["messages"][0]["content"]
    assert "Roman letters" in payload["messages"][0]["content"]
    assert payload["messages"][-1]["content"] == "আমি বাংলায় বলছি।"
    replies[-1].complete(200, {"choices": [{"finish_reason": "stop", "message": {"content": "আমি বাংলায় বলছি।"}}]})
    assert len(replies) == 2
    assert results[0][0].startswith("ami ") and not dictation_api._has_non_latin_letters(results[0][0])


@pytest.mark.parametrize(("original", "changed"), [
    ("Do not send 15 to Riya.", "Do send 15 to Riya."),
    ("Do not send 15 to Riya.", "Do not send 50 to Riya."),
    ("Please send this to Riya.", "Please send this to Priya."),
    ("Run git status --short.", "Run git status short."),
    ("मैं नहीं जाऊँगा। আমি বাংলায় বলছি। Can you hear me?", "मैं नहीं जाऊँगा। Can you hear me?"),
    ("उसने कहा कि मैं आया।", "उसने कहा की मैं आया।"),
])
def test_cleanup_cannot_silently_change_meaning(monkeypatch, original, changed):
    api = dictation_api.DictationApi()
    api.set_keys({"gemini": ["fixture"]})
    replies = mock_network(api, monkeypatch)
    results = []
    api.finished.connect(lambda *result: results.append(result))
    api.finish_transcript(original, cleanup=True, vocabulary=[], snippets={}, style="natural")
    replies[0].complete(200, gemini_text(changed))
    assert results == [(original, "Kept the original words")] and len(replies) == 1


def test_live_romanization_sends_one_text_request_and_keeps_original_on_timeout(monkeypatch):
    api = dictation_api.DictationApi()
    api.set_keys({"gemini": ["fixture"], "openrouter": ["backup"]})
    replies = mock_network(api, monkeypatch)
    results = []
    api.finished.connect(lambda *result: results.append(result))
    options = dict(cleanup=False, vocabulary=[], snippets={}, style="natural", romanize=True, language_mode="mixed")
    source = "अबे, what? আমি বাংলায় বলছি। Can you send it today?"
    expected = "Abe, what? Ami Banglay bolchi. Can you send it today?"
    api.finish_transcript(source, **options)
    assert len(replies) == 1 and b"inlineData" not in replies[-1].body
    replies[-1].complete(200, gemini_text(expected))
    assert results == [(expected, "")]
    api.finish_transcript(source, **dict(options, cleanup=True))
    assert api._request_timeout.interval() == 2500 and api._deadline.interval() == 4000
    api._abort_reply()
    assert len(replies) == 2 and results[-1][1] == "Cleanup unavailable"
    assert not dictation_api._has_non_latin_letters(results[-1][0])
    replies[-1].complete(200, gemini_text(expected))
    assert len(results) == 2


def test_recovery_checks_middle_and_ending_and_accepts_only_covering_batch(monkeypatch):
    final = "Start here. Keep the ending."
    reference = "Start here. আমি বাংলায় বলছি। Keep the ending."
    assert dictation_api.transcript_needs_recovery(final, reference)
    assert not dictation_api.transcript_needs_recovery("First phrase. Second phrase.", "First phrase. Sec")
    assert dictation_api.transcript_needs_recovery("Two words", "This preview has most of the original sentence")
    api = dictation_api.DictationApi()
    api.set_keys({"gemini": ["fixture"]})
    replies = mock_network(api, monkeypatch)
    results = []
    api.finished.connect(lambda *result: results.append(result))
    options = dict(cleanup=False, vocabulary=[], snippets={}, style="natural", language_mode="mixed")
    for text, warning in ((reference, ""), ("Keep that.", dictation_api.REVIEW_TRANSCRIPT)):
        api.start(b"RIFFsample-data", **options, live_text=final, preview_reference=reference)
        replies[-1].complete(200, gemini_text(text))
        assert results[-1] == (reference, warning)
    api.start(b"RIFFsample-data", **options, live_text=final)
    replies[-1].complete(200, gemini_text("Keep that."))
    assert results[-1] == (final, dictation_api.REVIEW_TRANSCRIPT)


def test_preview_rate_limit_without_retry_after_preserves_final_attempt(monkeypatch):
    api = dictation_api.DictationApi()
    api.set_keys({"gemini": ["fixture"]})
    replies = mock_network(api, monkeypatch)
    options = dict(cleanup=False, vocabulary=[], snippets={}, style="natural")
    api.start(b"RIFFsample-data", **options, preview=True)
    monkeypatch.setattr(replies[-1], "rawHeader", lambda name: b"")
    replies[-1].complete(429)
    assert api.live_key() == "fixture"
    api.start(b"RIFFsample-data", **options, preview=True)
    assert len(replies) == 1
    api.start(b"RIFFsample-data", **options)
    assert len(replies) == 2
    replies[-1].complete(429)
    assert api.live_key() == "fixture"


def test_settings_save_keys_encrypted_and_reopen_with_voice_options(audit_app, tmp_path):
    window = SettingsWindow()
    window.select_page("Voice typing")
    assert window.stack.currentWidget().widget() is window.voice_typing
    voice = window.voice_typing
    voice.keys["groq"].setText("demo-groq-key, demo-groq-key")
    voice.keys["gemini"].setText("demo-gemini-key")
    voice.enabled.setChecked(True)
    voice.languages.setCurrentIndex(voice.languages.findData("hi-bn-en"))
    voice.output_script.setCurrentIndex(voice.output_script.findData("roman"))
    voice.snippets.setPlainText("my link = https://example.test/?a=b")
    assert window._save_settings()
    saved = (tmp_path / "data" / "config.json").read_text()
    assert "demo-groq-key" not in saved and "demo-gemini-key" not in saved
    config = json.loads(saved)["dictation"]
    assert dictation_api.read_keys(config) == {"groq": ["demo-groq-key"], "gemini": ["demo-gemini-key"]}
    assert config["speech_languages"] == "hi-bn-en" and config["output_script"] == "roman"
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
    monkeypatch.setattr(native, "copy_text", lambda hwnd, text, **options: copies.append((text, options)) or True)
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
    assert manager._indicator.accessibleDescription().startswith("Transcribing")
    replies[-1].complete(200, gemini_text("Hello, Poppy."))
    replies[-1].complete(200, gemini_text("Hello, Poppy."))
    assert manager.last_text == "Hello, Poppy."
    assert manager._indicator.accessibleDescription().startswith("Copied to clipboard")
    assert copies == [("Hello, Poppy.", {"history": False, "preserve_complex": True})]
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
    monkeypatch.setattr(native, "copy_text", lambda hwnd, text, **kwargs: copies.append(text) or True)
    controller = window.dictation
    monkeypatch.setattr(controller, "_start_live", lambda: None)
    window.btn_hdr_dictation.click()
    pill = controller._indicator
    assert pill.isVisible() and window.btn_hdr_dictation.isChecked()
    assert pill.title.isHidden() and pill.width() < 120
    assert not controller._hide_timer.isActive() and pill.preview.isHidden()
    assert controller._mic is None
    QTest.mouseClick(pill, Qt.MouseButton.LeftButton, pos=pill.header.geometry().center())
    assert controller._indicator.listening
    assert abs(pill.action.geometry().center().y() - pill.header.rect().center().y()) <= 1
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
    controller._expire_status()
    assert pill.isVisible() and pill._ready and not controller._hide_timer.isActive()
    window.btn_hdr_dictation.click()
    assert not pill.isVisible()
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
    start = pill.header.geometry().center()
    QTest.mousePress(pill, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(pill, start + QPoint(52, -103))
    QTest.mouseRelease(pill, Qt.MouseButton.LeftButton, pos=start)
    assert pill.pos() != old and not clicks
    anchor = (pill.x() + pill.width() // 2, pill.y() + pill.height())
    manager._status("Listening", "Recording")
    assert (pill.x() + pill.width() // 2, pill.y() + pill.height()) == anchor
    pill.set_preview("This caption opens above the pill.")
    assert (pill.x() + pill.width() // 2, pill.y() + pill.height()) == anchor
    manager._status("Copied to clipboard", "Ctrl+V to paste")
    assert (pill.x() + pill.width() // 2, pill.y() + pill.height()) == anchor
    manager.close()
    reopened = DictationController(parent)
    reopened._status("Ready to dictate", "Click to start")
    pill = reopened._indicator
    assert (pill.x() + pill.width() // 2, pill.y() + pill.height()) == anchor
    reopened._reset_position()
    assert pill.pos() == old
    bounds = pill.screen().availableGeometry()
    near_top = QPoint(bounds.left() + 10, bounds.top() + 2)
    pill.place(near_top, pill.screen())
    reopened._status("Listening", "Recording")
    pill.set_preview("This caption fits on the screen.")
    assert pill.y() == bounds.top()
    reopened._status("Text sent", "Complete")
    assert pill.pos() == near_top
    reopened.close()


@pytest.fixture
def offline_socket(monkeypatch):
    class Socket(QObject):
        connected = Signal()
        textMessageReceived = Signal(str)
        binaryMessageReceived = Signal(bytes)
        disconnected = Signal()
        errorOccurred = Signal()

        def setMaxAllowedIncomingMessageSize(self, size):
            pass

        def bytesToWrite(self):
            return 0

        def abort(self):
            self.disconnected.emit()

        def closeReason(self):
            return "API key not valid. Please pass a valid API key."

    monkeypatch.setattr("poppy.core.dictation_live.QWebSocket", Socket)


def test_live_protocol_flushes_tail_and_only_finalizes_after_stop(monkeypatch, offline_socket):
    live = GeminiLiveDictation()
    packets, preview, completed, failures = [], [], [], []
    monkeypatch.setattr(live, "_send", lambda packet: packets.append(packet) or True)
    live.preview.connect(preview.append)
    live.finalized.connect(lambda *args: completed.append(args))
    live.failed.connect(failures.append)
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
    assert not completed
    live._message('{"serverContent":{"inputTranscription":{"text":"Last phrase."}}}')
    live._message('{"serverContent":{"generationComplete":true}}')
    live._message('{"serverContent":{"turnComplete":true}}')
    assert not completed
    QTest.qWait(240)
    assert completed == [("First phrase. Second phrase. Last phrase.", "")] and not failures
    live = GeminiLiveDictation()
    live._active = True
    live.failed.connect(failures.append)
    live._socket.disconnected.emit()
    assert failures == [401]


def test_stream_success_reuses_text_and_failure_uses_full_capture(audit_app, monkeypatch):
    class Mic:
        def read(self):
            return b"\x00\x10" * 3200

        def close(self, *, keep_audio=False):
            return b"\x00\x10" * 800 if keep_audio else b""

    class Live(QObject):
        ready = True
        has_transcript = True
        unconfirmed_ending = False
        preview = Signal(str)
        finalized = Signal(str, str)
        checkpointed = Signal(str)
        failed = Signal(int)

        def start(self, key, vocabulary, *, language_codes):
            self.audio = bytearray()
            self.language_codes = language_codes
            self.key = key

        def feed(self, pcm, *, voiced=True):
            self.audio.extend(pcm)

        replay = feed

        def checkpoint(self):
            self.cut = len(self.audio)

        def finish(self):
            pass

        def cancel(self):
            pass

    monkeypatch.setattr("poppy.ui.dictation.GeminiLiveDictation", Live)
    monkeypatch.setattr(native, "Microphone", Mic)
    monkeypatch.setattr(native, "focused_target", lambda: None)
    monkeypatch.setattr(native, "modifiers_down", lambda: False)
    copies = []
    monkeypatch.setattr(native, "copy_text", lambda hwnd, text, **kwargs: copies.append(text) or True)
    parent = QWidget()
    manager = DictationController(parent)
    manager.configure({"enabled": True, "protected_keys": dictation_api.protect_keys({"gemini": ["test", "backup"]})})
    replies = mock_network(manager._pipeline(), monkeypatch)
    manager.toggle()
    live = manager._live
    manager._read_mic()
    captured = bytes(live.audio)
    live.failed.emit(401)
    live = manager._live
    assert live.key == "backup" and live.audio == captured
    assert manager._pipeline().live_key() == "backup"
    live.preview.emit("Preview fragment")
    assert "Preview fragment" in manager._indicator.preview.text() and not copies
    manager.toggle()
    assert len(live.audio) == 8000 and not replies
    live.finalized.emit("Final recognized words.", "")
    assert len(replies) == 1 and b"Final recognized words." in replies[-1].body
    assert b"inlineData" not in replies[-1].body
    replies[-1].complete(200, gemini_text("Final recognized words."))
    assert copies == ["Final recognized words."]

    manager.toggle()
    live = manager._live
    manager._read_mic()
    manager.toggle()
    live.finalized.emit("Partial final.", "Partial final with an ending.")
    assert b"inlineData" in replies[-1].body
    assert manager._indicator.accessibleDescription().startswith("Checking transcript")
    assert b"Partial final with an ending." not in replies[-1].body
    replies[-1].complete(200, gemini_text("Keep that."))
    assert manager.last_text == "Partial final with an ending."
    assert manager._indicator.title.text() == "Review transcript" and copies == ["Final recognized words."]
    manager.cancel()

    manager.toggle()
    live = manager._live
    manager._read_mic()
    manager.toggle()
    live.failed.emit(0)
    payload = json.loads(replies[-1].body)
    audio = base64.b64decode(payload["contents"][0]["parts"][0]["inlineData"]["data"])
    assert audio[44:] == live.audio
    assert copies == ["Final recognized words."]
    manager.cancel()

    manager.configure(dict(manager._config, speech_languages="hi-bn-en", output_script="roman"))
    manager.toggle()
    live = manager._live
    assert live.language_codes == ("hi-IN", "bn-IN", "en-IN")
    manager._read_mic()
    manager.toggle()
    count = len(replies)
    live.finalized.emit("Abe, what? Ami Banglay bolchi.", "")
    payload = json.loads(replies[-1].body)
    assert len(replies) == count + 1
    assert payload["contents"][0]["parts"] == [{"text": "Abe, what? Ami Banglay bolchi."}]
    replies[-1].complete(200, gemini_text("Abe, what? Ami Banglay bolchi."))
    assert copies[-1] == "Abe, what? Ami Banglay bolchi."

    manager.configure(dict(manager._config, speech_languages="mixed", cleanup=False))
    manager.toggle()
    live = manager._live
    manager._read_mic()
    manager.toggle()
    count = len(replies)
    live.finalized.emit("One short note.", "")
    assert len(replies) == count and copies[-1] == "One short note."
    manager.close()


def test_failed_long_take_offers_only_its_current_draft_for_manual_copy(monkeypatch):
    parent = QWidget()
    manager = DictationController(parent)
    copies = []
    monkeypatch.setattr(native, "copy_text", lambda hwnd, text, **kwargs: copies.append(text) or True)
    manager.last_text = "Old result."
    manager._status("Listening", "")
    api = manager._pipeline()
    api.set_keys({"gemini": ["fixture"]})
    replies = mock_network(api, monkeypatch)
    manager._pcm = bytearray(60 * 32000)
    manager._stopped_at = dictation_api.time.monotonic()
    manager._remember_live_draft("This new take has English. আমি বাংলায় বলছি।")
    manager._transcribe_recording()
    assert 13000 < api._deadline.interval() <= 14000
    api._timed_out()
    assert manager._indicator.title.text() == "Review transcript"
    assert not copies
    manager._indicator.action.click()
    assert copies == ["This new take has English. আমি বাংলায় বলছি।"]
    manager.close()


@pytest.fixture
def recovery_session(monkeypatch, offline_socket):
    parent = QWidget()
    editor = QLineEdit(parent)
    manager = DictationController(parent)
    manager._keys = {"gemini": ["test"]}
    manager._config = {"cleanup": False}
    monkeypatch.setattr(native, "Microphone", lambda: SimpleNamespace(close=lambda **_: b""))
    monkeypatch.setattr(native, "focused_target", lambda: None)
    monkeypatch.setattr(native, "modifiers_down", lambda: False)
    monkeypatch.setattr(manager, "_local_editor", lambda: editor)
    copies = []
    monkeypatch.setattr(native, "copy_text", lambda hwnd, text, **kw: copies.append(text) or True)
    monkeypatch.setattr(GeminiLiveDictation, "_send", lambda self, packet: True)

    def start_socket(live, *args, **kwargs):
        live._active = True
        live._message('{"setupComplete":{}}')

    monkeypatch.setattr(GeminiLiveDictation, "start", start_socket)
    replies = mock_network(manager._pipeline(), monkeypatch)
    manager.toggle()
    yield manager, editor, copies, replies
    manager.close()


def _caption(live, text, offset=None):
    key = "interimInputTranscription" if offset is None else "inputTranscription"
    frame = {"text": text}
    if offset is not None:
        frame["endOffset"] = f"{offset}s"
    live._message(json.dumps({"serverContent": {key: frame}}))


def _wav_body(reply):
    part = json.loads(reply.body)["contents"][0]["parts"][0]
    return base64.b64decode(part["inlineData"]["data"])


def test_mixed_take_rechecks_locked_language_from_original_audio(recovery_session):
    manager, editor, _, replies = recovery_session
    manager._language_mode = "mixed"
    live = manager._live
    pcm = b"\x00\x10" * 16000
    first = "আমি বাংলায় কথা বলছি এবং এই পরীক্ষা চালাচ্ছি।"
    last = "আমরা আবার এখানে কথা বলছি এবং অন্য ভাষা শুনছি।"
    for _ in range(60):
        manager._add_audio(pcm)
        _caption(live, last)
    manager._covered = 32000
    manager._confirmed_text = first
    manager.toggle()
    live.finalized.emit(last, "")
    assert manager._indicator.accessibleDescription().startswith("Checking languages")
    payload = json.loads(replies[0].body)
    parts = payload["contents"][0]["parts"]
    assert len(parts) == 1
    assert _wav_body(replies[0])[44:] == pcm * 60
    assert first.encode("utf-8") not in replies[0].body
    assert "Devanagari for Hindi" in payload["systemInstruction"]["parts"][0]["text"]
    restored = "This is the audio test. मैं हिंदी में बोल रहा हूँ। আমি বাংলায় কথা বলছি। Back to English now."
    replies[0].complete(200, gemini_text(restored))
    assert editor.text() == restored


def test_mixed_take_can_confirm_single_language_or_require_review(monkeypatch):
    api = dictation_api.DictationApi()
    api.set_keys({"gemini": ["fixture"]})
    replies = mock_network(api, monkeypatch)
    results = []
    api.finished.connect(lambda *args: results.append(args))
    draft = "আমি বাংলায় কথা বলছি এবং এই পরীক্ষা করছি।"
    options = dict(cleanup=False, vocabulary=[], snippets={}, style="natural", language_mode="mixed",
                   language_reference=draft, stopped_at=dictation_api.time.monotonic())
    api.start(b"RIFFsample", **options)
    replies[-1].complete(200, gemini_text(draft))
    assert results[-1] == (draft, "")
    api.start(b"RIFFsample", **options)
    replies[-1].complete(200, gemini_text("Yes."))
    replies[-1].complete(200, gemini_text("হ্যাঁ।"))
    assert results[-1] == (draft, dictation_api.REVIEW_TRANSCRIPT)


def test_balanced_mixed_live_text_does_not_upload_audio(recovery_session):
    manager, editor, _, replies = recovery_session
    manager._language_mode = "mixed"
    live = manager._live
    text = "Testing language switches. আমি বাংলায় বলছি। फिर हिंदी में बात करते हैं। Now English again."
    for _ in range(9):
        manager._add_audio(b"\x00\x10" * 16000)
        _caption(live, text)
    manager.toggle()
    live.finalized.emit(text, "")
    assert editor.text() == text and not replies


def test_mic_feedback_distinguishes_low_level_from_pending_captions(recovery_session):
    manager, _, _, replies = recovery_session
    assert "Checking microphone…" in manager._indicator.accessibleDescription()
    assert manager._indicator.preview.isHidden()
    manager._started -= 3
    manager._mic.read = lambda: bytes(6400)
    manager._read_mic()
    assert "Low mic level · Check Windows input" in manager._indicator.accessibleDescription()
    manager._mic.read = lambda: b"\x00\x10" * 3200
    manager._read_mic()
    assert "Mic signal detected · Waiting for captions" in manager._indicator.accessibleDescription()
    _caption(manager._live, "Recognized words")
    manager._read_mic()
    assert manager._indicator.preview.text() == "Recognized words" and not replies


@pytest.mark.parametrize("partial_take", [False, True])
def test_stalled_microphone_preserves_any_captured_speech(recovery_session, partial_take):
    manager, editor, _, replies = recovery_session
    pcm = b"\x00\x10" * 3200
    if partial_take:
        manager._mic.read = lambda: pcm
        manager._read_mic()
    manager._last_pcm_at -= 2.1
    manager._mic.read = lambda: b""
    manager._read_mic()
    assert manager._live is None and manager._mic is None
    if partial_take:
        assert _wav_body(replies[0])[44:] == pcm
        assert manager._indicator.detail.text().startswith("Mic stopped")
        replies[0].complete(200, gemini_text("Captured words"))
        assert editor.text() == "Captured words"
    else:
        assert manager._indicator.title.text() == "Microphone stopped" and not replies


def test_ready_live_without_captions_does_not_add_wait_after_stop(recovery_session):
    manager, editor, _, replies = recovery_session
    pcm = b"\x00\x10" * 16000
    for _ in range(4):
        manager._add_audio(pcm)
    live = manager._live
    assert live.ready and not live.has_transcript
    manager.toggle()
    assert manager._live is None and len(replies) == 1
    assert _wav_body(replies[0])[44:] == pcm * 4
    replies[0].complete(200, gemini_text("Complete text"))
    assert editor.text() == "Complete text"


@pytest.mark.parametrize("stop_during_checkpoint", [False, True])
def test_delayed_checkpoint_recovers_exact_audio_after_pause(recovery_session, stop_during_checkpoint):
    manager, editor, copies, replies = recovery_session
    live = manager._live
    second = b"\x00\x10" * 16000
    for i in range(18):
        manager._add_audio(second)
        if i == 10:
            _caption(live, "Namaste", 11)
        else:
            _caption(live, "ami")
    manager._add_audio(bytes(32000))
    cut = 19 * 32000
    assert manager._cut == cut and manager._covered == 0
    # Eight more seconds arrive before Gemini acknowledges the original audio.
    tail = bytearray()
    for i in range(8):
        chunk = bytes((i, 12)) * 16000
        manager._add_audio(chunk)
        tail.extend(chunk)
    if stop_during_checkpoint:
        manager.toggle()
    _caption(live, "ami", 18)
    assert manager._covered == cut
    if not stop_during_checkpoint:
        replacement = manager._live
        assert replacement is not live and replacement._audio_bytes == len(tail)
        replacement._fail()
        assert manager._live is not replacement and manager._live._audio_bytes == len(tail)
        for i in range(33):
            manager._add_audio(second)
            _caption(manager._live, "hello")
            tail.extend(second)
        manager.toggle()
        manager._live._fail()
    assert len(replies) == 1 and _wav_body(replies[0])[44:] == tail
    replies[0].complete(200, gemini_text("hello"))
    assert editor.text() == "Namaste ami hello" and copies == []
    live.finalized.emit("old words", "")
    assert editor.text() == "Namaste ami hello" and not manager.can_retry


def test_retry_keeps_original_audio_and_requires_copy(recovery_session):
    manager, editor, copies, replies = recovery_session
    audio = b"\x00\x10" * 12000
    manager._add_audio(audio)
    manager.toggle()
    manager._live._fail()
    manager._api._timed_out()
    assert manager.can_retry and manager._indicator.retry.isVisible()
    manager._indicator.retry.click()
    assert _wav_body(replies[-1])[44:] == audio and not manager.can_retry
    replies[-1].complete(200, gemini_text("Recovered words"))
    assert not editor.text() and not copies and not manager._retry_audio
    manager._indicator.action.click()
    assert copies == ["Recovered words"]


@pytest.mark.parametrize("failed_before_stop", [False, True])
def test_cold_socket_never_delays_batch_at_stop(recovery_session, failed_before_stop):
    manager, editor, _, replies = recovery_session
    live = manager._live
    live._ready = False
    manager._add_audio(b"\x00\x10" * 12000)
    if failed_before_stop:
        live._fail()
        assert manager._live is None and not manager._reconnects
    manager.toggle()
    assert len(replies) == 1 and manager._phase == "processing"
    assert manager._api._request_timeout.interval() == 4500
    replies[0].complete(200, gemini_text("Quick note"))
    assert editor.text() == "Quick note"


def test_timestamps_finish_without_turn_marker_and_ignore_duplicate_segment(recovery_session):
    manager, editor, copies, replies = recovery_session
    live = manager._live
    manager._add_audio(b"\x00\x10" * 32000)
    _caption(live, "Abe", 1)
    _caption(live, "Abe", 1)
    manager.toggle()
    live._message('{"serverContent":{"turnComplete":true}}')
    assert not editor.text() and not replies
    _caption(live, "what?", 2)
    assert editor.text() == "Abe what?" and not copies and not replies


@pytest.mark.parametrize("marker_order", ["first", "last", "absent"])
def test_untimed_live_keeps_split_bengali_ending(recovery_session, marker_order):
    manager, editor, copies, replies = recovery_session
    manager._language_mode = "mixed"
    live = manager._live
    speech = b"\x00\x10" * 16000
    manager._add_audio(speech)
    live._message('{"serverContent":{"inputTranscription":{"text":"Mic testing."}}}')
    manager._add_audio(speech)
    manager.toggle()
    marker = '{"serverContent":{"generationComplete":true}}'
    if marker_order == "first":
        live._message(marker)
    assert not editor.text() and not replies and not live._settle.isActive()
    live._message('{"serverContent":{"inputTranscription":{"text":"আমি বাংলায়"}}}')
    assert live._settle.isActive() and not editor.text()
    first_timer = live._settle.timerId()
    live._message('{"serverContent":{"inputTranscription":{"text":"কথা বলছি।"}}}')
    assert live._settle.timerId() != first_timer
    if marker_order == "last":
        last_timer = live._settle.timerId()
        live._message(marker)
        assert live._settle.timerId() == last_timer
    assert not editor.text() and not replies
    live._settle.timeout.emit()
    assert editor.text() == "Mic testing. আমি বাংলায় কথা বলছি।" and not copies and not replies


@pytest.mark.parametrize("late_final", [False, True])
def test_unconfirmed_stop_recovers_once_without_live_cooldown(recovery_session, late_final):
    manager, editor, copies, replies = recovery_session
    live = manager._live
    speech = b"\x00\x10" * 16000
    manager._add_audio(speech)
    live._message('{"serverContent":{"inputTranscription":{"text":"Mic testing."}}}')
    manager._add_audio(speech)
    manager.toggle()
    live._message('{"serverContent":{"turnComplete":true}}')
    if late_final:
        live._message('{"serverContent":{"inputTranscription":{"text":"Ami Banglay"}}}')
    assert live._settle.isActive() == late_final and not replies
    live._timeout.timeout.emit()
    assert not live._settle.isActive()
    live._settle.timeout.emit()
    assert len(replies) == 1 and _wav_body(replies[0])[44:] == speech * 2
    manager._api._timed_out()
    assert not editor.text() and not copies and manager.can_retry
    assert manager._indicator.title.text() == dictation_api.REVIEW_TRANSCRIPT
    manager.toggle()
    assert manager._live is not None and manager._live is not live


def test_cancel_during_settling_cannot_deliver_to_new_take(recovery_session):
    manager, editor, copies, replies = recovery_session
    old_live = manager._live
    manager._add_audio(b"\x00\x10" * 16000)
    manager.toggle()
    old_live._message('{"serverContent":{"inputTranscription":{"text":"Discarded"}}}')
    assert old_live._settle.isActive()
    manager.cancel()
    manager.toggle()
    assert not old_live._settle.isActive()
    old_live._settle.timeout.emit()
    old_live._timeout.timeout.emit()
    assert manager._phase == "recording" and not editor.text() and not copies and not replies


def test_untimed_checkpoint_keeps_audio_recorded_during_settling(recovery_session):
    manager, editor, _, _ = recovery_session
    live = manager._live
    for _ in range(18):
        manager._add_audio(b"\x00\x10" * 16000)
        _caption(live, "Namaste ami")
    live._message('{"serverContent":{"inputTranscription":{"text":"Namaste"}}}')
    manager._add_audio(bytes(32000))
    live._message('{"serverContent":{"generationComplete":true}}')
    assert manager._covered == 0 and manager._live is live
    live._message('{"serverContent":{"inputTranscription":{"text":"ami"}}}')
    assert manager._covered == 0 and live._settle.isActive()
    tail = b"\x01\x10" * 16000
    manager._add_audio(tail)
    live._settle.timeout.emit()
    assert manager._covered == 19 * 32000 and manager._live is not live
    assert manager._live._audio_bytes == len(tail)
    live._settle.timeout.emit()
    assert manager._confirmed_text == "Namaste ami"
    manager.toggle()
    replacement = manager._live
    _caption(replacement, "back again", 1)
    assert editor.text() == "Namaste ami back again"


def test_failed_tail_only_offers_confirmed_prefix_for_review(recovery_session):
    manager, editor, copies, replies = recovery_session
    live = manager._live
    for i in range(18):
        manager._add_audio(b"\x00\x10" * 16000)
        _caption(live, "words", 18 if i == 17 else None)
    manager._add_audio(bytes(32000))
    manager._add_audio(b"\x01\x11" * 16000)
    manager.toggle()
    manager._live._fail()
    manager._api._timed_out()
    assert len(_wav_body(replies[-1])) == 32044 and not editor.text() and not copies
    assert manager.last_text == "words" and manager.can_retry
    assert manager._indicator.title.text() == dictation_api.REVIEW_TRANSCRIPT
    manager._indicator.dismiss_button.click()
    assert not manager.last_text and not manager.can_retry


@pytest.mark.parametrize("discard", [False, True])
def test_discard_or_new_recording_rejects_late_recovery(recovery_session, discard):
    manager, editor, copies, replies = recovery_session
    manager._add_audio(b"\x00\x10" * 12000)
    old_live = manager._live
    manager.toggle()
    old_live._fail()
    manager._api._timed_out()
    manager.retry()
    old_reply = replies[-1]
    if discard:
        manager._indicator.dismiss_button.click()
        assert not manager.can_retry and not manager._retry_audio
    manager.toggle()
    old_reply.complete(200, gemini_text("Discarded words"))
    old_live.finalized.emit("Stale final", "")
    assert manager._phase == "recording" and not editor.text() and not copies


def test_stall_reconnect_budget_and_quota_are_bounded(recovery_session):
    manager, _, _, replies = recovery_session
    _caption(manager._live, "Earlier words")
    for i in range(3):
        live = manager._live
        for _ in range(6):
            manager._add_audio(b"\x00\x10" * 16000)
        assert manager._live is not live
    assert manager._live is None and manager._reconnects == 2
    manager.toggle()
    assert len(_wav_body(replies[-1])) == 44 + 18 * 32000
    manager.cancel()
    manager._live_retry_at = 0
    manager.toggle()
    manager._live._fail(429)
    assert manager._live is None and not manager._reconnects
    assert manager._live_retry_at > dictation_api.time.monotonic()
    pcm = b"\x00\x10" * 16000
    manager._add_audio(pcm)
    manager.toggle()
    assert _wav_body(replies[-1])[44:] == pcm


def test_captionless_live_switches_to_batch_preview_instead_of_reconnecting(recovery_session):
    manager, _, _, replies = recovery_session
    for _ in range(5):
        manager._add_audio(b"\x00\x10" * 16000)
    assert manager._live is None and manager._reconnects == 0
    manager._maybe_preview()
    assert manager._previewing and replies
    replies[-1].complete(200, gemini_text("Batch caption"))
    assert manager._indicator.preview.text() == "Batch caption"


def test_failed_preview_still_allows_two_distinct_final_models(recovery_session):
    manager, editor, _, replies = recovery_session
    manager._live._fail(429)
    manager._add_audio(b"\x00\x10" * 48000)
    manager._maybe_preview()
    first_url = replies[-1].request.url().toString()
    replies[-1].complete(503)
    manager.toggle()
    assert replies[-1].request.url().toString() == first_url
    manager._api._abort_reply()
    assert replies[-1].request.url().toString() != first_url
    replies[-1].complete(200, gemini_text("Full batch result"))
    assert editor.text() == "Full batch result"


def test_batch_quota_has_a_specific_retry_message(recovery_session):
    manager, _, copies, replies = recovery_session
    manager._live._fail(429)
    manager._add_audio(b"\x00\x10" * 16000)
    manager.toggle()
    replies[-1].complete(429)
    assert manager._indicator.title.text() == "Transcription rate limited"
    assert manager.can_retry and not copies
    manager.retry()
    assert manager._indicator.title.text() == "Transcription rate limited"
    assert len(replies) == 1


def test_manual_retry_gets_fresh_attempt_after_a_transient_failure(recovery_session):
    manager, editor, copies, replies = recovery_session
    manager._live._fail(429)
    manager._add_audio(b"\x00\x10" * 16000)
    manager.toggle()
    replies[0].complete(503)
    replies[1].complete(503)
    assert manager._indicator.title.text() == "Transcription service busy"
    manager.retry()
    assert len(replies) == 3
    assert manager._api._deadline.interval() >= 17900
    replies[-1].complete(200, gemini_text("Retry worked"))
    assert not editor.text() and not copies


def test_empty_result_clears_old_dictation_and_never_copies_it(monkeypatch):
    parent = QWidget()
    manager = DictationController(parent)
    copies = []
    monkeypatch.setattr(native, "copy_text", lambda hwnd, text, **kwargs: copies.append(text) or True)
    manager.last_text = "Old result."
    manager._finished("", "Dictation timed out")
    manager.copy_last()
    assert not manager.last_text and not copies
    assert manager._indicator.title.text() == "Dictation timed out"
    assert manager._indicator.detail.text() == "No new text copied"
    manager.close()


def test_dictation_preserves_files_until_copy_is_clicked(monkeypatch):
    formats = {15: "copied file list"}
    clipboard = SimpleNamespace(
        CF_TEXT=1, CF_UNICODETEXT=13, CF_OEMTEXT=7, CF_LOCALE=16,
        RegisterClipboardFormat=lambda name: 60000 + native._CLIPBOARD_FLAGS.index(name),
        OpenClipboard=lambda hwnd: None, CloseClipboard=lambda: None,
        EnumClipboardFormats=lambda previous: next((n for n in sorted(formats) if n > previous), 0),
        EmptyClipboard=formats.clear, SetClipboardData=formats.__setitem__,
        SetClipboardText=lambda text, fmt: formats.__setitem__(fmt, text),
    )
    monkeypatch.setitem(sys.modules, "win32clipboard", clipboard)
    monkeypatch.setattr(native, "modifiers_down", lambda: False)
    parent = QWidget()
    manager = DictationController(parent)
    manager._previewing = False
    manager._finished("Dictated text.", "")
    assert formats == {15: "copied file list"}
    assert manager._indicator.title.text() == "Dictation ready"
    assert manager._indicator.action.accessibleName() == "Copy dictation"
    manager._indicator.action.click()
    assert 15 not in formats and formats[13] == "Dictated text."
    assert formats[60001] == b"\1\0\0\0"
    manager.close()


def test_paste_revalidates_the_field_and_keeps_previous_clipboard(monkeypatch):
    formats = {13: "clipboard before dictation"}
    target = (101, 102, (7,))
    focus = [target]
    sent = []

    def change_field():
        focus[0] = (*target[:2], (8,))

    clipboard = SimpleNamespace(
        CF_TEXT=1, CF_UNICODETEXT=13, CF_OEMTEXT=7, CF_LOCALE=16,
        RegisterClipboardFormat=lambda name: 60000 + native._CLIPBOARD_FLAGS.index(name),
        OpenClipboard=lambda hwnd: None, CloseClipboard=change_field,
        EnumClipboardFormats=lambda previous: next((n for n in sorted(formats) if n > previous), 0),
        EmptyClipboard=formats.clear, SetClipboardData=formats.__setitem__, GetClipboardData=formats.__getitem__,
        SetClipboardText=lambda text, fmt: formats.__setitem__(fmt, text),
    )
    monkeypatch.setitem(sys.modules, "win32clipboard", clipboard)
    monkeypatch.setattr(native, "focused_target", lambda: (focus[0], (0, 0)))
    monkeypatch.setattr(native, "_focused_window", lambda: target[:2])
    monkeypatch.setattr(native, "modifiers_down", lambda: False)
    monkeypatch.setattr(native, "_user32", lambda: SimpleNamespace(
        GetClipboardSequenceNumber=lambda: 1, SendInput=lambda count, *_: sent.append(count) or count))
    assert native.paste_text(1, target, "Dictated text.") is None
    assert not sent and formats == {13: "clipboard before dictation"}

    # The target may read Ctrl+V after Poppy's pill closes.
    clipboard.CloseClipboard = lambda: None
    focus[0] = target
    parent = QWidget()
    manager = DictationController(parent)
    manager._target = target
    manager._finished("Dictated text.", "")
    manager.close()
    assert sent == [4] and formats[13] == "Dictated text."


def test_pill_keeps_preview_during_language_check_and_respects_reduced_motion(monkeypatch):
    monkeypatch.setattr("poppy.ui.dictation.system_animations_enabled", lambda: False)
    pill = DictationIndicator()
    pill.set_status("Listening", "")
    pill.set_preview("Preview phrase.")
    assert pill.preview.geometry().bottom() < pill.header.geometry().top()
    assert pill.preview.fade == 1.0 and pill.preview._motion.state() == pill.preview._motion.State.Stopped
    pill.set_status("Checking languages", "")
    assert pill.preview.text() == "Preview phrase."
    pill.set_status("Copied to clipboard", "")
    assert pill.preview.isHidden() and pill._check_amount == 1.0
    assert pill._check.state() == pill._check.State.Stopped
    monkeypatch.setattr("poppy.ui.dictation.system_animations_enabled", lambda: True)
    pill.set_status("Listening", "")
    pill.set_preview("one two three four five six")
    pill.set_preview("one two three four five six seven")
    assert pill.preview.text() == "two three four five six seven"
    assert pill.preview._motion.state() == pill.preview._motion.State.Running
    pill.preview._motion.setCurrentTime(240)
    assert pill.preview._offset == 0.0
    pill.set_status("Text sent", "")
    assert pill._check.state() == pill._check.State.Running
    pill._check.setCurrentTime(100)
    assert 0 < pill._check_amount < 1
    pill._check.setCurrentTime(200)
    assert pill._check_amount == 1.0
    pill.close()


def test_hold_shortcut_stops_once_on_release(monkeypatch):
    class Mic:
        def read(self):
            return b"\0\x10" * 3200

        def close(self, *, keep_audio=False):
            return b""

    parent = QWidget()
    manager = DictationController(parent)
    monkeypatch.setattr(native, "Microphone", Mic)
    monkeypatch.setattr(native, "focused_target", lambda: None)
    monkeypatch.setattr(native, "unregister_shortcuts", lambda hwnd: None)
    monkeypatch.setattr(native, "unregister_extra_shortcut", lambda hwnd, shortcut: None)
    held = [True]
    monkeypatch.setattr(native, "hold_shortcut_down", lambda: held[0])
    manager.configure({"enabled": True, "streaming": False,
                       "protected_keys": dictation_api.protect_keys({"gemini": ["fixture"]})})
    manager._registered_hwnd = 1
    manager._extra_shortcuts.add(native.HOLD_HOTKEY)
    replies = mock_network(manager._pipeline(), monkeypatch)
    assert manager.handle_shortcut(native.HOLD_HOTKEY) and manager._mic is not None
    assert "Release" in manager._indicator.accessibleDescription()
    manager._read_mic()
    assert not replies
    held[0] = False
    manager._read_mic()
    assert manager._mic is None and len(replies) == 1
    assert manager.handle_shortcut(native.HOLD_HOTKEY) and len(replies) == 1
    manager.close()


def test_edit_replaces_only_the_original_selection_and_never_inserts_the_command(monkeypatch):
    class Mic:
        def read(self):
            return b"\0\x10" * 3200

        def close(self, *, keep_audio=False):
            return b""

    parent = QWidget()
    editor = QLineEdit("first middle last", parent)
    manager = DictationController(parent)
    monkeypatch.setattr(manager, "_local_editor", lambda: editor)
    monkeypatch.setattr(native, "Microphone", Mic)
    monkeypatch.setattr(native, "focused_target", lambda: None)
    monkeypatch.setattr(native, "modifiers_down", lambda: False)
    monkeypatch.setattr(native, "copy_text", lambda *args, **kwargs: pytest.fail("Edit must not copy automatically"))
    manager.configure({"enabled": True, "streaming": False, "cleanup": False, "output_script": "roman",
                       "protected_keys": dictation_api.protect_keys({"gemini": ["fixture"]})})
    replies = mock_network(manager._pipeline(), monkeypatch)

    def say_edit():
        editor.setSelection(6, 6)
        manager._start_capture(editing=True)
        manager._read_mic()
        manager.toggle()
        assert b"middle" not in replies[-1].body
        replies[-1].complete(200, gemini_text("Translate this to Spanish."))
        body = json.loads(replies[-1].body)
        payload = body["contents"][0]["parts"][0]["text"]
        assert json.loads(payload) == {"selection": "middle", "spoken_instruction": "Translate this to Spanish."}

    say_edit()
    replies[-1].complete(200, gemini_text("medio"))
    assert editor.text() == "first medio last"
    editor.setText("first middle last")
    say_edit()
    editor.setSelection(0, 5)
    replies[-1].complete(200, gemini_text("medio"))
    assert editor.text() == "first middle last" and manager.last_text == "medio"
    assert manager._indicator.title.text() == "Edit ready"
    say_edit()
    replies[-1].complete(200, gemini_text("[EDIT_UNAVAILABLE]"))
    assert editor.text() == "first middle last" and "Could not edit" in manager._indicator.title.text()
    manager.close()


def test_continuation_sends_bounded_context_only_to_cleanup_and_inserts_at_caret(monkeypatch):
    prefix = "x" * 225 + "I'm looking forward to"
    suffix = " | Already written after the cursor."
    parent = QWidget()
    editor = QLineEdit(prefix + suffix, parent)
    editor.setCursorPosition(len(prefix))
    manager = DictationController(parent)
    manager._local_target = editor
    monkeypatch.setattr(manager, "_local_editor", lambda: editor)
    monkeypatch.setattr(native, "modifiers_down", lambda: False)
    scope = manager._read_text_scope(selection=False)
    assert scope.text == prefix[-200:]
    manager._text_scope = scope
    api = manager._pipeline()
    api.set_keys({"gemini": ["fixture"]})
    replies = mock_network(api, monkeypatch)
    manager._status("Listening", "")
    manager._previewing = False
    api.start(b"RIFFsample-data", cleanup=True, vocabulary=[], snippets={}, style="natural", context=scope.text)
    assert b"looking forward" not in replies[-1].body
    replies[-1].complete(200, gemini_text("Discussing the timeline."))
    payload = json.loads(replies[-1].body)["contents"][0]["parts"][0]["text"]
    assert json.loads(payload) == {"before_caret": prefix[-200:], "dictation": "Discussing the timeline."}
    replies[-1].complete(200, gemini_text("discussing the timeline."))
    assert editor.text() == prefix + " discussing the timeline." + suffix
    manager.close()
