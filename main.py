"""
Poppy - Dynamic Notch & Productivity Island for Windows
Main application entry point and lifecycle manager.
"""

import sys
import os
import json
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu

# Ensure poppy package is importable
current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(current_dir.parent))

from poppy.core.window import DynamicNotchWindow
from poppy.ui.styles import get_stylesheet, DEFAULT_THEME


def load_config() -> dict:
    config_file = current_dir / "config.json"
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Poppy] Config load warning: {e}")
    return {}


def create_tray_icon() -> QIcon:
    """Generate a clean vector-style tray icon programmatically."""
    pix = QPixmap(32, 32)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Rounded pill badge
    painter.setBrush(QColor("#0a84ff"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(4, 8, 24, 16, 8, 8)

    painter.setPen(QColor("#ffffff"))
    font = painter.font()
    font.setPointSize(9)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "P")
    painter.end()
    return QIcon(pix)


def main():
    # Windows DPI awareness & rendering hints
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

    app = QApplication(sys.argv)
    app.setApplicationName("Poppy")
    app.setOrganizationName("PoppyNotch")
    app.setQuitOnLastWindowClosed(False)  # Keep running in tray

    # Load persistent settings
    config = load_config()
    active_theme = config.get("appearance", {}).get("theme", DEFAULT_THEME)
    app.setStyleSheet(get_stylesheet(active_theme))

    # Create & display dynamic notch window
    notch = DynamicNotchWindow(config=config)
    notch.show()

    # System Tray Icon Setup
    tray_icon = QSystemTrayIcon(create_tray_icon(), app)
    tray_icon.setToolTip("Poppy - Dynamic Notch & Productivity Island")

    tray_menu = QMenu()
    act_show = QAction("Show Notch", tray_menu)
    act_show.triggered.connect(notch.show)
    tray_menu.addAction(act_show)

    act_focus = QAction("Start Focus Sprint", tray_menu)
    act_focus.triggered.connect(notch.pomodoro.start)
    tray_menu.addAction(act_focus)

    act_note = QAction("New Sticky Note", tray_menu)
    act_note.triggered.connect(lambda: notch._tear_off_sticky_note(""))
    tray_menu.addAction(act_note)

    act_settings = QAction("Settings", tray_menu)
    act_settings.triggered.connect(notch.open_settings)
    tray_menu.addAction(act_settings)

    def restart_app():
        tray_icon.hide()
        notch.close()
        main_script = str(Path(__file__).resolve())
        args = [sys.executable, main_script] + sys.argv[1:]
        subprocess.Popen(args)
        app.quit()

    def exit_app():
        tray_icon.hide()
        notch.close()
        app.quit()

    tray_menu.addSeparator()

    act_restart = QAction("Restart Poppy", tray_menu)
    act_restart.triggered.connect(restart_app)
    tray_menu.addAction(act_restart)

    act_quit = QAction("Exit Poppy", tray_menu)
    act_quit.triggered.connect(exit_app)
    tray_menu.addAction(act_quit)

    tray_icon.setContextMenu(tray_menu)
    tray_icon.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
