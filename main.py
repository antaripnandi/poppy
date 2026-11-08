"""
Poppy - Dynamic Notch & Productivity Island for Windows
Main application entry point and lifecycle manager.
"""

import sys
import os
import json
import subprocess
from html import escape
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QUrl
from PySide6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor, QDesktopServices
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox, QToolTip

# Ensure poppy package is importable
current_dir = Path(__file__).resolve().parent
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(current_dir.parent))

from poppy.core.window import DynamicNotchWindow
from poppy.core import APP_VERSION
from poppy.ui.theme import set_widget_style
from poppy.ui.styles import get_stylesheet, DEFAULT_THEME
from poppy.core.instance import SingleInstance
from poppy.core.storage import data_path, resource_path, write_json, protect_spotify_cookie, spotify_cookie
from poppy.core.system_features import get_autostart_state, set_autostart_state
from poppy.core.updates import RELEASES_URL, UpdateChecker


def load_config() -> dict:
    user_config = data_path("config.json")
    bundled_config = resource_path("config.json")
    defaults = {}
    try:
        defaults = json.loads(bundled_config.read_text(encoding="utf-8"))
        if not isinstance(defaults, dict):
            defaults = {}
    except (OSError, ValueError):
        pass
    config_file = user_config if user_config.exists() else bundled_config
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)
            if not isinstance(config, dict):
                raise ValueError("Settings must contain a JSON object")
            for section, default in defaults.items():
                if isinstance(default, dict) and section in config and not isinstance(config[section], dict):
                    config[section] = default
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
    return defaults


def show_notification(notch, tray, title, message):
    if tray.isVisible() and tray.supportsMessages():
        tray.showMessage(title, message)
    else:
        position = notch._displayed_geometry().bottomLeft() + QPoint(8, 6)
        QToolTip.showText(position, f"<b>{escape(title)}</b><br>{escape(message)}", notch, msecShowTime=4500)


def create_tray_icon() -> QIcon:
    """Load Poppy's flower avatar, retaining a fallback for missing resources."""
    icon = QIcon(str(resource_path("assets/branding/poppy-avatar.png")))
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


def _check_install():
    """Check the bundled runtime without opening the user's profile."""
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtNetwork import QSslSocket
    from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
    from winsdk.windows.storage.streams import DataReader

    QPdfDocument()
    config = json.loads(resource_path("config.json").read_text(encoding="utf-8"))
    if (not isinstance(config, dict) or not QSslSocket.supportsSsl()
            or QIcon(str(resource_path("assets/branding/poppy-avatar.png"))).isNull()):
        return False
    with resource_path("assets/sounds/chime.wav").open("rb") as chime:
        if chime.read(4) != b"RIFF":
            return False
    probe = protect_spotify_cookie("poppy-install-check")
    return spotify_cookie({"spotify_sp_dc_protected": probe}) == "poppy-install-check"


def main():
    # Windows DPI awareness & rendering hints
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

    app = QApplication(sys.argv)
    app.setApplicationName("Poppy")
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("PoppyNotch")
    app.setWindowIcon(create_tray_icon())
    app.setQuitOnLastWindowClosed(False)  # Keep running in tray
    if sys.argv[1:] == ["--check-install"]:
        try:
            return 0 if _check_install() else 1
        except Exception as error:
            print(f"[Poppy] Install check failed: {error}", file=sys.stderr)
            return 1

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
    if getattr(sys, "frozen", False) and not os.environ.get("POPPY_DATA_DIR") and get_autostart_state():
        set_autostart_state(True)
    appearance = config.get("appearance", {})
    set_widget_style(app, get_stylesheet(appearance.get("theme", DEFAULT_THEME), appearance.get("layout", "Classic")))

    # Create & display dynamic notch window
    notch = DynamicNotchWindow(config=config)
    notch.show()
    if app.platformName() == "windows":
        notch.start_system_level_controls()
    def activate_notch():
        notch.show()
        notch.raise_()
        notch.activateWindow()
    instance.activation_requested.connect(activate_notch)

    # System Tray Icon Setup
    tray_icon = QSystemTrayIcon(create_tray_icon(), app)
    tray_icon.setToolTip("Poppy - Dynamic Notch & Productivity Island")
    notch.message_requested.connect(lambda title, message: show_notification(notch, tray_icon, title, message))

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

    checker = UpdateChecker(app)
    update_state = data_path("update_state.json")
    try:
        last_notified = json.loads(update_state.read_text(encoding="utf-8")).get("last_notified", "")
    except (OSError, ValueError, AttributeError):
        last_notified = ""
    release_url = RELEASES_URL

    def open_release():
        QDesktopServices.openUrl(QUrl(release_url))

    act_release = QAction("View available update", tray_menu)
    act_release.setVisible(False)
    act_release.triggered.connect(open_release)
    tray_menu.addAction(act_release)
    act_check = QAction("Check for updates", tray_menu)
    act_check.triggered.connect(lambda: checker.check(manual=True))
    tray_menu.addAction(act_check)
    notch.update_check_requested.connect(lambda: checker.check(manual=True))

    def report_update(version, message, manual):
        nonlocal last_notified, release_url
        if version:
            release_url = f"{RELEASES_URL}/tag/v{version}"
            act_release.setVisible(True)
            if manual:
                if QMessageBox.question(notch, "Poppy update", f"Poppy {version} is available. Open the release page?") == QMessageBox.StandardButton.Yes:
                    open_release()
            elif last_notified != version and notch._alerts_allowed():
                notch.trigger_island(f"Poppy {version} is available", "Check for updates in Settings > About.")
                last_notified = version
                try:
                    write_json(update_state, {"last_notified": version})
                except OSError:
                    pass
        elif manual:
            QMessageBox.information(notch, "Poppy updates", message)

    def sync_update_preferences():
        installed_profile = getattr(sys, "frozen", False) and not os.environ.get("POPPY_DATA_DIR")
        checker.configure(installed_profile and notch.config.get("updates", {}).get("automatic", True))

    checker.checked.connect(report_update)
    notch.settings_applied.connect(sync_update_preferences)
    sync_update_preferences()

    def restart_app():
        if not notch.close():
            return
        tray_icon.hide()
        instance.close()
        main_script = str(Path(__file__).resolve())
        frozen = getattr(sys, "frozen", False)
        args = [sys.executable] + ([] if frozen else [main_script]) + sys.argv[1:]
        env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1") if frozen else None
        try:
            subprocess.Popen(args, env=env)
        except OSError as error:
            QMessageBox.warning(None, "Poppy could not restart", str(error))
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

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
