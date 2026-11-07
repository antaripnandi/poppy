"""Poppy settings with live appearance previews and explicit saving."""

import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QSize, QTimer, QEvent, QPointF
from PySide6.QtGui import QGuiApplication, QPixmap, QColor, QPainter, QIcon, QWheelEvent, QIntValidator, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QSpinBox, QPushButton, QStackedWidget, QListWidget,
    QFrame, QComboBox, QSlider, QScrollArea, QProgressBar, QMessageBox,
    QApplication, QLayout, QCheckBox, QColorDialog, QFileDialog
)

from poppy.ui.theme import set_widget_style, configure_theme, refresh_theme, LAYOUT_THEMES, home_order, home_slots, current_layout
from poppy.ui.styles import (
    THEME_PRESETS, DEFAULT_THEME, DEFAULT_PANEL_WIDTH, DEFAULT_PANEL_HEIGHT,
    APPEARANCE_LAYOUT_VERSION, normalize_appearance,
)
from poppy.core import APP_VERSION
from poppy.core.download_watcher import default_download_folder
from poppy.core.system_features import get_autostart_state, set_autostart_state
from poppy.ui.components import ToggleSwitch, SettingRow, ScrollArea, ClickableSlider, CardFrame
from poppy.core.storage import data_dir, data_path, write_json, spotify_cookie, protect_spotify_cookie


class OrderCard(CardFrame):
    """A reorder handle; dragging never touches the user's live editor or controls."""
    def __init__(self, key, text, preview):
        super().__init__(preview)
        self.key = key
        self.preview = preview
        self._press = None
        self._dragging = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setAccessibleName(text)
        self.setToolTip("Drag to move. Alt + arrow keys also move this section.")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        label = QLabel(text)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_widget_style(label, "font-size: 11px; color: #bbc4c5; background: transparent;")
        layout.addWidget(label)

    def apply_layout(self, name):
        super().apply_layout(name)
        # Keep the handles visible even when the design uses borderless surfaces.
        source = self.property("poppyStyleSource")
        set_widget_style(self, source + "CardFrame#cardFrame { border: 1px dashed #66736d; } CardFrame#cardFrame:focus { border: 2px solid #a3b9ab; } CardFrame#cardFrame[dropTarget=true] { border: 2px solid #a3b9ab; background: rgba(130,156,142,0.18); }")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press is not None:
            if (event.position().toPoint() - self._press).manhattanLength() >= QApplication.startDragDistance():
                self._dragging = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            if self._dragging:
                self.preview.highlight_at(event.globalPosition().toPoint(), self)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._press is not None:
            if self._dragging:
                target = self.preview.card_at(event.globalPosition().toPoint())
                if target is not None:
                    self.preview.move_card(self.key, self.preview.order.index(target.key))
            self._press = None
            self._dragging = False
            self.preview.end_drag()
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        directions = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1,
                      Qt.Key.Key_Up: -2, Qt.Key.Key_Down: 2}
        if event.modifiers() == Qt.KeyboardModifier.AltModifier and event.key() in directions:
            self.preview.move_card(self.key, self.preview.order.index(self.key) + directions[event.key()])
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self._press = None
            self._dragging = False
            self.preview.end_drag()
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().keyPressEvent(event)


class LayoutPreview(QWidget):
    """Live Home arrangement editor, separate from the widgets containing user data."""
    order_changed = Signal(list)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAccessibleName("Dashboard layout preview")
        self.setFixedHeight(110)
        self.grid = QGridLayout(self)
        self._layout_name = None
        self.order = []
        self._highlighted = None
        self._drag_source = None
        self._ghost = QLabel(self)
        self._ghost.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._ghost.hide()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.cards = {}
        for key, text in (("clock", "Time & usage"), ("controls", "System controls"),
                          ("notes", "Notes"), ("shelf", "Shelf")):
            self.cards[key] = OrderCard(key, text, self)

    def apply_layout(self, name, order=None):
        order = list(home_order(name, {name: order}))
        if self._layout_name == name and self.order == order:
            return
        self._layout_name = name
        self.order = order
        spec = LAYOUT_THEMES[name]
        for card in self.cards.values():
            self.grid.removeWidget(card)
            card.apply_layout(name)
        for key, slot in zip(self.order, home_slots(name, len(self.order))):
            self.grid.addWidget(self.cards[key], *slot)
        self.grid.setColumnStretch(2, 0)
        for column, stretch in enumerate(spec["columns"]):
            self.grid.setColumnStretch(column, stretch)
        self.grid.setSpacing(spec["spacing"] // 2)
        self.setAccessibleDescription(spec["description"])

    def move_card(self, key, target):
        if key not in self.order or not 0 <= target < len(self.order):
            return
        order = list(self.order)
        origin = order.index(key)
        if origin == target:
            return
        order.insert(target, order.pop(origin))
        self.apply_layout(self._layout_name, order)
        self.cards[key].setFocus()
        self.order_changed.emit(list(order))

    def card_at(self, global_position):
        position = self.mapFromGlobal(global_position)
        return next((card for card in self.cards.values() if card.geometry().contains(position)), None)

    def clear_highlight(self):
        if self._highlighted is not None:
            card = self._highlighted
            self._highlighted = None
            card.setProperty("dropTarget", False)
            card.style().unpolish(card)
            card.style().polish(card)
            card.update()

    def highlight_at(self, global_position, source):
        if self._drag_source is not source:
            self._drag_source = source
            self._ghost.setPixmap(source.grab())
            self._ghost.resize(source.size())
        self._ghost.move(self.mapFromGlobal(global_position) - source._press)
        self._ghost.show()
        self._ghost.raise_()
        card = self.card_at(global_position)
        if card is source:
            card = None
        if card is self._highlighted:
            return
        self.clear_highlight()
        self._highlighted = card
        if card is not None:
            card.setProperty("dropTarget", True)
            card.style().unpolish(card)
            card.style().polish(card)
            card.update()

    def end_drag(self):
        self.clear_highlight()
        self._ghost.hide()
        self._drag_source = None


class ValueEdit(QLineEdit):
    """Compact validated numeric entry committed on Enter or focus loss."""
    valueEdited = Signal(int)

    def __init__(self, minimum, maximum, value, parent=None):
        super().__init__(parent)
        self.setValidator(QIntValidator(minimum, maximum, self))
        self.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.setValue(value)
        self.editingFinished.connect(self._commit)

    def value(self):
        return self._value

    def setValue(self, value):
        self._value = value
        self.setText(str(value))

    def _commit(self):
        if self.hasAcceptableInput():
            value, valid = self.validator().locale().toInt(self.text())
            if valid:
                changed = value != self._value
                self.setValue(value)
                if changed:
                    self.valueEdited.emit(value)
                return
        self.setText(str(self._value))

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._commit()
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        self._commit()
        super().focusOutEvent(event)



def _create_setting_card(rows: list[QWidget]) -> QFrame:
    """Frosted obsidian glass container grouping setting rows with subtle dividers."""
    card = QFrame()
    set_widget_style(card, """
        QFrame {
            background-color: #1d2021;
            border: 1px solid rgba(255, 255, 255, 0.065);
            border-radius: 12px;
        }
    """)
    l = QVBoxLayout(card)
    l.setContentsMargins(16, 6, 16, 6)
    l.setSpacing(0)
    for i, row in enumerate(rows):
        if i > 0:
            div = QFrame()
            div.setFixedHeight(1)
            set_widget_style(div, "background-color: rgba(255, 255, 255, 0.035); border: none;")
            l.addWidget(div)
        l.addWidget(row)
    return card


def _make_scroll_area(page_widget: QWidget) -> QScrollArea:
    """Zero-artifact transparent scroll container with auto-hidden horizontal bar."""
    sa = ScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.Shape.NoFrame)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    page_widget.layout().setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
    sa.setWidget(page_widget)
    sa.verticalScrollBar().setSingleStep(24)
    return sa


ALL_AVAILABLE_TABS = [
    ("Home", "Home dashboard, clocks, volume/brightness, notes, shelf & calc"),
    ("Music", "Now playing media player, timeline scrubbing & synced lyrics"),
    ("Calendar", "Interactive monthly calendar, reminders & agenda view"),
    ("Clipboard", "Clipboard history manager with search, copy & pinned clips"),
    ("Docs", "Document reader, quick preview & PDF converter utilities"),
    ("Desktops", "Windows Virtual Desktops switcher & active workspace overview"),
    ("Timer", "Pomodoro sprint focus tracker with short/long break cycles"),
    ("Shelf", "Staging drop shelf for files, dragged assets & snips"),
    ("Notes", "In-notch scratchpad with detachable desktop floating notes")
]


