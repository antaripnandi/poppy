"""Voice typing settings. Keys are written only by Settings' Done action."""

import json
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from poppy.core.dictation_api import (DictationKeyCheck, PROVIDERS, SPEECH_LANGUAGES, normalize_keys,
                                     protect_keys, read_keys, snippets_from_text)
from poppy.ui.components import SettingRow, ToggleSwitch
from poppy.ui.theme import set_widget_style


class DictationSettings(QWidget):
    def __init__(self, status=None):
        super().__init__()
        self._shortcut_status = status
        self._checker = DictationKeyCheck(self)
        self._checker.updated.connect(self._key_result)
        self._checker.finished.connect(self._check_finished)
        self._results = {}
        self._counts = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 8, 18)
        layout.setSpacing(9)
        title = QLabel("Voice typing")
        set_widget_style(title, "font-size: 21px; font-weight: 600;")
        layout.addWidget(title)
        self.enabled = ToggleSwitch()
        self.enabled.setAccessibleName("Enable voice typing")
        layout.addWidget(SettingRow("Use voice typing", "Use the mic in the drawer or press Ctrl+Alt+D.", self.enabled))
        self.hold_to_talk = ToggleSwitch()
        layout.addWidget(SettingRow("Hold to talk", "Hold Ctrl+Alt+Space to record. Release to finish.", self.hold_to_talk))
        self.voice_editing = ToggleSwitch()
        layout.addWidget(SettingRow("Edit Mode", "Select text and press Ctrl+Alt+Shift+E. Repeat to finish.", self.voice_editing))
        self.shortcut = QLabel()
        self.shortcut.setTextFormat(Qt.TextFormat.PlainText)
        set_widget_style(self.shortcut, "color: #9ca3a5; font-size: 11px;")
        layout.addWidget(self.shortcut)

        heading = QLabel("API keys")
        set_widget_style(heading, "font-size: 14px; font-weight: 600;")
        layout.addSpacing(8)
        layout.addWidget(heading)
        credentials = QGridLayout()
        credentials.setHorizontalSpacing(10)
        credentials.setVerticalSpacing(6)
        credentials.setColumnStretch(1, 1)
        self.keys = {}
        self._key_rows = {}
        for index, (key, name, url) in enumerate(PROVIDERS):
            field = QLineEdit()
            field.setAccessibleName(f"{name} API keys")
            field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setMaxLength(8000)
            field.setPlaceholderText("Separate multiple keys with commas")
            create = QPushButton("Get key")
            create.setAccessibleName(f"Get a {name} key")
            create.clicked.connect(lambda checked=False, link=url: QDesktopServices.openUrl(QUrl(link)))
            summary = QLabel()
            summary.setTextFormat(Qt.TextFormat.PlainText)
            set_widget_style(summary, "color: #a7afaf;")
            stack = QStackedWidget()
            stack.addWidget(summary)
            stack.addWidget(field)
            edit = QPushButton("Edit")
            edit.setAccessibleName(f"Edit {name} keys")
            edit.clicked.connect(lambda _, provider=key: self._edit(provider))
            field.textChanged.connect(lambda _, provider=key: self._edited(provider))
            field.returnPressed.connect(lambda provider=key: self._edit(provider))
            credentials.addWidget(QLabel(name), index, 0)
            credentials.addWidget(stack, index, 1)
            credentials.addWidget(edit, index, 2)
            credentials.addWidget(create, index, 3)
            self.keys[key] = field
            self._key_rows[key] = (summary, stack, edit)
        layout.addLayout(credentials)
        actions = QHBoxLayout()
        self.check_button = QPushButton("Check keys")
        self.check_button.clicked.connect(self._check)
        import_button = QPushButton("Import JSON…")
        import_button.clicked.connect(self._import)
        actions.addWidget(self.check_button)
        actions.addWidget(import_button)
        actions.addStretch()
        layout.addLayout(actions)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.hide()
        layout.addWidget(self.status)
        privacy = QLabel("Windows encrypts saved keys. Groq or Gemini receives audio, and Gemini’s free tier may use it "
                         "to improve its services. Cleanup and Roman spelling can also send text to OpenRouter. "
                         "Edit Mode sends the selection and spoken instruction to the editing provider.")
        privacy.setWordWrap(True)
        set_widget_style(privacy, "font-size: 11px; color: #a7afaf;")
        layout.addWidget(privacy)

        layout.addSpacing(8)
        heading = QLabel("Text output")
        set_widget_style(heading, "font-size: 14px; font-weight: 600;")
        layout.addWidget(heading)
        self.languages = QComboBox()
        for value, (label, _) in SPEECH_LANGUAGES.items():
            self.languages.addItem(label, value)
        layout.addWidget(SettingRow("Speech languages", "Choose Mixed languages if you switch languages mid-recording.",
                                    self.languages))
        self.output_script = QComboBox()
        self.output_script.addItem("Original scripts", "original")
        self.output_script.addItem("Roman letters", "roman")
        layout.addWidget(SettingRow("Writing system", "Use Roman letters in the final text, like ‘abe’ or ‘ami’.",
                                    self.output_script))
        self.cleanup = ToggleSwitch()
        self.cleanup.setAccessibleName("Clean up dictation")
        self.auto_paste = ToggleSwitch()
        self.auto_paste.setAccessibleName("Paste into the original field")
        self.streaming = ToggleSwitch()
        self.streaming.setAccessibleName("Show live transcription")
        self.continuation_context = ToggleSwitch()
        layout.addWidget(SettingRow("Live transcript", "Show words while you speak. Gemini streams audio during recording.", self.streaming))
        layout.addWidget(SettingRow("Clean up dictation", "Fix punctuation, fillers, and spoken corrections.", self.cleanup))
        layout.addWidget(SettingRow("Continuation context", "Send up to 200 characters before the cursor to the cleanup provider.",
                                    self.continuation_context))
        layout.addWidget(SettingRow("Paste into the original field", "Copy to the clipboard when there’s no editable target.", self.auto_paste))

        form = QFormLayout()
        self.style = QComboBox()
        for label, value in (("Match active app", "auto"), ("Natural", "natural"), ("Casual", "casual"),
                             ("Technical", "technical"), ("Professional", "professional")):
            self.style.addItem(label, value)
        self.style.setAccessibleName("Dictation cleanup style")
        self.vocabulary = QLineEdit()
        self.vocabulary.setAccessibleName("Dictation dictionary")
        self.vocabulary.setPlaceholderText("Names and terms, separated by commas")
        self.vocabulary.setMaxLength(1000)
        self.snippets = QPlainTextEdit()
        self.snippets.setAccessibleName("Dictation snippets")
        self.snippets.setPlaceholderText("One per line, such as: my website = https://example.com")
        self.snippets.setFixedHeight(75)
        form.addRow("Cleanup style", self.style)
        form.addRow("Dictionary", self.vocabulary)
        form.addRow("Snippets", self.snippets)
        layout.addLayout(form)
        layout.addStretch()

    def hideEvent(self, event):
        self._stop_check()
        super().hideEvent(event)

    def _message(self, text):
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def show_error(self, text):
        self._message(text)

    def _edit(self, provider):
        _, stack, button = self._key_rows[provider]
        editing = stack.currentIndex() == 0
        stack.setCurrentIndex(int(editing))
        button.setText("Hide" if editing else "Edit")
        if editing:
            self.keys[provider].setFocus()
        else:
            button.setFocus()

    def _edited(self, provider):
        self._stop_check()
        self._results.pop(provider, None)
        self._summary(provider)
        self._message("")

    def _summary(self, provider):
        label, _, _ = self._key_rows[provider]
        try:
            total = len(normalize_keys({provider: self.keys[provider].text()}).get(provider, []))
        except ValueError:
            label.setText("Check key format")
            label.setToolTip("")
            return
        results = self._results.get(provider, {})
        if results:
            accepted = sum(status == "Accepted" for status in results.values())
            if len(results) < total:
                text = f"Checking {len(results)}/{total}"
            elif accepted == total:
                text = f"{accepted}/{total} accepted"
            else:
                issues = ", ".join(f"#{slot}" for slot, status in sorted(results.items()) if status != "Accepted")
                text = f"{accepted}/{total} accepted · Check {issues}"
                text = label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, max(140, label.width()))
            label.setText(text)
            label.setToolTip("\n".join(f"Key {slot} · {status}" for slot, status in sorted(results.items())))
            label.setAccessibleDescription(label.toolTip())
        else:
            label.setText("Add a key" if not total else f"{total} key{'s' if total != 1 else ''}")
            label.setToolTip("")
            label.setAccessibleDescription("")

    def _stop_check(self):
        if self.check_button.isEnabled():
            return
        self._checker.cancel()
        self.check_button.setEnabled(True)
        self.check_button.setText("Check keys")
        self._message("")
        self._results.clear()
        for provider in self.keys:
            self._summary(provider)

    def _check(self):
        try:
            keys = self._current_keys()
        except ValueError as error:
            self._message(str(error))
            return
        if not keys:
            self._message("Add or import a key to check.")
            return
        self._counts = {provider: len(pool) for provider, pool in keys.items()}
        self._results.clear()
        for provider in self.keys:
            self._summary(provider)
        self.check_button.setEnabled(False)
        self.check_button.setText("Checking…")
        self._message(f"Checking {sum(self._counts.values())} keys with their providers…")
        self._checker.start(keys)

    def _key_result(self, provider, slot, result):
        self._results.setdefault(provider, {})[slot] = result
        self._summary(provider)

    def _check_finished(self):
        accepted = sum(status == "Accepted" for results in self._results.values() for status in results.values())
        self._message(f"{accepted} of {sum(self._counts.values())} keys accepted. Hover over a provider’s result for details.")
        self.check_button.setEnabled(True)
        self.check_button.setText("Check keys")

    def _import(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Import voice typing keys", "", "JSON files (*.json)")
        if not filename:
            return
        try:
            with Path(filename).open("rb") as file:
                raw = file.read(24 * 1024 + 1)
            if len(raw) > 24 * 1024:
                raise ValueError()
            keys = normalize_keys(json.loads(raw))
        except (OSError, ValueError):
            self._message("Use a JSON file with groq, gemini and openrouter key arrays (up to 15 keys).")
            return
        self._show_keys(keys)
        self._message(f"{sum(map(len, keys.values()))} keys loaded. Choose Done to save them.")

    def _show_keys(self, keys):
        for provider, field in self.keys.items():
            field.setText(", ".join(keys.get(provider, [])))
            _, stack, button = self._key_rows[provider]
            stack.setCurrentIndex(0)
            button.setText("Edit")
            self._summary(provider)

    def load(self, config):
        config = config if isinstance(config, dict) else {}
        self.enabled.setChecked(config.get("enabled", False))
        self.hold_to_talk.setChecked(config.get("hold_to_talk", True))
        self.voice_editing.setChecked(config.get("voice_editing", True))
        self.continuation_context.setChecked(config.get("continuation_context", False))
        self.cleanup.setChecked(config.get("cleanup", True))
        self.auto_paste.setChecked(config.get("auto_paste", True))
        self.streaming.setChecked(config.get("streaming", True))
        self.languages.setCurrentIndex(max(0, self.languages.findData(config.get("speech_languages"))))
        self.output_script.setCurrentIndex(max(0, self.output_script.findData(config.get("output_script"))))
        self._show_keys(read_keys(config))
        self.style.setCurrentIndex(max(0, self.style.findData(config.get("style", "auto"))))
        self.vocabulary.setText(", ".join(config.get("vocabulary", [])))
        self.snippets.setPlainText("\n".join(f"{phrase} = {text}" for phrase, text in config.get("snippets", {}).items()))
        status = self._shortcut_status() if self._shortcut_status else ""
        self.shortcut.setText("" if status in ("Ctrl+Alt+D is active.", "Voice typing is off.") else status)
        self.shortcut.setVisible(bool(self.shortcut.text()))
        self._message("")

    def _current_keys(self):
        return normalize_keys({name: field.text() for name, field in self.keys.items()})

    def values(self, previous):
        keys = self._current_keys()
        if self.enabled.isChecked() and not (keys.get("groq") or keys.get("gemini")):
            raise ValueError("Add a Groq or Gemini key to enable voice typing.")
        text = self.snippets.toPlainText()
        if len(text) > 8000:
            raise ValueError("Keep snippets under 8,000 characters total.")
        # Retain the existing encrypted bytes when other settings are saved.
        protected = (previous.get("protected_keys", "") if keys == read_keys(previous)
                     else protect_keys(keys))
        return {
            "enabled": self.enabled.isChecked(),
            "hold_to_talk": self.hold_to_talk.isChecked(),
            "voice_editing": self.voice_editing.isChecked(),
            "continuation_context": self.continuation_context.isChecked(),
            "cleanup": self.cleanup.isChecked(),
            "auto_paste": self.auto_paste.isChecked(),
            "streaming": self.streaming.isChecked(),
            "speech_languages": self.languages.currentData(),
            "output_script": self.output_script.currentData(),
            "style": self.style.currentData(),
            "vocabulary": [word.strip() for word in self.vocabulary.text().split(",") if word.strip()],
            "snippets": snippets_from_text(text),
            "protected_keys": protected,
        }
