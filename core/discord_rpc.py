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

        self._connected = False
        self._running = True
        self._lock = threading.Lock()
        self._connection = (0, None)
        self._pending_payload = None
        self._wake_event = threading.Event()

        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

    def start(self):
        """Apply the desired connection on the RPC worker."""
        with self._lock:
            if not self._running:
                return
            revision, _ = self._connection
            self._connection = (revision + 1, self.client_id if self.enabled else None)
            self._connected = False
            self._pending_payload = None
        self._wake_event.set()

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

        if old_enabled != self.enabled or (self.enabled and (old_client_id != self.client_id or not self._connected)):
            self.start()
        elif self.enabled and self.mode == "custom":
            self.apply_custom_presence()

    @staticmethod
    def _connect(client_id):
        from pypresence import Presence

        rpc = Presence(client_id)
        initial_loop = getattr(rpc, "loop", None)
        try:
            rpc.connect()
        except Exception:
            DiscordRPCManager._disconnect(rpc)
            raise
        finally:
            if initial_loop is not None and initial_loop is not rpc.loop:
                initial_loop.close()
        return rpc

    @staticmethod
    def _disconnect(rpc):
        if rpc is None:
            return
        try:
            rpc.close()
        except Exception:
            loop = getattr(rpc, "loop", None)
            if loop is not None and not loop.is_closed():
                loop.close()

    def _worker_loop(self):
        revision, rpc = 0, None
        delay, next_update = None, 0.0
        try:
            while True:
                self._wake_event.wait(delay)
                self._wake_event.clear()
                delay = None
                with self._lock:
                    if not self._running:
                        return
                    requested, client_id = self._connection
                if requested != revision:
                    revision = requested
                    self._disconnect(rpc)
                    rpc = None
                    next_update = 0.0
                    if client_id:
                        try:
                            rpc = self._connect(client_id)
                        except Exception:
                            pass
                    with self._lock:
                        if not self._running or revision != self._connection[0]:
                            continue
                        self._connected = rpc is not None
                    self.connection_status.emit(rpc is not None)
                    if rpc is not None and self.mode == "custom":
                        self.apply_custom_presence()
                    continue

                with self._lock:
                    payload = self._pending_payload
                    if rpc is None or payload is None or revision != self._connection[0]:
                        continue
                    if payload and (remaining := next_update - time.monotonic()) > 0:
                        delay = remaining
                        continue
                    self._pending_payload = None
                try:
                    if payload:
                        rpc.update(**payload)
                        next_update = time.monotonic() + 15.0
                    else:
                        rpc.clear()
                except Exception as error:
                    print(f"[Poppy Discord] Presence update error: {error}")
                    self._disconnect(rpc)
                    rpc = None
                    with self._lock:
                        self._connected = False
                    self.connection_status.emit(False)
        finally:
            self._disconnect(rpc)

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
            if not self._connected or not self.enabled:
                return
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
        with self._lock:
            if not self._connected:
                return
            self._pending_payload = {}
        self._wake_event.set()

    def close(self):
        with self._lock:
            self._running = False
            self._connected = False
            self._pending_payload = None
        self._wake_event.set()
