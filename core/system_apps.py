"""
Poppy System App Shortcuts
Native Windows hotkeys and launchers for Search, Game Bar, Discord, Settings,
Sticky Notes, Explorer, and Terminal.
"""

import os
import ctypes
import subprocess

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def open_search():
    """Trigger genuine Windows Search flyout via Win + S."""
    try:
        VK_LWIN = 0x5B
        VK_S = 0x53
        ctypes.windll.user32.keybd_event(VK_LWIN, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_S, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_S, 0, 2, 0)
        ctypes.windll.user32.keybd_event(VK_LWIN, 0, 2, 0)
    except Exception as e:
        print(f"[Poppy Apps] Search error: {e}")


def open_game_bar():
    """Trigger genuine Xbox Game Bar overlay via Win + G."""
    try:
        VK_LWIN = 0x5B
        VK_G = 0x47
        ctypes.windll.user32.keybd_event(VK_LWIN, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_G, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_G, 0, 2, 0)
        ctypes.windll.user32.keybd_event(VK_LWIN, 0, 2, 0)
    except Exception as e:
        print(f"[Poppy Apps] Game bar error: {e}")


def open_discord():
    """Launch the installed Discord application directly."""
    try:
        local_app = os.environ.get("LOCALAPPDATA", "")
        update_exe = os.path.join(local_app, "Discord", "Update.exe")
        if os.path.exists(update_exe):
            subprocess.Popen([update_exe, "--processStart", "Discord.exe"], creationflags=CREATE_NO_WINDOW)
            return
        os.startfile("discord:")
    except Exception:
        try:
            os.startfile("discord:")
        except Exception as e:
            print(f"[Poppy Apps] Discord error: {e}")


def open_settings():
    """Open Windows Settings."""
    try:
        os.startfile("ms-settings:")
    except Exception:
        try:
            subprocess.Popen(
                ["explorer.exe", "shell:appsfolder\\windows.immersivecontrolpanel_cw5n1h2txyewy!microsoft.windows.immersivecontrolpanel"],
                creationflags=CREATE_NO_WINDOW
            )
        except Exception as e:
            print(f"[Poppy Apps] Settings error: {e}")


def open_terminal():
    """Open Windows Terminal or PowerShell."""
    try:
        subprocess.Popen(["wt.exe"], creationflags=CREATE_NO_WINDOW)
    except Exception:
        try:
            subprocess.Popen(["powershell.exe"])
        except Exception as e:
            print(f"[Poppy Apps] Terminal error: {e}")


def open_explorer():
    """Open File Explorer."""
    try:
        subprocess.Popen(["explorer.exe"])
    except Exception as e:
        print(f"[Poppy Apps] Explorer error: {e}")
