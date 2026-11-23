"""
Hitodama In-App Control Flyouts for Poppy
Provides rich, native, in-app menus for Wi-Fi, Bluetooth, Audio Devices, and Night Light.
Styled to match Hitodama's dark frosted obsidian theme (#161a22).
"""

import subprocess
import threading
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor, QCursor
from PySide6.QtWidgets import (
    QMenu, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidgetAction, QScrollArea, QFrame, QSizePolicy
)

from poppy.ui.theme import set_widget_style
from poppy.ui.icons import Icons
from poppy.ui.components import ToggleSwitch
from poppy.core.system_features import AudioEndpointManager, BluetoothManager


FLYOUT_MENU_STYLE = """
    QMenu {
        background-color: #161a22;
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 14px;
        padding: 4px;
    }
    QMenu::item {
        background: transparent;
        padding: 0;
    }
"""


class WifiFlyoutMenu(QMenu):
    """In-app Wi-Fi networks flyout with real scanned networks and connect actions."""
    network_selected = Signal(str)
    wifi_toggled = Signal(bool)

    def __init__(self, parent=None, accent="#f28c5a"):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
        set_widget_style(self, FLYOUT_MENU_STYLE)
        self._accent = accent
        self._is_connected = False
        self._connected_ssid = ""
        self._networks = []

        self._panel = QWidget(self)
        self._panel.setFixedWidth(340)
        self._panel_lay = QVBoxLayout(self._panel)
        self._panel_lay.setContentsMargins(14, 14, 14, 14)
        self._panel_lay.setSpacing(10)

        # 1. Header: Wi-Fi Title & Toggle
        hdr = QHBoxLayout()
        lbl_title = QLabel("Wi-Fi")
        set_widget_style(lbl_title, "font-size: 14px; font-weight: 700; color: #ffffff; background: transparent;")
        hdr.addWidget(lbl_title)
        hdr.addStretch()

        self.toggle_wifi = ToggleSwitch(accent=self._accent, checked=True, parent=self._panel)
        self.toggle_wifi.toggled.connect(self._on_toggle_wifi)
        hdr.addWidget(self.toggle_wifi)
        self._panel_lay.addLayout(hdr)

        # 2. Connected Network Box
        self.box_connected = QFrame(self._panel)
        self.box_connected.setObjectName("box_connected")
        set_widget_style(self.box_connected, "#box_connected { background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 10px; padding: 6px; }")
        self.conn_lay = QHBoxLayout(self.box_connected)
        self.conn_lay.setContentsMargins(10, 8, 10, 8)
        self.conn_lay.setSpacing(10)

        self.lbl_conn_icon = QLabel("●")
        set_widget_style(self.lbl_conn_icon, "color: #10b981; font-size: 12px; background: transparent; border: none;")
        self.conn_lay.addWidget(self.lbl_conn_icon)

        v_conn = QVBoxLayout()
        v_conn.setSpacing(1)
        self.lbl_conn_ssid = QLabel("Connected")
        set_widget_style(self.lbl_conn_ssid, "font-size: 13px; font-weight: 700; color: #ffffff; background: transparent; border: none;")
        self.lbl_conn_status = QLabel("Connected • 100% signal")
        set_widget_style(self.lbl_conn_status, "font-size: 11px; color: rgba(255, 255, 255, 0.55); background: transparent; border: none;")
        v_conn.addWidget(self.lbl_conn_ssid)
        v_conn.addWidget(self.lbl_conn_status)
        self.conn_lay.addLayout(v_conn, 1)

        self.btn_disconnect = QPushButton("Disconnect")
        self.btn_disconnect.setCursor(Qt.CursorShape.PointingHandCursor)
        set_widget_style(self.btn_disconnect, """
            QPushButton {
                background: rgba(255, 255, 255, 0.06);
                border: 1px solid rgba(255, 255, 255, 0.09);
                border-radius: 7px;
                color: rgba(255, 255, 255, 0.8);
                font-size: 11px;
                font-weight: 600;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background: rgba(239, 68, 68, 0.2);
                border-color: rgba(239, 68, 68, 0.4);
                color: #fca5a5;
            }
        """)
        self.btn_disconnect.clicked.connect(self._disconnect_wifi)
        self.conn_lay.addWidget(self.btn_disconnect)
        self._panel_lay.addWidget(self.box_connected)

        # 3. Available Networks Section
        lbl_avail = QLabel("AVAILABLE NETWORKS")
        set_widget_style(lbl_avail, "font-size: 10px; font-weight: 700; color: #717d8f; background: transparent; letter-spacing: 0.5px;")
        self._panel_lay.addWidget(lbl_avail)

        # Scroll area for available networks
        self.scroll = QScrollArea(self._panel)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFixedHeight(150)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        set_widget_style(self.scroll, "QScrollArea { background: transparent; border: none; }")

        self.list_container = QWidget()
        set_widget_style(self.list_container, "background: transparent;")
        self.list_lay = QVBoxLayout(self.list_container)
        self.list_lay.setContentsMargins(0, 0, 4, 0)
        self.list_lay.setSpacing(4)
        self.list_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.list_container)
        self._panel_lay.addWidget(self.scroll)

        # 4. Bottom Link
        btn_settings = QPushButton("Windows Network & Internet settings")
        btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        set_widget_style(btn_settings, f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {self._accent};
                font-size: 11.5px;
                font-weight: 600;
                text-align: left;
                padding: 4px 0;
            }}
            QPushButton:hover {{
                text-decoration: underline;
            }}
        """)
        btn_settings.clicked.connect(self._open_windows_settings)
        self._panel_lay.addWidget(btn_settings)

        action = QWidgetAction(self)
        action.setDefaultWidget(self._panel)
        self.addAction(action)

    def refresh(self):
        """Scans current Wi-Fi status and networks."""
        def _scan():
            is_conn = False
            ssid = ""
            networks = []
            try:
                out = subprocess.check_output("netsh wlan show interfaces", shell=True, text=True, stderr=subprocess.DEVNULL)
                for line in out.splitlines():
                    line = line.strip()
                    if line.startswith("SSID") and not line.startswith("BSSID"):
                        parts = line.split(":", 1)
                        if len(parts) == 2 and parts[1].strip():
                            ssid = parts[1].strip()
                            is_conn = True
                            break
            except Exception:
                pass

            try:
                out_net = subprocess.check_output("netsh wlan show networks mode=bssid", shell=True, text=True, stderr=subprocess.DEVNULL)
                curr_ssid = None
                curr_sig = "100%"
                for line in out_net.splitlines():
                    line = line.strip()
                    if line.startswith("SSID") and not line.startswith("BSSID"):
                        parts = line.split(":", 1)
                        if len(parts) == 2 and parts[1].strip():
                            curr_ssid = parts[1].strip()
                    elif line.startswith("Signal") and curr_ssid:
                        curr_sig = line.split(":", 1)[1].strip()
                        if curr_ssid != ssid and not any(n["ssid"] == curr_ssid for n in networks):
                            networks.append({"ssid": curr_ssid, "signal": curr_sig})
                        curr_ssid = None
            except Exception:
                pass

            QTimer.singleShot(0, lambda: self._apply_scan(is_conn, ssid, networks))

        threading.Thread(target=_scan, daemon=True, name="poppy-wifi-scan").start()

    def _apply_scan(self, is_conn: bool, ssid: str, networks: list):
        self._is_connected = is_conn
        self._connected_ssid = ssid
        self._networks = networks
        self.toggle_wifi.blockSignals(True)
        self.toggle_wifi.setChecked(is_conn)
        self.toggle_wifi.blockSignals(False)

        if is_conn and ssid:
            self.box_connected.show()
            self.lbl_conn_ssid.setText(ssid)
            self.lbl_conn_status.setText("Connected • Active Internet")
        else:
            self.box_connected.hide()

        # Render available list
        while self.list_lay.count() > 0:
            item = self.list_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not networks:
            lbl_empty = QLabel("No other Wi-Fi networks in range." if is_conn else "No Wi-Fi networks found.")
            set_widget_style(lbl_empty, "color: rgba(255, 255, 255, 0.4); font-size: 11px; padding: 12px 0;")
            lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.list_lay.addWidget(lbl_empty)
            return

        for net in networks:
            n_ssid = net.get("ssid", "")
            n_sig = net.get("signal", "80%")
            row = QFrame()
            row.setObjectName("wifi_row")
            set_widget_style(row, "#wifi_row { background: rgba(255, 255, 255, 0.04); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 8px; padding: 4px 8px; } #wifi_row:hover { background: rgba(255, 255, 255, 0.08); }")
            r_lay = QHBoxLayout(row)
            r_lay.setContentsMargins(6, 4, 6, 4)
            r_lay.setSpacing(8)

            lbl_icon = QLabel("📶")
            set_widget_style(lbl_icon, "color: rgba(255, 255, 255, 0.7); font-size: 12px; background: transparent; border: none;")
            r_lay.addWidget(lbl_icon)

            lbl_name = QLabel(n_ssid)
            lbl_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            set_widget_style(lbl_name, "color: #ffffff; font-size: 12px; font-weight: 500; background: transparent; border: none;")
            r_lay.addWidget(lbl_name, 1)

            lbl_s = QLabel(n_sig)
            set_widget_style(lbl_s, "color: rgba(255, 255, 255, 0.4); font-size: 10px; background: transparent; border: none;")
            r_lay.addWidget(lbl_s)

            btn_conn = QPushButton("Connect")
            btn_conn.setCursor(Qt.CursorShape.PointingHandCursor)
            set_widget_style(btn_conn, f"""
                QPushButton {{
                    background: {self._accent};
                    color: #0e1117;
                    font-size: 10.5px;
                    font-weight: 700;
                    border: none;
                    border-radius: 6px;
                    padding: 3px 8px;
                }}
                QPushButton:hover {{
                    background: #f7a278;
                }}
            """)
            btn_conn.clicked.connect(lambda _, s=n_ssid: self._connect_network(s))
            r_lay.addWidget(btn_conn)

            self.list_lay.addWidget(row)

    def _connect_network(self, ssid: str):
        self.network_selected.emit(ssid)
        try:
            subprocess.Popen(f'netsh wlan connect name="{ssid}"', shell=True)
        except Exception:
            pass
        QTimer.singleShot(2000, self.refresh)

    def _disconnect_wifi(self):
        try:
            subprocess.Popen("netsh wlan disconnect", shell=True)
        except Exception:
            pass
        QTimer.singleShot(1000, self.refresh)

    def _on_toggle_wifi(self, enabled: bool):
        self.wifi_toggled.emit(enabled)
        cmd = f'netsh interface set interface "Wi-Fi" {"enable" if enabled else "disable"}'
        try:
            subprocess.Popen(cmd, shell=True)
        except Exception:
            pass
        QTimer.singleShot(1500, self.refresh)

    def _open_windows_settings(self):
        self.hide()
        try:
            subprocess.Popen("start ms-availablenetworks:", shell=True)
        except Exception:
            pass


class BluetoothFlyoutMenu(QMenu):
    """In-app Bluetooth flyout with live paired devices and connection controls."""
    device_selected = Signal(str)

    def __init__(self, parent=None, accent="#f28c5a"):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
        set_widget_style(self, FLYOUT_MENU_STYLE)
        self._accent = accent

        self._panel = QWidget(self)
        self._panel.setFixedWidth(340)
        self._panel_lay = QVBoxLayout(self._panel)
        self._panel_lay.setContentsMargins(14, 14, 14, 14)
        self._panel_lay.setSpacing(10)

        # 1. Header: Bluetooth Title & Toggle
        hdr = QHBoxLayout()
        lbl_title = QLabel("Bluetooth")
        set_widget_style(lbl_title, "font-size: 14px; font-weight: 700; color: #ffffff; background: transparent;")
        hdr.addWidget(lbl_title)
        hdr.addStretch()

        self.toggle_bt = ToggleSwitch(accent=self._accent, checked=True, parent=self._panel)
        hdr.addWidget(self.toggle_bt)
        self._panel_lay.addLayout(hdr)

        # 2. Devices Section
        lbl_devs = QLabel("DEVICES")
        set_widget_style(lbl_devs, "font-size: 10px; font-weight: 700; color: #717d8f; background: transparent; letter-spacing: 0.5px;")
        self._panel_lay.addWidget(lbl_devs)

        self.scroll = QScrollArea(self._panel)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFixedHeight(160)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        set_widget_style(self.scroll, "QScrollArea { background: transparent; border: none; }")

        self.list_container = QWidget()
        set_widget_style(self.list_container, "background: transparent;")
        self.list_lay = QVBoxLayout(self.list_container)
        self.list_lay.setContentsMargins(0, 0, 4, 0)
        self.list_lay.setSpacing(4)
        self.list_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.list_container)
        self._panel_lay.addWidget(self.scroll)

        # 3. Bottom Action
        btn_settings = QPushButton("+ Add device in Windows settings")
        btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        set_widget_style(btn_settings, f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {self._accent};
                font-size: 11.5px;
                font-weight: 600;
                text-align: left;
                padding: 4px 0;
            }}
            QPushButton:hover {{
                text-decoration: underline;
            }}
        """)
        btn_settings.clicked.connect(self._open_windows_settings)
        self._panel_lay.addWidget(btn_settings)

        action = QWidgetAction(self)
        action.setDefaultWidget(self._panel)
        self.addAction(action)

    def refresh(self):
        """Refreshes Bluetooth device status."""
        def _scan():
            devs = []
            try:
                devs = BluetoothManager._get_devices()
            except Exception:
                pass
            QTimer.singleShot(0, lambda: self._apply_devices(devs))

        threading.Thread(target=_scan, daemon=True, name="poppy-bt-scan").start()

    def _apply_devices(self, devices: list):
        while self.list_lay.count() > 0:
            item = self.list_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not devices:
            lbl_empty = QLabel("No Bluetooth devices currently connected.\nTurn on your headphones, mouse, or keyboard.")
            set_widget_style(lbl_empty, "color: rgba(255, 255, 255, 0.45); font-size: 11px; padding: 20px 0;")
            lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_empty.setWordWrap(True)
            self.list_lay.addWidget(lbl_empty)
            return

        for dev in devices:
            name = dev.get("name", "Bluetooth Device")
            conn = dev.get("connected", False)
            row = QFrame()
            set_widget_style(row, "QFrame { background: rgba(255, 255, 255, 0.04); border-radius: 8px; padding: 4px 8px; } QFrame:hover { background: rgba(255, 255, 255, 0.08); }")
            r_lay = QHBoxLayout(row)
            r_lay.setContentsMargins(6, 4, 6, 4)
            r_lay.setSpacing(8)

            lbl_icon = QLabel("🎧" if "head" in name.lower() or "audio" in name.lower() else "🖱" if "mouse" in name.lower() else "⌨" if "key" in name.lower() else "📱")
            set_widget_style(lbl_icon, "color: rgba(255, 255, 255, 0.7); font-size: 12px; background: transparent;")
            r_lay.addWidget(lbl_icon)

            lbl_name = QLabel(name)
            lbl_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            set_widget_style(lbl_name, "color: #ffffff; font-size: 12px; font-weight: 500; background: transparent;")
            r_lay.addWidget(lbl_name, 1)

            lbl_st = QLabel("Connected" if conn else "Paired")
            set_widget_style(lbl_st, f"color: {'#10b981' if conn else 'rgba(255,255,255,0.4)'}; font-size: 10px; font-weight: 600; background: transparent;")
            r_lay.addWidget(lbl_st)

            self.list_lay.addWidget(row)

    def _open_windows_settings(self):
        self.hide()
        try:
            subprocess.Popen("start ms-settings:bluetooth", shell=True)
        except Exception:
            pass


