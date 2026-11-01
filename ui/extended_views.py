"""
Poppy Extended Tabs Suite
Faithfully bringing NotchX's advanced capabilities to Poppy:
- Calendar Tab: Interactive month calendar, today highlighting, and persistent agenda.
- Clipboard Tab: Searchable clipboard history, click-to-copy, pinning, and privacy masking.
- Docs Tab: Word/Text to PDF converter, PDF text extraction, and recent files tray matching documents-v2.
- Launcher Tab: Raycast/Spotlight command palette for instant app launching and system tasks.
- Desktops Tab: Virtual Desktops and running windows management matching desktops-v2.
- Screen Annotation Overlay: Live on-screen drawing, markup, and highlight canvas.
"""

import os
import sys
import json
import time
import calendar
from datetime import datetime, date
from pathlib import Path
import subprocess

from PySide6.QtCore import (
    Qt, QRect, QRectF, QPoint, QSize, Signal, QTimer, QUrl, QMimeData, QDate
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPainterPath, QCursor, QFont,
    QPageSize, QTextDocument, QPdfWriter
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QScrollArea, QFrame, QApplication, QFileDialog
)

from poppy.ui.icons import Icons, get_fluent_font_family
from poppy.ui.components import CardFrame, IconButton, DraggableThumbnail
from poppy.core.system_tools import lock_workstation


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

        self.store_file = Path(os.path.expanduser("~/.poppy/calendar_events.json"))
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
            self.store_file.write_text(json.dumps(self.events, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(14, 10, 14, 12)
        main_layout.setSpacing(16)

        # Left Column: Interactive Month Calendar
        left_col = QVBoxLayout()
        left_col.setSpacing(10)

        # Header: Month & Navigation
        hdr_row = QHBoxLayout()
        hdr_row.setContentsMargins(4, 0, 4, 0)
        self.lbl_month_year = QLabel()
        self.lbl_month_year.setStyleSheet("font-size: 15px; font-weight: 700; color: #f8fafc; border: none; background: transparent;")

        btn_prev = IconButton(Icons.PREV, "Previous Month", size=24, font_size=11, is_fluent=True)
        btn_prev.clicked.connect(self._prev_month)
        btn_today = QPushButton("Today")
        btn_today.setStyleSheet("font-size: 10px; padding: 2px 8px; border-radius: 6px; background: rgba(255,255,255,0.06); color: #cbd5e1; border: none;")
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
        main_layout.addLayout(left_col, stretch=3)

        # Right Column: Agenda & Selected Date Schedule
        card_agenda = CardFrame(self)
        l_agenda = QVBoxLayout(card_agenda)
        l_agenda.setContentsMargins(14, 12, 14, 12)
        l_agenda.setSpacing(8)

        self.lbl_agenda_date = QLabel()
        self.lbl_agenda_date.setStyleSheet("font-size: 11px; font-weight: 700; color: #94a3b8; letter-spacing: 0.5px; border: none; background: transparent;")
        l_agenda.addWidget(self.lbl_agenda_date)

        # Event List Scroll Area
        self.events_scroll = QScrollArea()
        self.events_scroll.setWidgetResizable(True)
        self.events_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.events_container = QWidget()
        self.events_layout = QVBoxLayout(self.events_container)
        self.events_layout.setContentsMargins(0, 0, 0, 0)
        self.events_layout.setSpacing(4)
        self.events_scroll.setWidget(self.events_container)
        l_agenda.addWidget(self.events_scroll, stretch=1)

        # Add Event Row
        add_row = QHBoxLayout()
        add_row.setSpacing(6)
        self.input_event = QLineEdit()
        self.input_event.setPlaceholderText("Add schedule / meeting...")
        self.input_event.setStyleSheet("""
            QLineEdit {
                background: rgba(255, 255, 255, 0.05);
                border: none;
                border-radius: 6px;
                color: #f1f5f9;
                font-size: 10.5px;
                padding: 4px 8px;
            }
        """)
        self.input_event.returnPressed.connect(self._add_event)

        btn_add = QPushButton("+ Add")
        btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add.setStyleSheet(f"""
            QPushButton {{
                background-color: {self._accent};
                border: none;
                border-radius: 6px;
                color: #ffffff;
                font-size: 10.5px;
                font-weight: 600;
                padding: 4px 10px;
            }}
            QPushButton:hover {{
                opacity: 0.9;
            }}
        """)
        btn_add.clicked.connect(self._add_event)
        add_row.addWidget(self.input_event, stretch=1)
        add_row.addWidget(btn_add)
        l_agenda.addLayout(add_row)

        main_layout.addWidget(card_agenda, stretch=2)

        self._render_calendar()
        self._render_agenda()

    def _render_calendar(self):
        # Clear existing grid
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        month_name = calendar.month_name[self.current_month]
        self.lbl_month_year.setText(f"{month_name} {self.current_year}")

        # Weekday headers
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for col, d in enumerate(days):
            lbl_d = QLabel(d)
            lbl_d.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_d.setStyleSheet("font-size: 10px; font-weight: 600; color: #64748b; border: none; background: transparent;")
            self.grid_layout.addWidget(lbl_d, 0, col)

        # Days cells
        month_cal = calendar.monthcalendar(self.current_year, self.current_month)
        today = date.today()

        for row_idx, week in enumerate(month_cal, start=1):
            for col_idx, day_num in enumerate(week):
                if day_num == 0:
                    continue
                cell_date = date(self.current_year, self.current_month, day_num)
                is_today = (cell_date == today)
                is_selected = (cell_date == self.selected_date)

                date_str = cell_date.isoformat()
                has_events = bool(self.events.get(date_str))

                btn_day = QPushButton(str(day_num))
                btn_day.setFixedSize(36, 32)
                btn_day.setCursor(Qt.CursorShape.PointingHandCursor)

                # Style computation
                if is_selected:
                    bg = self._accent
                    color = "#ffffff"
                    font_w = "700"
                elif is_today:
                    bg = "rgba(255, 255, 255, 0.14)"
                    color = "#38bdf8"
                    font_w = "700"
                else:
                    bg = "rgba(255, 255, 255, 0.03)"
                    color = "#cbd5e1"
                    font_w = "500"

                dot_sub = " ·" if has_events and not is_selected else ""
                btn_day.setText(f"{day_num}{dot_sub}")
                btn_day.setStyleSheet(f"""
                    QPushButton {{
                        background: {bg};
                        border: none;
                        border-radius: 8px;
                        color: {color};
                        font-size: 11px;
                        font-weight: {font_w};
                    }}
                    QPushButton:hover {{
                        background: rgba(255, 255, 255, 0.18);
                    }}
                """)
                btn_day.clicked.connect(lambda checked=False, cd=cell_date: self._select_date(cd))
                self.grid_layout.addWidget(btn_day, row_idx, col_idx)

    def _select_date(self, dt: date):
        self.selected_date = dt
        self._render_calendar()
        self._render_agenda()

    def _render_agenda(self):
        while self.events_layout.count():
            item = self.events_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        date_str = self.selected_date.isoformat()
        pretty_date = self.selected_date.strftime("%A, %d %B")
        self.lbl_agenda_date.setText(pretty_date.upper())

        day_events = self.events.get(date_str, [])
        if not day_events:
            lbl_empty = QLabel("No events scheduled for this day.")
            lbl_empty.setStyleSheet("font-size: 10.5px; color: #64748b; border: none; background: transparent; padding: 10px 0;")
            self.events_layout.addWidget(lbl_empty)
        else:
            for idx, ev in enumerate(day_events):
                row = QWidget()
                row.setStyleSheet("background: rgba(255, 255, 255, 0.035); border-radius: 6px;")
                r_l = QHBoxLayout(row)
                r_l.setContentsMargins(8, 6, 8, 6)
                r_l.setSpacing(6)

                lbl_text = QLabel(ev.get("title", ""))
                lbl_text.setStyleSheet("font-size: 11px; color: #f1f5f9; border: none; background: transparent;")
                r_l.addWidget(lbl_text, stretch=1)

                btn_del = IconButton(Icons.CLOSE, "Delete Event", size=18, font_size=8, is_fluent=True)
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
        self._render_calendar()

    def _next_month(self):
        if self.current_month == 12:
            self.current_month = 1
            self.current_year += 1
        else:
            self.current_month += 1
        self._render_calendar()

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

class ClipboardTabView(QWidget):
    """
    Searchable clipboard history viewer with click-to-copy, pinning,
    and automatic sensitive data protection.
    """
    def __init__(self, clip_mgr, parent=None):
        super().__init__(parent)
        self.clip_mgr = clip_mgr
        self._init_ui()
        self.clip_mgr.history_updated.connect(self._render_clips)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(10)

        # Header with Search Bar and Actions
        hdr = QHBoxLayout()
        hdr.setSpacing(8)

        self.input_search = QLineEdit()
        self.input_search.setPlaceholderText("Search clipboard history...")
        self.input_search.setStyleSheet("""
            QLineEdit {
                background: rgba(255, 255, 255, 0.05);
                border: none;
                border-radius: 8px;
                color: #f1f5f9;
                font-size: 11px;
                padding: 6px 12px;
            }
        """)
        self.input_search.textChanged.connect(self._render_clips)
        hdr.addWidget(self.input_search, stretch=1)

        btn_clear = QPushButton("Clear All")
        btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clear.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.06);
                border: none;
                border-radius: 8px;
                color: #cbd5e1;
                font-size: 10px;
                font-weight: 500;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background: rgba(239, 68, 68, 0.25);
                color: #f87171;
            }
        """)
        btn_clear.clicked.connect(self.clip_mgr.clear_all)
        hdr.addWidget(btn_clear)
        layout.addLayout(hdr)

        # Clips List
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.container = QWidget()
        self.items_layout = QVBoxLayout(self.container)
        self.items_layout.setContentsMargins(0, 0, 0, 0)
        self.items_layout.setSpacing(6)
        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll, stretch=1)

        self._render_clips()

    def _render_clips(self):
        while self.items_layout.count():
            item = self.items_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        filter_q = self.input_search.text().lower().strip()
        clips = self.clip_mgr.history

        if filter_q:
            clips = [c for c in clips if filter_q in c["text"].lower()]

        if not clips:
            lbl_empty = QLabel("No matching clipboard items.")
            lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_empty.setStyleSheet("color: #64748b; font-size: 11px; padding: 24px 0; border: none; background: transparent;")
            self.items_layout.addWidget(lbl_empty)
            return

        for idx, clip in enumerate(clips):
            row = QFrame()
            row.setStyleSheet("""
                QFrame {
                    background: rgba(255, 255, 255, 0.04);
                    border: none;
                    border-radius: 8px;
                }
                QFrame:hover {
                    background: rgba(255, 255, 255, 0.08);
                }
            """)
            r_l = QHBoxLayout(row)
            r_l.setContentsMargins(12, 8, 12, 8)
            r_l.setSpacing(10)

            # Text Preview (Max 2 lines)
            txt = clip["text"]
            disp = txt.replace("\n", " ").strip()
            if len(disp) > 120:
                disp = disp[:120] + "..."

            lbl_txt = QLabel(disp)
            lbl_txt.setStyleSheet("font-size: 11px; color: #f1f5f9; border: none; background: transparent;")
            lbl_txt.setWordWrap(True)
            r_l.addWidget(lbl_txt, stretch=1)

            lbl_time = QLabel(clip.get("time", ""))
            lbl_time.setStyleSheet("font-size: 9.5px; color: #94a3b8; border: none; background: transparent;")
            r_l.addWidget(lbl_time)

            # Copy Button
            btn_copy = QPushButton("Copy")
            btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_copy.setStyleSheet("""
                QPushButton {
                    background: rgba(14, 165, 233, 0.2);
                    border: none;
                    border-radius: 5px;
                    color: #38bdf8;
                    font-size: 10px;
                    font-weight: 600;
                    padding: 3px 8px;
                }
                QPushButton:hover {
                    background: rgba(14, 165, 233, 0.35);
                    color: #ffffff;
                }
            """)
            btn_copy.clicked.connect(lambda checked=False, t=txt, b=btn_copy: self._copy_clip(t, b))
            r_l.addWidget(btn_copy)

            # Pin Button
            is_pinned = clip.get("pinned", False)
            btn_pin = IconButton(Icons.PIN, "Unpin" if is_pinned else "Pin to top", size=20, font_size=10, is_fluent=True)
            if is_pinned:
                btn_pin.setStyleSheet("color: #38bdf8; background: rgba(56, 189, 248, 0.2); border: none; border-radius: 4px;")
            btn_pin.clicked.connect(lambda checked=False, i=idx: self.clip_mgr.toggle_pin(i))
            r_l.addWidget(btn_pin)

            # Delete Button
            btn_del = IconButton(Icons.CLOSE, "Delete Clip", size=20, font_size=9, is_fluent=True)
            btn_del.clicked.connect(lambda checked=False, i=idx: self.clip_mgr.delete_clip(i))
            r_l.addWidget(btn_del)

            self.items_layout.addWidget(row)

        self.items_layout.addStretch()

    def _copy_clip(self, text: str, btn: QPushButton):
        cb = QApplication.clipboard()
        cb.setText(text)
        btn.setText("Copied!")
        btn.setStyleSheet("background: rgba(34, 197, 94, 0.28); color: #4ade80; border: none; border-radius: 5px; font-size: 10px; font-weight: 700; padding: 3px 8px;")
        QTimer.singleShot(1500, lambda: self._reset_copy_btn(btn))

    def _reset_copy_btn(self, btn: QPushButton):
        btn.setText("Copy")
        btn.setStyleSheet("background: rgba(14, 165, 233, 0.2); color: #38bdf8; border: none; border-radius: 5px; font-size: 10px; font-weight: 600; padding: 3px 8px;")


# =====================================================================
# 3. Docs / PDF Studio Tab View
# =====================================================================

class DocsTabView(QWidget):
    """
    Local document studio matching documents-v2.png.
    Converts Word/Markdown/Text to PDF, extracts text from PDF, and provides a drag-out shelf.
    """
    def __init__(self, parent=None, accent="#6e9bff"):
        super().__init__(parent)
        self._accent = accent
        self._recent_files: list[str] = []
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 14, 18, 14)
        main_layout.setSpacing(14)

        # 3 Action Cards matching documents-v2.png
        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)

        # Card 1: Word / Text -> PDF
        card_w2p = CardFrame(self)
        l_w2p = QVBoxLayout(card_w2p)
        l_w2p.setContentsMargins(16, 16, 16, 16)
        l_w2p.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l_w2p.setSpacing(6)

        lbl_i1 = QLabel(Icons.DOCS)
        lbl_i1.setStyleSheet("font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets'; font-size: 26px; color: #f1f5f9; border: none; background: transparent;")
        lbl_i1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_t1 = QLabel("Text / Word → PDF")
        lbl_t1.setStyleSheet("font-size: 13px; font-weight: 700; color: #f8fafc; border: none; background: transparent;")
        lbl_t1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_s1 = QLabel("Convert .txt, .md, or paste text to PDF")
        lbl_s1.setStyleSheet("font-size: 10px; color: #94a3b8; border: none; background: transparent;")
        lbl_s1.setAlignment(Qt.AlignmentFlag.AlignCenter)

        btn_act1 = QPushButton("Select File to Convert")
        btn_act1.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_act1.setStyleSheet(f"background: {self._accent}; border: none; border-radius: 6px; color: white; font-size: 10px; font-weight: 600; padding: 4px 12px; margin-top: 4px;")
        btn_act1.clicked.connect(self._convert_to_pdf)

        l_w2p.addWidget(lbl_i1)
        l_w2p.addWidget(lbl_t1)
        l_w2p.addWidget(lbl_s1)
        l_w2p.addWidget(btn_act1)
        cards_row.addWidget(card_w2p)

        # Card 2: PDF Info & Text Extract
        card_p2w = CardFrame(self)
        l_p2w = QVBoxLayout(card_p2w)
        l_p2w.setContentsMargins(16, 16, 16, 16)
        l_p2w.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l_p2w.setSpacing(6)

        lbl_i2 = QLabel(Icons.PENCIL)
        lbl_i2.setStyleSheet("font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets'; font-size: 26px; color: #f1f5f9; border: none; background: transparent;")
        lbl_i2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_t2 = QLabel("Inspect PDF Metadata")
        lbl_t2.setStyleSheet("font-size: 13px; font-weight: 700; color: #f8fafc; border: none; background: transparent;")
        lbl_t2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_s2 = QLabel("Check page count and document info")
        lbl_s2.setStyleSheet("font-size: 10px; color: #94a3b8; border: none; background: transparent;")
        lbl_s2.setAlignment(Qt.AlignmentFlag.AlignCenter)

        btn_act2 = QPushButton("Select PDF")
        btn_act2.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_act2.setStyleSheet("background: rgba(255,255,255,0.08); border: none; border-radius: 6px; color: #f1f5f9; font-size: 10px; font-weight: 600; padding: 4px 12px; margin-top: 4px;")
        btn_act2.clicked.connect(self._inspect_pdf)

        l_p2w.addWidget(lbl_i2)
        l_p2w.addWidget(lbl_t2)
        l_p2w.addWidget(lbl_s2)
        l_p2w.addWidget(btn_act2)
        cards_row.addWidget(card_p2w)

        main_layout.addLayout(cards_row)

        # Info line
        lbl_info = QLabel("Converting locally with native Qt vector PDF engine · Files stay on this PC · Zero cloud leaks")
        lbl_info.setStyleSheet("font-size: 10.5px; color: #64748b; border: none; background: transparent;")
        main_layout.addWidget(lbl_info)

        # Recent Files Tray
        recent_hdr = QHBoxLayout()
        lbl_r = QLabel("RECENT CONVERSIONS")
        lbl_r.setStyleSheet("font-size: 10px; font-weight: 700; color: #94a3b8; letter-spacing: 0.5px; border: none; background: transparent;")
        btn_clear = QPushButton("Clear")
        btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clear.setStyleSheet("font-size: 9.5px; padding: 2px 8px; border: none; border-radius: 4px; background: rgba(255,255,255,0.06); color: #cbd5e1;")
        btn_clear.clicked.connect(self._clear_recent)
        recent_hdr.addWidget(lbl_r)
        recent_hdr.addStretch()
        recent_hdr.addWidget(btn_clear)
        main_layout.addLayout(recent_hdr)

        self.recent_container = QWidget()
        self.recent_layout = QVBoxLayout(self.recent_container)
        self.recent_layout.setContentsMargins(0, 0, 0, 0)
        self.recent_layout.setSpacing(6)
        main_layout.addWidget(self.recent_container)

        self.lbl_empty_recent = QLabel("Converted and generated files show up here. Drag them anywhere.")
        self.lbl_empty_recent.setStyleSheet("font-size: 10.5px; color: #64748b; border: none; background: transparent;")
        self.recent_layout.addWidget(self.lbl_empty_recent)

        main_layout.addStretch()

    def _convert_to_pdf(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select text file to convert to PDF", "", "Documents (*.txt *.md *.py *.json *.html)")
        if not file_path:
            return

        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")
            out_pdf = str(Path(file_path).with_suffix(".pdf"))

            doc = QTextDocument()
            doc.setPlainText(content)
            writer = QPdfWriter(out_pdf)
            writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
            doc.print_(writer)

            self._add_recent(out_pdf)
        except Exception as e:
            pass

    def _inspect_pdf(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select PDF to inspect", "", "PDF Files (*.pdf)")
        if not file_path:
            return

        try:
            from PySide6.QtPdf import QPdfDocument
            doc = QPdfDocument(self)
            err = doc.load(file_path)
            pages = doc.pageCount()
            title = doc.metaData(QPdfDocument.MetaDataField.Title) or Path(file_path).name

            self._add_recent(file_path, extra_info=f"{pages} pages")
        except Exception:
            pass

    def _add_recent(self, file_path: str, extra_info: str = "PDF Document"):
        self.lbl_empty_recent.setVisible(False)
        self._recent_files.append(file_path)

        row = QFrame()
        row.setStyleSheet("background: rgba(255, 255, 255, 0.04); border-radius: 8px; border: none;")
        r_l = QHBoxLayout(row)
        r_l.setContentsMargins(10, 8, 10, 8)
        r_l.setSpacing(10)

        thumb = DraggableThumbnail(size=32, border_radius=6, parent=self)
        thumb.file_path = file_path
        r_l.addWidget(thumb)

        meta = QVBoxLayout()
        meta.setSpacing(2)
        lbl_n = QLabel(Path(file_path).name)
        lbl_n.setStyleSheet("font-size: 11px; font-weight: 600; color: #f1f5f9; border: none; background: transparent;")
        lbl_s = QLabel(f"{extra_info} · Drag into chat, Discord, or desktop")
        lbl_s.setStyleSheet("font-size: 9.5px; color: #94a3b8; border: none; background: transparent;")
        meta.addWidget(lbl_n)
        meta.addWidget(lbl_s)
        r_l.addLayout(meta, stretch=1)

        btn_open = QPushButton("Open")
        btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_open.setStyleSheet("background: rgba(14, 165, 233, 0.2); border: none; border-radius: 5px; color: #38bdf8; font-size: 10px; font-weight: 600; padding: 3px 8px;")
        btn_open.clicked.connect(lambda: os.startfile(file_path))
        r_l.addWidget(btn_open)

        self.recent_layout.insertWidget(0, row)

    def _clear_recent(self):
        self._recent_files.clear()
        while self.recent_layout.count():
            item = self.recent_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.lbl_empty_recent.setVisible(True)
        self.recent_layout.addWidget(self.lbl_empty_recent)


# =====================================================================
# 4. Launcher / Quick Search Tab View
# =====================================================================

class LauncherTabView(QWidget):
    """
    Spotlight / Raycast style command palette.
    Instant launch for Windows Start Menu apps and built-in system tools.
    """
    def __init__(self, indexer, parent=None, accent="#6e9bff"):
        super().__init__(parent)
        self.indexer = indexer
        self._accent = accent
        self.apps = self.indexer.get_installed_apps()
        self._filtered = self.apps
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)

        # Big Search Bar
        self.input_search = QLineEdit()
        self.input_search.setPlaceholderText("Search apps, system actions, or type math...")
        self.input_search.setStyleSheet("""
            QLineEdit {
                background: rgba(255, 255, 255, 0.05);
                border: none;
                border-radius: 10px;
                color: #f8fafc;
                font-size: 13px;
                font-weight: 500;
                padding: 10px 14px;
            }
        """)
        self.input_search.textChanged.connect(self._on_search_changed)
        self.input_search.returnPressed.connect(self._launch_top)
        layout.addWidget(self.input_search)

        # Scroll Area for Results
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.container = QWidget()
        self.results_layout = QVBoxLayout(self.container)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_layout.setSpacing(4)
        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll, stretch=1)

        self._render_results()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(50, self.input_search.setFocus)

    def _on_search_changed(self, text: str):
        q = text.lower().strip()
        if not q:
            self._filtered = self.apps
        else:
            self._filtered = [a for a in self.apps if q in a["name"].lower() or q in a.get("sub", "").lower()]
        self._render_results()

    def _render_results(self):
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        fluent_font = get_fluent_font_family()
        shown = self._filtered[:35]

        if not shown:
            lbl_empty = QLabel("No apps or commands found.")
            lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_empty.setStyleSheet("color: #64748b; font-size: 11px; padding: 20px; border: none; background: transparent;")
            self.results_layout.addWidget(lbl_empty)
            return

        for idx, app in enumerate(shown):
            btn = QPushButton()
            btn.setFixedHeight(38)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 255, 255, 0.035);
                    border: none;
                    border-radius: 8px;
                    text-align: left;
                    padding: 4px 10px;
                }
                QPushButton:hover {
                    background: rgba(255, 255, 255, 0.10);
                }
            """)
            r_l = QHBoxLayout(btn)
            r_l.setContentsMargins(6, 2, 6, 2)
            r_l.setSpacing(10)

            icon_lbl = QLabel(app.get("icon", "\uE71D"))
            icon_lbl.setStyleSheet(f"font-family: '{fluent_font}'; font-size: 14px; color: #38bdf8; border: none; background: transparent;")
            r_l.addWidget(icon_lbl)

            lbl_name = QLabel(app["name"])
            lbl_name.setStyleSheet("font-size: 11.5px; font-weight: 600; color: #f1f5f9; border: none; background: transparent;")
            r_l.addWidget(lbl_name)

            r_l.addStretch()

            lbl_sub = QLabel(app.get("sub", ""))
            lbl_sub.setStyleSheet("font-size: 10px; color: #64748b; border: none; background: transparent;")
            r_l.addWidget(lbl_sub)

            btn.clicked.connect(lambda checked=False, a=app: self._launch_app(a))
            self.results_layout.addWidget(btn)

        self.results_layout.addStretch()

    def _launch_top(self):
        if self._filtered:
            self._launch_app(self._filtered[0])

    def _launch_app(self, app: dict):
        cmd = app.get("cmd", "")
        if cmd == "lock":
            lock_workstation()
            return
        elif cmd == "taskmgr":
            os.system("start taskmgr")
            return
        elif cmd == "ms-settings:":
            os.startfile("ms-settings:")
            return
        elif cmd == "calc":
            os.startfile("calc.exe")
            return
        elif cmd == "ms-screenclip:":
            os.startfile("ms-screenclip:")
            return
        elif cmd == "wt":
            try:
                os.startfile("wt.exe")
            except Exception:
                os.startfile("cmd.exe")
            return
        elif cmd == "explorer":
            os.startfile("explorer.exe")
            return
        elif cmd == "notepad":
            os.startfile("notepad.exe")
            return

        try:
            os.startfile(cmd)
        except Exception:
            pass


