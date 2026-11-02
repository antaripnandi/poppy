# Poppy Design System & Aesthetic Guide (`DESIGNS.md`)
> Complete design specification, tokens, component anatomy, and layout principles for Poppy.

---

## 1. Visual Philosophy: Option 1 (Apple Studio Bento)

Poppy rejects AI slop—garish gradient borders, saturated blue primary blocks, cluttered badges, and boxy Windows 95 scrollbars. Instead, it follows a calm, high-craft aesthetic inspired by:
- **macOS Control Center & Dynamic Island:** Deep obsidian glass, tactile capsule sliders, and organic physics.
- **Apple Studio Bento Grid:** Modular rounded cards (`CardFrame`) grouping telemetry, media, scratchpads, and drop staging with proportional hierarchy.
- **React Bits Modern Craft:** Rubber segment animated tab navigation (`<RubberSegment />`) with dilation stretch and spring squash.
- **Native Spotify Desktop:** Clean synchronized lyrics with bold high-contrast active typography, smooth auto-centering, and click-to-seek playback.

---

## 2. Design Tokens & Color Palette

### Surfaces & Backgrounds
| Token | Value | Description |
|---|---|---|
| `bg-root` | `#07080c` to `#090d16` | Deep obsidian backdrop for notch and settings |
| `card-surface` | `rgba(255, 255, 255, 0.032)` | Bento card background fill |
| `card-border` | `1px solid rgba(255, 255, 255, 0.065)` | Whisper-thin card boundary |
| `card-hover-bg` | `rgba(255, 255, 255, 0.045)` | Subtle interaction illumination |
| `card-hover-border` | `1px solid rgba(255, 255, 255, 0.11)` | Interactive card focus |
| `card-radius` | `16px` | Standard Bento corner radius |

### Typography Hierarchy
| Role | Size / Weight | Color | Font Family |
|---|---|---|---|
| Active Lyric | `18px` / ExtraBold (800) | `#ffffff` | Segoe UI Variable / Segoe UI / SF Pro |
| Inactive Lyric | `15px` / DemiBold (700) | `rgba(255, 255, 255, 0.35)` | Segoe UI Variable / Segoe UI / SF Pro |
| Lyric Hover | `15px` / DemiBold (700) | `rgba(255, 255, 255, 0.85)` | Segoe UI Variable / Segoe UI / SF Pro |
| Header / Title | `16px` / Bold (700) | `#f8fafc` | Segoe UI Variable Display |
| Section Label | `12px` / SemiBold (600) | `#f1f5f9` | Segoe UI Variable Text |
| Secondary / Subtitle | `11px` / Medium (500) | `#94a3b8` | Segoe UI Variable Text |
| Caption / Telemetry | `10px` / SemiBold (600) | `#64748b` | Segoe UI Variable Text |

### Accent Lighting
- **Default Accent:** Apple Blue `#0a84ff` (or selected theme preset: Midnight `#6e9bff`, Aurora `#3ddc97`, Ember `#ff9f0a`, Lime `#b4e61e`, Rose `#ff6b9a`).
- **Pill Fills:** `rgba(accent, 0.20)` to `rgba(accent, 0.25)`.
- **Pill Borders:** `rgba(accent, 0.45)` to `rgba(accent, 0.50)`.
- **Text Highlights:** Full saturation `#0a84ff` or `#ffffff`.

---

## 3. Component Architecture

### A. React Bits `<RubberSegment />` (AnimatedTabStrip)
Native PySide6 implementation of React Bits segmented control:
- **Track Well:** Dark rounded pill (`rgba(0, 0, 0, 0.45)`, border `1px solid rgba(255, 255, 255, 0.07)`, radius `14px`, height `32px`).
- **Indicator Thumb:** Rubber capsule positioned directly beneath active button (`rgba(accent, 0.25)`, border `1px solid rgba(accent, 0.5)`, radius `11px`).
- **Spring & Rubber Physics (240ms OutCubic):**
  - Moving forward (left to right): Stretches leading edge forward across both slots (`+4px` dilation) at keyframe `0.38`, squashes into target (`+3px`) at `0.78`, and relaxes at `1.0`.
  - Moving backward (right to left): Stretches trailing edge backwards across slots (`-4px` dilation) before squashing and relaxing.

