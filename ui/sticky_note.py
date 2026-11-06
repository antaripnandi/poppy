"""
Poppy Detachable Floating Sticky Notes
Independent on-screen floating sticky notes inspired by macOS Quick Notes and Windows Sticky Notes.
Features native OS hardware-accelerated window dragging (startSystemMove), corner resizing (QSizeGrip),
pin-to-top toggle, multi-color themes (Charcoal, Pastel Yellow, Mint, Lavender, Amber),
and persistent on-screen presence across desktops.
"""

import json
import uuid

from PySide6.QtCore import Qt, QPoint, Signal, QSize, QTimer, QRectF
from PySide6.QtGui import QColor, QFont, QPixmap, QPainter, QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLabel, QPushButton,
    QSizeGrip, QFrame, QApplication
)

from poppy.ui.theme import set_widget_style
from poppy.ui.components import IconButton
from poppy.ui.icons import Icons
from poppy.core.storage import data_dir, write_json

NOTE_THEMES = {
    "charcoal": {
        "name": "Charcoal",
        "bg": "#1c201e",
        "header_bg": "#1c201e",
        "text": "#f1f5f9",
        "border": "rgba(255, 255, 255, 0.12)",
        "accent": "#476351",
        "btn_hover": "rgba(255, 255, 255, 0.1)",
    },
    "yellow": {
        "name": "Pastel Yellow",
        "bg": "#fef9c3",
        "header_bg": "#fef08a",
        "text": "#1c1917",
        "border": "rgba(161, 98, 7, 0.25)",
        "accent": "#ca8a04",
        "btn_hover": "rgba(0, 0, 0, 0.08)",
    },
    "mint": {
        "name": "Mint Green",
        "bg": "#dcfce7",
        "header_bg": "#bbf7d0",
        "text": "#064e3b",
        "border": "rgba(21, 128, 61, 0.25)",
        "accent": "#16a34a",
        "btn_hover": "rgba(0, 0, 0, 0.08)",
    },
    "lavender": {
        "name": "Lavender",
        "bg": "#f3e8ff",
        "header_bg": "#e9d5ff",
        "text": "#3b0764",
        "border": "rgba(126, 34, 206, 0.25)",
        "accent": "#9333ea",
        "btn_hover": "rgba(0, 0, 0, 0.08)",
    },
    "amber": {
        "name": "Amber",
        "bg": "#ffedd5",
        "header_bg": "#fed7aa",
        "text": "#431407",
        "border": "rgba(194, 65, 12, 0.25)",
        "accent": "#ea580c",
        "btn_hover": "rgba(0, 0, 0, 0.08)",
    },
}


class NoteTitleBar(QWidget):
    """
    Dedicated draggable title bar.
    Uses windowHandle().startSystemMove() for 100% native stutter-free Windows OS dragging.
    """
    def __init__(self, parent_note):
        super().__init__(parent_note)
        self.note = parent_note
        self.setFixedHeight(38)
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 6, 0)
        layout.setSpacing(4)

        # Title Label (transparent for mouse events so dragging works anywhere on title bar)
        self.lbl_title = QLabel("Note", self)
        self.lbl_title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        set_widget_style(self.lbl_title, "font-size: 11px; font-weight: 600; background: transparent; border: none;")
        layout.addWidget(self.lbl_title)

        layout.addStretch()

        # Always-on-Top Toggle
        self.btn_pin = IconButton(Icons.PIN, "Always on Top (Toggle)", parent=self, size=22, font_size=10, is_fluent=True)
        self.btn_pin.clicked.connect(self.note.toggle_always_on_top)
        layout.addWidget(self.btn_pin)

        # Theme Cycle Button
        self.btn_theme = IconButton(Icons.COLOR, "Cycle Color Theme", parent=self, size=22, font_size=10, is_fluent=True)
        self.btn_theme.clicked.connect(self.note.cycle_theme)
        layout.addWidget(self.btn_theme)

        # Copy Text Button
        self.btn_copy = IconButton(Icons.COPY, "Copy Note Text", parent=self, size=22, font_size=10, is_fluent=True)
        self.btn_copy.clicked.connect(self.note.copy_text)
        layout.addWidget(self.btn_copy)

        # Close Button
        self.btn_close = IconButton(Icons.CLOSE, "Close Note", parent=self, size=22, font_size=10, is_fluent=True)
        self.btn_close.clicked.connect(self.note.close)
        layout.addWidget(self.btn_close)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.note.windowHandle()
            if handle:
                handle.startSystemMove()
                event.accept()
                return
        super().mousePressEvent(event)


