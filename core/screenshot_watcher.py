"""Stage screenshots from the clipboard and Windows Screenshots folders."""

import os
import hashlib
import threading
import uuid
from datetime import datetime
from PySide6.QtCore import QObject, Signal, QUrl, QMimeData, QFileSystemWatcher, QTimer, QSaveFile, QIODevice
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from poppy.core.storage import data_dir
from poppy.core.system_features import clipboard_allows_history


class ScreenshotWatcher(QObject):
    screenshot_captured = Signal(str, QImage)  # file_path, qimage
    _capture_saved = Signal(str, QImage, int)

    def __init__(self, shelf_dir: str = None, parent=None):
        super().__init__(parent)
        self.shelf_dir = shelf_dir or str(data_dir() / "captures")
        os.makedirs(self.shelf_dir, exist_ok=True)

        self.enabled: bool = False
        self._started = False
        self.protected_paths = lambda: set()
        self._last_image_hash = None
        self._ignore_clipboard: bool = False
        self._capture_lock = threading.Lock()
        self._generation = 0
        self._pending = {}
        self._worker_running = False
        self._capture_saved.connect(self._deliver_capture)

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
        with self._capture_lock:
            self._generation += 1
            self._pending.clear()
            self._last_image_hash = None
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

        if mime is None or not mime.hasImage():
            return

        try:
            img = cb.image()
            if not img.isNull() and img.width() >= 16 and img.height() >= 16:
                self._enqueue_capture("clipboard", img)
        except Exception as e:
            print(f"[Poppy ScreenshotWatcher] Error reading clipboard image: {e}")

    def _on_screenshots_dir_changed(self, dir_path: str):
        """Handle new files written directly to Pictures/Screenshots (e.g. Win+PrtScn)."""
        if self.enabled:
            self._enqueue_capture(dir_path, datetime.now().timestamp())

    def _enqueue_capture(self, source, value):
        with self._capture_lock:
            # Bursts replace pending work for the same clipboard or folder.
            self._pending[source] = value
            if not self._worker_running:
                self._worker_running = True
                threading.Thread(target=self._process_pending, daemon=True, name="poppy-captures").start()

    def _process_pending(self):
        while True:
            with self._capture_lock:
                if not self._pending:
                    self._worker_running = False
                    return
                source = next(iter(self._pending))
                value = self._pending.pop(source)
                generation = self._generation
            try:
                image = value if source == "clipboard" else self._read_recent_capture(source, value)
                if image.isNull():
                    continue
                digest = self._image_hash(image)
                with self._capture_lock:
                    if generation != self._generation or digest == self._last_image_hash:
                        continue
                path = self._save_image(image)
                with self._capture_lock:
                    current = generation == self._generation
                    if current:
                        self._last_image_hash = digest
                if current:
                    try:
                        self._capture_saved.emit(path, image, generation)
                        continue
                    except RuntimeError:
                        pass  # The watcher closed while the image was encoding.
                self._discard_capture(path)
            except (OSError, RuntimeError) as error:
                print(f"[Poppy ScreenshotWatcher] Capture failed: {error}")

    @staticmethod
    def _read_recent_capture(folder, changed_at):
        latest = None
        with os.scandir(folder) as files:
            for entry in files:
                if entry.name.lower().endswith((".png", ".jpg", ".jpeg")) and entry.is_file():
                    modified = entry.stat().st_mtime
                    if changed_at - modified < 3.0 and (latest is None or modified > latest[0]):
                        latest = modified, entry.path
        return QImage(latest[1]) if latest else QImage()

    @staticmethod
    def _image_hash(image):
        return image.width(), image.height(), image.format(), hashlib.md5(image.constBits()).digest()

    @staticmethod
    def _discard_capture(path):
        try:
            os.remove(path)
        except OSError:
            pass

    def _deliver_capture(self, path, image, generation):
        if not self.enabled or generation != self._generation:
            self._discard_capture(path)
            return
        self.screenshot_captured.emit(path, image)
        self._clean_shelf_cap()

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
                digest = self._image_hash(img)
                with self._capture_lock:
                    self._last_image_hash = digest
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
