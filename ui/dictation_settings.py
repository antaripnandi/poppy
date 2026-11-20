"""Voice typing settings. Keys are written only by Settings' Done action."""

import json
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from poppy.core.dictation_api import PROVIDERS, normalize_keys, protect_keys, read_keys, snippets_from_text
from poppy.ui.theme import set_widget_style


class DictationSettings(QWidget):
    def __init__(self, status=None):
        super().__init__()
        self._shortcut_status = status
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 8, 18)
        layout.setSpacing(12)
        title = QLabel("Voice typing")
        set_widget_style(title, "font-size: 21px; font-weight: 600;")
        layout.addWidget(title)
        layout.addWidget(QLabel("Click a text field and press Ctrl+Alt+D to start or finish. Ctrl+Alt+Shift+D cancels."))
        self.enabled = QCheckBox("Enable voice typing")
        self.cleanup = QCheckBox("Clean up fillers, corrections and formatting")
        self.auto_paste = QCheckBox("Paste into the original field when it is still focused")
        for control in (self.enabled, self.cleanup, self.auto_paste):
            layout.addWidget(control)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)

        credentials = QFormLayout()
        self.keys = {}
        for key, name, url in PROVIDERS:
            field = QLineEdit()
            field.setAccessibleName(f"{name} API keys")
            field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setMaxLength(8000)
            field.setPlaceholderText("Separate multiple keys with commas")
            create = QPushButton("Get key")
            create.setAccessibleName(f"Get a {name} key")
            create.clicked.connect(lambda checked=False, link=url: QDesktopServices.openUrl(QUrl(link)))
            row = QHBoxLayout()
            row.addWidget(field, 1)
            row.addWidget(create)
            credentials.addRow(name, row)
            self.keys[key] = field
        layout.addLayout(credentials)
        actions = QHBoxLayout()
        import_button = QPushButton("Import key JSON…")
        import_button.clicked.connect(self._import)
        actions.addWidget(import_button)
        actions.addStretch()
        layout.addLayout(actions)
        privacy = QLabel("Groq or Gemini receives audio. Optional cleanup sends the transcript to the first available "
                         "configured provider. Gemini’s free tier may use prompts and responses to improve its services. "
                         "Poppy encrypts keys with Windows and holds the last dictation in memory for this session.")
        set_widget_style(privacy, "font-size: 11px;")
        layout.addWidget(privacy)

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
            self.status.setText("Could not import. Use a JSON object with groq, gemini and openrouter key arrays (up to 15 keys).")
            return
        self._show_keys(keys)
        self.status.setText(f"{sum(map(len, keys.values()))} keys loaded. Choose Done to save them.")

    def _show_keys(self, keys):
        for provider, field in self.keys.items():
            field.setText(", ".join(keys.get(provider, [])))

    def load(self, config):
        config = config if isinstance(config, dict) else {}
        self.enabled.setChecked(config.get("enabled", False))
        self.cleanup.setChecked(config.get("cleanup", True))
        self.auto_paste.setChecked(config.get("auto_paste", True))
        self._show_keys(read_keys(config))
        self.style.setCurrentIndex(max(0, self.style.findData(config.get("style", "auto"))))
        self.vocabulary.setText(", ".join(config.get("vocabulary", [])))
        self.snippets.setPlainText("\n".join(f"{phrase} = {text}" for phrase, text in config.get("snippets", {}).items()))
        self.status.setText(self._shortcut_status() if self._shortcut_status else "")

    def values(self, previous):
        keys = normalize_keys({name: field.text() for name, field in self.keys.items()})
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
            "cleanup": self.cleanup.isChecked(),
            "auto_paste": self.auto_paste.isChecked(),
            "style": self.style.currentData(),
            "vocabulary": [word.strip() for word in self.vocabulary.text().split(",") if word.strip()],
            "snippets": snippets_from_text(text),
            "protected_keys": protected,
        }
