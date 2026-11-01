# Poppy - Dynamic Notch & Productivity Island (Windows 11 / 10)

Poppy is a modern, high-performance **Top-Bezel Productivity Notch** built with Python and Qt 6 (`PySide6`), faithfully inspired by **NotchX** (by Navneet Kaur / Raho Osman) and macOS Dynamic Island.

It provides a smooth, anti-aliased floating island anchored to the top of the display with spring animations, deep Windows OS media integrations (GSMTC), a dedicated tabbed productivity suite (`Home`, `Music`, `Timer`, `Shelf`, `Notes`), and its own dedicated Settings App ("Make it yours").

---

## Key Features

### 1. Dynamic Notch Physics & States
- **Top-Center Docking:** Anchored at `y = 0` (or floating island `y = 8` in Pill mode) and dynamically centered.
- **Borderless & Floating:** Frameless, always-on-top, and hidden from Alt+Tab and taskbar.
- **Three Fluid States:**
  - **Collapsed (Pill):** Sleek top-bezel pill displaying active media visualizer bars, tabular digital clock, and Pomodoro progress badge.
  - **Peek (Hover HUD):** Smoothly blooms on hover to show Spotify / YouTube live track metadata, album art, and interactive Previous / Play / Pause / Next media controls. Protected by a 400ms leave grace timer to prevent accidental collapses.
  - **Expanded Drawer (Click):** Full productivity center featuring the NotchX tab bar (`Home`, `Music`, `Timer`, `Shelf`, `Notes`), tabular clock + battery capsule, and dedicated Settings button.
- **Click-Through Transparency:** Uses dynamic anti-aliased region masking (`setMask`), ensuring transparent bounding regions never intercept background desktop clicks.

### 2. NotchX Tabbed Suite
- **Home Tab:** Unified dashboard featuring responsive glass cards:
  - **Clock & Telemetry Card:** Big tabular clock, full formatted date, and live telemetry (`CPU %`, `GPU %` via NVIDIA NVML, `RAM %`, `BAT %`).
  - **Now Playing Quick Card:** Album art thumbnail, song title, artist, audio visualizer, prev/play/next controls, and volume slider.
  - **Quick Note Card:** Instant memo scratchpad with a `+ Tear Off` button that spawns an independent floating desktop sticky note.
  - **Quick Shelf & Calculator Card:** Drop staging status, clear shelf button, and real-time inline math evaluator (e.g. `45 * 12`, `120 / 3`).
- **Music Tab:** Dedicated full Now Playing view inspired by NotchX:
  - Large Album Art (140x140) with rounded corners and subtle shadow/glow.
  - Track title, artist, source badge (`Spotify`, `YouTube Music`, `Chrome`, etc.).
  - Progress scrubber bar with elapsed and remaining timestamps.
  - Transport controls: Shuffle, Previous, Large Play/Pause (in theme accent), Next, Repeat.
  - Volume slider with mute button.
- **Timer Tab:** Dedicated Pomodoro & Focus session deck:
  - Phase selector pills: `Focus (25m)`, `Short Break (5m)`, `Long Break (15m)`.
  - Anti-aliased circular progress ring (130px) with tabular countdown timer.
  - Reset, Start/Pause, Skip session buttons.
  - Focus streak counter and daily focus accumulation stats.
- **Shelf Tab:** Temporary file holding tray ("Dropover / Yoink" style):
  - File drop zone for staging files while switching folders or applications.
  - Staged files list with file icons, filenames, and drag-and-drop out support.
  - Clear shelf action.
- **Notes Tab:** Clean multiline scratchpad with live word/character counter and tear-off sticky note spawning.

### 3. Dedicated Settings Application ("Make it yours")
Accessible via the `⚙` icon in the notch header or the system tray menu:
- **7 NotchX Theme Presets:**
  - `Graphite` (`#141418` / `#202028`, Accent: `#0A84FF`)
  - `Midnight` (`#0A0E1C` / `#182040`, Accent: `#6E9BFF`)
  - `Aurora` (`#0C1717` / `#241534`, Accent: `#3DDC97`)
  - `Ember` (`#181110` / `#2B1610`, Accent: `#FF9F0A`)
  - `Lime` (`#111211` / `#1B1F12`, Accent: `#B4E61E`)
  - `Rose` (`#161012` / `#2A1420`, Accent: `#FF6B9A`)
  - `Pure black` (`#000000` / `#000000`, Accent: `#0A84FF`)
- **Live Size & Shape Customizer:**
  - Style switch: `Notch` (flush with top screen edge) vs `Pill` (floating island).
  - Collapsed Width & Height sliders (updates the notch live!).
  - Open Width & Height sliders.
  - Corner radius slider (8px – 24px).
- **Behavior:** Auto-hover peek toggle, animation spring duration (ms), system tray behavior.
- **Pomodoro:** Customizable work, short break, and long break intervals + chime sound toggle.
- **Discord RPC:** Toggle presence broadcasting, custom client ID, dynamic vs static presence mode.
- **Hardware HUD:** Toggles for dedicated NVIDIA GPU utilization and battery status.

### 4. Keyboard Shortcuts
- `Ctrl + 1`: Jump to **Home** tab
- `Ctrl + 2`: Jump to **Music** tab
- `Ctrl + 3`: Jump to **Timer** tab
- `Ctrl + 4`: Jump to **Shelf** tab
- `Ctrl + 5`: Jump to **Notes** tab
- `Escape`: Smoothly collapse the expanded drawer back to the pill

---

## Installation & Running

1. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
2. **Launch Poppy:**
   ```bash
   python main.py
   ```
   Or double-click `run.bat`.

---

## Standalone Executable Packaging

To build a standalone `.exe` without a console window:
```bash
pip install pyinstaller
pyinstaller --noconsole --name "Poppy" --onefile main.py
```
