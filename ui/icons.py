"""
Poppy Minimalist Iconography System
Native Windows Segoe Fluent Icons and Segoe MDL2 Assets.
Zero third-party bloat, zero AI emojis, pure native OS minimalism.
"""

from PySide6.QtGui import QFontDatabase


def get_fluent_font_family() -> str:
    families = QFontDatabase.families()
    if "Segoe Fluent Icons" in families:
        return "Segoe Fluent Icons"
    if "Segoe MDL2 Assets" in families:
        return "Segoe MDL2 Assets"
    return "Segoe UI"


class Icons:
    # Media & Volume
    VOLUME = "\uE994"       # Full volume
    VOLUME_MED = "\uE993"   # Medium volume
    VOLUME_LOW = "\uE992"   # Low volume
    MUTE = "\uE74F"         # Mute / Volume 0
    BRIGHTNESS = "\uE706"   # Screen Brightness
    PLAY = "\uE768"         # Play
    PAUSE = "\uE769"        # Pause
    PREV = "\uE892"         # Previous Track
    NEXT = "\uE893"         # Next Track
    SHUFFLE = "\uE8B1"      # Shuffle
    REPEAT = "\uE8EE"       # Repeat
    SPEAKER = "\uE7F5"      # Speaker device
    MUSIC = "\uE8D6"        # Musical note

    # Navigation & Tabs
    HOME = "\uE80F"         # Home
    CALENDAR = "\uE787"     # Calendar
    CLIPBOARD = "\uE77F"    # Clipboard
    DOCS = "\uE8A5"         # Documents
    LAUNCHER = "\uE71D"     # All Apps / Launcher
    DESKTOPS = "\uE7C4"     # Task View / Desktops
    BLUETOOTH = "\uE702"    # Bluetooth
    PENCIL = "\uED63"       # Pen / Draw / Annotate
    REFRESH = "\uE72C"      # Refresh
    CAMERA = "\uE722"       # Camera

    # Actions & Chrome
    SETTINGS = "\uE713"     # Settings Gear
    CLOSE = "\uE711"        # Minimal × (ChromeClose)
    MAXIMIZE = "\uE922"     # Chrome Maximize
    RESTORE = "\uE923"      # Chrome Restore
    ZOOM_IN = "\uE71E"      # Zoom In
    ZOOM_OUT = "\uE71F"     # Zoom Out
    LOCK = "\uE72E"         # Lock
    UNLOCK = "\uE785"       # Unlock
    PIN = "\uE718"          # Pin to Screen
    UNPIN = "\uE77A"        # Unpin
    COPY = "\uE8C8"         # Clipboard Copy
    CHECK = "\uE73E"        # Checkmark
    CLEAR = "\uE74D"        # Trash / Clear
    SEARCH = "\uE721"       # Magnifier / Search
    TEAR_OFF = "\uE8A7"     # Detach / Open in Window
    CALCULATOR = "\uE8EF"   # Calculator
    NOTES = "\uE70B"        # Document / Notes
    SHELF = "\uED25"        # Folder / Stash
    TIMER = "\uE916"        # Stopwatch / Timer
    IMAGE = "\uEB9F"        # Photo / Screenshot

    # Quick Tools Strip
    POWER = "\uE7E8"        # Keep Awake / Caffeine
    MIC = "\uE720"          # Microphone
    MIC_MUTE = "\uEC54"     # Microphone Mute
    SHIELD = "\uEA18"       # Focus Shield
    SNIP = "\uE7C8"         # Screen Snip
    COLOR = "\uEF3C"        # Color Eyedropper

    # Weather
    WEATHER_MOON = "\uEC46" # Clear Night
    WEATHER_SUN = "\uE706"  # Sunny Day
    WEATHER_CLOUD = "\uE753"# Cloudy / Overcast
    WEATHER_RAIN = "\uE774" # Rain / Showers
    WEATHER_SNOW = "\uE775" # Snow
    WEATHER_STORM = "\uEA39"# Thunderstorm

