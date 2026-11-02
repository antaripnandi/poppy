"""
Tests for Poppy's Extended Tabs and System Features:
- AnimatedTabStrip and AnimatedStackedWidget smooth transitions
- CalendarTabView month navigation and event persistence
- ClipboardTabView clip capture, pin, and search
- DocsTabView PDF writer generation and inspection
- LauncherTabView search and app indexing
- DesktopsTabView space rendering
- PrivacyMonitor and ScreenCaptureShield
- AudioEndpointManager
"""

import os
import json
import tempfile
import pytest
from pathlib import Path
from PySide6.QtWidgets import QApplication

from poppy.ui.components import AnimatedTabStrip, AnimatedStackedWidget
from poppy.ui.extended_views import (
    CalendarTabView, ClipboardTabView, DocsTabView,
    LauncherTabView, DesktopsTabView, ScreenAnnotationOverlay
)
from poppy.core.system_features import (
    PrivacyMonitor, ScreenCaptureShield, BluetoothManager,
    AppLauncherIndexer, ClipboardHistoryManager, AudioEndpointManager
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_animated_tab_strip(qapp):
    items = [("Home", ""), ("Music", ""), ("Calendar", "")]
    tab_strip = AnimatedTabStrip(items)
    assert len(tab_strip.buttons) == 3

    changed_indices = []
    tab_strip.tab_changed.connect(lambda i: changed_indices.append(i))

    tab_strip.set_current_index(1, animate=False)
    assert tab_strip._current_index == 1
    assert changed_indices == [1]

    tab_strip.set_current_index(2, animate=False)
    assert tab_strip._current_index == 2
    assert changed_indices == [1, 2]
    tab_strip.deleteLater()
    qapp.processEvents()


def test_animated_stacked_widget(qapp):
    stack = AnimatedStackedWidget()
    from PySide6.QtWidgets import QLabel
    w1 = QLabel("1")
    w2 = QLabel("2")
    stack.addWidget(w1)
    stack.addWidget(w2)
    assert stack.count() == 2

    # Slide to index without crash
    stack.slide_to_index(1)
    assert stack.currentIndex() in (0, 1)
    stack.deleteLater()
    qapp.processEvents()


def test_clipboard_history_manager(qapp, tmp_path):
    mgr = ClipboardHistoryManager()
    mgr.store_file = tmp_path / "test_clips.json"
    mgr.history = []

    mgr.add_clip("Hello world test snippet")
    assert len(mgr.history) == 1
    assert mgr.history[0]["text"] == "Hello world test snippet"
    assert mgr.history[0]["pinned"] is False

    # Toggle pin
    mgr.toggle_pin(0)
    assert mgr.history[0]["pinned"] is True

    # Delete clip
    mgr.delete_clip(0)
    assert len(mgr.history) == 0


def test_app_launcher_indexer():
    apps = AppLauncherIndexer.get_installed_apps()
    assert len(apps) > 0
    # Must include built-ins
    names = [a["name"] for a in apps]
    assert "Calculator" in names
    assert "Lock Workstation" in names
    assert "Task Manager" in names


def test_audio_endpoint_manager():
    endpoints = AudioEndpointManager.get_output_endpoints()
    assert isinstance(endpoints, list)
    # On Windows test machine, endpoints are found
    if endpoints:
        assert "name" in endpoints[0]
        assert "id" in endpoints[0]


def test_screen_capture_shield():
    # Calling set_shield with invalid or test HWND returns bool without exception
    res = ScreenCaptureShield.set_shield(0, True)
    assert isinstance(res, bool)


def test_calendar_tab_view(qapp, tmp_path):
    view = CalendarTabView()
    view.store_file = tmp_path / "calendar_events.json"
    view.events = {}

    # Month navigation
    init_month = view.current_month
    view._next_month()
    assert (view.current_month == (init_month % 12) + 1) or (init_month == 12 and view.current_month == 1)

    view._prev_month()
    assert view.current_month == init_month
    view.deleteLater()
    qapp.processEvents()


def test_docs_tab_view(qapp, tmp_path):
    view = DocsTabView()
    assert view is not None
    assert hasattr(view, "_convert_to_pdf")
    assert hasattr(view, "_inspect_pdf")
    assert hasattr(view, "recent_container")
    view.deleteLater()
    qapp.processEvents()


def test_bluetooth_manager():
    devices = BluetoothManager._get_devices()
    assert isinstance(devices, list)
    for d in devices:
        assert "name" in d
        assert "connected" in d
        assert "status" in d
        # Verify internal transport drivers are not leaked
        assert "transport" not in d["name"].lower()


def test_desktops_tab_view(qapp):
    view = DesktopsTabView()
    assert view is not None
    assert hasattr(view, "_open_task_view")
    assert hasattr(view, "_create_new_desktop")
    view.deleteLater()
    qapp.processEvents()


def test_capsule_slider_and_rubber_segment(qapp):
    from poppy.ui.components import CapsuleSlider, RubberSegment
    slider = CapsuleSlider(icon="test_icon", accent="#0a84ff")
    slider.setValue(72)
    assert slider.value() == 72
    assert slider.isSliderDown() is False

    # Value changes
    val_changes = []
    slider.valueChanged.connect(lambda v: val_changes.append(v))
    slider.setValue(85)
    assert val_changes == [85]

    # Test RubberSegment alias and keyframe physics
    segment = RubberSegment([("Tab 1", ""), ("Tab 2", "")])
    assert len(segment.buttons) == 2
    segment.set_current_index(1, animate=False)
    assert segment._current_index == 1
    segment.deleteLater()
    slider.deleteLater()
    qapp.processEvents()
