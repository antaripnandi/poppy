"""Asynchronous city suggestions for the Weather settings field."""

import json
from dataclasses import asdict

from PySide6.QtCore import QRect, QStringListModel, Qt, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QCompleter, QLineEdit

from poppy.core.weather_manager import WeatherLocation, city_search_results, city_search_url
from poppy.ui.theme import set_widget_style


_MAX_REPLY = 64 * 1024


class WeatherLocationEdit(QLineEdit):
    status_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAccessibleName("Weather location")
        self.setPlaceholderText("Search cities")
        self.setFixedWidth(220)
        self._legacy_city = ""
        self._selected = None
        self._matches = {}
        self._reply = None

        self._model = QStringListModel(self)
        self._completer = QCompleter(self._model, self)
        self._completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self._completer.setMaxVisibleItems(6)
        self._completer.setWrapAround(False)
        self.setCompleter(self._completer)
        popup = self._completer.popup()
        popup.setAccessibleName("Matching cities")
        set_widget_style(popup, """
            QListView { background: #1c201e; color: #eef0f0; border: 1px solid #414744; padding: 3px; }
            QListView::item { padding: 5px 8px; }
            QListView::item:selected { background: #36443e; color: #ffffff; }
        """)
        self._completer.activated[str].connect(self._select_match)

        self._network = QNetworkAccessManager(self)
        self._network.finished.connect(self._finish_search)
        self._debounce = QTimer(self, interval=250, singleShot=True)
        self._debounce.timeout.connect(self._search)
        self.textEdited.connect(self._edited)

    def load_location(self, weather):
        self._cancel_search()
        self._matches.clear()
        self._model.setStringList([])
        city = str(weather.get("city") or "").strip()
        location = WeatherLocation.from_data(weather.get("location"))
        self._selected = location if location and location.city == city else None
        self._legacy_city = "" if self._selected else city
        self.setText(self._selected.label if self._selected else city)
        self.status_changed.emit("")

    def selection(self):
        text = self.text().strip()
        if self._selected and text == self._selected.label:
            return {"city": self._selected.city, "location": asdict(self._selected)}
        if not text or text.casefold() == "auto-detect" or text == self._legacy_city:
            return {"city": "Auto-detect" if text.casefold() == "auto-detect" else text, "location": None}
        return None

    def _cancel_search(self):
        self._debounce.stop()
        self._completer.popup().hide()
        if self._reply is not None:
            reply, self._reply = self._reply, None
            reply.abort()

    def _edited(self, text):
        self._cancel_search()
        self._matches.clear()
        self._model.setStringList([])
        self.status_changed.emit("")
        if self.selection() is None and len(text.strip()) >= 2:
            self._debounce.start()

    def _search(self):
        request = QNetworkRequest(QUrl(city_search_url(self.text().strip())))
        request.setTransferTimeout(10000)
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        reply = self._network.get(request)
        self._reply = reply
        reply.setReadBufferSize(_MAX_REPLY + 1)
        reply.readyRead.connect(lambda: reply.abort() if reply.bytesAvailable() > _MAX_REPLY else None)
        self.status_changed.emit("Searching for cities…")

    def _finish_search(self, reply):
        reply.deleteLater()
        if reply is not self._reply:
            return
        self._reply = None
        try:
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            if reply.error() != QNetworkReply.NetworkError.NoError or status != 200 or reply.bytesAvailable() > _MAX_REPLY:
                raise ValueError("City search failed")
            self._matches = city_search_results(json.loads(bytes(reply.readAll())))
        except (ValueError, UnicodeError):
            self.status_changed.emit("Couldn’t load cities. Edit the search to try again.")
            return
        self._model.setStringList(list(self._matches))
        self.status_changed.emit("" if self._matches else "No matching cities. Try a different name.")
        if self._matches and self.hasFocus() and self.isVisible():
            self._show_matches()

    def _show_matches(self):
        width = max(self.fontMetrics().horizontalAdvance(label) for label in self._matches)
        self._completer.setCompletionPrefix("")
        self._completer.complete(QRect(0, 0, max(self.width(), min(450, width + 28)), self.height()))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Down and self._matches and not self._completer.popup().isVisible():
            self._show_matches()
            return
        super().keyPressEvent(event)

    def _select_match(self, label):
        if label in self._matches:
            self._selected = self._matches[label]
            self.setText(label)
            self.status_changed.emit("")
