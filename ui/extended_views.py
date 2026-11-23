"""Calendar, clipboard, PDF tools, commands, and Windows desktop views."""

import ast
import operator as op
import os
import sys
import json
import time
import calendar
from datetime import datetime, date
from html import escape
from pathlib import Path
from urllib.parse import unquote_plus, urlsplit
import subprocess
import ctypes
import uuid
import threading

from PySide6.QtCore import (
    Qt, QRect, QRectF, QPoint, QSize, Signal, QTimer, QUrl, QMimeData, QDate, QEvent
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPainterPath, QCursor, QFont,
    QPageSize, QTextDocument, QPdfWriter, QShortcut, QKeySequence
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QScrollArea, QFrame, QApplication, QFileDialog, QMessageBox, QLayout, QBoxLayout, QSizePolicy, QListWidget, QListWidgetItem
)
from PySide6.QtCore import QSaveFile, QIODevice
from shiboken6 import isValid

from poppy.ui.theme import contrast_ink, set_widget_style
from poppy.ui.icons import Icons, get_fluent_font_family
from poppy.ui.components import CardFrame, IconButton, DraggableThumbnail, ScrollArea, StatRingGauge
from poppy.core.annotation_wheel import AnnotationWheel
from poppy.core.system_tools import lock_workstation
from poppy.core.system_features import current_desktop_windows, activate_desktop_window
from poppy.core.storage import data_path, write_json


_WINDOW_LIST_STYLE = """
    QListWidget { background: #1b2027; color: #f1f5f9;
                  border: 1px solid rgba(255,255,255,0.12); border-radius: 6px; padding: 4px; }
    QListWidget:focus { border-color: rgba(255,255,255,0.55); }
    QListWidget::item { padding: 6px 8px; border-radius: 4px; }
    QListWidget::item:hover { background: rgba(255,255,255,0.08); }
    QListWidget::item:selected { background: rgba(255,255,255,0.16); color: #f1f5f9; }
"""


# =====================================================================
# 1. Calendar Tab View
# =====================================================================

