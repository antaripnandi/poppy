"""
Poppy Screenshot & Clipboard Capture Watcher
Directly inspired by NotchX ScreenCaptureService & ClipboardService.
Listens for Windows Snipping Tool (Win+Shift+S), PrtScn, and Windows Screenshots directory.
Zero-latency detection with hash debouncing, automatic staging, and chat format preparation.
"""

import os
import hashlib
from datetime import datetime
from PySide6.QtCore import QObject, Signal, QUrl, QMimeData, QFileSystemWatcher, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication


class ScreenshotWatcher(QObject):
    screenshot_captured = Signal(str, QImage)  # file_path, qimage

    def __init__(self, shelf_dir: str = None, parent=None):
        super().__init__(parent)
        self.shelf_dir = shelf_dir or os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "assets", "shelf")
        )
        os.makedirs(self.shelf_dir, exist_ok=True)

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
        cb = QApplication.clipboard()
        cb.dataChanged.connect(self._on_clipboard_data_changed)

        # Watch standard Windows screenshot locations
        possible_dirs = [
            os.path.expanduser(r"~\Pictures\Screenshots"),
            os.path.expanduser(r"~\OneDrive\Pictures\Screenshots"),
        ]
        for d in possible_dirs:
            if os.path.exists(d):
                self._fs_watcher.addPath(d)

    def stop(self):
        try:
            cb = QApplication.clipboard()
            cb.dataChanged.disconnect(self._on_clipboard_data_changed)
        except Exception:
            pass

    def _on_clipboard_data_changed(self):
        if self._ignore_clipboard:
            return
        # Debounce to allow clipboard writer to finish
        self._debounce_timer.start()

    def _process_clipboard(self):
        if self._ignore_clipboard:
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
            self._last_image_hash = img_hash

            # Save the captured screenshot to Poppy's shelf directory
            stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            file_name = f"Screenshot_{stamp}.png"
            file_path = os.path.join(self.shelf_dir, file_name)

            saved = img.save(file_path, "PNG")
            if saved:
                self.screenshot_captured.emit(file_path, img)
        except Exception as e:
            print(f"[Poppy ScreenshotWatcher] Error reading clipboard image: {e}")

    def _on_screenshots_dir_changed(self, dir_path: str):
        """Handle new files written directly to Pictures/Screenshots (e.g. Win+PrtScn)."""
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
                        self._last_image_hash = img_hash
                        # Copy to shelf folder for quick access
                        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                        file_name = f"Screenshot_{stamp}.png"
                        file_path = os.path.join(self.shelf_dir, file_name)
                        img.save(file_path, "PNG")
                        self.screenshot_captured.emit(file_path, img)
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
            mime.setUrls([QUrl.fromLocalFile(file_path)])
            cb.setMimeData(mime)

            # Re-enable clipboard watching after 1 second
            QTimer.singleShot(1000, self._reset_ignore_flag)
            return True
        except Exception as e:
            self._ignore_clipboard = False
            print(f"[Poppy ScreenshotWatcher] Copy for chat failed: {e}")
            return False

    def _reset_ignore_flag(self):
        self._ignore_clipboard = False