class FloatingStickyNote(QWidget):
    """
    True on-screen floating sticky note window.
    Independent top-level window with native dragging, resizing, and customizable themes.
    """
    closed = Signal(object)

    def __init__(self, initial_text: str = "", theme_name: str = "charcoal", parent=None, note_id: str = None):
        super().__init__(None)  # Top-level window independent of parent
        if note_id is not None and (len(note_id) != 32 or any(c not in "0123456789abcdef" for c in note_id)):
            raise ValueError("Invalid note identity")
        self.note_id = note_id or uuid.uuid4().hex
        self._note_file = data_dir() / "notes" / f"{self.note_id}.json"
        saved = {}
        if self._note_file.exists():
            saved = json.loads(self._note_file.read_text(encoding="utf-8"))
            initial_text = saved.get("text", initial_text)
            theme_name = saved.get("theme", theme_name)
        self.is_pinned = True
        self._current_theme_key = theme_name if theme_name in NOTE_THEMES else "charcoal"

        # Window Flags: True Window that stays on top and is borderless
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMinimumSize(200, 160)
        self.resize(320, 280)

        self._init_ui(initial_text)
        self._apply_theme()
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(600)
        self._save_timer.timeout.connect(self.save_note)
        self.editor.textChanged.connect(self._save_timer.start)
        self._save_timer.start()
        geometry = saved.get("geometry")
        if isinstance(geometry, list) and len(geometry) == 4 and all(isinstance(v, int) for v in geometry):
            self.resize(max(200, geometry[2]), max(160, geometry[3]))
            screen = QGuiApplication.screenAt(QPoint(geometry[0], geometry[1]))
            if screen:
                self.move(geometry[0], geometry[1])

    @staticmethod
    def saved_notes():
        notes = []
        for path in (data_dir() / "notes").glob("*.json"):
            if len(path.stem) != 32 or any(c not in "0123456789abcdef" for c in path.stem):
                continue
            try:
                note = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(note, dict) and isinstance(note.get("text"), str):
                    note["id"] = path.stem
                    notes.append(note)
            except (OSError, ValueError):
                continue
        return notes

    def save_note(self, is_open: bool = True):
        try:
            write_json(self._note_file, {
                "id": self.note_id, "text": self.editor.toPlainText(),
                "theme": self._current_theme_key, "open": is_open,
                "geometry": list(self.geometry().getRect()),
            })
            self._update_footer_stats()
            self.lbl_stats.setToolTip("")
            return True
        except OSError as error:
            self.lbl_stats.setText("Not saved. Close and retry to save.")
            self.lbl_stats.setToolTip(str(error))
            return False

    def _init_ui(self, initial_text: str):
        # Outer layout
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(4, 4, 4, 4)
        outer_layout.setSpacing(0)

        # Styled Container Card
        self.container = QFrame(self)
        self.container.setObjectName("noteContainer")
        card_layout = QVBoxLayout(self.container)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        # 1. Draggable Title Bar
        self.title_bar = NoteTitleBar(self)
        card_layout.addWidget(self.title_bar)

        # 2. Text Editor
        self.editor = QTextEdit(self)
        self.editor.setPlaceholderText("Write a note…")
        self.editor.setAcceptRichText(False)
        self.editor.setAccessibleName("Floating note editor")
        self.editor.setPlainText(initial_text)
        self.editor.textChanged.connect(self._update_footer_stats)
        card_layout.addWidget(self.editor, stretch=1)

        # 3. Footer Bar with Word Count and QSizeGrip for smooth corner resizing
        footer = QHBoxLayout()
        footer.setContentsMargins(10, 2, 4, 4)
        footer.setSpacing(6)

        self.lbl_stats = QLabel("0 words", self)
        set_widget_style(self.lbl_stats, "font-size: 11px; background: transparent; border: none;")
        footer.addWidget(self.lbl_stats)

        footer.addStretch()

        # Native corner resize grip
        self.size_grip = QSizeGrip(self)
        self.size_grip.setFixedSize(16, 16)
        set_widget_style(self.size_grip, "background: transparent;")
        footer.addWidget(self.size_grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)

        card_layout.addLayout(footer)
        outer_layout.addWidget(self.container)

        self._update_footer_stats()

    def _apply_theme(self):
        theme = NOTE_THEMES[self._current_theme_key]
        text_color = theme["text"]
        bg_color = theme["bg"]
        hdr_bg = theme["header_bg"]
        border_color = theme["border"]
        btn_hover = theme["btn_hover"]

        # Container styling
        set_widget_style(self.container, f"""
            QFrame#noteContainer {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 12px;
            }}
        """)

        # Title bar styling
        set_widget_style(self.title_bar, f"""
            QWidget {{
                background-color: {hdr_bg};
                border-top-left-radius: 11px;
                border-top-right-radius: 11px;
                border-bottom: none;
            }}
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
                color: {text_color};
                font-size: 11px;
                padding: 1px;
            }}
            QPushButton:hover {{
                background-color: {btn_hover};
            }}
        """)
        set_widget_style(self.title_bar.lbl_title, f"color: {text_color}; font-size: 11px; font-weight: 600; background: transparent; border: none;")

        # Editor styling
        set_widget_style(self.editor, f"""
            QTextEdit {{
                background-color: transparent;
                border: none;
                color: {text_color};
                font-family: 'Segoe UI';
                font-size: 14px;
                padding: 12px 14px;
                selection-background-color: {theme['accent']};
            }}
        """)
        set_widget_style(self.lbl_stats, f"color: {text_color}; font-size: 11px; background: transparent; border: none;")

    def cycle_theme(self):
        keys = list(NOTE_THEMES.keys())
        idx = (keys.index(self._current_theme_key) + 1) % len(keys)
        self._current_theme_key = keys[idx]
        self._apply_theme()
        self._save_timer.start()

    def toggle_always_on_top(self):
        self.is_pinned = not self.is_pinned
        self.title_bar.btn_pin.setText(Icons.PIN if self.is_pinned else Icons.UNPIN)
        self.title_bar.btn_pin.setToolTip("Always on Top: ON (Click to unpin)" if self.is_pinned else "Always on Top: OFF (Click to pin)")
        try:
            import ctypes
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOACTIVATE = 0x0010
            hwnd = int(self.winId())
            target = HWND_TOPMOST if self.is_pinned else HWND_NOTOPMOST
            ctypes.windll.user32.SetWindowPos(hwnd, target, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        except Exception:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.is_pinned)
            self.show()

    def copy_text(self):
        text = self.editor.toPlainText()
        if text:
            cb = QApplication.clipboard()
            cb.setText(text)
            old_tip = self.title_bar.btn_copy.toolTip()
            self.title_bar.btn_copy.setText(Icons.CHECK)
            QTimer.singleShot(1500, lambda: self._reset_copy_btn(old_tip))

    def _reset_copy_btn(self, old_tip):
        self.title_bar.btn_copy.setText(Icons.COPY)
        self.title_bar.btn_copy.setToolTip(old_tip)

    def _update_footer_stats(self):
        text = self.editor.toPlainText().strip()
        words = len(text.split()) if text else 0
        chars = len(text)
        self.lbl_stats.setText(f"{words} words · {chars} chars")

    def closeEvent(self, event):
        self._save_timer.stop()
        if not self.save_note(is_open=getattr(self, "_closing_with_app", False)):
            event.ignore()
            return
        self.closed.emit(self)
        super().closeEvent(event)


