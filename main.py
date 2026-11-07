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
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox

# Ensure poppy package is importable
current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(current_dir.parent))

from poppy.core.window import DynamicNotchWindow
from poppy.ui.theme import set_widget_style
from poppy.ui.styles import get_stylesheet, DEFAULT_THEME
from poppy.core.instance import SingleInstance
from poppy.core.storage import data_path, write_json, protect_spotify_cookie


def load_config() -> dict:
    user_config = data_path("config.json")
    config_file = user_config
    if not config_file.exists():
        config_file = current_dir / "config.json"
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)
            if not isinstance(config, dict):
                raise ValueError("Settings must contain a JSON object")
            media = config.get("media", {})
            migrate_cookie = isinstance(media, dict) and bool(media.get("spotify_sp_dc"))
            if migrate_cookie:
                try:
                    media["spotify_sp_dc_protected"] = protect_spotify_cookie(media["spotify_sp_dc"])
                    del media["spotify_sp_dc"]
                except OSError:
                    migrate_cookie = False
            if migrate_cookie or config_file != user_config:
                try:
                    write_json(user_config, config)
                except OSError as error:
                    print(f"[Poppy] Could not write settings: {error}")
            return config
        except Exception as e:
            print(f"[Poppy] Config load warning: {e}")
    return {}


def create_tray_icon() -> QIcon:
    """Load Poppy's flower avatar, retaining a fallback for missing resources."""
    icon = QIcon(str(current_dir / "assets" / "branding" / "poppy-avatar.png"))
    if not icon.isNull():
        return icon
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
    app.setWindowIcon(create_tray_icon())
    app.setQuitOnLastWindowClosed(False)  # Keep running in tray
    try:
        instance = SingleInstance(app)
        if not instance.acquire():
            return
    except OSError as error:
        QMessageBox.warning(None, "Poppy could not start", str(error))
        return
    app.aboutToQuit.connect(instance.close)

    # Load persistent settings
    config = load_config()
    appearance = config.get("appearance", {})
    set_widget_style(app, get_stylesheet(appearance.get("theme", DEFAULT_THEME), appearance.get("layout", "Classic")))

    # Create & display dynamic notch window
    notch = DynamicNotchWindow(config=config)
    notch.show()
    notch.start_system_level_controls()
    def activate_notch():
        notch.show()
        notch.raise_()
        notch.activateWindow()
    instance.activation_requested.connect(activate_notch)

    # System Tray Icon Setup
    tray_icon = QSystemTrayIcon(create_tray_icon(), app)
    tray_icon.setToolTip("Poppy - Dynamic Notch & Productivity Island")
    notch.message_requested.connect(lambda title, message: tray_icon.showMessage(title, message))

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
        if not notch.close():
            return
        tray_icon.hide()
        instance.close()
        main_script = str(Path(__file__).resolve())
        args = [sys.executable] + ([] if getattr(sys, "frozen", False) else [main_script]) + sys.argv[1:]
        subprocess.Popen(args)
        app.quit()

    def exit_app():
        if not notch.close():
            return
        tray_icon.hide()
        app.quit()

    tray_menu.addSeparator()

    act_restart = QAction("Restart Poppy", tray_menu)
    act_restart.triggered.connect(restart_app)
    tray_menu.addAction(act_restart)

    act_quit = QAction("Exit Poppy", tray_menu)
    act_quit.triggered.connect(exit_app)
    notch.quit_requested.connect(exit_app)
    tray_menu.addAction(act_quit)

    tray_icon.setContextMenu(tray_menu)
    def sync_tray():
        tray_icon.setVisible(notch.config.get("notch", {}).get("keep_in_tray", True))
    notch.settings_applied.connect(sync_tray)
    sync_tray()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
