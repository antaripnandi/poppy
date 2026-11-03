"""
Poppy Pomodoro Engine
Manages focus sessions, breaks, cycles, and completion chimes.
"""

import time
import winsound
import threading
import math
from enum import Enum
from pathlib import Path
from PySide6.QtCore import QObject, QTimer, Signal


class PomoState(Enum):
    STOPPED = "stopped"
    WORKING = "focus"
    SHORT_BREAK = "short_break"
    LONG_BREAK = "long_break"


class PomodoroManager(QObject):
    time_updated = Signal(int, int, str, float)  # remaining_sec, total_sec, "MM:SS", ratio 0.0-1.0
    state_changed = Signal(str, str)             # state_value, display_label
    cycle_completed = Signal(int, str)           # completed_cycles, just_finished_state

    def __init__(self, work_duration=1500, break_duration=300, long_break_duration=900, cycles_before_long=4, parent=None, clock=None):
        super().__init__(parent)
        self.work_duration = work_duration
        self.break_duration = break_duration
        self.long_break_duration = long_break_duration
        self.cycles_before_long = cycles_before_long

        self.state = PomoState.STOPPED
        self.remaining_seconds = self.work_duration
        self.total_seconds = self.work_duration
        self.completed_cycles = 0
        self.is_running = False
        self.sound_enabled = True
        self._clock = clock or time.monotonic
        self._deadline = None
        self._paused_remaining = None
        self.completed_focus_seconds = 0

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    def start(self):
        """Start or resume the timer."""
        if self.is_running:
            return
        if self.state == PomoState.STOPPED:
            self.state = PomoState.WORKING
            self.remaining_seconds = self.work_duration
            self.total_seconds = self.work_duration
        self.is_running = True
        remaining = self._paused_remaining if self._paused_remaining is not None else self.remaining_seconds
        self._deadline = self._clock() + remaining
        self._paused_remaining = None
        self._timer.start()
        self.state_changed.emit(self.state.value, self._get_label())
        self._emit_update()

    def pause(self):
        """Pause the timer."""
        if not self.is_running:
            return
        self._tick()
        self._paused_remaining = max(0.0, self._deadline - self._clock())
        self.is_running = False
        self._deadline = None
        self._timer.stop()
        self.state_changed.emit(self.state.value, f"Paused ({self._get_label()})")
        self._emit_update()

    def resume(self):
        """Resume the paused timer."""
        if self.state != PomoState.STOPPED:
            self.start()

    def toggle(self):
        """Toggle play/pause."""
        if self.is_running:
            self.pause()
        else:
            if self.state == PomoState.STOPPED:
                self.start()
            else:
                self.resume()

    def set_phase_focus(self):
        """Manually switch to Focus session."""
        self._paused_remaining = None
        self.state = PomoState.WORKING
        self.total_seconds = self.work_duration
        self.remaining_seconds = self.work_duration
        self._deadline = self._clock() + self.remaining_seconds if self.is_running else None
        self.state_changed.emit(self.state.value, "Focus Sprint")
        self._emit_update()

    def set_phase_break(self, is_long=False):
        """Manually switch to Break session."""
        self._paused_remaining = None
        self.state = PomoState.LONG_BREAK if is_long else PomoState.SHORT_BREAK
        self.total_seconds = self.long_break_duration if is_long else self.break_duration
        self.remaining_seconds = self.total_seconds
        self._deadline = self._clock() + self.remaining_seconds if self.is_running else None
        self.state_changed.emit(self.state.value, "Taking a Break" if not is_long else "Long Break")
        self._emit_update()

    def reset(self):
        """Reset back to stopped focus state."""
        self._paused_remaining = None
        self.is_running = False
        self._deadline = None
        self._timer.stop()
        self.state = PomoState.STOPPED
        self.remaining_seconds = self.work_duration
        self.total_seconds = self.work_duration
        self.state_changed.emit(self.state.value, "Ready to Focus")
        self._emit_update()

    def skip(self):
        """Skip to next phase."""
        if self.state != PomoState.STOPPED:
            self._transition_next_phase(completed=False)

    def _tick(self):
        if not self.is_running or self._deadline is None:
            return
        self.remaining_seconds = max(0, math.ceil(self._deadline - self._clock()))
        self._emit_update()

        if self.remaining_seconds <= 0:
            self._play_chime()
            self._transition_next_phase()

    def _transition_next_phase(self, completed=True):
        self._paused_remaining = None
        old_state = self.state.value
        if self.state == PomoState.WORKING:
            if completed:
                self.completed_cycles += 1
                self.completed_focus_seconds += self.total_seconds
                self.cycle_completed.emit(self.completed_cycles, old_state)

            if completed and self.completed_cycles % self.cycles_before_long == 0:
                self.state = PomoState.LONG_BREAK
                self.total_seconds = self.long_break_duration
            else:
                self.state = PomoState.SHORT_BREAK
                self.total_seconds = self.break_duration
        else:
            # Completed break, back to work
            if completed:
                self.cycle_completed.emit(self.completed_cycles, old_state)
            self.state = PomoState.WORKING
            self.total_seconds = self.work_duration

        self.remaining_seconds = self.total_seconds
        self._deadline = self._clock() + self.remaining_seconds if self.is_running else None
        self.state_changed.emit(self.state.value, self._get_label())
        self._emit_update()

    def _get_label(self) -> str:
        if self.state == PomoState.WORKING:
            return f"Focus Sprint #{self.completed_cycles + 1}"
        elif self.state == PomoState.SHORT_BREAK:
            return "Short Break"
        elif self.state == PomoState.LONG_BREAK:
            return "Long Break"
        return "Pomodoro Idle"

    def _emit_update(self):
        mins = max(0, self.remaining_seconds) // 60
        secs = max(0, self.remaining_seconds) % 60
        formatted = f"{mins:02d}:{secs:02d}"
        progress = 1.0 - (max(0, self.remaining_seconds) / max(1, self.total_seconds))
        self.time_updated.emit(self.remaining_seconds, self.total_seconds, formatted, progress)

    def _play_chime(self):
        """Soft harmonic chime on Windows without blocking Qt event loop."""
        if not self.sound_enabled:
            return

        def _sound_worker():
            try:
                sound_path = Path(__file__).resolve().parent.parent / "assets" / "sounds" / "chime.wav"
                if sound_path.exists():
                    winsound.PlaySound(str(sound_path), winsound.SND_ASYNC | winsound.SND_FILENAME)
                    return
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass

        threading.Thread(target=_sound_worker, daemon=True).start()

    def get_discord_status(self):
        """Returns details suitable for Discord RPC."""
        if not self.is_running or self.state == PomoState.STOPPED:
            return None
        now = int(time.time())
        end_time = now + self.remaining_seconds
        return {
            "state": self._get_label(),
            "details": f"Cycle {self.completed_cycles + 1} | Productivity Notch",
            "end": end_time
        }