class ImageCanvas(QWidget):
    """
    Subpixel smooth, zoomable and pannable image display canvas.
    Supports mouse-wheel zooming, click-drag panning when zoomed, and double-click toggle.
    """
    zoom_changed = Signal(float)

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self._pixmap = pixmap
        self._zoom: float = 1.0
        self._pan_x: float = 0.0
        self._pan_y: float = 0.0
        self._last_mouse_pos = None
        self._is_panning = False
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_zoom(self, zoom: float):
        self._zoom = max(0.1, min(10.0, zoom))
        if self._zoom <= 1.02:
            self._pan_x = 0.0
            self._pan_y = 0.0
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.update()
        self.zoom_changed.emit(self._zoom)

    def zoom_in(self):
        self.set_zoom(self._zoom * 1.2)

    def zoom_out(self):
        self.set_zoom(self._zoom / 1.2)

    def reset_zoom(self):
        self._pan_x = 0.0
        self._pan_y = 0.0
        self.set_zoom(1.0)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta > 0:
            self.zoom_in()
        elif delta < 0:
            self.zoom_out()
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._zoom > 1.02:
                self._is_panning = True
                self._last_mouse_pos = event.position()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_panning and self._last_mouse_pos is not None:
            delta = event.position() - self._last_mouse_pos
            self._pan_x += delta.x()
            self._pan_y += delta.y()
            self._last_mouse_pos = event.position()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._is_panning:
            self._is_panning = False
            self.setCursor(Qt.CursorShape.OpenHandCursor if self._zoom > 1.02 else Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if abs(self._zoom - 1.0) < 0.05:
                self.set_zoom(2.0)
            else:
                self.reset_zoom()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        if not self._pixmap or self._pixmap.isNull():
            return

        vw = float(self.width())
        vh = float(self.height())
        pw = float(self._pixmap.width())
        ph = float(self._pixmap.height())

        fit_scale = min(vw / max(1.0, pw), vh / max(1.0, ph))
        scale = fit_scale * self._zoom

        draw_w = pw * scale
        draw_h = ph * scale
        draw_x = (vw - draw_w) / 2.0 + self._pan_x
        draw_y = (vh - draw_h) / 2.0 + self._pan_y

        painter.drawPixmap(
            QRectF(draw_x, draw_y, draw_w, draw_h),
            self._pixmap,
            QRectF(0, 0, pw, ph)
        )


class FloatingStickyImage(QWidget):
    """
    Floating pinned screenshot / image on screen (like Snipaste / PureRef).
    Stays always on top, freely draggable with startSystemMove(), resizable with QSizeGrip.
    Supports mouse-wheel zooming, interactive panning, and maximize/fullscreen toggle.
    """
    closed = Signal(object)

    def __init__(self, image_path: str, parent=None):
        super().__init__(None)
        self.image_path = image_path
        self._pixmap = QPixmap(image_path)
        self.is_pinned = True
        self._is_maximized = False
        self._prev_geom = None

        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        # Scale initial window to wrap screenshot aspect ratio cleanly without massive black borders
        if not self._pixmap.isNull():
            orig_w = self._pixmap.width()
            orig_h = self._pixmap.height()
            aspect = orig_h / max(1, orig_w)
            chrome_h = 30 + 20 + 8  # header (30px) + footer (20px) + margins (8px)
            w = max(320, min(750, orig_w))
            content_h = int(w * aspect)
            h = max(70, min(650, content_h + chrome_h))
        else:
            w, h = 320, 240
        self.resize(w, h)

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        self.container = QFrame(self)
        self.container.setObjectName("imageContainer")
        set_widget_style(self.container, """
            QFrame#imageContainer {
                background-color: #12151c;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 12px;
            }
        """)
        c_layout = QVBoxLayout(self.container)
        c_layout.setContentsMargins(0, 0, 0, 0)
        c_layout.setSpacing(0)

        # Header Bar
        self.header = QWidget(self)
        self.header.setFixedHeight(30)
        set_widget_style(self.header, """
            QWidget {
                background: #181d27;
                border-top-left-radius: 11px;
                border-top-right-radius: 11px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            }
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 4px;
                color: #94a3b8;
                font-size: 11px;
                padding: 1px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.1);
                color: #ffffff;
            }
        """)
        h_layout = QHBoxLayout(self.header)
        h_layout.setContentsMargins(10, 0, 6, 0)
        h_layout.setSpacing(4)

        self.header.mousePressEvent = self._start_drag
        self.header.mouseDoubleClickEvent = lambda e: self.toggle_maximize()

        lbl = QLabel("Pinned Screenshot", self)
        lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        set_widget_style(lbl, "font-size: 11px; font-weight: 600; color: #e2e8f0; background: transparent; border: none;")
        h_layout.addWidget(lbl)
        h_layout.addStretch()

        # Zoom Controls
        btn_zoom_out = IconButton(Icons.ZOOM_OUT, "Zoom Out (Wheel Down)", parent=self, size=20, font_size=10, is_fluent=True)
        btn_zoom_out.clicked.connect(lambda: self.canvas.zoom_out())
        h_layout.addWidget(btn_zoom_out)

        btn_zoom_in = IconButton(Icons.ZOOM_IN, "Zoom In (Wheel Up)", parent=self, size=20, font_size=10, is_fluent=True)
        btn_zoom_in.clicked.connect(lambda: self.canvas.zoom_in())
        h_layout.addWidget(btn_zoom_in)

        self.btn_maximize = IconButton(Icons.MAXIMIZE, "Maximize / Fullscreen", parent=self, size=20, font_size=10, is_fluent=True)
        self.btn_maximize.clicked.connect(self.toggle_maximize)
        h_layout.addWidget(self.btn_maximize)

        self.btn_img_pin = IconButton(Icons.PIN, "Always on Top (Toggle)", parent=self, size=20, font_size=10, is_fluent=True)
        self.btn_img_pin.clicked.connect(self.toggle_pin)
        h_layout.addWidget(self.btn_img_pin)

        btn_copy = IconButton(Icons.COPY, "Copy Image", parent=self, size=20, font_size=10, is_fluent=True)
        btn_copy.clicked.connect(self.copy_image)
        h_layout.addWidget(btn_copy)

        btn_close = IconButton(Icons.CLOSE, "Close", parent=self, size=20, font_size=10, is_fluent=True)
        btn_close.clicked.connect(self.close)
        h_layout.addWidget(btn_close)
        c_layout.addWidget(self.header)

        # Image Canvas (Zoomable, Pannable, Fill Viewport)
        self.canvas = ImageCanvas(self._pixmap, parent=self)
        self.canvas.zoom_changed.connect(self._on_zoom_changed)
        c_layout.addWidget(self.canvas, stretch=1)

        # Bottom footer with size grip
        footer = QHBoxLayout()
        footer.setContentsMargins(10, 0, 4, 4)
        orig_dims = f"{self._pixmap.width()}×{self._pixmap.height()}" if not self._pixmap.isNull() else ""
        self.lbl_info = QLabel(f"{orig_dims} · 100%", self)
        set_widget_style(self.lbl_info, "font-size: 11px; color: #a7b2bf; background: transparent; border: none;")
        footer.addWidget(self.lbl_info)
        footer.addStretch()

        self.size_grip = QSizeGrip(self)
        self.size_grip.setFixedSize(14, 14)
        set_widget_style(self.size_grip, "background: transparent;")
        footer.addWidget(self.size_grip)
        c_layout.addLayout(footer)

        layout.addWidget(self.container)

    def _on_zoom_changed(self, zoom: float):
        orig_dims = f"{self._pixmap.width()}×{self._pixmap.height()}" if not self._pixmap.isNull() else ""
        pct = int(zoom * 100)
        self.lbl_info.setText(f"{orig_dims} · {pct}% (Wheel to zoom)")

    def _start_drag(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.windowHandle()
            if handle:
                handle.startSystemMove()
                event.accept()
                return

    def mousePressEvent(self, event):
        self._start_drag(event)
        super().mousePressEvent(event)

    def toggle_maximize(self):
        if self._is_maximized:
            if self._prev_geom:
                self.setGeometry(self._prev_geom)
            self._is_maximized = False
            self.btn_maximize.setText(Icons.MAXIMIZE)
            self.btn_maximize.setToolTip("Maximize / Fullscreen")
        else:
            self._prev_geom = self.geometry()
            cur_screen = QGuiApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()
            screen = cur_screen.availableGeometry() if cur_screen else self.geometry()
            self.setGeometry(screen)
            self._is_maximized = True
            self.btn_maximize.setText(Icons.RESTORE)
            self.btn_maximize.setToolTip("Restore Window")
        self.canvas.reset_zoom()

    def toggle_pin(self):
        self.is_pinned = not self.is_pinned
        self.btn_img_pin.setText(Icons.PIN if self.is_pinned else Icons.UNPIN)
        try:
            import ctypes
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOACTIVATE = 0x0010
            hwnd = int(self.winId())
            target = HWND_TOPMOST if self.is_pinned else HWND_NOTOPMOST
            ctypes.windll.user32.SetWindowPos(hwnd, target, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        except Exception:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.is_pinned)
            self.show()

    def copy_image(self):
        if self._pixmap and not self._pixmap.isNull():
            cb = QApplication.clipboard()
            cb.setPixmap(self._pixmap)

    def closeEvent(self, event):
        self.closed.emit(self)
        super().closeEvent(event)