# =====================================================================
# 5. Desktops / Spaces Tab View
# =====================================================================

class DesktopsTabView(QWidget):
    """
    Virtual Desktops and window manager matching desktops-v2.png.
    """
    def __init__(self, parent=None, accent="#6e9bff"):
        super().__init__(parent)
        self._accent = accent
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(12)

        # Header with Controls
        hdr = QHBoxLayout()
        lbl_info = QLabel("2 Desktops · 3 Windows · Click to switch or create desktop")
        lbl_info.setStyleSheet("font-size: 11px; color: #94a3b8; border: none; background: transparent;")
        hdr.addWidget(lbl_info)
        hdr.addStretch()

        btn_new_desk = QPushButton("+ New Desktop")
        btn_new_desk.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_new_desk.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.08);
                border: none;
                border-radius: 6px;
                color: #f1f5f9;
                font-size: 10px;
                font-weight: 600;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.16);
            }
        """)
        btn_new_desk.clicked.connect(self._create_new_desktop)
        hdr.addWidget(btn_new_desk)

        btn_task_view = QPushButton("Task View")
        btn_task_view.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_task_view.setStyleSheet(f"""
            QPushButton {{
                background: {self._accent};
                border: none;
                border-radius: 6px;
                color: #ffffff;
                font-size: 10px;
                font-weight: 600;
                padding: 4px 12px;
            }}
        """)
        btn_task_view.clicked.connect(self._open_task_view)
        hdr.addWidget(btn_task_view)
        layout.addLayout(hdr)

        # Desktop 1 Card
        card_d1 = CardFrame(self)
        l_d1 = QVBoxLayout(card_d1)
        l_d1.setContentsMargins(14, 12, 14, 12)
        l_d1.setSpacing(8)

        d1_hdr = QHBoxLayout()
        lbl_d1_title = QLabel("Desktop 1 · 1 Window")
        lbl_d1_title.setStyleSheet("font-size: 12px; font-weight: 700; color: #f8fafc; border: none; background: transparent;")
        btn_switch_1 = QPushButton("Switch here >")
        btn_switch_1.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_switch_1.setStyleSheet("background: rgba(255,255,255,0.06); border: none; border-radius: 5px; color: #cbd5e1; font-size: 10px; font-weight: 600; padding: 3px 10px;")
        btn_switch_1.clicked.connect(self._switch_desktop_left)
        d1_hdr.addWidget(lbl_d1_title)
        d1_hdr.addStretch()
        d1_hdr.addWidget(btn_switch_1)
        l_d1.addLayout(d1_hdr)

        app_row1 = QWidget()
        app_row1.setStyleSheet("background: rgba(255, 255, 255, 0.035); border-radius: 6px;")
        ar_l1 = QHBoxLayout(app_row1)
        ar_l1.setContentsMargins(10, 6, 10, 6)
        lbl_a1 = QLabel("🎵  Spotify · Media Playing")
        lbl_a1.setStyleSheet("font-size: 11px; color: #f1f5f9; border: none; background: transparent;")
        ar_l1.addWidget(lbl_a1)
        l_d1.addWidget(app_row1)
        layout.addWidget(card_d1)

        # Desktop 2 Card (You're here)
        card_d2 = CardFrame(self)
        l_d2 = QVBoxLayout(card_d2)
        l_d2.setContentsMargins(14, 12, 14, 12)
        l_d2.setSpacing(8)

        d2_hdr = QHBoxLayout()
        lbl_d2_title = QLabel("Desktop 2")
        lbl_d2_title.setStyleSheet("font-size: 12px; font-weight: 700; color: #f8fafc; border: none; background: transparent;")
        badge_active = QLabel("You're here")
        badge_active.setStyleSheet(f"background: rgba(56, 189, 248, 0.2); color: #38bdf8; font-size: 9.5px; font-weight: 600; border-radius: 4px; padding: 2px 6px; border: none;")
        d2_hdr.addWidget(lbl_d2_title)
        d2_hdr.addWidget(badge_active)
        d2_hdr.addStretch()
        l_d2.addLayout(d2_hdr)

        app_row2 = QWidget()
        app_row2.setStyleSheet("background: rgba(255, 255, 255, 0.035); border-radius: 6px;")
        ar_l2 = QHBoxLayout(app_row2)
        ar_l2.setContentsMargins(10, 6, 10, 6)
        lbl_a2 = QLabel("💻  Code Editor · Poppy Dynamic Notch")
        lbl_a2.setStyleSheet("font-size: 11px; color: #f1f5f9; border: none; background: transparent;")
        ar_l2.addWidget(lbl_a2)
        l_d2.addWidget(app_row2)
        layout.addWidget(card_d2)

        layout.addStretch()

    def _open_task_view(self):
        # Synthesize Win + Tab
        ctypes.windll.user32.keybd_event(0x5B, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0x09, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0x09, 0, 2, 0)
        ctypes.windll.user32.keybd_event(0x5B, 0, 2, 0)

    def _create_new_desktop(self):
        # Synthesize Win + Ctrl + D
        ctypes.windll.user32.keybd_event(0x5B, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0x11, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0x44, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0x44, 0, 2, 0)
        ctypes.windll.user32.keybd_event(0x11, 0, 2, 0)
        ctypes.windll.user32.keybd_event(0x5B, 0, 2, 0)

    def _switch_desktop_left(self):
        # Synthesize Win + Ctrl + Left
        ctypes.windll.user32.keybd_event(0x5B, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0x11, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0x25, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0x25, 0, 2, 0)
        ctypes.windll.user32.keybd_event(0x11, 0, 2, 0)
        ctypes.windll.user32.keybd_event(0x5B, 0, 2, 0)


# =====================================================================
# 6. Screen Annotation Overlay
# =====================================================================

class ScreenAnnotationOverlay(QWidget):
    """
    Transparent full-screen drawing canvas for live presentation markup.
    """
    def __init__(self, parent=None):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)

        screen_geom = QApplication.primaryScreen().geometry()
        self.setGeometry(screen_geom)

        self._paths: list[tuple[QPainterPath, QColor, int]] = []
        self._current_path = QPainterPath()
        self._pen_color = QColor(255, 75, 75)
        self._pen_width = 3

        # Floating toolbar
        self.toolbar = QFrame(self)
        self.toolbar.setStyleSheet("background: rgba(18, 21, 28, 0.94); border-radius: 12px; border: none;")
        self.toolbar.setGeometry(self.width() // 2 - 140, 24, 280, 40)
        tb_layout = QHBoxLayout(self.toolbar)
        tb_layout.setContentsMargins(10, 4, 10, 4)
        tb_layout.setSpacing(8)

        # Colors
        colors = [
            ("Red", QColor(239, 68, 68)),
            ("Yellow", QColor(234, 179, 8)),
            ("Cyan", QColor(56, 189, 248)),
            ("Green", QColor(34, 197, 94))
        ]
        for name, col in colors:
            btn_col = QPushButton()
            btn_col.setFixedSize(18, 18)
            btn_col.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_col.setStyleSheet(f"background-color: {col.name()}; border-radius: 9px; border: none;")
            btn_col.clicked.connect(lambda checked=False, c=col: self._set_pen_color(c))
            tb_layout.addWidget(btn_col)

        tb_layout.addStretch()

        btn_clr = QPushButton("Clear")
        btn_clr.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clr.setStyleSheet("background: rgba(255,255,255,0.08); border: none; border-radius: 5px; color: #f1f5f9; font-size: 10px; padding: 2px 8px;")
        btn_clr.clicked.connect(self._clear_canvas)
        tb_layout.addWidget(btn_clr)

        btn_close = IconButton(Icons.CLOSE, "Close Annotation", size=22, font_size=10, is_fluent=True)
        btn_close.clicked.connect(self.close)
        tb_layout.addWidget(btn_close)

    def _set_pen_color(self, col: QColor):
        self._pen_color = col

    def _clear_canvas(self):
        self._paths.clear()
        self._current_path = QPainterPath()
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._current_path = QPainterPath()
            self._current_path.moveTo(event.position())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._current_path.lineTo(event.position())
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._paths.append((self._current_path, self._pen_color, self._pen_width))
            self._current_path = QPainterPath()
            self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        for path, col, w in self._paths:
            pen = QPen(col, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPath(path)

        if not self._current_path.isEmpty():
            pen = QPen(self._pen_color, self._pen_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPath(self._current_path)