class CalendarTabView(QWidget):
    """
    Interactive month calendar with event scheduling and agenda management.
    Stores events persistently in ~/.poppy/calendar_events.json.
    """
    def __init__(self, parent=None, accent="#6e9bff"):
        super().__init__(parent)
        self._accent = accent
        today = date.today()
        self.current_year = today.year
        self.current_month = today.month
        self.selected_date = today
        self._day_buttons = {}

        self.store_file = data_path("calendar_events.json")
        self.store_file.parent.mkdir(parents=True, exist_ok=True)
        self.events: dict[str, list[dict]] = self._load_events()

        self._init_ui()

    def _load_events(self) -> dict:
        if self.store_file.exists():
            try:
                return json.loads(self.store_file.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_events(self):
        try:
            write_json(self.store_file, self.events)
        except OSError as error:
            QMessageBox.warning(self, "Calendar not saved", str(error))

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(14, 10, 14, 12)
        main_layout.setSpacing(16)

        # Left Column: Interactive Month Calendar
        left_col = QVBoxLayout()
        left_col.setSpacing(8)

        # Header: Month & Navigation
        hdr_row = QHBoxLayout()
        hdr_row.setContentsMargins(4, 0, 4, 0)
        self.lbl_month_year = QLabel()
        set_widget_style(self.lbl_month_year, "font-size: 16px; font-weight: 600; color: #f8fafc; border: none; background: transparent;")

        btn_prev = IconButton(Icons.PREV, "Previous Month", size=24, font_size=11, is_fluent=True)
        btn_prev.clicked.connect(self._prev_month)
        btn_today = QPushButton("Today")
        btn_today.setMinimumHeight(24)
        btn_today.clicked.connect(self._go_today)
        btn_next = IconButton(Icons.NEXT, "Next Month", size=24, font_size=11, is_fluent=True)
        btn_next.clicked.connect(self._next_month)

        hdr_row.addWidget(self.lbl_month_year)
        hdr_row.addStretch()
        hdr_row.addWidget(btn_prev)
        hdr_row.addWidget(btn_today)
        hdr_row.addWidget(btn_next)
        left_col.addLayout(hdr_row)

        # Calendar Grid
        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(4)
        left_col.addWidget(self.grid_widget)
        left_col.addStretch(1)
        main_layout.addLayout(left_col, stretch=3)

        # Right Column: Agenda & Selected Date Schedule
        card_agenda = CardFrame(self)
        l_agenda = QVBoxLayout(card_agenda)
        l_agenda.setContentsMargins(14, 12, 14, 12)
        l_agenda.setSpacing(8)

        self.lbl_agenda_date = QLabel()
        set_widget_style(self.lbl_agenda_date, "font-size: 12px; font-weight: 600; color: #e2e8f0; border: none; background: transparent;")
        l_agenda.addWidget(self.lbl_agenda_date)

        # Event List Scroll Area
        self.events_scroll = ScrollArea()
        self.events_scroll.setWidgetResizable(True)
        self.events_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        set_widget_style(self.events_scroll, "QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget { border: none; background: transparent; }")
        self.events_container = QWidget()
        self.events_layout = QVBoxLayout(self.events_container)
        self.events_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.events_layout.setContentsMargins(0, 0, 0, 0)
        self.events_layout.setSpacing(4)
        self.events_scroll.setWidget(self.events_container)
        l_agenda.addWidget(self.events_scroll, stretch=1)

        # Add Event Row
        add_row = QHBoxLayout()
        add_row.setSpacing(8)
        self.input_event = QLineEdit()
        self.input_event.setPlaceholderText("Event title")
        self.input_event.setAccessibleName("Event title")
        self.input_event.setMinimumWidth(0)
        self.input_event.returnPressed.connect(self._add_event)

        self.btn_add = QPushButton("Add event")
        self.btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add.clicked.connect(self._add_event)
        add_row.addWidget(self.input_event, stretch=1)
        add_row.addWidget(self.btn_add)
        l_agenda.addLayout(add_row)

        main_layout.addWidget(card_agenda, stretch=2)

        self.set_accent(self._accent)
        self._render_calendar()
        self._render_agenda()

    def _accent_button_style(self, radius, padding):
        # Author the fill and its ink together. Light mode must not recolor one independently.
        ink = contrast_ink(QColor(self._accent))
        return f"""
            QPushButton {{ background: {self._accent}; color: {ink}; border: 2px solid transparent;
                           border-radius: {radius}px; padding: {padding}; font-size: 12px; font-weight: 600; }}
            QPushButton:hover, QPushButton[poppyKeyboardFocus="true"]:focus {{ border-color: {ink}; }}
        """

    def set_accent(self, accent):
        self._accent = accent
        self.btn_add.setStyleSheet(self._accent_button_style(6, "2px 8px"))
        for day, button in self._day_buttons.items():
            self._style_day(day, button)

    def _style_day(self, day, button):
        today = day == date.today()
        selected = day == self.selected_date
        events = bool(self.events.get(day.isoformat()))
        button.setText(f"{day.day} ·" if events else str(day.day))
        label = day.strftime("%A, %d %B %Y")
        button.setAccessibleName(label + (", today" if today else "") + (", has events" if events else ""))
        button.setToolTip(button.accessibleName())
        button.setChecked(selected)
        if selected:
            button.setProperty("poppyStyleSource", None)
            button.setStyleSheet(self._accent_button_style(8, "0"))
        else:
            set_widget_style(button, """
                QPushButton { background: rgba(255,255,255,0.04); color: #e2e8f0;
                              border: 2px solid transparent; border-radius: 8px; padding: 0; }
                QPushButton:hover { background: rgba(255,255,255,0.12); }
                QPushButton:focus { border-color: rgba(255,255,255,0.65); }
            """)
        font = button.font()
        font.setUnderline(today)
        button.setFont(font)

    def _render_calendar(self):
        # Clear existing grid
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self._day_buttons.clear()

        month_name = calendar.month_name[self.current_month]
        self.lbl_month_year.setText(f"{month_name} {self.current_year}")

        # Weekday headers
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for col, d in enumerate(days):
            lbl_d = QLabel(d)
            lbl_d.setAlignment(Qt.AlignmentFlag.AlignCenter)
            set_widget_style(lbl_d, "font-size: 12px; color: #a7b2bf; border: none; background: transparent;")
            self.grid_layout.addWidget(lbl_d, 0, col)

        # Days cells
        month_cal = calendar.monthcalendar(self.current_year, self.current_month)
        for row_idx, week in enumerate(month_cal, start=1):
            for col_idx, day_num in enumerate(week):
                if day_num == 0:
                    continue
                cell_date = date(self.current_year, self.current_month, day_num)
                btn_day = QPushButton()
                btn_day.setFixedSize(36, 32)
                btn_day.setCheckable(True)
                btn_day.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_day.clicked.connect(lambda checked=False, cd=cell_date: self._select_date(cd))
                self._day_buttons[cell_date] = btn_day
                self._style_day(cell_date, btn_day)
                self.grid_layout.addWidget(btn_day, row_idx, col_idx, Qt.AlignmentFlag.AlignHCenter)

    def _select_date(self, dt: date):
        previous = self.selected_date
        self.selected_date = dt
        for day in {previous, dt}:
            if day in self._day_buttons:
                self._style_day(day, self._day_buttons[day])
        self._render_agenda()

    def _render_agenda(self):
        while self.events_layout.count():
            item = self.events_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()

        date_str = self.selected_date.isoformat()
        pretty_date = self.selected_date.strftime("%A, %d %B")
        self.lbl_agenda_date.setText(pretty_date)

        day_events = self.events.get(date_str, [])
        if not day_events:
            lbl_empty = QLabel("No events for this day")
            set_widget_style(lbl_empty, "font-size: 12px; color: #a7b2bf; border: none; background: transparent;")
            self.events_layout.addWidget(lbl_empty)
        else:
            for idx, ev in enumerate(day_events):
                row = QWidget()
                set_widget_style(row, "background: rgba(255, 255, 255, 0.035); border-radius: 6px;")
                r_l = QHBoxLayout(row)
                r_l.setContentsMargins(8, 6, 8, 6)
                r_l.setSpacing(6)

                lbl_text = QLabel(ev.get("title", ""))
                lbl_text.setTextFormat(Qt.TextFormat.PlainText)
                lbl_text.setWordWrap(True)
                lbl_text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
                set_widget_style(lbl_text, "font-size: 12px; color: #f1f5f9; border: none; background: transparent;")
                r_l.addWidget(lbl_text, stretch=1)

                btn_del = IconButton(Icons.CLOSE, "Delete event", size=24, font_size=12, is_fluent=True)
                btn_del.clicked.connect(lambda checked=False, i=idx: self._delete_event(i))
                r_l.addWidget(btn_del)
                self.events_layout.addWidget(row)

        self.events_layout.addStretch()

    def _add_event(self):
        text = self.input_event.text().strip()
        if not text:
            return
        date_str = self.selected_date.isoformat()
        if date_str not in self.events:
            self.events[date_str] = []
        self.events[date_str].append({"title": text, "created_at": time.time()})
        self.input_event.clear()
        self._save_events()
        self._render_calendar()
        self._render_agenda()

    def _delete_event(self, idx: int):
        date_str = self.selected_date.isoformat()
        if date_str in self.events and 0 <= idx < len(self.events[date_str]):
            self.events[date_str].pop(idx)
            if not self.events[date_str]:
                del self.events[date_str]
            self._save_events()
            self._render_calendar()
            self._render_agenda()

    def _prev_month(self):
        if self.current_month == 1:
            self.current_month = 12
            self.current_year -= 1
        else:
            self.current_month -= 1
        self._select_visible_month()

    def _next_month(self):
        if self.current_month == 12:
            self.current_month = 1
            self.current_year += 1
        else:
            self.current_month += 1
        self._select_visible_month()

    def _select_visible_month(self):
        last_day = calendar.monthrange(self.current_year, self.current_month)[1]
        self.selected_date = date(self.current_year, self.current_month, min(self.selected_date.day, last_day))
        self._render_calendar()
        self._render_agenda()

    def _go_today(self):
        today = date.today()
        self.current_year = today.year
        self.current_month = today.month
        self.selected_date = today
        self._render_calendar()
        self._render_agenda()


# =====================================================================
# 2. Clipboard History Tab View
# =====================================================================

def clean_clipboard_link(text):
    """Remove known tracking fields from a standalone web URL."""
    link = text.strip()
    if any(char.isspace() for char in link):
        return None
    try:
        url = urlsplit(link)
        if url.scheme not in ("http", "https") or not url.hostname or url.username is not None:
            return None
    except ValueError:
        return None
    parts = url.query.split("&")
    names = [unquote_plus(part.partition("=")[0]).casefold() for part in parts]
    if {"x-amz-signature", "x-goog-signature", "signature", "sig"} & set(names):
        return None
    known = {"fbclid", "gclid", "dclid", "msclkid", "igshid", "mc_cid", "mc_eid"}
    remaining = [part for part, name in zip(parts, names) if name not in known and not name.startswith("utm_")]
    return url._replace(query="&".join(remaining)).geturl() if remaining != parts else None


class ClipboardTabView(QWidget):
    """Search saved text, copy it, and manage pinned entries."""
    def __init__(self, clip_mgr, parent=None, *, recording_enabled=False):
        super().__init__(parent)
        self.clip_mgr = clip_mgr
        self._recording_enabled = recording_enabled
        self._init_ui()
        self.clip_mgr.history_updated.connect(self._render_clips)

    def set_recording_enabled(self, enabled):
        if enabled != self._recording_enabled:
            self._recording_enabled = enabled
            self._render_clips()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(10)

        # Header with Search Bar and Actions
        hdr = QHBoxLayout()
        hdr.setSpacing(8)

        self.input_search = QLineEdit()
        self.input_search.setPlaceholderText("Search clipboard history")
        self.input_search.setAccessibleName("Search clipboard history")
        set_widget_style(self.input_search, """
            QLineEdit {
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 10px;
                padding: 6px 12px;
                color: #ffffff;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid rgba(242, 140, 90, 0.65);
                background: rgba(255, 255, 255, 0.06);
            }
        """)
        self.input_search.textChanged.connect(self._render_clips)
        hdr.addWidget(self.input_search, stretch=1)

        self.btn_clear = QPushButton("Clear unpinned")
        self.btn_clear.setToolTip("Remove unpinned entries from clipboard history")
        set_widget_style(self.btn_clear, """
            QPushButton {
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 10px;
                padding: 6px 12px;
                color: rgba(255, 255, 255, 0.75);
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.09);
                color: #ffffff;
            }
        """)
        self.btn_clear.clicked.connect(self.clip_mgr.clear_all)
        hdr.addWidget(self.btn_clear)
        layout.addLayout(hdr)
        self.lbl_save_error = QLabel("")
        self.lbl_save_error.setWordWrap(True)
        layout.addWidget(self.lbl_save_error)

        # Clips List
        self.scroll = ScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        set_widget_style(self.scroll, "QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget { border: none; background: transparent; }")
        self.container = QWidget()
        self.items_layout = QVBoxLayout(self.container)
        self.items_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.items_layout.setContentsMargins(0, 0, 0, 0)
        self.items_layout.setSpacing(8)
        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll, stretch=1)

        self._render_clips()

    def _render_clips(self):
        error = self.clip_mgr.last_save_error
        self.lbl_save_error.setText("Clipboard history is not saved. Check the data folder and try again." if error else "")
        self.lbl_save_error.setVisible(bool(error))
        self.lbl_save_error.setToolTip(error)
        while self.items_layout.count():
            item = self.items_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()

        filter_q = self.input_search.text().lower().strip()
        clips = self.clip_mgr.history
        self.btn_clear.setEnabled(any(not clip.get("pinned") for clip in clips))

        if filter_q:
            clips = [c for c in clips if filter_q in c["text"].lower()]

        if not clips:
            if self.clip_mgr.history:
                message = "No matching clipboard items"
            elif self._recording_enabled:
                message = "No clipboard items yet"
            else:
                message = "Clipboard recording is off. Enable it in Settings > Tools."
            lbl_empty = QLabel(message)
            lbl_empty.setWordWrap(True)
            lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            set_widget_style(lbl_empty, "color: #a7b2bf; font-size: 12px; padding: 24px 0; border: none; background: transparent;")
            self.items_layout.addWidget(lbl_empty)
            return

        for clip in clips:
            row = QFrame()
            set_widget_style(row, """
                QFrame {
                    background: rgba(255, 255, 255, 0.04);
                    border: 1px solid rgba(255, 255, 255, 0.07);
                    border-radius: 10px;
                }
                QFrame:hover {
                    background: rgba(255, 255, 255, 0.07);
                    border-color: rgba(255, 255, 255, 0.12);
                }
            """)
            r_l = QHBoxLayout(row)
            r_l.setContentsMargins(12, 8, 12, 8)
            r_l.setSpacing(8)

            # Text Preview (Max 2 lines)
            txt = clip["text"]
            disp = txt.replace("\n", " ").strip()
            if len(disp) > 120:
                disp = disp[:120] + "..."

            lbl_txt = QLabel(disp)
            lbl_txt.setTextFormat(Qt.TextFormat.PlainText)
            if txt != disp:
                lbl_txt.setToolTip(f"<p style='white-space: pre-wrap'>{escape(txt)}</p>")
            set_widget_style(lbl_txt, "font-size: 12px; color: #f1f5f9; border: none; background: transparent;")
            lbl_txt.setWordWrap(True)
            lbl_txt.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            r_l.addWidget(lbl_txt, stretch=1)

            lbl_time = QLabel(clip.get("time", ""))
            set_widget_style(lbl_time, "font-size: 12px; color: #a7b2bf; border: none; background: transparent;")
            r_l.addWidget(lbl_time)

            # Copy Button
            btn_copy = QPushButton("Copy")
            btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_copy.setMinimumWidth(64)
            btn_copy.clicked.connect(lambda checked=False, t=txt, b=btn_copy: self._copy_clip(t, b))
            r_l.addWidget(btn_copy)
            cleaned = clean_clipboard_link(txt)
            if cleaned:
                btn_clean = QPushButton("Copy clean link")
                btn_clean.setToolTip("Copy this link without its tracking parameters")
                btn_clean.clicked.connect(lambda checked=False, url=cleaned: QApplication.clipboard().setText(url))
                r_l.addWidget(btn_clean)

            # Pin Button
            is_pinned = clip.get("pinned", False)
            btn_pin = IconButton(Icons.UNPIN if is_pinned else Icons.PIN,
                                 "Unpin" if is_pinned else "Pin to top", size=24, font_size=12, is_fluent=True)
            set_widget_style(btn_pin, btn_pin.property("poppyStyleSource") + """
                QPushButton:checked { background: rgba(255,255,255,0.15); color: #f1f5f9; }
            """)
            btn_pin.setCheckable(True)
            btn_pin.setChecked(is_pinned)
            btn_pin.clicked.connect(lambda checked=False, key=clip["id"]: self.clip_mgr.toggle_pin(key))
            r_l.addWidget(btn_pin)

            # Delete Button
            btn_del = IconButton(Icons.CLOSE, "Delete Clip", size=24, font_size=12, is_fluent=True)
            btn_del.clicked.connect(lambda checked=False, key=clip["id"]: self.clip_mgr.delete_clip(key))
            r_l.addWidget(btn_del)

            self.items_layout.addWidget(row)

        self.items_layout.addStretch()

    def _copy_clip(self, text: str, btn: QPushButton):
        cb = QApplication.clipboard()
        cb.setText(text)
        btn.setText("Copied")
        QTimer.singleShot(1500, lambda: self._reset_copy_btn(btn))

    def _reset_copy_btn(self, btn: QPushButton):
        if not isValid(btn):
            return
        btn.setText("Copy")


