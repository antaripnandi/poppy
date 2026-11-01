"""
Poppy Discord Rich Presence Integration
Fully customizable Discord Rich Presence via pypresence.
Supports custom images, tooltips, buttons, states, details, and dynamic variables.
Throttled to Discord's 15s rate-limit via a dedicated worker thread.
"""

import time
import threading
from PySide6.QtCore import QObject, Signal


class DiscordRPCManager(QObject):
    connection_status = Signal(bool)

    def __init__(self, config: dict = None, parent=None):
        super().__init__(parent)
        self.config = config or {}
        self.client_id = self.config.get("client_id", "120000000000000000")
        self.enabled = self.config.get("enabled", False)
        self.mode = self.config.get("mode", "dynamic")  # "dynamic" or "custom"
        self.custom_cfg = self.config.get("custom_presence", {})
        self.templates = self.config.get("dynamic_templates", {})

        self._rpc = None
        self._connected = False
        self._running = True
        self._lock = threading.Lock()
        self._pending_payload = None
        self._wake_event = threading.Event()
        self._last_update_time = 0.0

        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

    def start(self):
        """Asynchronously connect to Discord in background thread."""
        if not self.enabled:
            return
        threading.Thread(target=self._try_connect, daemon=True).start()

    def update_config(self, new_config: dict):
        """Live update configuration without restarting application."""
        old_client_id = self.client_id
        old_enabled = self.enabled

        self.config = new_config
        self.client_id = self.config.get("client_id", self.client_id)
        self.enabled = self.config.get("enabled", self.enabled)
        self.mode = self.config.get("mode", self.mode)
        self.custom_cfg = self.config.get("custom_presence", self.custom_cfg)
        self.templates = self.config.get("dynamic_templates", self.templates)

        if not self.enabled:
            self.clear()
            self.close()
        elif not old_enabled or (old_client_id != self.client_id and self.enabled):
            self.close()
            self.start()
        elif self.mode == "custom":
            self.apply_custom_presence()

    def _try_connect(self):
        try:
            from pypresence import Presence
            with self._lock:
                self._rpc = Presence(self.client_id)
                self._rpc.connect()
                self._connected = True
            self.connection_status.emit(True)

            if self.mode == "custom":
                self.apply_custom_presence()
        except Exception:
            with self._lock:
                self._connected = False
                self._rpc = None
            self.connection_status.emit(False)

    def _worker_loop(self):
        while self._running:
            self._wake_event.wait(timeout=1.0)
            self._wake_event.clear()
            if not self._running:
                break

            with self._lock:
                payload = self._pending_payload
                self._pending_payload = None
                connected = self._connected
                rpc = self._rpc

            if not payload or not connected or not rpc:
                continue

            # Respect Discord 15-second client IPC rate limit
            now = time.monotonic()
            elapsed = now - self._last_update_time
            if elapsed < 15.0:
                time.sleep(15.0 - elapsed)

            with self._lock:
                if not self._connected or not self._rpc:
                    continue
                try:
                    self._rpc.update(**payload)
                    self._last_update_time = time.monotonic()
                except Exception as e:
                    print(f"[Poppy Discord] Presence update error: {e}")
                    self._connected = False

    def set_presence(
        self,
        details: str = None,
        state: str = None,
        large_image: str = None,
        large_text: str = None,
        small_image: str = None,
        small_text: str = None,
        buttons: list = None,
        start: int = None,
        end: int = None
    ):
        """Directly queue a custom presence update with 15s rate-limiting."""
        if not self._connected or not self.enabled:
            return

        payload = {}
        if details:
            payload["details"] = details[:128]
        if state:
            payload["state"] = state[:128]
        if large_image:
            payload["large_image"] = large_image
        if large_text:
            payload["large_text"] = large_text[:128]
        if small_image:
            payload["small_image"] = small_image
        if small_text:
            payload["small_text"] = small_text[:128]
        if start:
            payload["start"] = int(start)
        if end:
            payload["end"] = int(end)

        if buttons and isinstance(buttons, list):
            valid_buttons = []
            for b in buttons[:2]:
                lbl = b.get("label", "")[:32]
                url = b.get("url", "")
                if lbl and url.startswith(("http://", "https://")):
                    valid_buttons.append({"label": lbl, "url": url})
            if valid_buttons:
                payload["buttons"] = valid_buttons

        with self._lock:
            self._pending_payload = payload
        self._wake_event.set()

    def apply_custom_presence(self):
        """Apply current custom presence configuration."""
        cfg = self.custom_cfg
        self.set_presence(
            details=cfg.get("details", "Focusing with Poppy"),
            state=cfg.get("state", "Deep Work"),
            large_image=cfg.get("large_image", "poppy_logo"),
            large_text=cfg.get("large_text", "Poppy Notch"),
            small_image=cfg.get("small_image"),
            small_text=cfg.get("small_text"),
            buttons=cfg.get("buttons")
        )

    def update_pomodoro(self, state_name: str, cycle: int, remaining_fmt: str, end_timestamp: int = None, task: str = "Focus Sprint"):
        """Update Discord status with customizable Pomodoro template."""
        if not self._connected or not self.enabled or self.mode == "custom":
            return

        template_key = "pomo_focus" if state_name == "focus" else "pomo_break"
        tpl = self.templates.get(template_key, {})

        vars_dict = {
            "cycle": str(cycle),
            "task": task,
            "remaining": remaining_fmt,
            "state": state_name
        }

        details = self._format_template(tpl.get("details", f"Focus Sprint #{cycle}"), vars_dict)
        state = self._format_template(tpl.get("state", task), vars_dict)
        large_image = tpl.get("large_image", "focus_icon")
        large_text = self._format_template(tpl.get("large_text", "Focusing with Poppy"), vars_dict)
        small_image = tpl.get("small_image", "clock")
        small_text = self._format_template(tpl.get("small_text", f"{remaining_fmt} left"), vars_dict)
        buttons = self.custom_cfg.get("buttons")

        self.set_presence(
            details=details,
            state=state,
            large_image=large_image,
            large_text=large_text,
            small_image=small_image,
            small_text=small_text,
            buttons=buttons,
            end=end_timestamp
        )

    def update_media(self, title: str, artist: str, album: str, is_playing: bool):
        """Update Discord status with customizable Media template."""
        if not self._connected or not self.enabled or self.mode == "custom":
            return

        if not is_playing:
            return

        tpl = self.templates.get("media", {})
        vars_dict = {
            "title": title or "Unknown Track",
            "artist": artist or "Desktop Audio",
            "album": album or "Audio Stream"
        }

        details = self._format_template(tpl.get("details", "{title}"), vars_dict)
        state = self._format_template(tpl.get("state", "by {artist}"), vars_dict)
        large_image = tpl.get("large_image", "music_disc")
        large_text = self._format_template(tpl.get("large_text", "{album}"), vars_dict)
        small_image = tpl.get("small_image", "play_icon")
        small_text = self._format_template(tpl.get("small_text", "Playing"), vars_dict)
        buttons = self.custom_cfg.get("buttons")

        self.set_presence(
            details=details,
            state=state,
            large_image=large_image,
            large_text=large_text,
            small_image=small_image,
            small_text=small_text,
            buttons=buttons
        )

    def _format_template(self, text: str, vars_dict: dict) -> str:
        for k, v in vars_dict.items():
            text = text.replace(f"{{{k}}}", str(v))
        return text

    def clear(self):
        """Clear presence."""
        if not self._connected:
            return

        def _do_clear():
            with self._lock:
                if self._rpc:
                    try:
                        self._rpc.clear()
                    except Exception:
                        pass

        threading.Thread(target=_do_clear, daemon=True).start()

    def close(self):
        with self._lock:
            self._running = False
            self._wake_event.set()
            if self._rpc:
                try:
                    self._rpc.close()
                except Exception:
                    pass
                self._connected = False
