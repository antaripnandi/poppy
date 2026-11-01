"""
Poppy Pomodoro Engine
Manages focus sessions, breaks, cycles, and completion chimes.
"""

import time
import winsound
from enum import Enum
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

    def __init__(self, work_duration=1500, break_duration=300, long_break_duration=900, cycles_before_long=4, parent=None):
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

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    def start(self):
        """Start or resume the timer."""
        if self.state == PomoState.STOPPED:
            self.state = PomoState.WORKING
            self.remaining_seconds = self.work_duration
            self.total_seconds = self.work_duration
            self.state_changed.emit(self.state.value, "Focus Sprint")

        self.is_running = True
        self._timer.start()
        self._emit_update()

    def pause(self):
        """Pause the timer."""
        self.is_running = False
        self._timer.stop()
        self.state_changed.emit(self.state.value, f"Paused ({self._get_label()})")

    def resume(self):
        """Resume the paused timer."""
        if self.state != PomoState.STOPPED:
            self.is_running = True
            self._timer.start()
            self.state_changed.emit(self.state.value, self._get_label())

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
        self.state = PomoState.WORKING
        self.total_seconds = self.work_duration
        self.remaining_seconds = self.work_duration
        self.state_changed.emit(self.state.value, "Focus Sprint")
        self._emit_update()

    def set_phase_break(self, is_long=False):
        """Manually switch to Break session."""
        self.state = PomoState.LONG_BREAK if is_long else PomoState.SHORT_BREAK
        self.total_seconds = self.long_break_duration if is_long else self.break_duration
        self.remaining_seconds = self.total_seconds
        self.state_changed.emit(self.state.value, "Taking a Break" if not is_long else "Long Break")
        self._emit_update()

    def reset(self):
        """Reset back to stopped focus state."""
        self.is_running = False
        self._timer.stop()
        self.state = PomoState.STOPPED
        self.remaining_seconds = self.work_duration
        self.total_seconds = self.work_duration
        self.state_changed.emit(self.state.value, "Ready to Focus")
        self._emit_update()

    def skip(self):
        """Skip to next phase."""
        self._transition_next_phase()

    def _tick(self):
        if self.remaining_seconds > 0:
            self.remaining_seconds -= 1
            self._emit_update()

        if self.remaining_seconds <= 0:
            self._play_chime()
            self._transition_next_phase()

    def _transition_next_phase(self):
        old_state = self.state.value
        if self.state == PomoState.WORKING:
            self.completed_cycles += 1
            self.cycle_completed.emit(self.completed_cycles, old_state)

            if self.completed_cycles % self.cycles_before_long == 0:
                self.state = PomoState.LONG_BREAK
                self.total_seconds = self.long_break_duration
            else:
                self.state = PomoState.SHORT_BREAK
                self.total_seconds = self.break_duration
        else:
            # Completed break, back to work
            self.cycle_completed.emit(self.completed_cycles, old_state)
            self.state = PomoState.WORKING
            self.total_seconds = self.work_duration

        self.remaining_seconds = self.total_seconds
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
        mins = self.remaining_seconds // 60
        secs = self.remaining_seconds % 60
        formatted = f"{mins:02d}:{secs:02d}"
        progress = 1.0 - (self.remaining_seconds / max(1, self.total_seconds))
        self.time_updated.emit(self.remaining_seconds, self.total_seconds, formatted, progress)

    def _play_chime(self):
        """Soft harmonic chime on Windows without third-party audio libs."""
        try:
            import os
            from pathlib import Path
            sound_path = Path(__file__).resolve().parent.parent / "assets" / "sounds" / "chime.wav"
            if sound_path.exists():
                winsound.PlaySound(str(sound_path), winsound.SND_ASYNC | winsound.SND_FILENAME)
                return
            # Ascending 2-tone pleasant alert fallback
            winsound.Beep(587, 180)  # D5
            winsound.Beep(880, 260)  # A5
        except Exception:
            try:
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass

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
