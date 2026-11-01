"""
Poppy Dedicated Settings Application ("Make it yours")
Faithfully recreating NotchX's Appearance & Configuration studio:
- 7 Theme preset cards (Graphite, Midnight, Aurora, Ember, Lime, Rose, Pure black)
- Size & Shape controls with live updates (Notch vs Pill style, width, height, corner radius)
- Pomodoro timer settings
- Discord Rich Presence customizer
- Hardware HUD telemetry options
"""

import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor, QPainter, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QSpinBox, QCheckBox, QPushButton, QStackedWidget, QListWidget,
    QFrame, QComboBox, QSlider, QScrollArea
)

from poppy.ui.styles import THEME_PRESETS, DEFAULT_THEME


class ThemeCard(QFrame):
    """Visual theme preset selector card matching NotchX's Appearance page."""
    clicked = Signal(str)

    def __init__(self, theme_key: str, theme_data: dict, is_selected: bool = False, parent=None):
        super().__init__(parent)
        self.theme_key = theme_key
        self.theme_data = theme_data
        self.is_selected = is_selected
        self.setFixedSize(115, 65)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_appearance()

    def set_selected(self, selected: bool):
        self.is_selected = selected
        self.update_appearance()

    def update_appearance(self):
        bg = self.theme_data["bg"]
        accent = self.theme_data["accent"]
        border_col = accent if self.is_selected else "rgba(255, 255, 255, 0.12)"
        border_w = 2 if self.is_selected else 1

        self.setStyleSheet(f"""
            ThemeCard {{
                background-color: {bg};
                border: {border_w}px solid {border_col};
                border-radius: 8px;
            }}
            ThemeCard:hover {{
                border: {border_w}px solid {accent};
            }}
        """)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.theme_key)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw Accent dot inside
        accent = QColor(self.theme_data["accent"])
        painter.setBrush(QBrush(accent))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(self.width() - 20, self.height() - 20, 10, 10)

        # Theme Name text
        painter.setPen(QColor("#f1f5f9" if self.is_selected else "#94a3b8"))
        font = QFont("Segoe UI", 8, QFont.Weight.DemiBold if self.is_selected else QFont.Weight.Medium)
        painter.setFont(font)
        painter.drawText(10, 22, self.theme_data["name"])


