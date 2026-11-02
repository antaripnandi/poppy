# Poppy AI Engineering Guide (`AGENTS.md`)
> High-density, context-compacted technical reference for AI agents and pair-programmers working on Poppy.

---

## 1. Project Overview & Philosophy
- **What Poppy Is:** A top-bezel Dynamic Notch and Productivity Island for Windows 11/10 built with Python 3.11 and Qt 6 (`PySide6`).
- **Design Metaphor:** Option 1: Apple Studio Bento + macOS Control Center + Obsidian frosted glass.
- **Senior Developer Decision Ladder (Ponytail Rules):**
  1. **YAGNI First:** Never add scaffolding, speculative abstractions, or unused features.
  2. **Zero Bloat / Zero AI Slop:** No garish border lines, no emojis in code, no bloated external dependencies. Pure stdlib + `PySide6` + `ctypes` Win32 API only.
  3. **High Craft & Quality:** Never break accessibility, typography metrics, error handling, or test suites.

---

## 2. Directory Architecture & Responsibilities

```
poppy/
├── main.py                     # Entry point, single-instance enforcement (.poppy.pid), tray icon & app lifecycle
├── config.json                 # Persistent JSON settings (themes, notch geometry, enabled tabs, screentime)
├── requirements.txt           # Minimal dependencies (PySide6, requests, winsdk)
├── core/
│   ├── window.py               # DynamicNotchWindow: Frameless top-docked window, 4-state machine, DWM masking, animations
│   ├── screentime_manager.py   # ScreenTimeManager: Active foreground app tracking, AFK idle detection, daily goals & streak
│   ├── lyrics_manager.py       # LyricsManager: LRCLIB API client, parse_lrc parser, fuzzy matching, synced timestamps
│   ├── system_controls.py      # AudioPeakMeter (Core Audio), volume/brightness wrappers, GSMTC media sessions
│   ├── system_tools.py         # CaffeineManager (SetThreadExecutionState), ScreenSnip, Eyedropper, Workstation Lock
│   ├── pomodoro_manager.py     # Pomodoro sprint timer state machine (work, short break, long break cycles)
│   ├── discord_rpc.py          # Minimalist Discord Rich Presence integration
│   └── weather_manager.py      # Lightweight asynchronous weather provider
├── ui/
│   ├── components.py           # Reusable UI primitives: AnimatedTabStrip (RubberSegment), CapsuleSlider,
│   │                           # SpotifyLyricsWidget, LyricLineWidget, CardFrame, AudioVisualizerBars, IconButton
│   ├── views.py                # Primary tab views: HomeTabView, MusicTabView (Bento 2-card studio), Calendar, Shelf, Notes
│   ├── extended_views.py       # Extended modular views: ClipboardTabView, DocsTabView, DesktopsTabView, TimerTabView
│   ├── settings_window.py      # Dedicated 11-page Settings Window (840x580) with frosted Bento cards and zero-artifact scroll
│   ├── styles.py               # Theme presets (Graphite, Midnight, Aurora, Ember, Lime, Rose, Pure black) & QSS engine
│   └── icons.py                # Fluent icon codepoints and Segoe Fluent font family helpers
└── tests/
    ├── test_lyrics_and_timeline.py         # LRC parsing, synced lyrics widget, slider scrubbing
    ├── test_screentime_and_animation.py    # Screen time tracking, streak calculation, center-pop geometry
    ├── test_extended_tabs.py               # Extended tabs instantiation, Bento layouts, CapsuleSlider APIs
    └── test_audit_fixes.py                 # Single-instance enforcement, theme tokens, styling integrity
```

---

## 3. Runtime Lifecycle & Process Management

### Single-Instance Enforcement
Multiple running Poppy processes cause invisible overlap, audio hook collisions, and stale UI rendering.
- `poppy/main.py` enforces a single instance via `.poppy.pid` using Win32 API:
  ```python
  handle = ctypes.windll.kernel32.OpenProcess(0x0001, False, old_pid)
  if handle:
      ctypes.windll.kernel32.TerminateProcess(handle, 0)
      ctypes.windll.kernel32.CloseHandle(handle)
  ```
- Always clean up `.poppy.pid` on application exit (`exit_app`).