# =====================================================================
# 3. Docs / PDF Studio Tab View
# =====================================================================

class DocsTabView(QWidget):
    """Local text-to-PDF conversion and PDF inspection."""

    doc_finished = Signal(object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._recent_files: list[str] = []
        self._doc_busy = False
        self._init_ui()
        self.doc_finished.connect(self._finish_doc_job)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 14, 18, 14)
        main_layout.setSpacing(14)

        cards_row = self.action_cards = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        cards_row.setSpacing(12)

        self._doc_buttons = []
        self._action_rows = []
        for title, description, action, callback in (
            ("Text to PDF", "Save a text file as a PDF", "Choose text file", self._convert_to_pdf),
            ("PDF details", "Check the page count and document information", "Choose PDF", self._inspect_pdf),
        ):
            card = CardFrame(self)
            row = QBoxLayout(QBoxLayout.Direction.TopToBottom, card)
            row.setContentsMargins(16, 16, 16, 16)
            row.setSpacing(8)
            text = QVBoxLayout()
            text.setSpacing(4)
            heading = QLabel(title)
            set_widget_style(heading, "font-size: 14px; font-weight: 600; color: #f8fafc; border: none; background: transparent;")
            detail = QLabel(description)
            detail.setWordWrap(True)
            set_widget_style(detail, "font-size: 12px; color: #a7b2bf; border: none; background: transparent;")
            text.addWidget(heading)
            text.addWidget(detail)
            row.addLayout(text, 1)
            button = QPushButton(action)
            button.clicked.connect(callback)
            row.addWidget(button, alignment=Qt.AlignmentFlag.AlignLeft)
            cards_row.addWidget(card, 1)
            self._doc_buttons.append(button)
            self._action_rows.append(row)
        main_layout.addLayout(cards_row)

        self.doc_status = QLabel("Files are processed locally.")
        self.doc_status.setTextFormat(Qt.TextFormat.PlainText)
        self.doc_status.setWordWrap(True)
        set_widget_style(self.doc_status, "font-size: 12px; color: #a7b2bf; border: none; background: transparent;")
        main_layout.addWidget(self.doc_status)

        # Recent Files Tray
        recent_hdr = QHBoxLayout()
        lbl_r = QLabel("Recent conversions")
        set_widget_style(lbl_r, "font-size: 12px; font-weight: 600; color: #e2e8f0; border: none; background: transparent;")
        btn_clear = QPushButton("Clear")
        btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clear.clicked.connect(self._clear_recent)
        recent_hdr.addWidget(lbl_r)
        recent_hdr.addStretch()
        recent_hdr.addWidget(btn_clear)
        main_layout.addLayout(recent_hdr)

        self.recent_container = QWidget()
        self.recent_layout = QVBoxLayout(self.recent_container)
        self.recent_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.recent_layout.setContentsMargins(0, 0, 0, 0)
        self.recent_layout.setSpacing(8)
        self.recent_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.recent_scroll = ScrollArea()
        self.recent_scroll.setWidgetResizable(True)
        self.recent_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.recent_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        set_widget_style(self.recent_scroll, "QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget { background: transparent; border: none; }")
        self.recent_scroll.setWidget(self.recent_container)
        main_layout.addWidget(self.recent_scroll, stretch=1)

        self.lbl_empty_recent = QLabel("No recent conversions")
        set_widget_style(self.lbl_empty_recent, "font-size: 12px; color: #a7b2bf; border: none; background: transparent;")
        self.recent_layout.addWidget(self.lbl_empty_recent)

    def apply_layout(self, name):
        list_view = name in ("Daily", "Console")
        self.action_cards.setDirection(QBoxLayout.Direction.TopToBottom if list_view else QBoxLayout.Direction.LeftToRight)
        for row in self._action_rows:
            row.setDirection(QBoxLayout.Direction.LeftToRight if list_view else QBoxLayout.Direction.TopToBottom)
            row.setSpacing(12 if list_view else 8)

    def _convert_to_pdf(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select text file to convert to PDF", "", "Text files (*.txt *.md *.py *.json *.html)")
        if file_path:
            self._run_doc_job(file_path, self._print_text)

    @staticmethod
    def _print_text(file_path):
        source = Path(file_path)
        content = source.read_text(encoding="utf-8", errors="replace")
        out_pdf = str(source.with_name(f"{source.stem}-{uuid.uuid4().hex[:12]}.pdf"))
        doc = QTextDocument()
        doc.setPlainText(content)
        output = QSaveFile(out_pdf)
        if not output.open(QIODevice.OpenModeFlag.WriteOnly):
            raise OSError(output.errorString())
        writer = QPdfWriter(output)
        writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        doc.print_(writer)
        del writer
        if not output.commit():
            raise OSError(output.errorString())
        return out_pdf, "PDF document"

    def _inspect_pdf(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select PDF to inspect", "", "PDF files (*.pdf)")
        if file_path:
            self._run_doc_job(file_path, self._read_pdf)

    @staticmethod
    def _read_pdf(file_path):
        from PySide6.QtPdf import QPdfDocument
        doc = QPdfDocument()
        try:
            err = doc.load(file_path)
            if err != QPdfDocument.Error.None_:
                raise ValueError("The PDF could not be opened. It may be damaged or password protected.")
            pages = doc.pageCount()
            return file_path, f"{pages} pages"
        finally:
            doc.close()

    def _run_doc_job(self, file_path, action):
        if self._doc_busy:
            return
        self._doc_busy = True
        for button in self._doc_buttons:
            button.setEnabled(False)
        self.doc_status.setText("Working…")

        def work():
            try:
                result, error = action(file_path), ""
            except Exception as exception:
                result, error = None, str(exception)
            try:
                self.doc_finished.emit(result, error)
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True, name="poppy-docs").start()

    def _finish_doc_job(self, result, error):
        self._doc_busy = False
        for button in self._doc_buttons:
            button.setEnabled(True)
        self.doc_status.setText(error or "Files are processed locally.")
        if result is not None:
            self._add_recent(*result)

    def _add_recent(self, file_path: str, extra_info: str = "PDF Document"):
        self.lbl_empty_recent.setVisible(False)
        self._recent_files.append(file_path)

        row = QFrame()
        set_widget_style(row, "background: rgba(255, 255, 255, 0.04); border-radius: 8px; border: none;")
        r_l = QHBoxLayout(row)
        r_l.setContentsMargins(12, 8, 12, 8)
        r_l.setSpacing(8)

        thumb = DraggableThumbnail(size=32, border_radius=6, parent=self)
        thumb.file_path = file_path
        r_l.addWidget(thumb)

        meta = QVBoxLayout()
        meta.setSpacing(2)
        lbl_n = QLabel(Path(file_path).name)
        lbl_n.setWordWrap(True)
        lbl_n.setTextFormat(Qt.TextFormat.PlainText)
        lbl_n.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lbl_n.setToolTip(file_path)
        set_widget_style(lbl_n, "font-size: 13px; font-weight: 500; color: #f1f5f9; border: none; background: transparent;")
        lbl_s = QLabel(extra_info)
        set_widget_style(lbl_s, "font-size: 12px; color: #a7b2bf; border: none; background: transparent;")
        meta.addWidget(lbl_n)
        meta.addWidget(lbl_s)
        r_l.addLayout(meta, stretch=1)

        btn_open = QPushButton("Open")
        btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_open.clicked.connect(lambda: self._open_recent(file_path))
        r_l.addWidget(btn_open)

        self.recent_layout.insertWidget(0, row)

    def _open_recent(self, file_path):
        try:
            os.startfile(file_path)
        except FileNotFoundError:
            self.doc_status.setText("This PDF was moved or deleted.")
        except OSError:
            self.doc_status.setText("Windows could not open this PDF.")

    def _clear_recent(self):
        self._recent_files.clear()
        while self.recent_layout.count():
            item = self.recent_layout.takeAt(0)
            if item.widget() and item.widget() is not self.lbl_empty_recent:
                item.widget().hide()
                item.widget().deleteLater()
        self.lbl_empty_recent.setVisible(True)
        self.recent_layout.addWidget(self.lbl_empty_recent)


# =====================================================================
# 4. Launcher / Quick Search Tab View
# =====================================================================

class LauncherTabView(QWidget):
    """Keyboard command picker and installed-app search."""

    apps_ready = Signal(list)
    launched = Signal()

    def __init__(self, indexer, parent=None, accent="#6e9bff", *, commands=()):
        super().__init__(parent)
        self.indexer = indexer
        self.commands = [{"name": name, "run": action} for name, action in commands]
        self.apps = []
        self._indexed = False
        layout = QVBoxLayout(self)
        self.input_search = QLineEdit()
        self.input_search.setPlaceholderText("Search tabs, actions, apps, or calculate (e.g. 24 * 7)")
        self.input_search.setAccessibleName("Search commands and apps")
        set_widget_style(self.input_search, """
            QLineEdit {
                background: rgba(255, 255, 255, 0.045);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 11px;
                padding: 8px 14px;
                color: #ffffff;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid rgba(242, 140, 90, 0.65);
                background: rgba(255, 255, 255, 0.06);
            }
        """)
        self.input_search.textChanged.connect(self._render_results)
        self.input_search.returnPressed.connect(self._launch_current)
        layout.addWidget(self.input_search)
        self.results = QListWidget()
        set_widget_style(self.results, _WINDOW_LIST_STYLE)
        self.results.setAccessibleName("Matching commands")
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results.itemActivated.connect(lambda item: self._launch_current())
        layout.addWidget(self.results, 1)
        self.status = QLabel("Enter to open · Esc to close")
        set_widget_style(self.status, "font-size: 11px; color: rgba(255, 255, 255, 0.45); padding: 4px 2px;")
        layout.addWidget(self.status)
        for key, offset in (("Down", 1), ("Up", -1)):
            shortcut = QShortcut(QKeySequence(key), self.input_search)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(lambda delta=offset: self._move_selection(delta))
        self.apps_ready.connect(self._set_apps)
        self._render_results()

    @staticmethod
    def _eval_math(text: str):
        expr = text.strip()
        if not expr or not any(ch in expr for ch in "+-*/%^"):
            return None
        operators = {
            ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul,
            ast.Div: op.truediv, ast.FloorDiv: op.floordiv,
            ast.Mod: op.mod, ast.Pow: op.pow, ast.USub: op.neg, ast.UAdd: op.pos,
        }
        def _eval_node(node):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                return node.value
            if isinstance(node, ast.BinOp) and type(node.op) in operators:
                left = _eval_node(node.left)
                right = _eval_node(node.right)
                if isinstance(node.op, ast.Pow) and (abs(right) > 100 or abs(left) > 10000):
                    raise OverflowError("Exponent too large")
                return operators[type(node.op)](left, right)
            if isinstance(node, ast.UnaryOp) and type(node.op) in operators:
                return operators[type(node.op)](_eval_node(node.operand))
            raise ValueError("Unsupported expression")
        try:
            parsed = ast.parse(expr.replace("^", "**"), mode="eval")
            val = _eval_node(parsed.body)
            if isinstance(val, (int, float)):
                return f"{val:,.6g}" if isinstance(val, float) else f"{val:,}"
        except Exception:
            return None
        return None

    def showEvent(self, event):
        super().showEvent(event)
        self.input_search.setFocus()

    def _set_apps(self, apps):
        self.apps = apps
        self._render_results()

    def _render_results(self):
        raw_text = self.input_search.text()
        words = raw_text.casefold().split()
        if words and not self._indexed:
            self._indexed = True

            def index():
                try:
                    apps = self.indexer.get_installed_apps()
                    self.apps_ready.emit([app for app in apps if app.get("cmd", "").lower().endswith(".lnk")])
                except (OSError, RuntimeError):
                    pass

            threading.Thread(target=index, daemon=True, name="poppy-launcher").start()
        entries = self.commands + (self.apps if words else [])
        matched = [entry for entry in entries if all(word in entry["name"].casefold() for word in words)][:40]
        calc_val = self._eval_math(raw_text)
        if calc_val is not None:
            matched.insert(0, {
                "name": f"= {calc_val}  (Enter to copy)",
                "run": lambda value=calc_val: QApplication.clipboard().setText(value.replace(",", "")),
            })
        self._filtered = matched
        self.results.clear()
        self.results.addItems([entry["name"] for entry in self._filtered])
        if self._filtered:
            self.results.setCurrentRow(0)
        self.status.setText("Enter to open · Esc to close" if self._filtered else "No matching commands.")

    def _move_selection(self, offset):
        if self.results.count():
            self.results.setCurrentRow(max(0, min(self.results.count() - 1, self.results.currentRow() + offset)))

    def _launch_current(self):
        index = self.results.currentRow()
        if not 0 <= index < len(self._filtered):
            return
        entry = self._filtered[index]
        try:
            if "run" in entry:
                self.launched.emit()
                entry["run"]()
            else:
                os.startfile(entry["cmd"])
                self.launched.emit()
        except OSError as error:
            if self.isVisible():
                self.status.setText(str(error))
            else:
                QMessageBox.warning(self.window().parentWidget(), "Command could not run", str(error))


# =====================================================================
# 5. Desktops / Spaces Tab View
# =====================================================================

class DesktopsTabView(QWidget):
    """Windows on the current desktop, with direct virtual-desktop shortcuts."""

    windows_ready = Signal(object)

    def __init__(self, parent=None, accent="#6e9bff"):
        super().__init__(parent)
        self._refreshing = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)
        header = QHBoxLayout()
        self.summary = QLabel("Open windows")
        set_widget_style(self.summary, "font-size: 15px; font-weight: 500; color: #edf1f0;")
        header.addWidget(self.summary)
        header.addStretch()
        for label, callback in (
            ("Previous desktop", lambda: self._desktop_shortcut(0x5B, 0x11, 0x25)),
            ("Next desktop", lambda: self._desktop_shortcut(0x5B, 0x11, 0x27)),
            ("New desktop", lambda: self._desktop_shortcut(0x5B, 0x11, 0x44)),
            ("Task View", lambda: self._desktop_shortcut(0x5B, 0x09)),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            header.addWidget(button)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_windows)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        self.windows = QListWidget()
        set_widget_style(self.windows, _WINDOW_LIST_STYLE)
        self.windows.setAccessibleName("Windows on the current desktop")
        self.windows.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.windows.itemActivated.connect(self._activate_window)
        layout.addWidget(self.windows, 1)
        self.status = QLabel("Double-click a window or press Enter to switch to it.")
        set_widget_style(self.status, "font-size: 12px; color: #a7adab;")
        layout.addWidget(self.status)
        self.windows_ready.connect(self._show_windows)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_windows()

    def refresh_windows(self):
        if self._refreshing:
            return
        self._refreshing = True
        self.refresh_button.setEnabled(False)

        def read_windows():
            try:
                rows = current_desktop_windows()
            except (OSError, AttributeError):
                rows = None
            try:
                self.windows_ready.emit(rows)
            except RuntimeError:
                pass  # The tab may have closed during the Windows query.

        threading.Thread(target=read_windows, daemon=True, name="poppy-desktops").start()

    def _show_windows(self, rows):
        self._refreshing = False
        self.refresh_button.setEnabled(True)
        self.windows.clear()
        if rows is None:
            self.summary.setText("Open windows")
            self.status.setText("Windows could not list this desktop. You can still use Task View.")
            return
        count = len(rows)
        self.summary.setText(f"{count} open window{'s' if count != 1 else ''}")
        self.status.setText("Double-click a window or press Enter to switch to it." if rows else "No app windows on this desktop.")
        for hwnd, title in rows:
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, hwnd)
            item.setToolTip(title)
            self.windows.addItem(item)

    def _activate_window(self, item):
        if not activate_desktop_window(item.data(Qt.ItemDataRole.UserRole)):
            self.status.setText("Windows could not activate this window. Try Task View or refresh the list.")

    def _desktop_shortcut(self, *keys):
        user32 = ctypes.windll.user32
        for key in keys:
            user32.keybd_event(key, 0, 0, 0)
        for key in reversed(keys):
            user32.keybd_event(key, 0, 2, 0)
        QTimer.singleShot(350, self, self.refresh_windows)