class SettingsWindow(QWidget):
    settings_saved = Signal(dict)
    appearance_live_updated = Signal(dict)

    def __init__(self, config: dict = None, parent=None):
        super().__init__(parent)
        self.config = config or {}
        self.setWindowTitle("Poppy Settings — Make it yours")
        self.resize(680, 480)
        self.setMinimumSize(600, 420)

        self._theme_cards = {}
        self._init_ui()
        self._load_values()

    def _init_ui(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #08090d;
                color: #e2e8f0;
                font-family: 'Segoe UI Variable Display', 'Segoe UI', system-ui, sans-serif;
            }
            QListWidget {
                background-color: #050608;
                border: none;
                border-right: 1px solid rgba(255, 255, 255, 0.06);
                padding: 10px 6px;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 8px 14px;
                border-radius: 6px;
                color: #94a3b8;
                font-weight: 500;
            }
            QListWidget::item:selected {
                background-color: rgba(10, 132, 255, 0.16);
                color: #0a84ff;
                font-weight: 600;
            }
            QListWidget::item:hover:!selected {
                background-color: rgba(255, 255, 255, 0.04);
                color: #f1f5f9;
            }
            QSpinBox, QComboBox, QLineEdit {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.09);
                border-radius: 6px;
                padding: 4px 8px;
                color: #f8fafc;
            }
            QSlider::groove:horizontal {
                height: 4px;
                background: rgba(255, 255, 255, 0.12);
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #0a84ff;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #f8fafc;
                width: 12px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 6px;
            }
            QCheckBox {
                spacing: 8px;
                color: #cbd5e1;
                font-size: 11px;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 3px;
                background-color: rgba(255, 255, 255, 0.05);
            }
            QCheckBox::indicator:checked {
                background-color: #0a84ff;
                border: 1px solid #38bdf8;
            }
        """)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Left Nav Sidebar
        self.nav_list = QListWidget()
        self.nav_list.setFixedWidth(160)
        self.nav_list.addItem("Appearance")
        self.nav_list.addItem("Behavior")
        self.nav_list.addItem("Pomodoro")
        self.nav_list.addItem("Discord RPC")
        self.nav_list.addItem("Hardware HUD")
        self.nav_list.addItem("About")
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)
        main_layout.addWidget(self.nav_list)

        # Right Content Area
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(22, 18, 22, 18)
        right_layout.setSpacing(14)

        self.stack = QStackedWidget()

        # =====================================================================
        # 1. Appearance Page (NotchX "Make it yours")
        # =====================================================================
        scroll_app = QScrollArea()
        scroll_app.setWidgetResizable(True)
        scroll_app.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        page_app = QWidget()
        l_app = QVBoxLayout(page_app)
        l_app.setContentsMargins(0, 0, 8, 0)
        l_app.setSpacing(14)

        lbl_app_hdr = QLabel("Appearance")
        lbl_app_hdr.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        lbl_app_sub = QLabel("One click sets the background, gradient and accent together.")
        lbl_app_sub.setStyleSheet("font-size: 11px; color: #94a3b8;")
        l_app.addWidget(lbl_app_hdr)
        l_app.addWidget(lbl_app_sub)

        # Theme preset grid
        theme_grid = QGridLayout()
        theme_grid.setSpacing(10)
        row, col = 0, 0
        for key, data in THEME_PRESETS.items():
            card = ThemeCard(key, data, is_selected=(key == DEFAULT_THEME), parent=self)
            card.clicked.connect(self._on_theme_card_clicked)
            self._theme_cards[key] = card
            theme_grid.addWidget(card, row, col)
            col += 1
            if col >= 5:
                col = 0
                row += 1
        l_app.addLayout(theme_grid)

        # Size & Shape Section
        l_app.addSpacing(10)
        lbl_shape_hdr = QLabel("Size & Shape")
        lbl_shape_hdr.setStyleSheet("font-size: 13px; font-weight: 700; color: #f8fafc;")
        lbl_shape_sub = QLabel("Drag the sliders — the notch updates live.")
        lbl_shape_sub.setStyleSheet("font-size: 11px; color: #94a3b8;")
        l_app.addWidget(lbl_shape_hdr)
        l_app.addWidget(lbl_shape_sub)

        # Style dropdown (Notch vs Pill)
        row_style = QHBoxLayout()
        lbl_style = QLabel("Style:")
        lbl_style.setStyleSheet("font-size: 11px; color: #cbd5e1;")
        self.combo_style = QComboBox()
        self.combo_style.addItems(["Notch", "Pill"])
        self.combo_style.setToolTip("Notch hugs the top screen edge; Pill floats as an island.")
        self.combo_style.currentTextChanged.connect(self._on_live_appearance_change)
        row_style.addWidget(lbl_style)
        row_style.addWidget(self.combo_style)
        row_style.addStretch()
        l_app.addLayout(row_style)

        # Sliders: Collapsed W, Collapsed H, Open W, Open H, Radius
        self.slider_col_w, self.lbl_val_col_w = self._create_slider_row(l_app, "Collapsed width (px)", 160, 320, 210)
        self.slider_col_h, self.lbl_val_col_h = self._create_slider_row(l_app, "Collapsed height (px)", 24, 40, 30)
        self.slider_open_w, self.lbl_val_open_w = self._create_slider_row(l_app, "Open width (px)", 520, 800, 660)
        self.slider_open_h, self.lbl_val_open_h = self._create_slider_row(l_app, "Open height (px)", 260, 460, 340)
        self.slider_radius, self.lbl_val_radius = self._create_slider_row(l_app, "Corner radius (px)", 8, 24, 16)

        scroll_app.setWidget(page_app)
        self.stack.addWidget(scroll_app)

        # =====================================================================
        # 2. Behavior Page
        # =====================================================================
        page_beh = QWidget()
        l_beh = QVBoxLayout(page_beh)
        l_beh.setSpacing(12)

        lbl_beh_hdr = QLabel("Behavior & Interactions")
        lbl_beh_hdr.setStyleSheet("font-size: 15px; font-weight: bold; color: #f8fafc;")
        l_beh.addWidget(lbl_beh_hdr)

        self.chk_hover_peek = QCheckBox("Bloom to Media HUD automatically on mouse hover")
        l_beh.addWidget(self.chk_hover_peek)

        self.chk_tray_close = QCheckBox("Keep Poppy active in System Tray when drawer is closed")
        l_beh.addWidget(self.chk_tray_close)

        row_dur = QHBoxLayout()
        lbl_dur = QLabel("Animation Spring Duration (ms):")
        lbl_dur.setStyleSheet("font-size: 11px; color: #cbd5e1;")
        self.spin_anim_ms = QSpinBox()
        self.spin_anim_ms.setRange(80, 500)
        self.spin_anim_ms.setSingleStep(20)
        row_dur.addWidget(lbl_dur)
        row_dur.addWidget(self.spin_anim_ms)
        row_dur.addStretch()
        l_beh.addLayout(row_dur)

        l_beh.addStretch()
        self.stack.addWidget(page_beh)

        # =====================================================================
        # 3. Pomodoro Page
        # =====================================================================
        page_pomo = QWidget()
        l_pomo = QVBoxLayout(page_pomo)
        l_pomo.setSpacing(12)

        lbl_pomo_hdr = QLabel("Pomodoro Timer")
        lbl_pomo_hdr.setStyleSheet("font-size: 15px; font-weight: bold; color: #f8fafc;")
        l_pomo.addWidget(lbl_pomo_hdr)

        self.spin_pomo_work = self._create_spin_row(l_pomo, "Focus Sprint (minutes):", 1, 120, 25)
        self.spin_pomo_break = self._create_spin_row(l_pomo, "Short Break (minutes):", 1, 60, 5)
        self.spin_pomo_long = self._create_spin_row(l_pomo, "Long Break (minutes):", 1, 90, 15)

        self.chk_pomo_sound = QCheckBox("Play notification chime on cycle completion")
        l_pomo.addWidget(self.chk_pomo_sound)

        l_pomo.addStretch()
        self.stack.addWidget(page_pomo)

        # =====================================================================
        # 4. Discord RPC Page
        # =====================================================================
        page_rpc = QWidget()
        l_rpc = QVBoxLayout(page_rpc)
        l_rpc.setSpacing(10)

        lbl_rpc_hdr = QLabel("Discord Rich Presence")
        lbl_rpc_hdr.setStyleSheet("font-size: 15px; font-weight: bold; color: #f8fafc;")
        l_rpc.addWidget(lbl_rpc_hdr)

        self.chk_rpc_enable = QCheckBox("Enable Discord Rich Presence status broadcasting")
        l_rpc.addWidget(self.chk_rpc_enable)

        row_client = QHBoxLayout()
        lbl_cid = QLabel("Application Client ID:")
        lbl_cid.setStyleSheet("font-size: 11px; color: #cbd5e1;")
        self.txt_rpc_client = QLineEdit()
        self.txt_rpc_client.setPlaceholderText("Enter your Discord Developer Client ID")
        row_client.addWidget(lbl_cid)
        row_client.addWidget(self.txt_rpc_client)
        l_rpc.addLayout(row_client)

        row_mode = QHBoxLayout()
        lbl_mode = QLabel("Presence Mode:")
        lbl_mode.setStyleSheet("font-size: 11px; color: #cbd5e1;")
        self.combo_rpc_mode = QComboBox()
        self.combo_rpc_mode.addItems(["Dynamic (Follows Pomodoro & Media)", "Static Custom Presence"])
        row_mode.addWidget(lbl_mode)
        row_mode.addWidget(self.combo_rpc_mode)
        row_mode.addStretch()
        l_rpc.addLayout(row_mode)

        l_rpc.addStretch()
        self.stack.addWidget(page_rpc)

        # =====================================================================
        # 5. Hardware HUD Page
        # =====================================================================
        page_hw = QWidget()
        l_hw = QVBoxLayout(page_hw)
        l_hw.setSpacing(12)

        lbl_hw_hdr = QLabel("Hardware Telemetry HUD")
        lbl_hw_hdr.setStyleSheet("font-size: 15px; font-weight: bold; color: #f8fafc;")
        l_hw.addWidget(lbl_hw_hdr)

        self.chk_monitor_gpu = QCheckBox("Query NVIDIA GPU Utilization (via NVML)")
        l_hw.addWidget(self.chk_monitor_gpu)

        self.chk_monitor_bat = QCheckBox("Monitor Battery Level & AC Power State")
        l_hw.addWidget(self.chk_monitor_bat)

        l_hw.addStretch()
        self.stack.addWidget(page_hw)

        # =====================================================================
        # 6. About Page
        # =====================================================================
        page_abt = QWidget()
        l_abt = QVBoxLayout(page_abt)
        l_abt.setSpacing(10)

        lbl_abt_hdr = QLabel("Poppy Dynamic Notch")
        lbl_abt_hdr.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        lbl_abt_ver = QLabel("Version 2.0 (Windows 11 / 10)")
        lbl_abt_ver.setStyleSheet("font-size: 11px; color: #94a3b8;")
        lbl_abt_desc = QLabel("Hardware-accelerated top-bezel notch inspired by NotchX and Apple Dynamic Island.\nBuilt in Python with PySide6.")
        lbl_abt_desc.setStyleSheet("font-size: 11px; color: #64748b; line-height: 1.5;")
        l_abt.addWidget(lbl_abt_hdr)
        l_abt.addWidget(lbl_abt_ver)
        l_abt.addWidget(lbl_abt_desc)
        l_abt.addStretch()
        self.stack.addWidget(page_abt)

        right_layout.addWidget(self.stack, stretch=1)

        # Bottom Bar: Save & Close button
        bottom_bar = QHBoxLayout()
        bottom_bar.addStretch()
        self.btn_save = QPushButton("Save & Apply")
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #0a84ff;
                border: none;
                border-radius: 6px;
                padding: 6px 18px;
                font-weight: 600;
                font-size: 12px;
                color: #ffffff;
            }
            QPushButton:hover {
                background-color: #38bdf8;
            }
        """)
        self.btn_save.clicked.connect(self._save_settings)
        bottom_bar.addWidget(self.btn_save)
        right_layout.addLayout(bottom_bar)

        main_layout.addWidget(right_container, stretch=1)
        self.nav_list.setCurrentRow(0)

    def _create_slider_row(self, layout, label_text: str, min_v: int, max_v: int, default_v: int):
        row = QHBoxLayout()
        lbl = QLabel(label_text)
        lbl.setStyleSheet("font-size: 11px; color: #cbd5e1;")
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(min_v, max_v)
        slider.setValue(default_v)
        val_lbl = QLabel(str(default_v))
        val_lbl.setFixedWidth(36)
        val_lbl.setStyleSheet("font-size: 11px; color: #0a84ff; font-weight: 600;")
        slider.valueChanged.connect(lambda v: val_lbl.setText(str(v)))
        slider.valueChanged.connect(self._on_live_appearance_change)

        row.addWidget(lbl, stretch=1)
        row.addWidget(slider, stretch=2)
        row.addWidget(val_lbl)
        layout.addLayout(row)
        return slider, val_lbl

    def _create_spin_row(self, layout, label_text: str, min_v: int, max_v: int, default_v: int):
        row = QHBoxLayout()
        lbl = QLabel(label_text)
        lbl.setStyleSheet("font-size: 11px; color: #cbd5e1;")
        spin = QSpinBox()
        spin.setRange(min_v, max_v)
        spin.setValue(default_v)
        row.addWidget(lbl)
        row.addWidget(spin)
        row.addStretch()
        layout.addLayout(row)
        return spin

    def _on_nav_changed(self, row: int):
        self.stack.setCurrentIndex(row)

    def _on_theme_card_clicked(self, theme_key: str):
        for k, card in self._theme_cards.items():
            card.set_selected(k == theme_key)
        self._on_live_appearance_change()

    def _get_current_selected_theme(self) -> str:
        for k, card in self._theme_cards.items():
            if card.is_selected:
                return k
        return DEFAULT_THEME

    def _on_live_appearance_change(self):
        appearance_dict = {
            "theme": self._get_current_selected_theme(),
            "style": self.combo_style.currentText(),
            "collapsed_width": self.slider_col_w.value(),
            "collapsed_height": self.slider_col_h.value(),
            "open_width": self.slider_open_w.value(),
            "open_height": self.slider_open_h.value(),
            "corner_radius": self.slider_radius.value(),
        }
        self.appearance_live_updated.emit(appearance_dict)

    def _load_values(self):
        app_cfg = self.config.get("appearance", {})
        active_theme = app_cfg.get("theme", DEFAULT_THEME)
        for k, card in self._theme_cards.items():
            card.set_selected(k == active_theme)

        style = app_cfg.get("style", "Notch")
        idx = self.combo_style.findText(style)
        if idx >= 0:
            self.combo_style.setCurrentIndex(idx)

        self.slider_col_w.setValue(app_cfg.get("collapsed_width", 210))
        self.slider_col_h.setValue(app_cfg.get("collapsed_height", 30))
        self.slider_open_w.setValue(app_cfg.get("open_width", 660))
        self.slider_open_h.setValue(app_cfg.get("open_height", 340))
        self.slider_radius.setValue(app_cfg.get("corner_radius", 16))

        notch_cfg = self.config.get("notch", {})
        self.chk_hover_peek.setChecked(notch_cfg.get("auto_hover_peek", True))
        self.spin_anim_ms.setValue(notch_cfg.get("animation_duration_ms", 200))
        self.chk_tray_close.setChecked(notch_cfg.get("keep_in_tray", True))

        pomo_cfg = self.config.get("pomodoro", {})
        self.spin_pomo_work.setValue(pomo_cfg.get("work_duration", 1500) // 60)
        self.spin_pomo_break.setValue(pomo_cfg.get("break_duration", 300) // 60)
        self.spin_pomo_long.setValue(pomo_cfg.get("long_break_duration", 900) // 60)
        self.chk_pomo_sound.setChecked(pomo_cfg.get("sound_enabled", True))

        rpc_cfg = self.config.get("discord_rpc", {})
        self.chk_rpc_enable.setChecked(rpc_cfg.get("enabled", False))
        self.txt_rpc_client.setText(rpc_cfg.get("client_id", "120000000000000000"))
        mode_idx = 0 if rpc_cfg.get("mode") == "dynamic" else 1
        self.combo_rpc_mode.setCurrentIndex(mode_idx)

        hw_cfg = self.config.get("hardware_hud", {})
        self.chk_monitor_gpu.setChecked(hw_cfg.get("monitor_gpu", True))
        self.chk_monitor_bat.setChecked(hw_cfg.get("monitor_battery", True))

    def _save_settings(self):
        new_config = {
            "appearance": {
                "theme": self._get_current_selected_theme(),
                "style": self.combo_style.currentText(),
                "collapsed_width": self.slider_col_w.value(),
                "collapsed_height": self.slider_col_h.value(),
                "open_width": self.slider_open_w.value(),
                "open_height": self.slider_open_h.value(),
                "corner_radius": self.slider_radius.value(),
            },
            "pomodoro": {
                "work_duration": self.spin_pomo_work.value() * 60,
                "break_duration": self.spin_pomo_break.value() * 60,
                "long_break_duration": self.spin_pomo_long.value() * 60,
                "sound_enabled": self.chk_pomo_sound.isChecked(),
            },
            "notch": {
                "auto_hover_peek": self.chk_hover_peek.isChecked(),
                "animation_duration_ms": self.spin_anim_ms.value(),
                "keep_in_tray": self.chk_tray_close.isChecked(),
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

        # Save to config.json
        cfg_path = Path(__file__).resolve().parent.parent / "config.json"
        try:
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(new_config, f, indent=2)
        except Exception as e:
            print(f"[Poppy Settings] Error saving config: {e}")

        self.config = new_config
        self.settings_saved.emit(new_config)
        self.close()
