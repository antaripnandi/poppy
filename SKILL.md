---
name: poppy
description: Comprehensive development, design, and debugging skill for Poppy (Dynamic Notch & Productivity Island for Windows). Use when building, modifying, styling, or troubleshooting Poppy components, views, lyrics, screen time, or animations.
---

# Poppy Engineering & Design Skill

Use this skill when reading, developing, debugging, refactoring, or designing for the **Poppy** Windows Dynamic Notch application (`poppy/`).

---

## 1. Core Principles & Decision Ladder
- **Follow the Ponytail Ladder:** Minimal, ultra-clean code. YAGNI (You Aren't Gonna Need It). Zero bloat, zero AI slop, no garish colored borders.
- **Dependency Guardrail:** Pure Python stdlib + `PySide6` + `ctypes` Win32 API. Never introduce external packages unless strictly requested.
- **Option 1 Aesthetic:** Apple Studio Bento + macOS Control Center + Obsidian frosted glass (`rgba(255, 255, 255, 0.032)`).

---

## 2. Key Files Map

| Domain | Key Files | Description |
|---|---|---|
| **App Lifecycle** | [`main.py`](file:///c:/Users/banta/Desktop/Personal tests/poppy/main.py) | Single-instance enforcement (`.poppy.pid`), system tray, DPI scaling, global startup |
| **Window & Physics** | [`core/window.py`](file:///c:/Users/banta/Desktop/Personal tests/poppy/core/window.py) | `DynamicNotchWindow`, 4 states (`COLLAPSED`, `PEEK`, `ISLAND`, `EXPANDED`), symmetric center-pop |
| **Design Components** | [`ui/components.py`](file:///c:/Users/banta/Desktop/Personal tests/poppy/ui/components.py) | `<RubberSegment />` (`AnimatedTabStrip`), `CapsuleSlider`, `SpotifyLyricsWidget`, `LyricLineWidget` |
| **Tab Views** | [`ui/views.py`](file:///c:/Users/banta/Desktop/Personal tests/poppy/ui/views.py) | `HomeTabView` (Bento dashboard), `MusicTabView` (2-Card Studio), `Calendar`, `Shelf`, `Notes` |
| **Extended Views** | [`ui/extended_views.py`](file:///c:/Users/banta/Desktop/Personal tests/poppy/ui/extended_views.py) | `ClipboardTabView`, `DocsTabView`, `DesktopsTabView`, `TimerTabView` |
| **Settings App** | [`ui/settings_window.py`](file:///c:/Users/banta/Desktop/Personal tests/poppy/ui/settings_window.py) | Dedicated 840x580 window, 11 categories, `_make_scroll_area`, zero-artifact transparent corners |
| **Digital Wellbeing** | [`core/screentime_manager.py`](file:///c:/Users/banta/Desktop/Personal tests/poppy/core/screentime_manager.py) | Foreground app tracking, idle/AFK detection, streaks, goal monitoring |
| **Synchronized Lyrics** | [`core/lyrics_manager.py`](file:///c:/Users/banta/Desktop/Personal tests/poppy/core/lyrics_manager.py) | LRCLIB query, `parse_lrc`, fuzzy match, click-to-seek playback |
| **Documentation** | [`AGENTS.md`](file:///c:/Users/banta/Desktop/Personal tests/poppy/AGENTS.md), [`DESIGNS.md`](file:///c:/Users/banta/Desktop/Personal tests/poppy/DESIGNS.md) | Architectural spec and design system documentation |

---

## 3. Invariants & Critical Gotchas

### 1. ScrollArea Baseline Clipping Prevention
Always set `self.lines_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)` on scroll containers!
Without this, `QScrollArea` compresses widgets down to viewport height, crushing multiline text rows and horizontally slicing off font baselines.
Ensure dynamic text rows set `setMinimumHeight(44)` (or `56` when active) with `+18px` to `+20px` vertical padding.

### 2. Qt CSS Typography Limitation
Qt CSS does not support `line-height`. Do not set `line-height` in stylesheets. Use explicit `QFont` objects (`QFont("Segoe UI", 18, QFont.Weight.ExtraBold)`) so font metrics compute exact bounding geometry.

### 3. Scrollbar Checkered Artifact
Always use `_make_scroll_area(widget)` in settings and extended views with:
```python
sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
```
and ensure `QScrollBar::corner { background: transparent; border: none; }` is applied.

### 4. Single-Instance & Process Cleanliness
When running Poppy, ensure stale instances are terminated:
```powershell
python poppy/main.py # Automatically terminates old PID via .poppy.pid
```

---

## 4. Verification & Testing

Always verify all changes using the workspace virtualenv:
```powershell
C:\Users\banta\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe -m pytest poppy/tests/
```
All **31 unit tests** must pass without errors.