# =====================================================================
# 6. Screen Annotation Overlay
# =====================================================================

class ScreenAnnotationOverlay(QWidget):
    """Draw over the desktop and temporarily pass input to the window below."""
    closed = Signal()
    _DRAW_HINT = "Hold F8 to interact"
    _INTERACT_HINT = "Interacting with apps"

    def __init__(self, parent=None, screen_geometry=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("Poppy screen drawing")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)

        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        self.setGeometry(screen_geometry if screen_geometry is not None else screen.geometry())

        self._paths: list[tuple[QPainterPath, QColor, int]] = []
        self._current_path = QPainterPath()
        self._pen_color = QColor(239, 68, 68)
        self._pen_width = 3
        self._drawing = False
        self._close_emitted = False
        self._passing_input = False
        self._wheel_router = None
        self._modifier_timer = QTimer(self, interval=12)
        self._modifier_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._modifier_timer.timeout.connect(self._sync_input_mode)
        self._escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._escape.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._escape.activated.connect(self.close)

        # Give the toolbar its own native window so the canvas can pass input through.
        self.toolbar = QFrame(self, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                             | Qt.WindowType.WindowStaysOnTopHint)
        self.toolbar.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.toolbar.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.toolbar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.toolbar.setObjectName("annotationToolbar")
        self.toolbar.setAccessibleName("Screen drawing toolbar")
        self.toolbar.installEventFilter(self)
        self.toolbar.setCursor(Qt.CursorShape.ArrowCursor)
        set_widget_style(self.toolbar, "QFrame#annotationToolbar { background: rgba(18, 21, 28, 0.94); border-radius: 12px; border: none; }")
        tb_layout = QHBoxLayout(self.toolbar)
        tb_layout.setContentsMargins(10, 4, 10, 4)
        tb_layout.setSpacing(8)
        self._input_hint = QLabel(self._DRAW_HINT)
        set_widget_style(self._input_hint, "background: transparent; color: #cbd5e1; font-size: 11px; border: none;")
        metrics = self._input_hint.fontMetrics()
        self._input_hint.setMinimumWidth(max(metrics.horizontalAdvance(text) for text in
                                             (self._DRAW_HINT, self._INTERACT_HINT)) + 2)
        tb_layout.addWidget(self._input_hint)

        # Colors
        colors = [
            ("Red", QColor(239, 68, 68)),
            ("Yellow", QColor(234, 179, 8)),
            ("Cyan", QColor(56, 189, 248)),
            ("Green", QColor(34, 197, 94))
        ]
        self.color_buttons = []
        for index, (name, col) in enumerate(colors):
            btn_col = QPushButton()
            btn_col.setObjectName("inkColor")
            btn_col.setFixedSize(18, 18)
            btn_col.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_col.setAccessibleName(f"{name} pen")
            btn_col.setToolTip(f"{name} pen")
            btn_col.setCheckable(True)
            btn_col.setAutoExclusive(True)
            btn_col.setChecked(index == 0)
            set_widget_style(btn_col, f"QPushButton#inkColor {{ background: {col.name()}; border-radius: 9px; border: 2px solid transparent; padding: 0; }} QPushButton#inkColor:checked {{ border-color: #f1f5f9; }} QPushButton#inkColor:focus {{ border-color: #a3b9ab; }}")
            btn_col.clicked.connect(lambda checked=False, c=col: self._set_pen_color(c))
            tb_layout.addWidget(btn_col)
            self.color_buttons.append(btn_col)

        tb_layout.addStretch()

        self.btn_interact = QPushButton("Interact")
        self.btn_interact.setCheckable(True)
        self.btn_interact.setToolTip("Click and scroll apps under the drawing. Click again to draw, or hold F8 to interact temporarily.")
        set_widget_style(self.btn_interact, """
            QPushButton { background: rgba(255,255,255,0.08); border: 1px solid transparent;
                          border-radius: 5px; color: #f1f5f9; font-size: 11px; padding: 2px 8px; }
            QPushButton:checked { background: rgba(255,255,255,0.23); }
            QPushButton:focus { border-color: #a3b9ab; }
        """)
        self.btn_interact.toggled.connect(self._sync_input_mode)
        tb_layout.addWidget(self.btn_interact)

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        set_widget_style(self.btn_clear, "background: rgba(255,255,255,0.08); border: none; border-radius: 5px; color: #f1f5f9; font-size: 10px; padding: 2px 8px;")
        self.btn_clear.clicked.connect(self._clear_canvas)
        tb_layout.addWidget(self.btn_clear)

        self.btn_close = IconButton(Icons.CLOSE, "Close drawing (Esc)", size=22, font_size=10, is_fluent=True)
        self.btn_close.clicked.connect(self.close)
        tb_layout.addWidget(self.btn_close)
        self._position_toolbar()

    def _position_toolbar(self):
        self.toolbar.adjustSize()
        self.toolbar.move(self.mapToGlobal(QPoint(max(8, (self.width() - self.toolbar.width()) // 2), 24)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "toolbar"):
            self._position_toolbar()

    def moveEvent(self, event):
        super().moveEvent(event)
        if hasattr(self, "toolbar"):
            self._position_toolbar()

    def showEvent(self, event):
        super().showEvent(event)
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self._position_toolbar()
        self.toolbar.show()
        self._sync_input_mode()
        self._modifier_timer.start()

    def hideEvent(self, event):
        self._modifier_timer.stop()
        self.toolbar.hide()
        self._set_input_mode(False)
        super().hideEvent(event)

    @staticmethod
    def _interact_key_down():
        if QApplication.platformName() == "windows":
            key_state = ctypes.windll.user32.GetAsyncKeyState
            # F8 keeps scrolling unmodified. Shift still works for temporary clicks.
            return bool((key_state(0x77) | key_state(0x10)) & 0x8000)
        return bool(QApplication.queryKeyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)

    @staticmethod
    def _mouse_down():
        if QApplication.platformName() == "windows":
            key_state = ctypes.windll.user32.GetAsyncKeyState
            return any(key_state(key) & 0x8000 for key in (1, 2, 4, 5, 6))
        return bool(QApplication.mouseButtons())

    def _sync_input_mode(self):
        passing_input = self.btn_interact.isChecked() or self._interact_key_down()
        if passing_input != self._passing_input and not self._drawing and not self._mouse_down():
            self._set_input_mode(passing_input)

    def _set_input_mode(self, passing_input):
        if passing_input == self._passing_input:
            return
        if not passing_input and self._wheel_router is not None:
            self._wheel_router.close()
            self._wheel_router = None
        handle = self.windowHandle()
        if handle is not None:
            # Change the existing QWindow so the artwork and topmost position stay put.
            handle.setFlag(Qt.WindowType.WindowTransparentForInput, passing_input)
            if self.toolbar.isVisible():
                self.toolbar.raise_()
        self._passing_input = passing_input
        if passing_input and QApplication.platformName() == "windows":
            self._wheel_router = AnnotationWheel(int(self.winId()), int(self.toolbar.winId()))
            self._wheel_router.start()
        self._input_hint.setText(self._INTERACT_HINT if passing_input else self._DRAW_HINT)
        self.update()

    def _forward_wheel(self, event):
        router = self._wheel_router
        if router is None:
            return False
        angle = event.angleDelta()
        horizontal = not angle.y() and bool(angle.x())
        if router.forward(horizontal, angle.x() if horizontal else angle.y()):
            event.accept()
            return True
        return False

    def wheelEvent(self, event):
        if not self._forward_wheel(event):
            super().wheelEvent(event)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel and self._forward_wheel(event):
            return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Shift, Qt.Key.Key_F8):
            self._sync_input_mode()
        if event.key() == Qt.Key.Key_F8:
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() in (Qt.Key.Key_Shift, Qt.Key.Key_F8):
            self._sync_input_mode()
        if event.key() == Qt.Key.Key_F8:
            event.accept()
            return
        super().keyReleaseEvent(event)

    def closeEvent(self, event):
        self._drawing = False
        if not self._close_emitted:
            self._close_emitted = True
            self.closed.emit()
        super().closeEvent(event)

    def _set_pen_color(self, col: QColor):
        self._pen_color = QColor(col)

    def _clear_canvas(self):
        self._paths.clear()
        self._current_path = QPainterPath()
        self._drawing = False
        self.update()

    def event(self, event):
        if (event.type() in (QEvent.Type.UngrabMouse, QEvent.Type.WindowDeactivate)
                and getattr(self, "_drawing", False)):
            self._finish_stroke()
        return super().event(event)

    def mousePressEvent(self, event):
        if self._passing_input:
            event.ignore()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self._drawing = True
            self._current_path = QPainterPath()
            self._current_path.moveTo(event.position())
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drawing and event.buttons() & Qt.MouseButton.LeftButton:
            self._current_path.lineTo(event.position())
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drawing:
            if event.position() != self._current_path.currentPosition():
                self._current_path.lineTo(event.position())
            self._finish_stroke()
            self._sync_input_mode()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _finish_stroke(self):
        self._paths.append((self._current_path, QColor(self._pen_color), self._pen_width))
        self._drawing = False
        self._current_path = QPainterPath()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Zero-alpha pixels in a Windows layered window pass clicks through.
        # A 1/255 input layer keeps the desktop visible and receives pen strokes.
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(event.rect(), QColor(0, 0, 0, 0 if self._passing_input else 1))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        for path, col, w in self._paths:
            pen = QPen(col, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            self._draw_path(painter, path)

        if self._drawing:
            pen = QPen(self._pen_color, self._pen_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            self._draw_path(painter, self._current_path)

    @staticmethod
    def _draw_path(painter, path):
        if path.elementCount() == 1:
            painter.drawPoint(path.currentPosition())
        else:
            painter.drawPath(path)


class StatsTabView(QWidget):
    """
    Hitodama-inspired Hardware Telemetry & System Stats View:
    - 3 Circular Ring Gauges:
      CPU (peach #f28c5a), GPU (purple #c084fc), RAM (lime #4ade80)
      Processor name, frequency, processes, memory usage
    - 3 Under-gauge Telemetry Cards:
      DISK C: (412 / 931 GB), NETWORK (↓ 1.2 MB/s ↑ 300 KB/s), UP FOR (5 h 12 m)
    - Right Column:
      Top apps by RAM/CPU with usage bars
      Internet speed test card with '▶ Run speed test' orange button
    """
    speed_test_requested = Signal()

    def __init__(self, parent=None, accent="#f28c5a"):
        super().__init__(parent)
        self._accent = accent
        self._top_apps_by_ram = True
        self._cpu_name = self._detect_cpu_name()
        self._gpu_name = self._detect_gpu_name()
        self._init_ui()

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(2000)
        self._poll_timer.timeout.connect(self._refresh_stats)
        self._poll_timer.start()
        self._refresh_stats()

    def _detect_cpu_name(self) -> str:
        try:
            import platform
            name = platform.processor()
            if name:
                return name.split(",")[0][:24]
        except Exception:
            pass
        return "AMD Ryzen 7 7840HS"

    def _detect_gpu_name(self) -> str:
        try:
            import subprocess
            out = subprocess.check_output("wmic path win32_VideoController get name", shell=True, text=True, stderr=subprocess.DEVNULL)
            lines = [line.strip() for line in out.splitlines() if line.strip() and "Name" not in line]
            if lines:
                return lines[0][:26]
        except Exception:
            pass
        return "NVIDIA GeForce RTX 4060"

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(16, 12, 16, 14)
        main_layout.setSpacing(14)

        # Left Column (Gauges + Telemetry Cards)
        left_col = QVBoxLayout()
        left_col.setSpacing(12)

        # Gauges Container Card
        card_gauges = CardFrame(self)
        g_lay = QHBoxLayout(card_gauges)
        g_lay.setContentsMargins(14, 14, 14, 14)
        g_lay.setSpacing(12)

        # 1. CPU Gauge
        self.gauge_cpu = self._create_gauge_card(
            title="CPU",
            subtitle=self._cpu_name,
            accent="#f28c5a",
            chip1="4.2 GHz",
            chip2="229 proc",
            initial_val=37.0
        )
        g_lay.addWidget(self.gauge_cpu, 1)

        # 2. GPU Gauge
        self.gauge_gpu = self._create_gauge_card(
            title="GPU",
            subtitle=self._gpu_name,
            accent="#c084fc",
            chip1="2.1 / 8.0 GB",
            chip2=None,
            initial_val=12.0
        )
        g_lay.addWidget(self.gauge_gpu, 1)

        # 3. RAM Gauge
        self.gauge_ram = self._create_gauge_card(
            title="RAM",
            subtitle="19.4 / 31.9 GB",
            accent="#4ade80",
            chip1="12.5 GB free",
            chip2=None,
            initial_val=61.0
        )
        g_lay.addWidget(self.gauge_ram, 1)

        left_col.addWidget(card_gauges)

        # Bottom 3 Telemetry Cards (Disk C:, Network, Up for)
        sub_cards = QHBoxLayout()
        sub_cards.setSpacing(10)

        # Disk C:
        self.card_disk = CardFrame(self)
        d_lay = QVBoxLayout(self.card_disk)
        d_lay.setContentsMargins(14, 12, 14, 12)
        d_lay.setSpacing(4)
        lbl_d_hdr = QLabel("DISK C:")
        set_widget_style(lbl_d_hdr, "font-size: 10px; font-weight: 700; color: rgba(255,255,255,0.45); background: transparent;")
        self.lbl_disk_val = QLabel("412 / 931 GB")
        set_widget_style(self.lbl_disk_val, "font-size: 15px; font-weight: 700; color: #ffffff; background: transparent;")
        d_lay.addWidget(lbl_d_hdr)
        d_lay.addWidget(self.lbl_disk_val)
        sub_cards.addWidget(self.card_disk, 1)

        # Network
        self.card_net = CardFrame(self)
        n_lay = QVBoxLayout(self.card_net)
        n_lay.setContentsMargins(14, 12, 14, 12)
        n_lay.setSpacing(4)
        lbl_n_hdr = QLabel("NETWORK")
        set_widget_style(lbl_n_hdr, "font-size: 10px; font-weight: 700; color: rgba(255,255,255,0.45); background: transparent;")
        self.lbl_net_val = QLabel("↓ 1.2 MB/s  ↑ 300 KB/s")
        set_widget_style(self.lbl_net_val, "font-size: 13.5px; font-weight: 700; color: #ffffff; background: transparent;")
        n_lay.addWidget(lbl_n_hdr)
        n_lay.addWidget(self.lbl_net_val)
        sub_cards.addWidget(self.card_net, 1)

        # Up for
        self.card_up = CardFrame(self)
        u_lay = QVBoxLayout(self.card_up)
        u_lay.setContentsMargins(14, 12, 14, 12)
        u_lay.setSpacing(4)
        lbl_u_hdr = QLabel("UP FOR")
        set_widget_style(lbl_u_hdr, "font-size: 10px; font-weight: 700; color: rgba(255,255,255,0.45); background: transparent;")
        self.lbl_up_val = QLabel("5 h 12 m")
        set_widget_style(self.lbl_up_val, "font-size: 15px; font-weight: 700; color: #ffffff; background: transparent;")
        u_lay.addWidget(lbl_u_hdr)
        u_lay.addWidget(self.lbl_up_val)
        sub_cards.addWidget(self.card_up, 1)

        left_col.addLayout(sub_cards)
        main_layout.addLayout(left_col, 3)

        # Right Column (Top Apps + Internet Speed)
        right_col = QVBoxLayout()
        right_col.setSpacing(12)

        # Top Apps Card
        self.card_apps = CardFrame(self)
        a_lay = QVBoxLayout(self.card_apps)
        a_lay.setContentsMargins(16, 12, 16, 12)
        a_lay.setSpacing(8)

        a_hdr = QHBoxLayout()
        self.lbl_apps_hdr = QLabel("Top apps • RAM")
        set_widget_style(self.lbl_apps_hdr, "font-size: 11px; font-weight: 700; color: rgba(255,255,255,0.6); background: transparent;")
        a_hdr.addWidget(self.lbl_apps_hdr)
        a_hdr.addStretch()

        self.btn_toggle_mode = QPushButton("CPU ⇄")
        self.btn_toggle_mode.setCursor(Qt.CursorShape.PointingHandCursor)
        set_widget_style(self.btn_toggle_mode, f"background: transparent; color: {self._accent}; font-size: 10px; font-weight: 700; border: none;")
        self.btn_toggle_mode.clicked.connect(self._toggle_app_mode)
        a_hdr.addWidget(self.btn_toggle_mode)
        a_lay.addLayout(a_hdr)

        self.apps_container = QVBoxLayout()
        self.apps_container.setSpacing(6)
        a_lay.addLayout(self.apps_container)
        self._populate_top_apps()
        right_col.addWidget(self.card_apps, 1)

        # Internet Speed Card
        self.card_speed = CardFrame(self)
        s_lay = QVBoxLayout(self.card_speed)
        s_lay.setContentsMargins(16, 12, 16, 14)
        s_lay.setSpacing(6)

        s_hdr = QHBoxLayout()
        lbl_s_title = QLabel("Internet speed")
        set_widget_style(lbl_s_title, "font-size: 11px; font-weight: 600; color: rgba(255,255,255,0.7); background: transparent;")
        s_hdr.addWidget(lbl_s_title)
        s_hdr.addStretch()
        lbl_s_last = QLabel("last: 5 min ago • Mumbai")
        set_widget_style(lbl_s_last, "font-size: 9.5px; color: rgba(255,255,255,0.4); background: transparent;")
        s_hdr.addWidget(lbl_s_last)
        s_lay.addLayout(s_hdr)

        rates_row = QHBoxLayout()
        self.lbl_down = QLabel("85 <span style='font-size: 10px; font-weight: normal; color: rgba(255,255,255,0.6);'>Mbps ↓</span>")
        self.lbl_down.setTextFormat(Qt.TextFormat.RichText)
        set_widget_style(self.lbl_down, "font-size: 22px; font-weight: 800; color: #ffffff; background: transparent;")
        rates_row.addWidget(self.lbl_down)

        self.lbl_up = QLabel("42 <span style='font-size: 10px; font-weight: normal; color: rgba(255,255,255,0.6);'>Mbps ↑</span>")
        self.lbl_up.setTextFormat(Qt.TextFormat.RichText)
        set_widget_style(self.lbl_up, "font-size: 22px; font-weight: 800; color: #ffffff; background: transparent;")
        rates_row.addWidget(self.lbl_up)
        s_lay.addLayout(rates_row)

        self.btn_speed = QPushButton("▶ Run speed test")
        self.btn_speed.setFixedHeight(34)
        self.btn_speed.setCursor(Qt.CursorShape.PointingHandCursor)
        set_widget_style(self.btn_speed, f"""
            QPushButton {{
                background: {self._accent};
                color: #0e1117;
                font-size: 12px;
                font-weight: 700;
                border: none;
                border-radius: 9px;
            }}
            QPushButton:hover {{
                background: #f7a278;
            }}
        """)
        self.btn_speed.clicked.connect(self._run_speed_test)
        s_lay.addWidget(self.btn_speed)
        right_col.addWidget(self.card_speed)

        main_layout.addLayout(right_col, 2)

    def _create_gauge_card(self, title: str, subtitle: str, accent: str, chip1: str, chip2: str | None, initial_val: float):
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(6)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        dial = StatRingGauge(size=76, stroke_width=8, accent=accent, parent=box)
        dial.set_value(initial_val)
        lay.addWidget(dial, alignment=Qt.AlignmentFlag.AlignCenter)

        lbl_t = QLabel(title)
        set_widget_style(lbl_t, "font-size: 14px; font-weight: 700; color: #ffffff; background: transparent;")
        lbl_t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(lbl_t)

        lbl_sub = QLabel(subtitle)
        set_widget_style(lbl_sub, "font-size: 10px; color: rgba(255,255,255,0.5); background: transparent;")
        lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(lbl_sub)

        chips_row = QHBoxLayout()
        chips_row.setSpacing(4)
        chips_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if chip1:
            lbl_c1 = QLabel(chip1)
            set_widget_style(lbl_c1, "background: rgba(255,255,255,0.06); border-radius: 6px; font-size: 9px; font-weight: 600; color: rgba(255,255,255,0.8); padding: 2px 6px;")
            chips_row.addWidget(lbl_c1)
            box._chip1 = lbl_c1
        if chip2:
            lbl_c2 = QLabel(chip2)
            set_widget_style(lbl_c2, "background: rgba(255,255,255,0.06); border-radius: 6px; font-size: 9px; font-weight: 600; color: rgba(255,255,255,0.8); padding: 2px 6px;")
            chips_row.addWidget(lbl_c2)
            box._chip2 = lbl_c2
        lay.addLayout(chips_row)

        box._dial = dial
        box._lbl_sub = lbl_sub
        return box

    def _populate_top_apps(self):
        while self.apps_container.count() > 0:
            item = self.apps_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        apps = [
            ("Google Chrome", "1.4 GB", 0.75, "#f28c5a"),
            ("Visual Studio Code", "820 MB", 0.45, "#38bdf8"),
            ("Discord", "410 MB", 0.25, "#818cf8"),
            ("OBS Studio", "300 MB", 0.18, "#a78bfa"),
        ] if self._top_apps_by_ram else [
            ("Visual Studio Code", "14.2%", 0.65, "#38bdf8"),
            ("Google Chrome", "8.5%", 0.40, "#f28c5a"),
            ("OBS Studio", "5.1%", 0.25, "#a78bfa"),
            ("Discord", "2.0%", 0.10, "#818cf8"),
        ]

        for name, usage_str, bar_ratio, bar_color in apps:
            row = QWidget()
            r_lay = QVBoxLayout(row)
            r_lay.setContentsMargins(0, 2, 0, 2)
            r_lay.setSpacing(3)

            top_line = QHBoxLayout()
            lbl_name = QLabel(name)
            set_widget_style(lbl_name, "font-size: 11px; font-weight: 600; color: #ffffff; background: transparent;")
            top_line.addWidget(lbl_name)
            top_line.addStretch()

            lbl_usage = QLabel(usage_str)
            set_widget_style(lbl_usage, "font-size: 10px; color: rgba(255,255,255,0.6); background: transparent;")
            top_line.addWidget(lbl_usage)
            r_lay.addLayout(top_line)

            bar = QFrame()
            bar.setFixedHeight(4)
            set_widget_style(bar, f"QFrame {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {bar_color}, stop:{bar_ratio} {bar_color}, stop:{bar_ratio + 0.01} rgba(255,255,255,0.08), stop:1 rgba(255,255,255,0.08)); border-radius: 2px; }}")
            r_lay.addWidget(bar)
            self.apps_container.addWidget(row)

    def _toggle_app_mode(self):
        self._top_apps_by_ram = not self._top_apps_by_ram
        self.lbl_apps_hdr.setText("Top apps • RAM" if self._top_apps_by_ram else "Top apps • CPU")
        self.btn_toggle_mode.setText("CPU ⇄" if self._top_apps_by_ram else "RAM ⇄")
        self._populate_top_apps()

    def _run_speed_test(self):
        self.btn_speed.setEnabled(False)
        self.btn_speed.setText("Testing speed...")
        QTimer.singleShot(1500, self._finish_speed_test)

    def _finish_speed_test(self):
        self.btn_speed.setEnabled(True)
        self.btn_speed.setText("▶ Run speed test")
        self.speed_test_requested.emit()

    def _refresh_stats(self):
        try:
            import psutil
            cpu_pct = psutil.cpu_percent(interval=None)
            self.gauge_cpu._dial.set_value(cpu_pct)

            mem = psutil.virtual_memory()
            ram_pct = mem.percent
            used_gb = (mem.total - mem.available) / (1024 ** 3)
            total_gb = mem.total / (1024 ** 3)
            free_gb = mem.available / (1024 ** 3)
            self.gauge_ram._dial.set_value(ram_pct)
            self.gauge_ram._lbl_sub.setText(f"{used_gb:.1f} / {total_gb:.1f} GB")
            if hasattr(self.gauge_ram, "_chip1"):
                self.gauge_ram._chip1.setText(f"{free_gb:.1f} GB free")

            disk = psutil.disk_usage("C:\\")
            d_used = disk.used / (1024 ** 3)
            d_total = disk.total / (1024 ** 3)
            self.lbl_disk_val.setText(f"{int(d_used)} / {int(d_total)} GB")

            import time
            up_sec = int(time.time() - psutil.boot_time())
            up_h = up_sec // 3600
            up_m = (up_sec % 3600) // 60
            self.lbl_up_val.setText(f"{up_h} h {up_m} m")
        except Exception:
            pass


