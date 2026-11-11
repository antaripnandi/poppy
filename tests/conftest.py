"""Keep tests away from personal files, running media apps, and the desktop."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def pytest_addoption(parser):
    parser.addoption("--live-services", action="store_true", help="Run lyrics tests against live providers")


def pytest_configure(config):
    config.addinivalue_line("markers", "live_service: requires a third-party network service")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--live-services"):
        for item in items:
            if "live_service" in item.keywords:
                item.add_marker(pytest.mark.skip(reason="Use --live-services to test live lyrics providers"))


@pytest.fixture(scope="session")
def audit_app():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFont, QFontDatabase
    app = QApplication.instance() or QApplication([])
    if os.name == "nt":
        for filename in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf", "SegoeIcons.ttf", "segmdl2.ttf", "cambria.ttc", "consola.ttf"):
            QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / filename))
        app.setFont(QFont("Segoe UI", 9))
    yield app


@pytest.fixture(autouse=True)
def isolate_runtime(tmp_path, monkeypatch, audit_app):
    from PySide6.QtCore import QCoreApplication, QEvent, Qt
    from poppy.core.media_manager import MediaManager
    from poppy.core.weather_manager import WeatherManager
    from poppy.core.screenshot_watcher import ScreenshotWatcher
    from poppy.core.system_features import BluetoothManager
    from poppy.core.window import DynamicNotchWindow
    from poppy.ui import extended_views

    autostart_enabled = False

    def set_autostart(enable):
        nonlocal autostart_enabled
        autostart_enabled = enable
        return True

    monkeypatch.setenv("POPPY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr("poppy.ui.settings_window.get_autostart_state", lambda: autostart_enabled)
    monkeypatch.setattr("poppy.ui.settings_window.set_autostart_state", set_autostart)
    monkeypatch.setattr(MediaManager, "start", lambda self: None)
    monkeypatch.setattr(MediaManager, "_dispatch_command", lambda *args: None)
    monkeypatch.setattr(WeatherManager, "start", lambda self: None)
    monkeypatch.setattr(WeatherManager, "refresh", lambda self: None)
    monkeypatch.setattr(ScreenshotWatcher, "start", lambda self: None)
    monkeypatch.setattr(BluetoothManager, "_get_devices", staticmethod(lambda: []))
    monkeypatch.setattr(extended_views, "current_desktop_windows", lambda: [])
    monkeypatch.setattr(DynamicNotchWindow, "_sync_system_controls", lambda *args, **kwargs: None)
    monkeypatch.setattr("poppy.core.window.system_animations_enabled", lambda: True)
    monkeypatch.setattr("poppy.ui.components.system_animations_enabled", lambda: True)
    baseline = set(audit_app.topLevelWidgets())
    yield
    # Qt controls can own top-level popups that disappear with their windows.
    for is_popup in (False, True):
        for widget in set(audit_app.topLevelWidgets()) - baseline:
            if (widget.windowType() == Qt.WindowType.Popup) == is_popup:
                widget.close()
                widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    from poppy.ui.theme import configure_theme, refresh_theme
    configure_theme({"mode": "Dark"})
    refresh_theme()
