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
    assert api.live_key() is None


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
    assert manager._indicator.title.text() == "Transcribing"
    replies[-1].complete(200, gemini_text("Hello, Poppy."))
    replies[-1].complete(200, gemini_text("Hello, Poppy."))
    assert manager.last_text == "Hello, Poppy."
    assert manager._indicator.title.text() == "Copied to clipboard"
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

        def closeReason(self):
            return "API key not valid. Please pass a valid API key."

    monkeypatch.setattr("poppy.core.dictation_live.QWebSocket", Socket)
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
    assert completed == [("First phrase. Second phrase. Last phrase.", "")] and not failures
    live._active = True
    live._message('{"serverContent":{"interimInputTranscription":{"text":"Full sentence."}}}')
    live._message('{"serverContent":{"inputTranscription":{"text":"Full"},"turnComplete":true}}')
    assert completed[-1] == ("Full", "Full sentence.")
    live._active = True
    live._socket.disconnected.emit()
    assert failures == [401]


def test_stream_success_reuses_text_and_failure_uses_full_capture(audit_app, monkeypatch):
    class Mic:
        def read(self):
            return b"\x00\x10" * 3200

        def close(self, *, keep_audio=False):
            return b"\x00\x10" * 800 if keep_audio else b""

    class Live(QObject):
        preview = Signal(str)
        finalized = Signal(str, str)
        failed = Signal(int)

        def start(self, key, vocabulary, *, language_codes):
            self.audio = bytearray()
            self.language_codes = language_codes
            self.key = key

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
    assert b"inlineData" in replies[-1].body and manager._indicator.title.text() == "Checking transcript"
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


def test_pill_keeps_preview_during_language_check_and_respects_reduced_motion(monkeypatch):
    monkeypatch.setattr("poppy.ui.dictation.system_animations_enabled", lambda: False)
    pill = DictationIndicator()
    pill.set_status("Listening", "")
    pill.set_preview("Preview phrase.")
    assert pill.height() == 94 and pill._glow.state() == pill._glow.State.Stopped
    pill.set_status("Checking languages", "")
    assert pill.height() == 94 and pill.preview.text() == "Preview phrase."
    pill.set_status("Copied to clipboard", "")
    assert pill.height() == 54 and pill._check_amount == 1.0
    assert pill._check.state() == pill._check.State.Stopped
    monkeypatch.setattr("poppy.ui.dictation.system_animations_enabled", lambda: True)
    pill.set_status("Listening", "")
    assert pill._glow.state() == pill._glow.State.Running
    pill._glow.setCurrentTime(900)
    assert pill._glow_amount > 0.99
    pill.set_status("Text sent", "")
    assert pill._glow.state() == pill._glow.State.Stopped
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
    assert "Release" in manager._indicator.detail.text()
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
    assert editor.text() == "first middle last" and "Could not edit" in manager._indicator.detail.text()
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
