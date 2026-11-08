"""Read-only activity for the folder Poppy is watching."""

from PySide6.QtCore import QLocale, QSize, Qt
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QMenu, QPushButton, QVBoxLayout, QWidget, QWidgetAction

from poppy.ui.theme import set_widget_style


class DownloadActivityMenu(QMenu):
    def __init__(self, watcher, open_folder, parent):
        super().__init__(parent)
        self.watcher = watcher
        panel = QWidget()
        panel.setFixedWidth(330)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        title = QLabel("Downloads")
        set_widget_style(title, "font-size: 14px; font-weight: 600;")
        layout.addWidget(title)
        self.items = QListWidget()
        self.items.setAccessibleName("Download activity")
        self.items.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.items.setWordWrap(True)
        self.items.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.items.setFixedHeight(120)
        set_widget_style(self.items, """
            QListWidget { background: #242829; color: #edf0f0; border: none; border-radius: 6px; }
            QListWidget::item { padding: 4px 8px; }
            QScrollBar::corner { background: transparent; }
        """)
        layout.addWidget(self.items)
        self._open_folder = open_folder
        button = QPushButton("Open download folder")
        button.clicked.connect(self._open_watched_folder)
        layout.addWidget(button)
        action = QWidgetAction(self)
        action.setDefaultWidget(panel)
        self.addAction(action)
        watcher.activity_changed.connect(self._refresh_visible)
        self.aboutToShow.connect(self.refresh)

    def _refresh_visible(self):
        if self.isVisible():
            self.refresh()

    def _open_watched_folder(self):
        self.hide()
        self._open_folder()

    def refresh(self):
        locale = QLocale()
        rows = [(name, f"Partial file · {locale.formattedDataSize(size)}")
                for name, size in self.watcher.partials]
        rows.extend((path.name, "Ready") for path in self.watcher.recent)
        if not rows:
            rows.append(("No new files in this session.", ""))
        while self.items.count() > len(rows):
            self.items.takeItem(self.items.count() - 1)
        for index, (name, status) in enumerate(rows):
            item = self.items.item(index)
            if item is None:
                item = QListWidgetItem(self.items)
            item.setText(f"{name}\n{status}" if status else name)
            item.setSizeHint(QSize(0, 40))
