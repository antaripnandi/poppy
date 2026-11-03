"""
Poppy Screenshot & Clipboard Capture Watcher
Directly inspired by NotchX ScreenCaptureService & ClipboardService.
Listens for Windows Snipping Tool (Win+Shift+S), PrtScn, and Windows Screenshots directory.
Zero-latency detection with hash debouncing, automatic staging, and chat format preparation.
"""

import os
import hashlib
import uuid
from datetime import datetime
from PySide6.QtCore import QObject, Signal, QUrl, QMimeData, QFileSystemWatcher, QTimer, QSaveFile, QIODevice
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from poppy.core.storage import data_dir
from poppy.core.system_features import clipboard_allows_history


class ScreenshotWatcher(QObject):
    screenshot_captured = Signal(str, QImage)  # file_path, qimage

    def __init__(self, shelf_dir: str = None, parent=None):
        super().__init__(parent)
        self.shelf_dir = shelf_dir or str(data_dir() / "captures")
        os.makedirs(self.shelf_dir, exist_ok=True)

        self.enabled: bool = False
        self._started = False
        self.protected_paths = lambda: set()
        self._last_image_hash: str | None = None
        self._ignore_clipboard: bool = False
        self._last_capture_time: float = 0.0

        # Debounce timer for clipboard changes (Windows apps sometimes write multi-pass)
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(100)
        self._debounce_timer.timeout.connect(self._process_clipboard)

        # File system watcher for Windows Pictures/Screenshots
        self._fs_watcher = QFileSystemWatcher(self)
        self._fs_watcher.directoryChanged.connect(self._on_screenshots_dir_changed)

    def start(self):
        """Connect clipboard and screenshot directory listeners."""
        if self._started:
            return
        cb = QApplication.clipboard()
        cb.dataChanged.connect(self._on_clipboard_data_changed)
        self._started = True

        # Watch standard Windows screenshot locations
        possible_dirs = [
            os.path.expanduser(r"~\Pictures\Screenshots"),
            os.path.expanduser(r"~\OneDrive\Pictures\Screenshots"),
        ]
        for d in possible_dirs:
            if os.path.exists(d):
                self._fs_watcher.addPath(d)

    def stop(self):
        self._debounce_timer.stop()
        if self._started:
            QApplication.clipboard().dataChanged.disconnect(self._on_clipboard_data_changed)
            self._started = False
        paths = self._fs_watcher.directories()
        if paths:
            self._fs_watcher.removePaths(paths)

    def _clean_shelf_cap(self, max_items: int = 50):
        """Keep shelf storage bounded to prevent disk bloat."""
        try:
            if not os.path.exists(self.shelf_dir):
                return
            protected = {os.path.normcase(os.path.abspath(p)) for p in self.protected_paths()}
            files = [
                os.path.join(self.shelf_dir, f)
                for f in os.listdir(self.shelf_dir)
                if f.startswith("Screenshot_") and f.endswith(".png")
                and os.path.isfile(os.path.join(self.shelf_dir, f))
                and os.path.normcase(os.path.abspath(os.path.join(self.shelf_dir, f))) not in protected
            ]
            if len(files) > max_items:
                files.sort(key=os.path.getmtime)
                to_delete = files[:len(files) - max_items]
                for f in to_delete:
                    try:
                        os.remove(f)
                    except Exception:
                        pass
        except Exception:
            pass

    def _on_clipboard_data_changed(self):
        if not self.enabled or self._ignore_clipboard:
            return
        # Debounce to allow clipboard writer to finish
        self._debounce_timer.start()

    def _process_clipboard(self):
        if not self.enabled or self._ignore_clipboard:
            return
        if not clipboard_allows_history():
            return

        cb = QApplication.clipboard()
        mime = cb.mimeData()

        # Check if clipboard has image data
        if not mime.hasImage():
            return

        try:
            img = cb.image()
            if img.isNull() or img.width() < 16 or img.height() < 16:
                return

            # Compute pixel hash to avoid duplicate events
            bits = img.bits()
            img_hash = hashlib.md5(bytes(bits)).hexdigest()
            if img_hash == self._last_image_hash:
                return
            file_path = self._save_image(img)
            self._last_image_hash = img_hash
            self.screenshot_captured.emit(file_path, img)
            self._clean_shelf_cap()
        except Exception as e:
            print(f"[Poppy ScreenshotWatcher] Error reading clipboard image: {e}")

    def _on_screenshots_dir_changed(self, dir_path: str):
        """Handle new files written directly to Pictures/Screenshots (e.g. Win+PrtScn)."""
        if not self.enabled:
            return
        try:
            if not os.path.exists(dir_path):
                return
            files = [
                os.path.join(dir_path, f)
                for f in os.listdir(dir_path)
                if f.lower().endswith((".png", ".jpg", ".jpeg"))
            ]
            if not files:
                return
            latest_file = max(files, key=os.path.getmtime)
            # Only trigger if modified within the last 3 seconds
            if datetime.now().timestamp() - os.path.getmtime(latest_file) < 3.0:
                img = QImage(latest_file)
                if not img.isNull():
                    bits = img.bits()
                    img_hash = hashlib.md5(bytes(bits)).hexdigest()
                    if img_hash != self._last_image_hash:
                        file_path = self._save_image(img)
                        self._last_image_hash = img_hash
                        self.screenshot_captured.emit(file_path, img)
                        self._clean_shelf_cap()
        except Exception as e:
            print(f"[Poppy ScreenshotWatcher] Dir watcher error: {e}")

    def copy_image_for_chat(self, file_path: str) -> bool:
        """
        Formats image on clipboard specifically for pasting into chat apps
        (Discord, Slack, WhatsApp, Teams, ChatGPT, Browser, etc.).
        Sets both raw image bitmap and file URLs so every application accepts it.
        """
        if not os.path.exists(file_path):
            return False

        try:
            self._ignore_clipboard = True
            cb = QApplication.clipboard()
            mime = QMimeData()
            img = QImage(file_path)
            if not img.isNull():
                mime.setImageData(img)
                self._last_image_hash = hashlib.md5(bytes(img.bits())).hexdigest()
            mime.setUrls([QUrl.fromLocalFile(file_path)])
            cb.setMimeData(mime)

            return True
        except Exception as e:
            self._ignore_clipboard = False
            print(f"[Poppy ScreenshotWatcher] Copy for chat failed: {e}")
            return False
        finally:
            self._ignore_clipboard = False

    def _save_image(self, image: QImage) -> str:
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = os.path.join(self.shelf_dir, f"Screenshot_{stamp}_{uuid.uuid4().hex}.png")
        output = QSaveFile(path)
        if not output.open(QIODevice.OpenModeFlag.WriteOnly):
            raise OSError(output.errorString())
        if not image.save(output, "PNG"):
            output.cancelWriting()
            raise OSError("The image could not be encoded.")
        if not output.commit():
            raise OSError(output.errorString())
        return path

    def _reset_ignore_flag(self):
        self._ignore_clipboard = False
