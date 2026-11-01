"""
Poppy Detachable Floating Sticky Notes
Independent on-screen floating sticky notes inspired by macOS Quick Notes and Windows Sticky Notes.
Features native OS hardware-accelerated window dragging (startSystemMove), corner resizing (QSizeGrip),
pin-to-top toggle, multi-color themes (Charcoal, Pastel Yellow, Mint, Lavender, Amber),
and persistent on-screen presence across desktops.
"""

from PySide6.QtCore import Qt, QPoint, Signal, QSize, QTimer
from PySide6.QtGui import QColor, QFont, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLabel, QPushButton,
    QSizeGrip, QFrame, QApplication
)

from poppy.ui.components import IconButton
from poppy.ui.icons import Icons

NOTE_THEMES = {
    "charcoal": {
        "name": "Charcoal",
        "bg": "#181e2a",
        "header_bg": "#131822",
        "text": "#f1f5f9",
        "border": "rgba(255, 255, 255, 0.12)",
        "accent": "#6366f1",
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
        self.setFixedHeight(32)
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 6, 0)
        layout.setSpacing(4)

        # Title Label (transparent for mouse events so dragging works anywhere on title bar)
        self.lbl_title = QLabel("Note", self)
        self.lbl_title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.lbl_title.setStyleSheet("font-size: 11px; font-weight: 600; background: transparent; border: none;")
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

    def __init__(self, initial_text: str = "", theme_name: str = "charcoal", parent=None):
        super().__init__(None)  # Top-level window independent of parent
        self.is_pinned = True
        self._current_theme_key = theme_name if theme_name in NOTE_THEMES else "charcoal"

        # Window Flags: True Window that stays on top and is borderless
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(200, 160)
        self.resize(270, 230)

        self._init_ui(initial_text)
        self._apply_theme()

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
        self.editor.setPlaceholderText("Type quick thought or paste text...")
        self.editor.setPlainText(initial_text)
        self.editor.textChanged.connect(self._update_footer_stats)
        card_layout.addWidget(self.editor, stretch=1)

        # 3. Footer Bar with Word Count and QSizeGrip for smooth corner resizing
        footer = QHBoxLayout()
        footer.setContentsMargins(10, 2, 4, 4)
        footer.setSpacing(6)

        self.lbl_stats = QLabel("0 words", self)
        self.lbl_stats.setStyleSheet("font-size: 9.5px; opacity: 0.7; background: transparent; border: none;")
        footer.addWidget(self.lbl_stats)

        footer.addStretch()

        # Native corner resize grip
        self.size_grip = QSizeGrip(self)
        self.size_grip.setFixedSize(16, 16)
        self.size_grip.setStyleSheet("background: transparent;")
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
        self.container.setStyleSheet(f"""
            QFrame#noteContainer {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 12px;
            }}
        """)

        # Title bar styling
        self.title_bar.setStyleSheet(f"""
            QWidget {{
                background-color: {hdr_bg};
                border-top-left-radius: 11px;
                border-top-right-radius: 11px;
                border-bottom: 1px solid {border_color};
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
        self.title_bar.lbl_title.setStyleSheet(f"color: {text_color}; font-size: 11px; font-weight: 600; background: transparent; border: none;")

        # Editor styling
        self.editor.setStyleSheet(f"""
            QTextEdit {{
                background-color: transparent;
                border: none;
                color: {text_color};
                font-family: 'Segoe UI Variable Text', 'Segoe UI', -apple-system, sans-serif;
                font-size: 12px;
                line-height: 1.45;
                padding: 8px 10px;
                selection-background-color: {theme['accent']};
            }}
        """)
        self.lbl_stats.setStyleSheet(f"color: {text_color}; font-size: 9.5px; opacity: 0.65; background: transparent; border: none;")

    def cycle_theme(self):
        keys = list(NOTE_THEMES.keys())
        idx = (keys.index(self._current_theme_key) + 1) % len(keys)
        self._current_theme_key = keys[idx]
        self._apply_theme()

    def toggle_always_on_top(self):
        self.is_pinned = not self.is_pinned
        if self.is_pinned:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            self.title_bar.btn_pin.setText(Icons.PIN)
            self.title_bar.btn_pin.setToolTip("Always on Top: ON (Click to unpin)")
        else:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
            self.title_bar.btn_pin.setText(Icons.UNPIN)
            self.title_bar.btn_pin.setToolTip("Always on Top: OFF (Click to pin)")
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
        self.closed.emit(self)
        super().closeEvent(event)


class FloatingStickyImage(QWidget):
    """
    Floating pinned screenshot / image on screen (like Snipaste / PureRef).
    Stays always on top, freely draggable with startSystemMove(), resizable with QSizeGrip.
    """
    closed = Signal(object)

    def __init__(self, image_path: str, parent=None):
        super().__init__(None)
        self.image_path = image_path
        self._pixmap = QPixmap(image_path)
        self.is_pinned = True

        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        # Scale initial size based on image
        if not self._pixmap.isNull():
            orig_w = self._pixmap.width()
            orig_h = self._pixmap.height()
            w = max(240, min(480, orig_w))
            aspect = orig_h / max(1, orig_w)
            h = int(w * aspect) + 38
            h = max(180, min(520, h))
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
        self.container.setStyleSheet("""
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
        self.header.setStyleSheet("""
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
        lbl = QLabel("Pinned Screenshot", self)
        lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lbl.setStyleSheet("font-size: 11px; font-weight: 600; color: #e2e8f0; background: transparent; border: none;")
        h_layout.addWidget(lbl)
        h_layout.addStretch()

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

        # Image display area
        self.lbl_img = QLabel(self)
        self.lbl_img.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.lbl_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_img.setStyleSheet("background: transparent; border: none; padding: 4px;")
        c_layout.addWidget(self.lbl_img, stretch=1)

        # Bottom footer with size grip
        footer = QHBoxLayout()
        footer.setContentsMargins(10, 0, 4, 4)
        dims = f"{self._pixmap.width()}×{self._pixmap.height()}" if not self._pixmap.isNull() else ""
        lbl_info = QLabel(dims, self)
        lbl_info.setStyleSheet("font-size: 9px; color: #64748b; background: transparent; border: none;")
        footer.addWidget(lbl_info)
        footer.addStretch()

        self.size_grip = QSizeGrip(self)
        self.size_grip.setFixedSize(14, 14)
        self.size_grip.setStyleSheet("background: transparent;")
        footer.addWidget(self.size_grip)
        c_layout.addLayout(footer)

        layout.addWidget(self.container)
        self._update_scaled_pixmap()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_scaled_pixmap()

    def _update_scaled_pixmap(self):
        if self._pixmap and not self._pixmap.isNull():
            target_w = max(10, self.lbl_img.width() - 8)
            target_h = max(10, self.lbl_img.height() - 8)
            scaled = self._pixmap.scaled(
                target_w, target_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.lbl_img.setPixmap(scaled)

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

    def toggle_pin(self):
        self.is_pinned = not self.is_pinned
        self.btn_img_pin.setText(Icons.PIN if self.is_pinned else Icons.UNPIN)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.is_pinned)
        self.show()

    def copy_image(self):
        if self._pixmap:
            cb = QApplication.clipboard()
            cb.setPixmap(self._pixmap)

    def closeEvent(self, event):
        self.closed.emit(self)
        super().closeEvent(event)