### Development & Python Environment
- **Workspace Interpreter:** `C:\Users\banta\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe`
- **Run Poppy:** `python poppy/main.py`
- **Run Tests:** `python -m pytest poppy/tests/` (All 31 unit tests must always pass).

---

## 4. State Machine & Window Geometry

`DynamicNotchWindow` operates across 4 distinct states (`NotchState`):
1. `COLLAPSED` (`240x30`): Compact top-bezel pill with live audio visualizer bars, tabular clock, battery readout.
2. `PEEK` (`380x68`): Hover HUD showing now-playing track metadata and media transport controls.
3. `ISLAND` (`420x64`): Floating interactive notification or system prompt island.
4. `EXPANDED` (`960x480`): Full productivity drawer containing the Bento tabbed suite.

### Smooth Center-Pop Animation
When expanding or collapsing, the notch must animate symmetrically from the horizontal center:
```python
start_x = screen.x() + (screen.width() - current_w) // 2
target_x = screen.x() + (screen.width() - target_w) // 2
```
Never animate from left/right or introduce horizontal jitter.

### Settings Window Interaction
When the Settings button is pressed (`open_settings`):
- The notch drawer **immediately collapses** to `NotchState.COLLAPSED` so Settings (`840x580`) is completely unobscured.
- Settings opens cleanly centered on the active screen comfortably below the collapsed pill.

---

## 5. Critical Qt Pitfalls & Architectural Invariants

### 1. ScrollArea Baseline Slicing Bug (MANDATORY RULE)
- **Problem:** If a widget inside `QScrollArea(widgetResizable=True)` does not enforce layout constraints, `QScrollArea` squishes the container down to viewport height. In a song with 30+ lyrics, each line gets compressed to 7px–17px, slicing off the bottom half of letters horizontally!
- **Rule:** Every scroll container inside `QScrollArea` **MUST** set:
  ```python
  self.lines_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
  ```
- In addition, dynamic rows (`LyricLineWidget`) must call `setMinimumHeight(44)` (or `56` when active) and account for `fontMetrics().height() + 18px` padding in `sizeHint()`.

### 2. Qt CSS Has No `line-height`
- Qt Stylesheets do not implement the CSS `line-height` property. Setting `line-height` in QSS is silently ignored or corrupts font bounding boxes.
- Always configure typography using explicit `QFont` objects on `QLabel` (`QFont("Segoe UI", 18, QFont.Weight.ExtraBold)`), letting Qt font metrics calculate accurate dimensions.

### 3. Transparent ScrollBar Corners
- Standard Qt scroll areas generate an unstyled gray checkered square in the bottom-right corner when both scrollbars are defined.
- Always standardize scroll areas using `_make_scroll_area()`:
  - `setHorizontalScrollBarPolicy(ScrollBarAlwaysOff)`
  - `QScrollBar::corner { background: transparent; border: none; }`
  - `QScrollBar:horizontal { height: 0px; }`

### 4. Background Click-Through Transparency
- Translucent frameless windows in Windows intercept clicks across their full bounding box if not masked.
- `DynamicNotchWindow` updates its click-mask dynamically via `self.setMask(QRegion(rounded_path.toFillPolygon().toPolygon()))` so clicks outside the rounded notch pass directly to the desktop or background apps.

---

## 6. Testing & Quality Verification Contract
All tests in `poppy/tests/` protect public interfaces and behaviors:
- `LyricLineWidget`: Must preserve `time_sec`, `_lbl`, `_is_active`, `clicked = Signal(float)`, `set_active(bool)`, and `font-weight: 800` / `700` in stylesheet.
- `SpotifyLyricsWidget`: Must preserve `set_synced_lyrics(list)`, `set_plain_lyrics(str)`, `update_playback_time(float)`, `seek_requested = Signal(float)`, `_line_buttons`, and `content_stack`.
- `ScreenTimeManager`: Must track foreground sessions, streak time, top application breakdown, and emit `stats_updated`.
- `CapsuleSlider`: Must maintain standard `QSlider` APIs (`value()`, `setValue()`, `setRange()`, `isSliderDown()`) with custom 30px pill painting.

Always run:
```bash
python -m pytest poppy/tests/
```
Ensure all 31 tests pass with zero warnings before committing changes.