class SettingsWindow(QWidget):
    settings_saved = Signal(dict)
    appearance_live_updated = Signal(dict)
    screentime_reset_requested = Signal()
    update_check_requested = Signal()

    def __init__(self, config: dict = None, parent=None):
        super().__init__(parent)
        self.config = config or {}
        self.setWindowTitle("Poppy Settings")
        self.resize(860, 640)
        self.setMinimumSize(720, 480)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)

        self._tab_checkboxes = {}
        self._home_orders = {}
        self._loading_values = False
        self._last_preview = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(32)
        self._preview_timer.timeout.connect(self._on_live_appearance_change)
        self._init_ui()
        self._load_values()
        self._last_preview = self._appearance_values()

    def _init_ui(self):
        set_widget_style(self, """
            QWidget {
                background-color: #17191a;
                color: #e3e7e7;
                font-family: 'Segoe UI';
            }
            QListWidget {
                background-color: #121415;
                border: none;
                border-right: 1px solid rgba(255, 255, 255, 0.05);
                padding: 14px 6px;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 9px 12px;
                border-radius: 8px;
                color: #9ca3a5;
                font-weight: 500;
                margin: 2px 2px;
            }
            QListWidget::item:selected {
                background-color: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.12);
                color: #ffffff;
                font-weight: 600;
            }
            QListWidget::item:hover:!selected {
                background-color: rgba(255, 255, 255, 0.035);
                color: #f1f5f9;
            }
            QSpinBox, QComboBox, QLineEdit {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
                padding: 5px 9px;
                color: #eef0f0;
                font-size: 12px;
            }
            QSpinBox:focus, QComboBox:focus, QLineEdit:focus {
                border: 1px solid rgba(130, 156, 142, 0.5);
                background-color: rgba(255, 255, 255, 0.08);
            }
            QComboBox::drop-down {
                border: none;
                width: 18px;
            }
            QSlider::groove:horizontal {
                height: 4px;
                background: rgba(255, 255, 255, 0.12);
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #bbc4c5;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #7f8b91;
                width: 12px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 6px;
            }
            QScrollBar:vertical {
                width: 8px;
                background: transparent;
                margin: 2px 0px;
            }
            QScrollBar::horizontal {
                height: 0px;
                border: none;
                background: transparent;
            }
            QScrollBar::corner {
                background: transparent;
                border: none;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.14);
                min-height: 28px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.28);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
        """)

        set_widget_style(self, self.property("poppyStyleSource") + """
            QLabel { background: transparent; border: none; }
            QPushButton { background: #292d2e; color: #e3e7e7; border: 1px solid #383e40;
                          border-radius: 6px; padding: 6px 12px; font-size: 12px; }
            QPushButton:hover { background: #343a3b; }
            QPushButton:focus { border-color: #bbc4c5; }
            QComboBox QAbstractItemView { background: #242829; color: #edf0f0; selection-background-color: #3d4547; }
        """)
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Left Nav Sidebar
        sidebar = QWidget()
        sidebar.setFixedWidth(168)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(8, 12, 8, 0)
        sidebar_layout.setSpacing(6)
        self.search_settings = QLineEdit()
        self.search_settings.setPlaceholderText("Search settings")
        self.search_settings.setAccessibleName("Search settings")
        self.search_settings.setClearButtonEnabled(True)
        self.search_settings.textChanged.connect(self._filter_settings)
        QShortcut(QKeySequence.StandardKey.Find, self, activated=self.search_settings.setFocus)
        sidebar_layout.addWidget(self.search_settings)
        self.nav_list = QListWidget()
        set_widget_style(self.nav_list, "QListWidget { outline: 0; }")
        self.nav_list.setAccessibleName("Settings pages")
        self.nav_list.addItem("Appearance")
        self.nav_list.addItem("Tools")
        self.nav_list.addItem("Behavior")
        self.nav_list.addItem("Notifications")
        self.nav_list.addItem("Screen time")
        self.nav_list.addItem("Music")
        self.nav_list.addItem("Weather")
        self.nav_list.addItem("Timer")
        self.nav_list.addItem("Discord")
        self.nav_list.addItem("System")
        self.nav_list.addItem("About")
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)
        sidebar_layout.addWidget(self.nav_list, 1)
        main_layout.addWidget(sidebar)

        # Right Content Area
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(28, 26, 24, 18)
        right_layout.setSpacing(12)

        self.stack = QStackedWidget()
        self.no_search_results = QLabel("No matching settings")
        self.no_search_results.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.no_search_results.hide()

        # =====================================================================
        # 0. Appearance Page
        # =====================================================================
        page_app = QWidget()
        l_app = QVBoxLayout(page_app)
        l_app.setContentsMargins(0, 0, 8, 0)
        l_app.setSpacing(12)

        lbl_app_hdr = QLabel("Appearance")
        set_widget_style(lbl_app_hdr, "font-size: 21px; font-weight: 600; color: #eef0f0;")
        lbl_app_sub = QLabel("Choose a layout theme, appearance mode and color palette.")
        set_widget_style(lbl_app_sub, "font-size: 12px; color: #9ca3a5;")
        l_app.addWidget(lbl_app_hdr)
        l_app.addWidget(lbl_app_sub)

        self.combo_layout = QComboBox()
        self.combo_layout.addItems(list(LAYOUT_THEMES))
        self.combo_layout.currentTextChanged.connect(self._on_live_appearance_change)
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["Dark", "Light", "System"])
        self.combo_mode.setItemText(2, "Follow Windows")
        self.combo_mode.currentTextChanged.connect(self._on_live_appearance_change)
        l_app.addWidget(_create_setting_card([
            SettingRow("Layout theme", f"{len(LAYOUT_THEMES)} layouts for navigation, typography and all tabs", self.combo_layout),
            SettingRow("Appearance mode", "Dark, Light, or follow the Windows app setting", self.combo_mode),
        ]))
        self.layout_preview = LayoutPreview()
        self.layout_preview.order_changed.connect(self._on_home_order_changed)
        order_header = QHBoxLayout()
        order_hint = QLabel("Home order · Drag sections, or use Alt + arrow keys")
        set_widget_style(order_hint, "font-size: 11px; color: #9ca3a5;")
        order_hint.setWordWrap(True)
        order_header.addWidget(order_hint, 1)
        self.btn_reset_order = QPushButton("Reset order")
        self.btn_reset_order.setToolTip("Restore this design's default Home order")
        self.btn_reset_order.clicked.connect(self._reset_home_order)
        order_header.addWidget(self.btn_reset_order)
        self.lbl_layout_description = QLabel()
        self.lbl_layout_description.setWordWrap(True)
        set_widget_style(self.lbl_layout_description, "font-size: 12px; color: #9ca3a5;")
        l_app.addLayout(order_header)
        l_app.addWidget(self.layout_preview)
        l_app.addWidget(self.lbl_layout_description)

        sections_title = QLabel("Home sections")
        set_widget_style(sections_title, "font-size: 14px; font-weight: 600; color: #eef0f0;")
        l_app.addWidget(sections_title)
        sections = QGridLayout()
        sections.setHorizontalSpacing(16)
        sections.setVerticalSpacing(8)
        self._home_section_checks = {}
        for index, (key, label) in enumerate((
            ("player", "Mini-player"), ("clock", "Time and usage"),
            ("controls", "System controls"), ("notes", "Notes"),
            ("shelf", "Shelf"), ("screentime", "Screen time"),
        )):
            checkbox = QCheckBox(label)
            checkbox.setChecked(True)
            self._home_section_checks[key] = checkbox
            sections.addWidget(checkbox, index // 2, index % 2)
        l_app.addLayout(sections)

        self.combo_theme = QComboBox()
        for name, theme in THEME_PRESETS.items():
            swatch = QPixmap(20, 14)
            swatch.fill(QColor(theme["bg"]))
            painter = QPainter(swatch)
            painter.setPen(QColor("#6d7572"))
            painter.drawRect(0, 0, 19, 13)
            painter.fillRect(1, 10, 18, 3, QColor(theme["accent"]))
            painter.end()
            self.combo_theme.addItem(QIcon(swatch), name)
            self.combo_theme.setItemData(self.combo_theme.count() - 1, theme["desc"], Qt.ItemDataRole.ToolTipRole)
        self.combo_theme.setIconSize(QSize(20, 14))
        self.combo_theme.setAccessibleName("Color palette")
        self.combo_theme.currentTextChanged.connect(self._on_theme_changed)
        l_app.addWidget(_create_setting_card([SettingRow("Color palette", "Choose colors separately from the layout and appearance mode", self.combo_theme)]))

        # Size & Shape Section
        l_app.addSpacing(6)
        lbl_shape_hdr = QLabel("Size and position")
        set_widget_style(lbl_shape_hdr, "font-size: 14px; font-weight: 600; color: #eef0f0;")
        lbl_shape_sub = QLabel("Changes preview on the panel as you adjust them.")
        set_widget_style(lbl_shape_sub, "font-size: 12px; color: #9ca3a5;")
        l_app.addWidget(lbl_shape_hdr)
        l_app.addWidget(lbl_shape_sub)

        self.combo_style = QComboBox()
        self.combo_style.addItems(["Notch", "Pill"])
        self.combo_style.setToolTip("Notch hugs top screen edge (y=0); Pill floats with top padding.")
        self.combo_style.currentTextChanged.connect(self._on_live_appearance_change)

        self.combo_display = QComboBox()
        self.combo_display.addItem("Primary")
        for i, s in enumerate(QGuiApplication.screens()):
            self.combo_display.addItem(f"Display {i + 1} ({s.geometry().width()}x{s.geometry().height()})")
        self.combo_display.currentTextChanged.connect(self._on_live_appearance_change)

        row_style = SettingRow("Window style", "Notch sits at the screen edge. Pill leaves a small gap.", self.combo_style)
        row_disp = SettingRow("Display", "Screen used for the panel", self.combo_display)

        self.slider_col_w, self.lbl_val_col_w, row_col_w = self._make_slider_setting("Closed width", "Width when notch is closed (px)", 180, 360, 240)
        self.slider_col_h, self.lbl_val_col_h, row_col_h = self._make_slider_setting("Closed height", "Height of the compact pill (px)", 24, 44, 30)
        self.slider_open_w, self.lbl_val_open_w, row_open_w = self._make_slider_setting("Panel width", "Preferred width in pixels", 780, 1200, DEFAULT_PANEL_WIDTH)
        self.slider_open_h, self.lbl_val_open_h, row_open_h = self._make_slider_setting("Panel height", "Home scrolls when its sections need more room", 480, 800, DEFAULT_PANEL_HEIGHT)
        self.slider_radius, self.lbl_val_radius, row_radius = self._make_slider_setting("Corner radius", "Curvature for rounded bezel corners (px)", 8, 28, 22)
        self.slider_top_offset, self.lbl_val_top_offset, row_top = self._make_slider_setting("Top offset", "Vertical padding gap from top bezel (px)", 0, 40, 0)

        card_shape = _create_setting_card([
            row_style, row_disp, row_col_w, row_col_h, row_open_w, row_open_h, row_radius, row_top
        ])
        l_app.addWidget(card_shape)
        self.combo_peek_color = QComboBox()
        for label, value in (("Album artwork", "artwork"), ("Fixed color", "fixed"), ("Match layout", "theme")):
            self.combo_peek_color.addItem(label, value)
        self.btn_peek_color = QPushButton()
        self.btn_peek_color.setAccessibleName("Choose fixed hover player color")
        self.btn_peek_color.clicked.connect(self._choose_peek_color)
        self.combo_peek_color.currentIndexChanged.connect(self._on_peek_color_changed)
        l_app.addWidget(_create_setting_card([
            SettingRow("Hover player color", "Follow the current artwork or choose a consistent color", self.combo_peek_color),
            SettingRow("Fixed hover color", "Used when Hover player color is set to Fixed color", self.btn_peek_color),
        ]))
        l_app.addStretch()

        self.stack.addWidget(_make_scroll_area(page_app))

        # =====================================================================
        # 1. Tabs Manager Page
        # =====================================================================
        page_tabs = QWidget()
        l_tabs = QVBoxLayout(page_tabs)
        l_tabs.setContentsMargins(0, 0, 8, 0)
        l_tabs.setSpacing(12)

        lbl_tabs_hdr = QLabel("Tools")
        set_widget_style(lbl_tabs_hdr, "font-size: 21px; font-weight: 600; color: #eef0f0;")
        lbl_tabs_sub = QLabel("Every enabled tool has its own tab. Home opens the dashboard.")
        set_widget_style(lbl_tabs_sub, "font-size: 12px; color: #9ca3a5;")
        l_tabs.addWidget(lbl_tabs_hdr)
        l_tabs.addWidget(lbl_tabs_sub)

        # Default tab dropdown
        self.combo_default_tab = QComboBox()
        self.combo_default_tab.addItem("Dashboard (Home)")
        for tab_name, _ in ALL_AVAILABLE_TABS:
            self.combo_default_tab.addItem(tab_name)

        card_dtab = _create_setting_card([
            SettingRow("Open to", "What appears when you open Poppy", self.combo_default_tab)
        ])
        l_tabs.addWidget(card_dtab)

        l_tabs.addSpacing(4)
        lbl_list_hdr = QLabel("Tabs shown in the drawer")
        set_widget_style(lbl_list_hdr, "font-size: 14px; font-weight: 600; color: #eef0f0;")
        l_tabs.addWidget(lbl_list_hdr)

        tab_rows = []
        for tab_name, tab_desc in ALL_AVAILABLE_TABS:
            toggle = ToggleSwitch(accent="#829c8e", checked=True)
            self._tab_checkboxes[tab_name] = toggle
            row = SettingRow(tab_name, tab_desc, toggle)
            tab_rows.append(row)

        card_tabs = _create_setting_card(tab_rows)
        l_tabs.addWidget(card_tabs)
        features_heading = QLabel("Optional features")
        set_widget_style(features_heading, "font-size: 14px; font-weight: 600; color: #eef0f0;")
        l_tabs.addWidget(features_heading)
        self.chk_app_mixer = ToggleSwitch(accent="#829c8e", checked=True)
        self.chk_clipboard_history = ToggleSwitch(accent="#829c8e", checked=False)
        self.chk_capture_images = ToggleSwitch(accent="#829c8e", checked=False)
        self.chk_downloads = ToggleSwitch(accent="#829c8e", checked=False)
        self.download_folder = QLineEdit()
        self.download_folder.setReadOnly(True)
        self.download_folder.setPlaceholderText("Windows Downloads folder")
        self.download_folder.setAccessibleName("Selected download folder")
        choose_download_folder = QPushButton("Browse")
        choose_download_folder.clicked.connect(self._choose_download_folder)
        reset_download_folder = QPushButton("Reset")
        reset_download_folder.clicked.connect(self.download_folder.clear)
        folder_controls = QWidget()
        folder_layout = QHBoxLayout(folder_controls)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        folder_layout.addWidget(self.download_folder)
        folder_layout.addWidget(choose_download_folder)
        folder_layout.addWidget(reset_download_folder)
        l_tabs.addWidget(_create_setting_card([
            SettingRow("App mixer", "Show per-app volume controls on Home and in the hover player.", self.chk_app_mixer),
            SettingRow("Record clipboard text", "Off by default. Save copied text locally, respecting Windows exclusions.", self.chk_clipboard_history),
            SettingRow("Stage copied images", "Off by default. Save copied images and screenshots to the shelf.", self.chk_capture_images),
            SettingRow("Download alerts", "Watch one folder for new files that finish writing. Uses your notification and focus settings.", self.chk_downloads),
            SettingRow("Download folder", "Choose the folder your browser or downloader saves into.", folder_controls),
        ]))
        l_tabs.addStretch()

        self.stack.addWidget(_make_scroll_area(page_tabs))

        # =====================================================================
        # 2. Behavior Page
        # =====================================================================
        page_beh = QWidget()
        l_beh = QVBoxLayout(page_beh)
        l_beh.setContentsMargins(0, 0, 8, 0)
        l_beh.setSpacing(12)

        lbl_beh_hdr = QLabel("Behavior")
        set_widget_style(lbl_beh_hdr, "font-size: 21px; font-weight: 600; color: #eef0f0;")
        lbl_beh_sub = QLabel("Choose how Poppy opens and runs.")
        set_widget_style(lbl_beh_sub, "font-size: 12px; color: #9ca3a5;")
        l_beh.addWidget(lbl_beh_hdr)
        l_beh.addWidget(lbl_beh_sub)

        self.chk_hover_peek = ToggleSwitch(accent="#829c8e", checked=True)
        self.chk_scroll_volume = ToggleSwitch(accent="#829c8e", checked=True)
        self.chk_pill_levels = ToggleSwitch(accent="#829c8e", checked=True)
        self.chk_autostart = ToggleSwitch(accent="#829c8e", checked=False)
        self.chk_tray_close = ToggleSwitch(accent="#829c8e", checked=True)

        self.spin_anim_ms = QSpinBox()
        self.spin_anim_ms.setRange(80, 500)
        self.spin_anim_ms.setSingleStep(20)

        card_beh = _create_setting_card([
            SettingRow("Preview on hover", "Show the compact player and volume control when you hover over the closed pill", self.chk_hover_peek),
            SettingRow("Scroll to change volume", "Scroll over the pill for volume. Shift + scroll adjusts supported displays.", self.chk_scroll_volume),
            SettingRow("Pill level feedback", "Use Poppy for volume and brightness feedback when Windows supports it.", self.chk_pill_levels),
            SettingRow("Launch at login", "Start Poppy when you sign in to Windows", self.chk_autostart),
            SettingRow("Show tray icon", "Right-click the pill to open settings or exit with the tray icon hidden", self.chk_tray_close),
            SettingRow("Animation duration", "Open and close animation, in milliseconds", self.spin_anim_ms)
        ])
        l_beh.addWidget(card_beh)
        l_beh.addStretch()

        self.stack.addWidget(_make_scroll_area(page_beh))

        # =====================================================================
        # 3. Notifications Page
        # =====================================================================
        page_notif = QWidget()
        l_notif = QVBoxLayout(page_notif)
        l_notif.setContentsMargins(0, 0, 8, 0)
        l_notif.setSpacing(12)

        lbl_notif_hdr = QLabel("Notifications")
        set_widget_style(lbl_notif_hdr, "font-size: 21px; font-weight: 600; color: #eef0f0;")
        lbl_notif_sub = QLabel("Choose how Poppy shows its alerts.")
        set_widget_style(lbl_notif_sub, "font-size: 12px; color: #9ca3a5;")
        l_notif.addWidget(lbl_notif_hdr)
        l_notif.addWidget(lbl_notif_sub)

        self.chk_notif_enabled = ToggleSwitch(accent="#829c8e", checked=True)
        self.chk_notif_show_island = ToggleSwitch(accent="#829c8e", checked=True)
        self.chk_notif_mute_focus = ToggleSwitch(accent="#829c8e", checked=True)
        self.chk_notif_sound = ToggleSwitch(accent="#829c8e", checked=True)
        self.chk_notif_preview = ToggleSwitch(accent="#829c8e", checked=True)

        card_notif = _create_setting_card([
            SettingRow("Show alerts", "Show alerts from Poppy", self.chk_notif_enabled),
            SettingRow("Expand for alerts", "Expand notch into a floating island when notifications arrive", self.chk_notif_show_island),
            SettingRow("Quiet during focus", "Silence incoming notification popups during Pomodoro sprints", self.chk_notif_mute_focus),
            SettingRow("Island sound", "Play a sound when an alert opens on the notch", self.chk_notif_sound),
            SettingRow("Show message text", "Display message text in alert (disable to protect privacy)", self.chk_notif_preview)
        ])
        l_notif.addWidget(card_notif)
        l_notif.addStretch()

        self.stack.addWidget(_make_scroll_area(page_notif))

        # =====================================================================
        # 4. Screen Time Page (Digital Wellbeing)
        # =====================================================================
        page_st = QWidget()
        l_st = QVBoxLayout(page_st)
        l_st.setContentsMargins(0, 0, 8, 0)
        l_st.setSpacing(12)

        lbl_st_hdr = QLabel("Screen time")
        set_widget_style(lbl_st_hdr, "font-size: 21px; font-weight: 600; color: #eef0f0;")
        lbl_st_sub = QLabel("Track active time and choose when to take a break.")
        set_widget_style(lbl_st_sub, "font-size: 12px; color: #9ca3a5;")
        l_st.addWidget(lbl_st_hdr)
        l_st.addWidget(lbl_st_sub)

        # Clean obsidian stat card
        card_st_summary = QFrame()
        set_widget_style(card_st_summary, """
            QFrame {
                background-color: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 12px;
            }
        """)
        l_card_summary = QVBoxLayout(card_st_summary)
        l_card_summary.setContentsMargins(16, 14, 16, 14)
        l_card_summary.setSpacing(10)

        row_top_stat = QHBoxLayout()
        stat_left = QVBoxLayout()
        stat_left.setSpacing(2)
        lbl_st_tag = QLabel("Today")
        set_widget_style(lbl_st_tag, "font-size: 12px; font-weight: 500; color: #a7b2bf; background: transparent; border: none;")
        self.lbl_st_today_time = QLabel("0m")
        set_widget_style(self.lbl_st_today_time, "font-size: 26px; font-weight: 600; color: #eef0f0; background: transparent; border: none;")
        stat_left.addWidget(lbl_st_tag)
        stat_left.addWidget(self.lbl_st_today_time)
        row_top_stat.addLayout(stat_left)
        row_top_stat.addStretch()

        readings = QVBoxLayout()
        readings.setSpacing(4)
        self.lbl_st_streak = QLabel("Active streak: 0m")
        self.lbl_st_goal_pct = QLabel("Goal: 0%")
        for label in (self.lbl_st_streak, self.lbl_st_goal_pct):
            set_widget_style(label, "font-size: 12px; color: #cbd5e1; background: transparent; border: none;")
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            readings.addWidget(label)
        row_top_stat.addLayout(readings)
        l_card_summary.addLayout(row_top_stat)

        # Micro progress bar
        self.bar_st_goal = QProgressBar()
        self.bar_st_goal.setFixedHeight(5)
        self.bar_st_goal.setTextVisible(False)
        set_widget_style(self.bar_st_goal, """
            QProgressBar {
                background-color: rgba(255, 255, 255, 0.08);
                border: none;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background-color: #b3c3ba;
                border-radius: 2px;
            }
        """)
        self.bar_st_goal.setRange(0, 100)
        self.bar_st_goal.setValue(0)
        l_card_summary.addWidget(self.bar_st_goal)

        # Top Apps Breakdown row
        self.lbl_st_top_apps = QLabel("Top apps will appear as you work...")
        set_widget_style(self.lbl_st_top_apps, "font-size: 12px; color: #9ca3a5; background: transparent; border: none;")
        l_card_summary.addWidget(self.lbl_st_top_apps)
        l_st.addWidget(card_st_summary)

        # Card 1: Tracking & Display
        self.chk_st_enabled = ToggleSwitch(accent="#829c8e", checked=True)
        self.chk_st_show_main_menu = ToggleSwitch(accent="#829c8e", checked=True)
        home_screen_time = self._home_section_checks["screentime"]
        home_screen_time.toggled.connect(lambda checked: self.chk_st_show_main_menu.setChecked(checked, animate=False))
        self.chk_st_show_main_menu.toggled.connect(home_screen_time.setChecked)
        self.chk_st_track_apps = ToggleSwitch(accent="#829c8e", checked=True)

        self.combo_st_afk = QComboBox()
        self.combo_st_afk.addItem("1 minute", 60)
        self.combo_st_afk.addItem("2 minutes (Recommended)", 120)
        self.combo_st_afk.addItem("5 minutes", 300)
        self.combo_st_afk.addItem("10 minutes", 600)

        card_st_track = _create_setting_card([
            SettingRow("Track active time", "Monitor active keyboard/mouse foreground session time", self.chk_st_enabled),
            SettingRow("Show on Home", "Show today's screen time and five most-used apps", self.chk_st_show_main_menu),
            SettingRow("Track time by app", "Record per-application duration (Code, Brave, Spotify, etc.)", self.chk_st_track_apps),
            SettingRow("Idle timeout", "Pause tracking when mouse and keyboard are idle", self.combo_st_afk)
        ])
        l_st.addWidget(card_st_track)

        # Card 2: Daily Target & Wellbeing
        self.slider_st_goal = ClickableSlider(Qt.Orientation.Horizontal)
        self.slider_st_goal.setRange(1, 16)
        self.slider_st_goal.setValue(6)
        self.slider_st_goal.setFixedWidth(130)
        self.lbl_goal_val = QLabel("6 hrs")
        set_widget_style(self.lbl_goal_val, "font-size: 12px; font-weight: 600; color: #b3c3ba; min-width: 42px;")
        self.slider_st_goal.valueChanged.connect(lambda v: self.lbl_goal_val.setText(f"{v} hrs"))

        goal_widget = QWidget()
        gw_l = QHBoxLayout(goal_widget)
        gw_l.setContentsMargins(0, 0, 0, 0)
        gw_l.setSpacing(8)
        gw_l.addWidget(self.slider_st_goal)
        gw_l.addWidget(self.lbl_goal_val)

        self.chk_st_goal_alert = ToggleSwitch(accent="#829c8e", checked=True)
        self.chk_st_break_reminder = ToggleSwitch(accent="#829c8e", checked=True)

        self.combo_st_break_interval = QComboBox()
        self.combo_st_break_interval.addItem("Every 30 minutes", 30)
        self.combo_st_break_interval.addItem("Every 45 minutes", 45)
        self.combo_st_break_interval.addItem("Every 60 minutes (Recommended)", 60)
        self.combo_st_break_interval.addItem("Every 90 minutes", 90)
        self.combo_st_break_interval.addItem("Every 120 minutes", 120)

        card_st_goals = _create_setting_card([
            SettingRow("Daily goal", "Maximum desired screen time per day", goal_widget),
            SettingRow("Goal reminder", "Pop up dynamic island alert when reaching daily limit", self.chk_st_goal_alert),
            SettingRow("Break reminders", "Prompt rest breaks during continuous uninterrupted screen time", self.chk_st_break_reminder),
            SettingRow("Remind me every", "Interval between posture and eye rest reminders", self.combo_st_break_interval)
        ])
        l_st.addWidget(card_st_goals)

        # Card 3: Privacy & Reset
        self.txt_st_excluded = QLineEdit()
        self.txt_st_excluded.setPlaceholderText("e.g. keepass, 1password, bitwarden")
        self.txt_st_excluded.setFixedWidth(200)

        self.btn_st_reset = QPushButton("Reset Today")
        self.btn_st_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        set_widget_style(self.btn_st_reset, """
            QPushButton {
                background-color: rgba(239, 68, 68, 0.12);
                border: 1px solid rgba(239, 68, 68, 0.3);
                border-radius: 6px;
                color: #fca5a5;
                font-size: 12px;
                font-weight: 600;
                padding: 5px 14px;
            }
            QPushButton:hover {
                background-color: rgba(239, 68, 68, 0.25);
                color: #ffffff;
            }
        """)
        self.btn_st_reset.clicked.connect(self._on_screentime_reset_clicked)

        card_st_privacy = _create_setting_card([
            SettingRow("Excluded apps", "Sensitive apps to omit from logs (comma-separated)", self.txt_st_excluded),
            SettingRow("Reset Today's Screen Time", "Clear active session counter and app stats for today", self.btn_st_reset)
        ])
        l_st.addWidget(card_st_privacy)
        l_st.addStretch()

        self.stack.addWidget(_make_scroll_area(page_st))

        # =====================================================================
        # 5. Media & Lyrics Page
        # =====================================================================
        page_media = QWidget()
        l_media = QVBoxLayout(page_media)
        l_media.setContentsMargins(0, 0, 8, 0)
        l_media.setSpacing(12)

        lbl_media_hdr = QLabel("Music")
        set_widget_style(lbl_media_hdr, "font-size: 21px; font-weight: 600; color: #eef0f0;")
        lbl_media_sub = QLabel("Optional lyrics for the current track.")
        set_widget_style(lbl_media_sub, "font-size: 12px; color: #9ca3a5;")
        l_media.addWidget(lbl_media_hdr)
        l_media.addWidget(lbl_media_sub)

        self.txt_sp_dc = QLineEdit()
        self.txt_sp_dc.setPlaceholderText("Paste sp_dc cookie from open.spotify.com")
        self.txt_sp_dc.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        self.txt_sp_dc.setFixedWidth(240)

        self.chk_lyrics_auto_scroll = ToggleSwitch(accent="#829c8e", checked=True)
        self.combo_media_background = QComboBox()
        self.combo_media_background.addItems(["Artwork", "Theme"])
        self.chk_media_players = ToggleSwitch(accent="#829c8e", checked=True)

        card_media = _create_setting_card([
            SettingRow("Player color", "Use album artwork or match the selected theme", self.combo_media_background),
            SettingRow("Player buttons", "Show buttons for switching between active media players", self.chk_media_players),
            SettingRow("Spotify cookie", "Optional sp_dc cookie for Spotify lyrics", self.txt_sp_dc),
            SettingRow("Follow playback", "Follow song timeline and center current line in real time", self.chk_lyrics_auto_scroll)
        ])
        l_media.addWidget(card_media)

        lbl_cookie_hint = QLabel(
            "Lyrics sources:\n"
            "Poppy looks for lyrics through LRCLIB and NetEase. Results depend on the track and provider.\n\n"
            "A Spotify sp_dc cookie is optional. Windows protects it for your account. "
            "Leave this blank to use the public providers."
        )
        set_widget_style(lbl_cookie_hint, """
            background-color: #1d2021;
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-radius: 8px;
            padding: 10px 12px;
            font-size: 10.5px;
            color: #9ca3a5;
        """)
        lbl_cookie_hint.setWordWrap(True)
        l_media.addWidget(lbl_cookie_hint)
        l_media.addStretch()

        self.stack.addWidget(_make_scroll_area(page_media))

        # =====================================================================
        # 6. Weather & Location Page
        # =====================================================================
        page_weath = QWidget()
        l_weath = QVBoxLayout(page_weath)
        l_weath.setContentsMargins(0, 0, 8, 0)
        l_weath.setSpacing(12)

        lbl_weath_hdr = QLabel("Weather")
        set_widget_style(lbl_weath_hdr, "font-size: 21px; font-weight: 600; color: #eef0f0;")
        lbl_weath_sub = QLabel("Weather stays off until you choose a location.")
        set_widget_style(lbl_weath_sub, "font-size: 12px; color: #9ca3a5;")
        l_weath.addWidget(lbl_weath_hdr)
        l_weath.addWidget(lbl_weath_sub)

        self.txt_weather_city = QLineEdit()
        self.txt_weather_city.setPlaceholderText("City or Auto-detect")
        self.txt_weather_city.setFixedWidth(220)

        self.combo_weather_unit = QComboBox()
        self.combo_weather_unit.addItems(["Celsius (°C)", "Fahrenheit (°F)"])
        self.combo_weather_unit.setFixedWidth(140)

        card_weath = _create_setting_card([
            SettingRow("Location", "Enter a city or type Auto-detect to look up your IP location", self.txt_weather_city),
            SettingRow("Temperature Unit", "Display temperatures in Celsius or Fahrenheit", self.combo_weather_unit)
        ])
        l_weath.addWidget(card_weath)
        l_weath.addStretch()

        self.stack.addWidget(_make_scroll_area(page_weath))

        # =====================================================================
        # 7. Pomodoro Page
        # =====================================================================
        page_pomo = QWidget()
        l_pomo = QVBoxLayout(page_pomo)
        l_pomo.setContentsMargins(0, 0, 8, 0)
        l_pomo.setSpacing(12)

        lbl_pomo_hdr = QLabel("Timer")
        set_widget_style(lbl_pomo_hdr, "font-size: 21px; font-weight: 600; color: #eef0f0;")
        lbl_pomo_sub = QLabel("Set your focus and break lengths.")
        set_widget_style(lbl_pomo_sub, "font-size: 12px; color: #9ca3a5;")
        l_pomo.addWidget(lbl_pomo_hdr)
        l_pomo.addWidget(lbl_pomo_sub)

        self.spin_pomo_work = QSpinBox()
        self.spin_pomo_work.setRange(1, 120)
        self.spin_pomo_work.setValue(25)

        self.spin_pomo_break = QSpinBox()
        self.spin_pomo_break.setRange(1, 60)
        self.spin_pomo_break.setValue(5)

        self.spin_pomo_long = QSpinBox()
        self.spin_pomo_long.setRange(1, 90)
        self.spin_pomo_long.setValue(15)

        self.chk_pomo_sound = ToggleSwitch(accent="#829c8e", checked=True)

        card_pomo = _create_setting_card([
            SettingRow("Focus", "Minutes dedicated to focused work", self.spin_pomo_work),
            SettingRow("Short break", "Minutes for quick recharge breaks", self.spin_pomo_break),
            SettingRow("Long break", "Minutes for extended recovery after 4 sprints", self.spin_pomo_long),
            SettingRow("Timer sound", "Play acoustic chime when sprint or break finishes", self.chk_pomo_sound)
        ])
        l_pomo.addWidget(card_pomo)
        l_pomo.addStretch()

        self.stack.addWidget(_make_scroll_area(page_pomo))

        # =====================================================================
        # 8. Discord RPC Page
        # =====================================================================
        page_rpc = QWidget()
        l_rpc = QVBoxLayout(page_rpc)
        l_rpc.setContentsMargins(0, 0, 8, 0)
        l_rpc.setSpacing(12)

        lbl_rpc_hdr = QLabel("Discord")
        set_widget_style(lbl_rpc_hdr, "font-size: 21px; font-weight: 600; color: #eef0f0;")
        lbl_rpc_sub = QLabel("Broadcast active Spotify media and Pomodoro status to Discord.")
        set_widget_style(lbl_rpc_sub, "font-size: 12px; color: #9ca3a5;")
        l_rpc.addWidget(lbl_rpc_hdr)
        l_rpc.addWidget(lbl_rpc_sub)

        self.chk_rpc_enable = ToggleSwitch(accent="#829c8e", checked=False)

        self.txt_rpc_client = QLineEdit()
        self.txt_rpc_client.setPlaceholderText("Enter Discord Client ID")
        self.txt_rpc_client.setFixedWidth(200)

        self.combo_rpc_mode = QComboBox()
        self.combo_rpc_mode.addItems(["Dynamic (Follows Pomodoro & Media)", "Static Custom Presence"])

        card_rpc = _create_setting_card([
            SettingRow("Share activity", "Broadcast active Poppy activity to Discord profile", self.chk_rpc_enable),
            SettingRow("Application ID", "Discord Developer Portal application ID", self.txt_rpc_client),
            SettingRow("Status mode", "Dynamic sync (Media & Pomodoro) or static status", self.combo_rpc_mode)
        ])
        l_rpc.addWidget(card_rpc)
        l_rpc.addStretch()

        self.stack.addWidget(_make_scroll_area(page_rpc))

        # =====================================================================
        # 9. Hardware HUD Page
        # =====================================================================
        page_hw = QWidget()
        l_hw = QVBoxLayout(page_hw)
        l_hw.setContentsMargins(0, 0, 8, 0)
        l_hw.setSpacing(12)

        lbl_hw_hdr = QLabel("System")
        set_widget_style(lbl_hw_hdr, "font-size: 21px; font-weight: 600; color: #eef0f0;")
        lbl_hw_sub = QLabel("Choose which background monitors run.")
        set_widget_style(lbl_hw_sub, "font-size: 12px; color: #9ca3a5;")
        l_hw.addWidget(lbl_hw_hdr)
        l_hw.addWidget(lbl_hw_sub)

        self.chk_monitor_gpu = ToggleSwitch(accent="#829c8e", checked=True)
        self.chk_monitor_bat = ToggleSwitch(accent="#829c8e", checked=True)

        card_hw = _create_setting_card([
            SettingRow("GPU monitoring", "Show GPU utilization on supported NVIDIA devices", self.chk_monitor_gpu),
            SettingRow("Battery monitoring", "Monitor laptop battery percentage and charging state", self.chk_monitor_bat)
        ])
        l_hw.addWidget(card_hw)
        l_hw.addStretch()

        self.stack.addWidget(_make_scroll_area(page_hw))

        # =====================================================================
        # 10. About & System Page
        # =====================================================================
        page_abt = QWidget()
        l_abt = QVBoxLayout(page_abt)
        l_abt.setContentsMargins(0, 0, 8, 0)
        l_abt.setSpacing(12)

        lbl_abt_hdr = QLabel("Poppy")
        set_widget_style(lbl_abt_hdr, "font-size: 21px; font-weight: 600; color: #eef0f0;")
        lbl_abt_ver = QLabel(f"Version {APP_VERSION} · Windows 10 and 11")
        set_widget_style(lbl_abt_ver, "font-size: 12px; color: #9ca3a5;")
        lbl_abt_desc = QLabel("A small desktop panel for music, files, notes and focus.\n")
        set_widget_style(lbl_abt_desc, "font-size: 12px; color: #939a9c; ")
        l_abt.addWidget(lbl_abt_hdr)
        l_abt.addWidget(lbl_abt_ver)
        l_abt.addWidget(lbl_abt_desc)

        btn_open_cfg = QPushButton("Edit config.json")
        btn_open_cfg.setCursor(Qt.CursorShape.PointingHandCursor)
        set_widget_style(btn_open_cfg, """
            QPushButton {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 5px 12px;
                color: #e3e7e7;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.12);
                color: #ffffff;
            }
        """)
        btn_open_cfg.clicked.connect(self._open_config_file)

        btn_open_folder = QPushButton("Open app folder")
        btn_open_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        set_widget_style(btn_open_folder, """
            QPushButton {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 5px 12px;
                color: #e3e7e7;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.12);
                color: #ffffff;
            }
        """)
        btn_open_folder.clicked.connect(self._open_poppy_folder)
        btn_open_data = QPushButton("Open data folder")
        btn_open_data.clicked.connect(self._open_data_folder)
        btn_updates = QPushButton("Check for updates")
        btn_updates.clicked.connect(self.update_check_requested)
        self.chk_update_notifications = ToggleSwitch(checked=True)

        card_abt = _create_setting_card([
            SettingRow("Configuration", "Open config.json directly in your default editor", btn_open_cfg),
            SettingRow("App folder", "Browse the Poppy installation", btn_open_folder),
            SettingRow("User data", "Open the local folder for settings, notes and history", btn_open_data),
            SettingRow("Updates", "Check GitHub for a newer installer", btn_updates),
            SettingRow("Update notifications", "Check daily when running the installed app", self.chk_update_notifications),
        ])
        l_abt.addWidget(card_abt)
        l_abt.addStretch()

        self.stack.addWidget(_make_scroll_area(page_abt))

        right_layout.addWidget(self.stack, stretch=1)
        right_layout.addWidget(self.no_search_results, stretch=1)

        # Bottom Action Footer
        bottom_bar = QHBoxLayout()
        bottom_bar.setContentsMargins(4, 4, 4, 0)

        lbl_auto_save = QLabel("Close to cancel · Done to save")
        set_widget_style(lbl_auto_save, "font-size: 10.5px; color: #939a9c; background: transparent; border: none;")
        lbl_auto_save.setProperty("singleLine", True)
        bottom_bar.addWidget(lbl_auto_save, 1)

        self.btn_done = QPushButton("Done")
        self.btn_done.setCursor(Qt.CursorShape.PointingHandCursor)
        set_widget_style(self.btn_done, """
            QPushButton {
                background-color: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 8px;
                padding: 7px 24px;
                font-size: 12px;
                font-weight: 600;
                color: #eef0f0;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.16);
                border: 1px solid rgba(255, 255, 255, 0.22);
                color: #ffffff;
            }
        """)
        self.btn_done.clicked.connect(self._save_and_close)
        self.btn_save = self.btn_done
        self.btn_close = self.btn_done
        bottom_bar.addWidget(self.btn_done)

        right_layout.addLayout(bottom_bar)

        main_layout.addWidget(right_container, stretch=1)
        for label in self.findChildren(QLabel):
            if not label.minimumWidth() and label.maximumWidth() == 16777215 and not label.property("singleLine"):
                label.setWordWrap(True)
        for control in self.findChildren(QWidget):
            if isinstance(control, (QSlider, QSpinBox, QComboBox, ValueEdit)):
                control.installEventFilter(self)
        self.nav_list.setCurrentRow(0)

    def _save_and_close(self):
        if self._save_settings():
            self.close()

    def closeEvent(self, event):
        self._preview_timer.stop()
        self.blockSignals(True)
        try:
            self._load_values()
        finally:
            self.blockSignals(False)
        appearance = normalize_appearance(self.config.get("appearance", {}))
        self.appearance_live_updated.emit(appearance)
        layout_changed = current_layout() != appearance["layout"]
        if configure_theme(appearance) or layout_changed:
            refresh_theme()
        self._last_preview = self._appearance_values()
        super().closeEvent(event)

    def _open_config_file(self):
        cfg_path = data_path("config.json")
        try:
            os.startfile(str(cfg_path))
        except Exception:
            pass

    def _open_poppy_folder(self):
        folder_path = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
        try:
            os.startfile(str(folder_path))
        except Exception:
            pass

    def _open_data_folder(self):
        folder = data_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(str(folder))
        except OSError as error:
            QMessageBox.warning(self, "Could not open user data", str(error))

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel and isinstance(watched, (QSlider, QSpinBox, QComboBox, ValueEdit)):
            if isinstance(watched, QComboBox) and watched.view().isVisible():
                return super().eventFilter(watched, event)
            area = watched.parentWidget()
            while area is not None and not isinstance(area, QScrollArea):
                area = area.parentWidget()
            if area is not None:
                viewport = area.viewport()
                wheel = QWheelEvent(QPointF(viewport.mapFromGlobal(event.globalPosition().toPoint())),
                    event.globalPosition(), event.pixelDelta(), event.angleDelta(), event.buttons(),
                    event.modifiers(), event.phase(), event.inverted(), event.source())
                QApplication.sendEvent(viewport, wheel)
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def _make_slider_setting(self, title: str, subtitle: str, min_v: int, max_v: int, default_v: int):
        slider = ClickableSlider(Qt.Orientation.Horizontal)
        slider.setRange(min_v, max_v)
        slider.setValue(default_v)
        slider.setFixedWidth(130)
        slider.setAccessibleName(title)

        value_input = ValueEdit(min_v, max_v, default_v)
        value_input.setFixedWidth(60)
        value_input.setAccessibleName(f"{title}, exact value")
        value_input.setToolTip(f"Type a value from {min_v} to {max_v}")
        set_widget_style(value_input, "QLineEdit { background: transparent; color: #c9d0cf; border: 1px solid transparent; border-radius: 4px; padding: 3px 4px; } QLineEdit:focus { border-color: #3a8b73; }")
        slider.valueChanged.connect(value_input.setValue)
        value_input.valueEdited.connect(slider.setValue)
        slider.valueChanged.connect(self._queue_appearance_preview)
        slider.sliderReleased.connect(self._on_live_appearance_change)
        value_input.editingFinished.connect(self._on_live_appearance_change)

        ctrl_wrap = QWidget()
        set_widget_style(ctrl_wrap, "background: transparent;")
        ctrl_l = QHBoxLayout(ctrl_wrap)
        ctrl_l.setContentsMargins(0, 0, 0, 0)
        ctrl_l.setSpacing(8)
        ctrl_l.addWidget(slider)
        ctrl_l.addWidget(value_input)
        row = SettingRow(title, subtitle, ctrl_wrap)
        return slider, value_input, row

    def _queue_appearance_preview(self):
        if not self._loading_values and not self._preview_timer.isActive():
            self._preview_timer.start()

    def _on_nav_changed(self, row: int):
        if row >= 0:
            self.stack.setCurrentIndex(row)
            match = self._settings_search_match(row, self.search_settings.text().casefold().split())
            if isinstance(match, SettingRow):
                self.stack.widget(row).ensureWidgetVisible(match, 0, 12)

    def _settings_search_match(self, index, terms):
        if not terms:
            return True
        title = self.nav_list.item(index).text().casefold()
        if all(term in title for term in terms):
            return True
        for row in self.stack.widget(index).findChildren(SettingRow):
            if all(term in f"{title} {row.search_text}" for term in terms):
                return row
        return False

    def _filter_settings(self, query):
        terms = query.casefold().split()
        matching = []
        for index in range(self.nav_list.count()):
            match = self._settings_search_match(index, terms)
            self.nav_list.item(index).setHidden(not match)
            if match:
                matching.append(index)
        current = self.nav_list.currentRow()
        self.no_search_results.setVisible(not matching)
        if not matching:
            self.stack.hide()
        else:
            self.stack.show()
            if current not in matching:
                self.nav_list.setCurrentRow(matching[0])
            else:
                self._on_nav_changed(current)

    def _choose_download_folder(self):
        initial = self.download_folder.text() or str(default_download_folder())
        folder = QFileDialog.getExistingDirectory(self, "Choose download folder", initial)
        if folder:
            self.download_folder.setText(os.path.normpath(folder))

    def _on_theme_changed(self, theme_key: str):
        self._on_live_appearance_change()

    def _get_current_selected_theme(self) -> str:
        return self.combo_theme.currentText() or DEFAULT_THEME

    def _set_peek_color(self, color):
        self._peek_color = color.name()
        swatch = QPixmap(16, 12)
        swatch.fill(color)
        self.btn_peek_color.setIcon(QIcon(swatch))
        self.btn_peek_color.setText(self._peek_color.upper())

    def _on_peek_color_changed(self):
        self.btn_peek_color.setEnabled(self.combo_peek_color.currentData() == "fixed")
        self._on_live_appearance_change()

    def _choose_peek_color(self):
        color = QColorDialog.getColor(QColor(self._peek_color), self, "Hover player color")
        if color.isValid():
            self._set_peek_color(color)
            self._on_live_appearance_change()

    def _appearance_values(self):
        return {
            "theme": self._get_current_selected_theme(),
            "layout": self.combo_layout.currentText(),
            "home_orders": {name: list(order) for name, order in self._home_orders.items()},
            "mode": "System" if self.combo_mode.currentIndex() == 2 else self.combo_mode.currentText(),
            "style": self.combo_style.currentText(),
            "peek_color_source": self.combo_peek_color.currentData(),
            "peek_color": self._peek_color,
            "collapsed_width": self.slider_col_w.value(),
            "collapsed_height": self.slider_col_h.value(),
            "layout_version": APPEARANCE_LAYOUT_VERSION,
            "open_width": self.slider_open_w.value(),
            "open_height": self.slider_open_h.value(),
            "corner_radius": self.slider_radius.value(),
            "top_offset": self.slider_top_offset.value(),
            "display": self.combo_display.currentText()
        }

    def _on_live_appearance_change(self):
        if self._loading_values:
            return
        self._preview_timer.stop()
        appearance = self._appearance_values()
        if appearance == self._last_preview:
            return
        self._last_preview = appearance
        self.appearance_live_updated.emit(appearance)
        layout_changed = current_layout() != appearance["layout"]
        if configure_theme(appearance) or layout_changed:
            refresh_theme()
        self._update_layout_preview()

    def _update_layout_preview(self):
        name = self.combo_layout.currentText()
        self.layout_preview.apply_layout(name, home_order(name, self._home_orders))
        self.lbl_layout_description.setText(LAYOUT_THEMES[name]["description"])

    def _on_home_order_changed(self, order):
        self._home_orders[self.combo_layout.currentText()] = list(order)
        self._on_live_appearance_change()

    def _reset_home_order(self):
        self._home_orders.pop(self.combo_layout.currentText(), None)
        self._on_live_appearance_change()
        self._update_layout_preview()

    def _load_values(self):
        self._loading_values = True
        try:
            self._load_control_values()
        finally:
            self._loading_values = False
        self._update_layout_preview()

    def _load_control_values(self):
        self.chk_update_notifications.setChecked(self.config.get("updates", {}).get("automatic", True), animate=False)
        self.chk_clipboard_history.setChecked(self.config.get("clipboard", {}).get("enabled", False), animate=False)
        self.chk_app_mixer.setChecked(self.config.get("mixer", {}).get("enabled", True), animate=False)
        downloads = self.config.get("downloads", {})
        self.chk_downloads.setChecked(downloads.get("enabled", False), animate=False)
        self.download_folder.setText(downloads.get("folder", ""))
        self.chk_pill_levels.setChecked(self.config.get("notch", {}).get("pill_levels", True), animate=False)
        self.chk_capture_images.setChecked(self.config.get("capture", {}).get("enabled", False), animate=False)
        # 0. Appearance
        app_cfg = normalize_appearance(self.config.get("appearance", {}))
        self._set_peek_color(QColor(app_cfg["peek_color"]))
        self.combo_peek_color.setCurrentIndex(self.combo_peek_color.findData(app_cfg["peek_color_source"]))
        self.btn_peek_color.setEnabled(app_cfg["peek_color_source"] == "fixed")
        hidden = app_cfg.get("hidden_home_sections", [])
        hidden = hidden if isinstance(hidden, list) else []
        for key, checkbox in self._home_section_checks.items():
            if key != "screentime":
                checkbox.setChecked(key not in hidden)
        self._home_orders = {name: list(order) for name, order in app_cfg.get("home_orders", {}).items()}
        self.combo_layout.setCurrentText(app_cfg.get("layout", "Classic"))
        self.combo_mode.setCurrentIndex({"Dark": 0, "Light": 1, "System": 2}.get(app_cfg.get("mode"), 0))
        active_theme = app_cfg.get("theme", DEFAULT_THEME)
        self.combo_theme.blockSignals(True)
        self.combo_theme.setCurrentText(active_theme)
        self.combo_theme.blockSignals(False)

        style = app_cfg.get("style", "Notch")
        idx = self.combo_style.findText(style)
        if idx >= 0:
            self.combo_style.setCurrentIndex(idx)

        display = app_cfg.get("display", "Primary")
        d_idx = self.combo_display.findText(display)
        if d_idx >= 0:
            self.combo_display.setCurrentIndex(d_idx)

        self.slider_col_w.setValue(app_cfg.get("collapsed_width", 240))
        self.slider_col_h.setValue(app_cfg.get("collapsed_height", 30))
        self.slider_open_w.setValue(app_cfg["open_width"])
        self.slider_open_h.setValue(app_cfg["open_height"])
        self.slider_radius.setValue(app_cfg.get("corner_radius", 22))
        self.slider_top_offset.setValue(app_cfg.get("top_offset", 0))

        # 1. Tabs
        tabs_cfg = self.config.get("tabs", {})
        enabled_tabs = tabs_cfg.get("enabled", [name for name, _ in ALL_AVAILABLE_TABS])
        for name, chk in self._tab_checkboxes.items():
            chk.setChecked(name in enabled_tabs, animate=False)

        dtab = self.config.get("notch", {}).get("default_tab", "Smart")
        index = 0 if dtab == "Smart" else self.combo_default_tab.findText(dtab)
        self.combo_default_tab.setCurrentIndex(max(0, index))

        # 2. Behavior
        notch_cfg = self.config.get("notch", {})
        self.chk_hover_peek.setChecked(notch_cfg.get("auto_hover_peek", True), animate=False)
        self.chk_scroll_volume.setChecked(notch_cfg.get("scroll_volume", True), animate=False)
        self.spin_anim_ms.setValue(notch_cfg.get("animation_duration_ms", 200))
        self.chk_tray_close.setChecked(notch_cfg.get("keep_in_tray", True), animate=False)
        self.chk_autostart.setChecked(get_autostart_state(), animate=False)

        # 3. Notifications
        notif_cfg = self.config.get("notifications", {})
        self.chk_notif_enabled.setChecked(notif_cfg.get("enabled", True), animate=False)
        self.chk_notif_show_island.setChecked(notif_cfg.get("show_island_on_notify", True), animate=False)
        self.chk_notif_mute_focus.setChecked(notif_cfg.get("mute_in_focus", True), animate=False)
        self.chk_notif_sound.setChecked(notif_cfg.get("sound", True), animate=False)
        self.chk_notif_preview.setChecked(notif_cfg.get("preview_text", True), animate=False)

        # 4. Screen Time
        st_cfg = self.config.get("screentime", {})
        self.chk_st_enabled.setChecked(st_cfg.get("enabled", True), animate=False)
        self.chk_st_show_main_menu.setChecked(st_cfg.get("show_in_main_menu", True), animate=False)
        self.chk_st_track_apps.setChecked(st_cfg.get("track_apps", True), animate=False)

        afk_sec = st_cfg.get("idle_threshold_seconds", 120)
        for i in range(self.combo_st_afk.count()):
            if self.combo_st_afk.itemData(i) == afk_sec:
                self.combo_st_afk.setCurrentIndex(i)
                break

        goal_h = int(st_cfg.get("daily_goal_hours", 6))
        self.slider_st_goal.setValue(goal_h)
        self.lbl_goal_val.setText(f"{goal_h} hrs")

        self.chk_st_goal_alert.setChecked(st_cfg.get("goal_alert_enabled", True), animate=False)
        self.chk_st_break_reminder.setChecked(st_cfg.get("break_reminders_enabled", True), animate=False)

        break_int = st_cfg.get("break_interval_minutes", 60)
        for i in range(self.combo_st_break_interval.count()):
            if self.combo_st_break_interval.itemData(i) == break_int:
                self.combo_st_break_interval.setCurrentIndex(i)
                break

        excl_list = st_cfg.get("excluded_apps", [])
        self.txt_st_excluded.setText(", ".join(excl_list))

        # 5. Media & Lyrics
        media_cfg = self.config.get("media", {})
        self.combo_media_background.setCurrentIndex(1 if media_cfg.get("background") == "theme" else 0)
        self.chk_media_players.setChecked(media_cfg.get("show_player_tiles", True), animate=False)
        self.txt_sp_dc.setText(spotify_cookie(media_cfg))
        self.chk_lyrics_auto_scroll.setChecked(media_cfg.get("auto_scroll_lyrics", True), animate=False)

        # 6. Weather
        w_cfg = self.config.get("weather", {})
        self.txt_weather_city.setText(str(w_cfg.get("city") or ""))
        u_idx = 1 if w_cfg.get("unit", "celsius").lower() == "fahrenheit" else 0
        self.combo_weather_unit.setCurrentIndex(u_idx)

        # 7. Pomodoro
        pomo_cfg = self.config.get("pomodoro", {})
        self.spin_pomo_work.setValue(pomo_cfg.get("work_duration", 1500) // 60)
        self.spin_pomo_break.setValue(pomo_cfg.get("break_duration", 300) // 60)
        self.spin_pomo_long.setValue(pomo_cfg.get("long_break_duration", 900) // 60)
        self.chk_pomo_sound.setChecked(pomo_cfg.get("sound_enabled", True), animate=False)

        # 8. Discord RPC
        rpc_cfg = self.config.get("discord_rpc", {})
        self.chk_rpc_enable.setChecked(rpc_cfg.get("enabled", False), animate=False)
        self.txt_rpc_client.setText(rpc_cfg.get("client_id", "120000000000000000"))
        mode_idx = 0 if rpc_cfg.get("mode") == "dynamic" else 1
        self.combo_rpc_mode.setCurrentIndex(mode_idx)

        # 9. Hardware HUD
        hw_cfg = self.config.get("hardware_hud", {})
        self.chk_monitor_gpu.setChecked(hw_cfg.get("monitor_gpu", True), animate=False)
        self.chk_monitor_bat.setChecked(hw_cfg.get("monitor_battery", True), animate=False)

    def _save_settings(self):
        self._preview_timer.stop()
        try:
            protected_cookie = protect_spotify_cookie(self.txt_sp_dc.text().strip())
        except OSError as error:
            QMessageBox.warning(self, "Settings were not saved", str(error))
            return False
        # Always retain one usable tab.
        enabled_tabs = [name for name, chk in self._tab_checkboxes.items() if chk.isChecked()]
        if not enabled_tabs:
            enabled_tabs = ["Home"]

        sel_dtab_txt = self.combo_default_tab.currentText()
        if self.combo_default_tab.currentIndex() == 0:
            saved_dtab = "Smart"
        else:
            saved_dtab = sel_dtab_txt

        unit_str = "fahrenheit" if self.combo_weather_unit.currentIndex() == 1 else "celsius"
        city_str = self.txt_weather_city.text().strip()

        new_config = {
            "clipboard": {"enabled": self.chk_clipboard_history.isChecked()},
            "capture": {"enabled": self.chk_capture_images.isChecked()},
            "mixer": {"enabled": self.chk_app_mixer.isChecked()},
            "downloads": {"enabled": self.chk_downloads.isChecked(), "folder": self.download_folder.text()},
            "updates": {"automatic": self.chk_update_notifications.isChecked()},
            "appearance": {
                **self._appearance_values(),
                "hidden_home_sections": [key for key, checkbox in self._home_section_checks.items()
                                         if key != "screentime" and not checkbox.isChecked()],
            },
            "tabs": {
                "enabled": enabled_tabs
            },
            "notifications": {
                "enabled": self.chk_notif_enabled.isChecked(),
                "show_island_on_notify": self.chk_notif_show_island.isChecked(),
                "mute_in_focus": self.chk_notif_mute_focus.isChecked(),
                "sound": self.chk_notif_sound.isChecked(),
                "preview_text": self.chk_notif_preview.isChecked(),
            },
            "screentime": {
                "enabled": self.chk_st_enabled.isChecked(),
                "show_in_main_menu": self.chk_st_show_main_menu.isChecked(),
                "track_apps": self.chk_st_track_apps.isChecked(),
                "idle_threshold_seconds": self.combo_st_afk.currentData() or 120,
                "daily_goal_hours": self.slider_st_goal.value(),
                "goal_alert_enabled": self.chk_st_goal_alert.isChecked(),
                "break_reminders_enabled": self.chk_st_break_reminder.isChecked(),
                "break_interval_minutes": self.combo_st_break_interval.currentData() or 60,
                "excluded_apps": [x.strip() for x in self.txt_st_excluded.text().split(",") if x.strip()]
            },
            "media": {
                "background": "theme" if self.combo_media_background.currentIndex() == 1 else "artwork",
                "show_player_tiles": self.chk_media_players.isChecked(),
                "spotify_sp_dc_protected": protected_cookie,
                "auto_scroll_lyrics": self.chk_lyrics_auto_scroll.isChecked()
            },
            "weather": {
                "city": city_str,
                "unit": unit_str
            },
            "pomodoro": {
                "work_duration": self.spin_pomo_work.value() * 60,
                "break_duration": self.spin_pomo_break.value() * 60,
                "long_break_duration": self.spin_pomo_long.value() * 60,
                "sound_enabled": self.chk_pomo_sound.isChecked(),
            },
            "notch": {
                "auto_hover_peek": self.chk_hover_peek.isChecked(),
                "scroll_volume": self.chk_scroll_volume.isChecked(),
                "pill_levels": self.chk_pill_levels.isChecked(),
                "default_tab": saved_dtab,
                "animation_duration_ms": self.spin_anim_ms.value(),
                "keep_in_tray": self.chk_tray_close.isChecked(),
                "autostart": self.chk_autostart.isChecked()
            },
            "discord_rpc": {
                "enabled": self.chk_rpc_enable.isChecked(),
                "client_id": self.txt_rpc_client.text().strip(),
                "mode": "dynamic" if self.combo_rpc_mode.currentIndex() == 0 else "custom",
                "custom_presence": self.config.get("discord_rpc", {}).get("custom_presence", {}),
                "dynamic_templates": self.config.get("discord_rpc", {}).get("dynamic_templates", {}),
            },
            "hardware_hud": {
                "monitor_gpu": self.chk_monitor_gpu.isChecked(),
                "monitor_battery": self.chk_monitor_bat.isChecked(),
            }
        }

        # Preserve settings that this window does not edit.
        merged_config = dict(self.config)
        for section, values in new_config.items():
            previous = merged_config.get(section, {})
            merged_config[section] = {**(previous if isinstance(previous, dict) else {}), **values}
        new_config = merged_config
        new_config["media"].pop("spotify_sp_dc", None)
        cfg_path = data_path("config.json")
        try:
            write_json(cfg_path, new_config)
        except OSError as error:
            QMessageBox.warning(self, "Settings were not saved", str(error))
            return False

        requested = self.chk_autostart.isChecked()
        if requested != get_autostart_state() and not set_autostart_state(requested):
            QMessageBox.warning(self, "Startup was not changed", "Your other settings were saved. Windows startup could not be changed.")

        self.config = new_config
        self.settings_saved.emit(new_config)
        return True

    def _on_screentime_reset_clicked(self):
        self.screentime_reset_requested.emit()
        self.lbl_st_today_time.setText("0m")
        self.lbl_st_goal_pct.setText("Goal: 0%")
        self.bar_st_goal.setValue(0)
        self.lbl_st_streak.setText("Active streak: 0m")
        self.lbl_st_top_apps.setText("Reset complete.")

    def update_screentime_display(self, total_sec: int, streak_sec: int, top_apps: list, active_app: str, goal_hours: float):
        h = total_sec // 3600
        m = (total_sec % 3600) // 60
        time_str = f"{h}h {m:02d}m" if h > 0 else f"{m}m"
        self.lbl_st_today_time.setText(time_str)

        goal_sec = max(1.0, goal_hours * 3600.0)
        pct = min(100, int((total_sec / goal_sec) * 100))
        self.lbl_st_goal_pct.setText(f"Goal: {pct}% of {int(goal_hours)}h")
        self.bar_st_goal.setValue(pct)

        self.lbl_st_streak.setText(f"Active streak: {streak_sec // 60}m")

        if top_apps:
            app_text = "Top Apps: " + "  •  ".join(f"{name}: {fmt}" for name, sec, fmt in top_apps[:3])
            self.lbl_st_top_apps.setText(app_text)
        else:
            self.lbl_st_top_apps.setText(f"Active now: {active_app}")

    def select_page(self, page_name: str):
        self.search_settings.clear()
        aliases = {"tabs manager": "tools", "media & lyrics": "music", "pomodoro": "timer", "hardware hud": "system", "about & system": "about"}
        target = aliases.get(page_name.strip().lower(), page_name.strip().lower())
        for idx in range(self.nav_list.count()):
            text = self.nav_list.item(idx).text().strip().lower()
            if target in text:
                self.nav_list.setCurrentRow(idx)
                break