### B. macOS Control Center Capsule Sliders (`CapsuleSlider`)
Thick tactile sliders for volume and brightness:
- **Dimensions:** Fixed height `30px`, border radius `15px`.
- **Track Well:** `rgba(255, 255, 255, 0.08)` with subtle inner border.
- **Fluid Fill:** Symmetrically rounded pill fill extending from 0 to current percentage in theme accent.
- **Embedded Glyphs:** Icon (`Icons.VOLUME_HIGH`, `Icons.BRIGHTNESS`) painted directly inside the pill on the left.
- **Numeric Readout:** Tabular readout (`100%`) aligned right.
- **Interaction:** Draggable, clickable anywhere along the capsule track with instantaneous smooth visual response.

### C. Bento 2-Card Studio Music View (`MusicTabView`)
Divided into two balanced obsidian cards:
1. **Left Bento Card (Player & Studio Controls):**
   - **Artwork:** `144x144` square with 12px corner radius and smooth scaling.
   - **Track Metadata:** Clean title (15px bold), artist (12px secondary).
   - **Visualizer Source Pill:** Embedded capsule pill with active source name (`Spotify`, `Brave`) and 4-bar live audio equalizer (`AudioVisualizerBars`).
   - **Scrubber:** Slimline timeline slider with elapsed timestamp on left and negative remaining timestamp (`-03:59`) on right.
   - **Transport Deck:** Shuffle, Previous, 36px Accent Circular Play/Pause, Next, Repeat.
2. **Right Bento Card (Expansive Spotify Synced Lyrics):**
   - **Header:** Quiet "Lyrics" title label without any noisy "SYNCED" badge.
   - **Auto-Scrolling:** Vertically centered active line with smooth easing animation (`OutCubic`).
   - **Spacing Padding:** 60px top margin and 100px bottom margin so both opening and closing song verses can rest cleanly in the center of the viewport.
   - **Interactive Scrubbing:** Clicking any lyric line jumps playback immediately to that timestamp.
   - **Zero Baseline Clipping:** Layout uses `SetMinimumSize` constraint and `setMinimumHeight` rows so glyphs never get sliced.

### D. Digital Wellbeing & Screen Time
- **Home Tab Pill:** Minimalist 24px capsule on the Home clock card displaying today's active screen duration (`54m`), current active app (`• Python`), and a 2px micro-progress bar indicating progress toward daily goal.
- **Settings Screen Time Page:**
  - **Hero Bento Card:** Large typography readout (`54m`), Active Streak chip (`Active Streak: 22m`), and Goal Progress chip (`Goal: 15%`).
  - **Controls Bento Card:** Smooth toggle switches for usage tracking, in-notch pill visibility, per-app breakdown, and AFK idle timeout dropdown.
  - **Daily Goal Bento Card:** Capsule slider for daily goal hours (1h–14h) with alert toggles.

### E. Settings Window ("Make it yours")
- **Geometry:** `840x580` (minimum `780x520`) preventing squished controls.
- **Sidebar:** Clean navigation list with Fluent icons (`🎨 Appearance`, `🗂️ Tabs Manager`, `⚡ Behavior & Gestures`, `🔔 Notifications`, `⏳ Screen Time`, `🎵 Media & Lyrics`, `⛅ Weather & Location`, `⏱️ Pomodoro`, `🎮 Discord RPC`, `📊 Hardware HUD`, `⚙️ About & System`) and frosted pill active indicators.
- **Scroll Container:** Every page uses `_make_scroll_area()` with hidden horizontal scrollbar and `QScrollBar::corner { background: transparent; border: none; }` eliminating the checkered corner artifact.
- **Actions:** Minimal frosted `Done` pill button (`_save_and_close`) replacing the harsh blue block button.

---

## 4. Layout & Spacing Rules

1. **Card Margins & Padding:**
   - Bento Cards: `14px` content margins, `10px` spacing between cards.
   - Card Corner Radius: Always `16px`.
2. **Notch Drawer Dimensions:**
   - Standard Open Width: `960px`.
   - Standard Open Height: `480px`.
   - Header Bar Height: `36px` containing `<RubberSegment />` and right-side system capsule.
3. **Animations:**
   - State Transitions: `320ms` with `OutCubic` or `OutQuint` easing.
   - Hover Grace Period: `400ms` leave timer to prevent accidental collapses when mousing between controls.
   - Notch Center Pop: Symmetrically scales width from horizontal screen center.
