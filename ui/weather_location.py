"""Asynchronous city suggestions for the Weather settings field."""

import json
from dataclasses import asdict

from PySide6.QtCore import QRect, QStringListModel, Qt, QThreadPool, QTimer, QUrl, Signal, Slot
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QCompleter, QLineEdit

from poppy.core.weather_cities import city_key, local_city_search
from poppy.core.weather_manager import WeatherLocation, city_search_results, city_search_url
from poppy.ui.theme import set_widget_style


_MAX_REPLY = 64 * 1024


class WeatherLocationEdit(QLineEdit):
    status_changed = Signal(str)
    _local_results = Signal(int, str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAccessibleName("Weather location")
        self.setPlaceholderText("Search cities")
        self.setFixedWidth(220)
        self._legacy_city = ""
        self._selected = None
        self._matches = {}
        self._reply = None
        self._search_id = 0

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
        self._local_results.connect(self._finish_local_search)
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
        self._search_id += 1
        self._debounce.stop()
        self._completer.popup().hide()
        if self._reply is not None:
            reply, self._reply = self._reply, None
            reply.abort()

    def _edited(self, text):
        self._cancel_search()
        self._legacy_city = ""
        self._matches.clear()
        self._model.setStringList([])
        self.status_changed.emit("")
        if self.selection() is None and len(text.strip()) >= 2:
            self._debounce.start()

    def _search(self):
        query = self.text().strip()
        search_id = self._search_id

        def lookup():
            matches = local_city_search(query)
            try:
                self._local_results.emit(search_id, query, matches)
            except RuntimeError:
                pass  # Settings closed before the search finished.

        QThreadPool.globalInstance().start(lookup)

    @Slot(int, str, object)
    def _finish_local_search(self, search_id, query, matches):
        if search_id != self._search_id:
            return
        self._set_matches(matches)
        prefix = city_key(query.partition(",")[0])
        if any(city_key(location.city).startswith(prefix) for location in self._matches.values()):
            return
        request = QNetworkRequest(QUrl(city_search_url(query)))
        request.setTransferTimeout(10000)
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        reply = self._network.get(request)
        self._reply = reply
        reply.setReadBufferSize(_MAX_REPLY + 1)
        reply.readyRead.connect(lambda: reply.abort() if reply.bytesAvailable() > _MAX_REPLY else None)
        if not self._matches:
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
            matches = city_search_results(json.loads(bytes(reply.readAll())))
        except (ValueError, UnicodeError):
            if not self._matches:
                self.status_changed.emit("Couldn’t load cities. Edit the search to try again.")
            return
        if matches or not self._matches:
            self._set_matches(matches)
            if not self._matches:
                self.status_changed.emit("No matching cities. Try a different name.")

    def _set_matches(self, matches):
        self._matches = matches
        self._model.setStringList(list(self._matches))
        if self._matches:
            self.status_changed.emit("")
            self._show_matches()

    def _show_matches(self):
        if not self._matches or not self.hasFocus() or not self.isVisible() or self.selection() is not None:
            return
        width = max(self.fontMetrics().horizontalAdvance(label) for label in self._matches)
        self._completer.setCompletionPrefix("")
        self._completer.complete(QRect(0, 0, max(self.width(), min(450, width + 28)), self.height()))

    def keyPressEvent(self, event):
        if (event.key() == Qt.Key.Key_Down and self._matches and self.selection() is None
                and not self._completer.popup().isVisible()):
            self._show_matches()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        QTimer.singleShot(0, self, self._show_matches)

    def _select_match(self, label):
        if label in self._matches:
            self._selected = self._matches[label]
            self.setText(label)
            self._cancel_search()
            self.status_changed.emit("")
