"""
Poppy Drop Shelf & App Pinning Manager
Dropover / Yoink style drag-and-drop staging shelf and quick app shortcuts.
"""

import os
import json
from pathlib import Path
from datetime import datetime
from PySide6.QtCore import QObject, Signal, QUrl, QMimeData, Qt, QFileInfo
from PySide6.QtGui import QDrag, QPixmap
from PySide6.QtWidgets import QFileIconProvider


class StagedItem:
    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self.name = Path(path).name
        self.is_dir = os.path.isdir(path)
        self.is_app = path.lower().endswith((".exe", ".lnk", ".bat", ".cmd"))
        self.is_image = path.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"))
        self.icon = None
        self.thumbnail = None
        try:
            self.size_bytes = os.path.getsize(path) if (os.path.exists(path) and not self.is_dir) else 0
            self.created_at = datetime.fromtimestamp(os.path.getmtime(path)) if os.path.exists(path) else datetime.now()
        except (OSError, PermissionError):
            self.size_bytes = 0
            self.created_at = datetime.now()


class DropShelfManager(QObject):
    shelf_updated = Signal()
    pinned_updated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.staged_items: list[StagedItem] = []
        self.pinned_apps: list[str] = []
        self._icon_provider = QFileIconProvider()
        self._state_file = Path(os.path.expanduser("~/.poppy/shelf_state.json"))
        self._load_state()

    def _save_state(self):
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "staged_paths": [item.path for item in self.staged_items if os.path.exists(item.path)],
                "pinned_apps": [p for p in self.pinned_apps if os.path.exists(p)]
            }
            with open(self._state_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _load_state(self):
        try:
            if not self._state_file.exists():
                return
            with open(self._state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            staged = data.get("staged_paths", [])
            pinned = data.get("pinned_apps", [])
            for p in pinned:
                if os.path.exists(p) and p not in self.pinned_apps:
                    self.pinned_apps.append(p)
            for p in staged:
                if os.path.exists(p) and not any(it.path == p for it in self.staged_items):
                    item = StagedItem(p)
                    if item.is_image:
                        item.thumbnail = QPixmap(p)
                    item.icon = self._icon_provider.icon(QFileInfo(p))
                    self.staged_items.append(item)
        except Exception:
            pass

    def add_paths(self, file_paths: list[str]):
        """Stage new files/directories into the shelf or pin apps."""
        changed = False
        for p in file_paths:
            if not os.path.exists(p):
                continue
            # Check if it's an executable/shortcut to prompt pinning or pin automatically
            if p.lower().endswith((".exe", ".lnk")) and p not in self.pinned_apps:
                self.pinned_apps.append(p)
                self.pinned_updated.emit()

            if not any(item.path == p for item in self.staged_items):
                item = StagedItem(p)
                # Cache thumbnail if image, else system file icon
                if item.is_image:
                    item.thumbnail = QPixmap(p)
                item.icon = self._icon_provider.icon(QFileInfo(p))
                self.staged_items.append(item)
                changed = True

        if changed:
            self._save_state()
            self.shelf_updated.emit()

    def remove_item(self, path: str):
        self.staged_items = [it for it in self.staged_items if it.path != path]
        self._save_state()
        self.shelf_updated.emit()

    def clear_shelf(self):
        self.staged_items.clear()
        self._save_state()
        self.shelf_updated.emit()

    def launch_pinned(self, app_path: str):
        """Quick launch pinned app or shortcut."""
        try:
            os.startfile(app_path)
        except Exception as e:
            print(f"[Poppy] Failed to launch {app_path}: {e}")

    def create_drag(self, source_widget, item: StagedItem) -> QDrag:
        """
        Create a native Windows QDrag object with file drop URLs (CF_HDROP).
        Accepts drops on Windows Desktop, Explorer folders, Discord, Slack,
        Photoshop, browsers, etc.
        """
        drag = QDrag(source_widget)
        mime = QMimeData()
        abs_path = os.path.abspath(item.path)
        mime.setUrls([QUrl.fromLocalFile(abs_path)])
        drag.setMimeData(mime)

        if item.thumbnail and not item.thumbnail.isNull():
            scaled = item.thumbnail.scaled(
                52, 52, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            drag.setPixmap(scaled)
            drag.setHotSpot(scaled.rect().center())
        elif item.icon:
            pixmap = item.icon.pixmap(40, 40)
            drag.setPixmap(pixmap)
            drag.setHotSpot(pixmap.rect().center())
        return drag
