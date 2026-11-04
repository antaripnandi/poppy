# Poppy

A Windows 10/11 desktop utility built with Python 3.11 and PySide6. Inspired by [NotchX](https://github.com/Navneet035/NotchX).

The top-edge pill opens a drawer with media controls, a focus timer, a file shelf, and notes. Home is the front dashboard: time, music, CPU/GPU/RAM usage, battery, notes and the shelf. Every enabled tool has a directly visible tab.

## Run

```powershell
python -m pip install -r requirements.txt
python main.py
```

You can also use `run.bat`. Keep the checkout folder named `poppy` while running from source.

Close any older running version from its tray menu before launching this update. The updated version uses a per-user lock; subsequent launches activate it without terminating another process.

## Daily use

- Click the pill to open the drawer. Escape closes it.
- Hover opens compact controls when a media session is available and hover peek is enabled. With no media, the idle pill shows the clock. Click the pill or hover preview to open Home by default. Use **Open to** in Settings to pick another starting tab.
- Ctrl+1 through Ctrl+9 select header tabs while the drawer has keyboard focus.
- Drop files on the pill to stage them on the shelf, then drag them into another application.
- Start, pause, reset, or skip a focus timer. Skipped phases do not count as completed sprints.
- **Floating copy** opens a separate saved note and keeps the original scratchpad text. Use **Notes > Saved notes** to reopen a closed floating note.
- The **Float current tab** button below the content moves the live view into a resizable floating window. Controls, notes and lyrics keep working there. Closing returns the same view to the drawer without changing the tab you are currently using. Repeating the action raises the existing window.
- **Done** saves settings. Closing Settings without Done discards its previews and unsaved edits.

The player shows centered artwork and track details, a seekable timeline when supported, and optional lyrics. Playback controls sit centered above a separate volume row. Quiet source buttons switch between real media sessions; the player menu lists all sessions. Shuffle and repeat are not exposed. The audio-device menu lists detected outputs and links to Windows Sound Settings; it does not switch devices itself.

## Appearance

**Settings > Appearance** separates three choices:

- **Layout theme:** Classic, Minimal and Soft remain available. Flat adds divider lines, underline tabs, slim sliders and a compact player. Paper uses an open page, serif clock, plain notes and text-led controls. Instrument uses header strips, numeric readouts, rectangular controls and segmented meters. Each design works in light and dark modes.
- **Appearance mode:** Dark, Light, or Follow Windows. Windows mode updates while the app is running.
- **Color palette:** All seven original presets plus Charcoal, Sage and Slate.

Window style, size, corner radius, display and top offset remain configurable. Drag a size slider, click its track, or type an exact value beside it. The wheel scrolls the Settings page without changing hovered fields. Size previews are coalesced and do not reload themes or rebuild the dashboard; releasing a slider applies its final value. Done saves the changes. Closing without Done restores the saved appearance. Switching themes preserves notes, views and playback state.

Under **Home order**, drag a section onto another position in the preview. The other sections shift to make room; a moving preview and drop highlight show the destination. You can also focus a section with Tab and move it with Alt + arrow keys. Each design remembers its own arrangement. Reset order restores only the selected design. Done saves the order; closing cancels unsaved changes.

**Settings > Music** controls artwork/theme color, player buttons and Follow playback. Music uses separate player and lyrics areas, with playback controls always visible and no outer page scrollbar. Lyrics are looked up while that view is open, and can be hidden. Follow playback can be turned off without disabling lyric highlighting.

Rapid track changes wait 200 ms before starting a new lyrics lookup. Old searches stop between requests, duplicate queries are removed, and cached lyrics open immediately. Artwork and source buttons are reused when unchanged. Lyrics cache writes run outside the lock used by the interface. External providers can still be slow or lack a matching track.

**Draw on screen** collapses the panel and opens a live drawing layer on Poppy's display. Drag to draw, click to make a dot, choose a pen color, and use Clear to remove marks. Press Esc or the toolbar's close button to leave drawing mode and interact with the desktop again.

The default dashboard is 960 × 560 logical pixels. Earlier untouched defaults migrate once; custom dimensions are retained. The Home dashboard fits all four cards without an outer scroll area. It grows to the required height and tightens padding on shorter screens; long lyrics and collection lists scroll inside their own areas. Battery information is confined to Home, with no battery text in the closed pill. GPU monitoring displays N/A when unavailable instead of inventing a percentage.

## Data and privacy

Settings, notes, clipboard history, screen-time data, shelf state, lyrics cache, and new captures live in `%LOCALAPPDATA%\Poppy`. Existing files in `~/.poppy` are copied on first use without removing the originals. The checkout's `config.json` supplies initial settings when no user settings exist. Existing shelf items continue referencing their original paths.

Clipboard text recording and automatic image staging are **off by default**. Enable them explicitly in **Settings > Tools**. Recording respects Windows clipboard-history exclusion formats; it is not a guarantee that arbitrary copied text contains no secrets. Captures and clipboard history are stored locally without encryption.

Clearing the shelf removes its entries, not the original files. Capture cleanup preserves files still staged on the shelf. Floating notes save on close and are restored after exiting Poppy with them open. Save failures leave note content available and display an error.

Weather and lyrics providers receive location or track queries when those features are used. Discord presence is optional. Lyrics can still depend on provider availability and matching quality.

## Tests

```powershell
python -m pytest tests -q
```

Tests use temporary data folders and stub background app integrations. Live-provider checks are separate:

```powershell
python -m pytest tests -m live_service --live-services
```

For tests or a separate development profile, set `POPPY_DATA_DIR` to a dedicated folder. Legacy data is not imported when this override is set.

Native focus behavior, multi-monitor placement, capture exclusion, and hardware support still need testing on the target Windows device. The current source does not provide a verified standalone executable build.