class AudioDeviceFlyoutMenu(QMenu):
    """In-app Sound Output device switcher flyout with instant endpoint switching."""
    device_changed = Signal(str)

    def __init__(self, parent=None, accent="#f28c5a"):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
        set_widget_style(self, FLYOUT_MENU_STYLE)
        self._accent = accent

        self._panel = QWidget(self)
        self._panel.setFixedWidth(340)
        self._panel_lay = QVBoxLayout(self._panel)
        self._panel_lay.setContentsMargins(14, 14, 14, 14)
        self._panel_lay.setSpacing(10)

        # 1. Header: Sound Output
        hdr = QHBoxLayout()
        lbl_title = QLabel("Sound Output")
        set_widget_style(lbl_title, "font-size: 14px; font-weight: 700; color: #ffffff; background: transparent;")
        hdr.addWidget(lbl_title)
        hdr.addStretch()
        self._panel_lay.addLayout(hdr)

        # 2. Output Endpoints List
        self.list_box = QWidget(self._panel)
        self.list_lay = QVBoxLayout(self.list_box)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(6)
        self._panel_lay.addWidget(self.list_box)

        # 3. Bottom Links
        bot_row = QHBoxLayout()
        btn_settings = QPushButton("Windows Sound settings")
        btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        set_widget_style(btn_settings, f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {self._accent};
                font-size: 11.5px;
                font-weight: 600;
                text-align: left;
                padding: 4px 0;
            }}
            QPushButton:hover {{
                text-decoration: underline;
            }}
        """)
        btn_settings.clicked.connect(self._open_windows_sound)
        bot_row.addWidget(btn_settings)
        bot_row.addStretch()
        self._panel_lay.addLayout(bot_row)

        action = QWidgetAction(self)
        action.setDefaultWidget(self._panel)
        self.addAction(action)

    def refresh(self):
        """Scans output audio endpoints."""
        while self.list_lay.count() > 0:
            item = self.list_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        endpoints = []
        try:
            endpoints = AudioEndpointManager.get_output_endpoints()
        except Exception:
            pass

        if not endpoints:
            lbl_empty = QLabel("Speakers (Default Audio Device)")
            set_widget_style(lbl_empty, "color: #ffffff; font-size: 12px; padding: 8px;")
            self.list_lay.addWidget(lbl_empty)
            return

        for ep in endpoints:
            name = ep.get("name", "Audio Device")
            dev_id = ep.get("id", "")
            is_def = ep.get("default", False)

            btn_row = QPushButton()
            btn_row.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_row.setFixedHeight(38)

            r_lay = QHBoxLayout(btn_row)
            r_lay.setContentsMargins(10, 4, 10, 4)
            r_lay.setSpacing(10)

            lbl_icon = QLabel("🎧" if "headphone" in name.lower() or "headset" in name.lower() else "🔊")
            set_widget_style(lbl_icon, "font-size: 13px; background: transparent;")
            r_lay.addWidget(lbl_icon)

            lbl_name = QLabel(name)
            lbl_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            set_widget_style(lbl_name, "color: #ffffff; font-size: 12px; font-weight: 600; background: transparent;")
            r_lay.addWidget(lbl_name, 1)

            if is_def:
                lbl_chk = QLabel("✓")
                set_widget_style(lbl_chk, f"color: {self._accent}; font-size: 13px; font-weight: 800; background: transparent;")
                r_lay.addWidget(lbl_chk)
                set_widget_style(btn_row, f"""
                    QPushButton {{
                        background: rgba(242, 140, 90, 0.12);
                        border: 1px solid rgba(242, 140, 90, 0.4);
                        border-radius: 9px;
                        text-align: left;
                    }}
                """)
            else:
                set_widget_style(btn_row, """
                    QPushButton {
                        background: rgba(255, 255, 255, 0.04);
                        border: 1px solid rgba(255, 255, 255, 0.07);
                        border-radius: 9px;
                        text-align: left;
                    }
                    QPushButton:hover {
                        background: rgba(255, 255, 255, 0.08);
                    }
                """)

            btn_row.clicked.connect(lambda _, d_id=dev_id, d_name=name: self._select_device(d_id, d_name))
            self.list_lay.addWidget(btn_row)

    def _select_device(self, dev_id: str, dev_name: str):
        try:
            AudioEndpointManager.set_default_output(dev_id)
            self.device_changed.emit(dev_name)
        except Exception:
            pass
        self.refresh()

    def _open_windows_sound(self):
        self.hide()
        try:
            subprocess.Popen("start ms-settings:sound", shell=True)
        except Exception:
            pass


class NightLightFlyoutMenu(QMenu):
    """In-app Night Light flyout."""
    night_light_toggled = Signal(bool)

    def __init__(self, parent=None, accent="#f28c5a"):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
        set_widget_style(self, FLYOUT_MENU_STYLE)
        self._accent = accent

        self._panel = QWidget(self)
        self._panel.setFixedWidth(280)
        self._panel_lay = QVBoxLayout(self._panel)
        self._panel_lay.setContentsMargins(14, 14, 14, 14)
        self._panel_lay.setSpacing(10)

        # 1. Header: Night Light
        hdr = QHBoxLayout()
        lbl_title = QLabel("Night Light")
        set_widget_style(lbl_title, "font-size: 14px; font-weight: 700; color: #ffffff; background: transparent;")
        hdr.addWidget(lbl_title)
        hdr.addStretch()

        self.toggle_night = ToggleSwitch(accent=self._accent, checked=False, parent=self._panel)
        self.toggle_night.toggled.connect(self._on_toggle)
        hdr.addWidget(self.toggle_night)
        self._panel_lay.addLayout(hdr)

        lbl_desc = QLabel("Warmer screen colors filter blue light to help you fall asleep.")
        lbl_desc.setWordWrap(True)
        set_widget_style(lbl_desc, "font-size: 11px; color: rgba(255, 255, 255, 0.55); background: transparent;")
        self._panel_lay.addWidget(lbl_desc)

        # Bottom Link
        btn_settings = QPushButton("Windows Night light settings")
        btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        set_widget_style(btn_settings, f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {self._accent};
                font-size: 11.5px;
                font-weight: 600;
                text-align: left;
                padding: 4px 0;
            }}
            QPushButton:hover {{
                text-decoration: underline;
            }}
        """)
        btn_settings.clicked.connect(self._open_windows_nightlight)
        self._panel_lay.addWidget(btn_settings)

        action = QWidgetAction(self)
        action.setDefaultWidget(self._panel)
        self.addAction(action)

    def set_status(self, is_on: bool):
        self.toggle_night.blockSignals(True)
        self.toggle_night.setChecked(is_on)
        self.toggle_night.blockSignals(False)

    def _on_toggle(self, enabled: bool):
        self.night_light_toggled.emit(enabled)
        try:
            subprocess.Popen("start ms-settings:nightlight", shell=True)
        except Exception:
            pass

    def _open_windows_nightlight(self):
        self.hide()
        try:
            subprocess.Popen("start ms-settings:nightlight", shell=True)
        except Exception:
            pass
