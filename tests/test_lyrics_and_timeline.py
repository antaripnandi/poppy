"""
Tests for Synchronized Lyrics, Timeline Scrubber, and Auto-Dismiss features.
"""

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from poppy.core.lyrics_manager import parse_lrc, LyricsManager
from poppy.ui.components import ClickableSlider, SpotifyLyricsWidget
from poppy.ui.views import MusicTabView


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if not app:
        app = QApplication([])
    return app


def test_parse_lrc_basic():
    sample_lrc = """
[00:12.50]Line 1
[00:15.00]Line 2
[01:02.30]Line 3
"""
    parsed = parse_lrc(sample_lrc)
    assert len(parsed) == 3
    assert parsed[0] == (12.5, "Line 1")
    assert parsed[1] == (15.0, "Line 2")
    assert parsed[2] == (62.3, "Line 3")


def test_parse_lrc_unsorted_and_empty():
    sample_lrc = """
[01:00.00]Second line
[00:30.00]First line
[invalid]Not a line
[00:00.00]
"""
    parsed = parse_lrc(sample_lrc)
    assert len(parsed) == 2
    assert parsed[0] == (30.0, "First line")
    assert parsed[1] == (60.0, "Second line")


def test_lyrics_query_lrclib_mind_over_matter():
    mgr = LyricsManager()
    data = mgr._query_lrclib("Mind Over Matter (Reprise)", "Young the Giant", "Mirrorball / Mind Over Matter (Reprise)")
    assert data is not None
    assert bool(data.get("syncedLyrics")) is True
    synced = parse_lrc(data.get("syncedLyrics"))
    assert len(synced) > 10
    assert any("matter" in text.lower() for _, text in synced)



def test_music_tab_format_time(qapp):
    tab = MusicTabView()
    assert tab._format_time(0.0) == "00:00"
    assert tab._format_time(65.0) == "01:05"
    assert tab._format_time(3600.0) == "60:00"


def test_spotify_lyrics_widget_sync_and_progress(qapp):
    widget = SpotifyLyricsWidget()
    widget.show()
    synced = [
        (5.0, "Intro"),
        (10.0, "Verse 1"),
        (20.0, "Chorus")
    ]
    widget.set_synced_lyrics(synced)
    assert len(widget._line_buttons) == 3
    assert widget.content_stack.currentIndex() == 0

    # Time before any lyrics
    widget.update_playback_time(2.0)
    assert widget._current_line_idx == -1

    # Time at Intro
    widget.update_playback_time(5.5)
    assert widget._current_line_idx == 0
    assert widget._line_buttons[0]._is_active
    assert not widget._line_buttons[1]._is_active

    # Time at Chorus
    widget.update_playback_time(22.0)
    assert widget._current_line_idx == 2
    assert widget._line_buttons[2]._is_active
    assert not widget._line_buttons[0]._is_active


def test_clickable_slider_jump(qapp):
    slider = ClickableSlider(Qt.Orientation.Horizontal)
    slider.setRange(0, 100)
    slider.setValue(10)
    assert slider.value() == 10


def test_audio_peak_meter_telemetry():
    from poppy.core.system_controls import AudioPeakMeter
    meter = AudioPeakMeter.get_instance()
    peaks = meter.get_peaks()
    assert isinstance(peaks, tuple)
    assert len(peaks) == 3
    master, left, right = peaks
    assert 0.0 <= master <= 1.0
    assert 0.0 <= left <= 1.0
    assert 0.0 <= right <= 1.0


def test_audio_visualizer_bars_fluid_physics(qapp):
    from poppy.ui.components import AudioVisualizerBars
    viz = AudioVisualizerBars()
    viz.show()
    assert len(viz._heights) == 4
    for h in viz._heights:
        assert h == 2.5

    # Start playing
    viz.set_playing(True)
    assert viz._is_playing is True
    assert viz._timer.isActive()

    # Step simulation
    viz._animate_bars()
    for h in viz._heights:
        assert 2.5 <= h <= 14.0

    # Stop playing -> should trigger decay
    viz.set_playing(False)
    assert viz._is_playing is False
    # Simulate a decay tick
    viz._animate_bars()
    for h in viz._heights:
        assert 2.5 <= h <= 14.0


def test_netease_romanized_synced_lyrics():
    mgr = LyricsManager()
    data = mgr._query_netease("Dilliwaali Girlfriend", "Pritam")
    assert data is not None
    assert bool(data.get("syncedLyrics")) is True
    synced = parse_lrc(data.get("syncedLyrics"))
    assert len(synced) > 10
    # Must have Romanized lyrics matching Spotify, NOT Gurmukhi script
    assert any("girlfriend" in text.lower() or "dilliwali" in text.lower() for _, text in synced)


