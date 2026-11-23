import pytest
from PySide6.QtWidgets import QApplication
from poppy.ui.control_flyouts import (
    WifiFlyoutMenu, BluetoothFlyoutMenu, AudioDeviceFlyoutMenu, NightLightFlyoutMenu
)
from poppy.ui.views import ControlsTabView, TodayTabView, ShelfTabView
from poppy.ui.extended_views import StatsTabView, LauncherTabView
from poppy.ui.components import WeekCalendarStrip, TodoChecklistWidget


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if not app:
        app = QApplication([])
    return app


def test_flyout_menus_initialization(qapp):
    wifi = WifiFlyoutMenu()
    assert wifi is not None
    assert hasattr(wifi, "refresh")
    assert hasattr(wifi, "network_selected")
    assert hasattr(wifi, "wifi_toggled")

    bt = BluetoothFlyoutMenu()
    assert bt is not None
    assert hasattr(bt, "refresh")
    assert hasattr(bt, "device_selected")

    audio = AudioDeviceFlyoutMenu()
    assert audio is not None
    assert hasattr(audio, "refresh")
    assert hasattr(audio, "device_changed")

    night = NightLightFlyoutMenu()
    assert night is not None
    assert hasattr(night, "night_light_toggled")
    night.set_status(True)
    assert night.toggle_night.isChecked() is True


def test_controls_tab_view_dual_sliders_and_no_hardcoding(qapp):
    controls = ControlsTabView()
    assert hasattr(controls, "slider_vol")
    assert hasattr(controls, "slider_bright")
    assert hasattr(controls, "volume_changed")
    assert hasattr(controls, "brightness_changed")
    assert hasattr(controls, "wifi_menu_requested")
    assert hasattr(controls, "bluetooth_menu_requested")
    assert hasattr(controls, "audio_device_menu_requested")
    assert hasattr(controls, "night_light_menu_requested")

    # Verify no hardcoded track / artist / wifi
    assert controls.lbl_title.text() == "Nothing playing"
    assert controls.lbl_artist.text() == "Play audio or video in any app"
    assert controls.tile_wifi._subtitle != "Home 5G"

    # Test slider setters
    controls.set_volume_display(75)
    assert controls.slider_vol.value() == 75
    assert controls.lbl_vol_pct.text() == "75%"

    controls.set_brightness_display(88)
    assert controls.slider_bright.value() == 88
    assert controls.lbl_bright_pct.text() == "88%"

    # Test status setters
    controls.set_wifi_status(True, "MyCustomWifi")
    assert controls.tile_wifi._subtitle == "MyCustomWifi"
    assert controls.tile_wifi.isChecked() is True

    controls.set_audio_device_name("Headphones (Realtek)")
    assert controls.tile_audio._subtitle == "Headphones (Realtek)"
    assert "< Headphones (Realtek)" in controls.btn_output_device.text()


def test_today_tab_view_dynamic_weather_and_empty_states(qapp):
    today = TodayTabView()
    assert today.lbl_hitodama_temp.text() == "--°C"
    assert today.lbl_hitodama_cond.text() == "Updating..."

    today.update_weather({"temp": 24, "condition": "Partly Cloudy", "unit": "°C"})
    assert today.lbl_hitodama_temp.text() == "24°C"
    assert today.lbl_hitodama_cond.text() == "Partly Cloudy"


def test_components_empty_states_no_fake_items(qapp):
    strip = WeekCalendarStrip()
    assert strip._next_event_title != "Daily AI news research"

    todos = TodoChecklistWidget()
    # Ensure "Buy Hitodama!" is not forced
    for item in todos._todos:
        assert item.get("text") != "Buy Hitodama!"


def test_stats_tab_view_dynamic_initialization(qapp):
    stats = StatsTabView()
    assert stats.lbl_disk_val.text() != "412 / 931 GB"
    assert "Mumbai" not in stats.lbl_s_last.text()
    assert stats.lbl_down.text().startswith("--")
    assert stats.lbl_up.text().startswith("--")


def test_shelf_tab_view_no_fake_folders(qapp):
    from poppy.core.drop_shelf import DropShelfManager
    shelf_mgr = DropShelfManager()
    shelf = ShelfTabView(shelf_mgr)
    assert "Footage" not in shelf._staged_folders
    assert "Client work" not in shelf._staged_folders
