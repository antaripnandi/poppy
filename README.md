# Poppy

A Windows 10/11 desktop utility built with Python 3.11 and PySide6. Inspired by [NotchX](https://github.com/Navneet035/NotchX).

The top-edge pill opens a drawer with media controls, a focus timer, a file shelf, and notes. Home is the front dashboard: time, music, CPU/GPU/RAM usage, battery, notes and the shelf. Every enabled tool has a directly visible tab.

## Install

Run `Poppy-Setup-0.1.0-x64.exe` and launch **Poppy** from the Start menu. The installer targets Windows 10 version 1809 or later and Windows 11 on x64. It installs for the current user without administrator rights and includes Python, Qt, and the app's runtime dependencies.

Before replacing a source checkout with the installed app, close Poppy from its tray menu. The installer and source app use the same local profile. Install a newer build over an existing installation to update it. Uninstalling through Windows removes the program and its shortcuts and keeps the profile.

Installed Poppy checks GitHub after startup and daily while it runs. Use **Settings > About** or the tray menu to check manually. You can turn off scheduled checks in About. When a newer stable installer is available, you can open its release page and install it yourself.

### Run from source

```powershell
python -m pip install -r requirements.txt
python main.py
```

You can also use `run.bat`. Keep the checkout folder named `poppy` while running from source.

Close any older running version from its tray menu before launching this update. The updated version uses a per-user lock; subsequent launches activate it without terminating another process.

## Daily use

- Click the pill to open the drawer. Escape closes it.
- Hover opens the compact player when **Preview on hover** is enabled. With no media session, the closed pill shows the clock and the hover card shows **Nothing playing** with system volume still available. Click the pill or hover preview to open Home by default. Use **Open to** in Settings to pick another starting tab.
- Standard Windows volume keys and scrolling over the pill adjust system volume. Hold Shift while scrolling over the pill to adjust brightness on a supported display. On supported Windows 11 systems, Poppy clips the recognized shared volume and brightness popup in advance while the compact pill can show feedback and Poppy owns all volume keys. It restores the popup when the drawer opens or Poppy exits. If a volume key is unavailable, Poppy leaves the shared popup in place and can still dismiss it after a matching brightness change.
- Ctrl+1 through Ctrl+9 select header tabs while the drawer has keyboard focus.
- Open **Commands** from the drawer footer or press Ctrl+Shift+Space while Poppy has focus. Search tabs, built-in actions, and Start menu shortcuts.
- **Desktops** lists open windows on the current virtual desktop. Press Enter on a window to activate it, or use the desktop buttons to switch, create a desktop, or open Task View.
- Drop files on the pill to stage them on the shelf, then drag them into another application.
- Start, pause, reset, or skip a focus timer. Skipped phases do not count as completed sprints.
- **Floating copy** opens a separate saved note and keeps the original scratchpad text. Use **Notes > Saved notes** to reopen a closed floating note.
- The **Float current tab** button below the content moves the live view into a resizable floating window. Controls, notes and lyrics keep working there. Closing returns the same view to the drawer without changing the tab you are currently using. Repeating the action raises the existing window.
- **Done** saves settings. Closing Settings without Done discards its previews and unsaved edits.

The player shows centered artwork and track details, a seekable timeline when supported, and optional lyrics. Playback controls sit centered above a separate volume row. Source buttons switch between real media sessions. The sound output menu marks the current device and can switch the default playback output. Windows Sound Settings is available from the same menu.

## Appearance

**Settings > Appearance** separates three choices:

- **Layout theme:** Choose from nine layouts. Classic, Minimal, Soft, Flat, Paper and Instrument remain available. Deck has icon tabs and tinted modules. Daily uses serif text, a date masthead, a bottom player and bottom tabs. Console uses compact status panels, labeled playback controls and timestamped lyrics. Each design styles all tabs and supports Light and Dark.
- **Appearance mode:** Dark, Light, or Follow Windows. Windows mode updates while the app is running.
- **Color palette:** All seven original presets plus Charcoal, Sage and Slate.

Window style, size, corner radius, display and top offset remain configurable. Drag a size slider, click its track, or type an exact value beside it. The wheel scrolls the Settings page without changing hovered fields. Size previews are coalesced and do not reload themes or rebuild the dashboard; releasing a slider applies its final value. Done saves the changes. Closing without Done restores the saved appearance. Switching themes preserves notes, views and playback state.

Use **Appearance > Hover player color** to follow album artwork, choose a fixed color, or match the layout. The compact hover card shows artwork, playback controls and a timeline. Click the speaker to open the vertical volume slider below the card. The card closes when the cursor leaves both the player and the slider. Right-click for mute, media player selection when multiple sources are available, and sound output. The collapsed thumbnail scales with the pill. Notch style curves outward at the top edge. Floating Pill style rounds all four corners.

Under **Home order**, drag a section onto another position in the preview. The other sections shift to make room; a moving preview and drop highlight show the destination. You can also focus a section with Tab and move it with Alt + arrow keys. Each design remembers its own arrangement. Reset order restores only the selected design. Done saves the order; closing cancels unsaved changes.

Under **Appearance > Home sections**, choose which sections appear. Done saves the choices. Hiding a card keeps its content and saved order. Screen Time shows today's total and up to five apps ranked by active time when app tracking is enabled. Its visibility can also be changed from **Screen Time > Show on Home**.

**Settings > Music** controls artwork/theme color, player buttons and Follow playback. Music uses separate player and lyrics areas, with playback controls always visible and no outer page scrollbar. Lyrics are looked up while that view is open, and can be hidden. Follow playback can be turned off without disabling lyric highlighting.

Rapid track changes wait 200 ms before starting a new lyrics lookup. Old searches stop between requests, duplicate queries are removed, and cached lyrics open immediately. Artwork and source buttons are reused when unchanged. Lyrics cache writes run outside the lock used by the interface. External providers can still be slow or lack a matching track.

**Draw on screen** collapses the panel and opens a live drawing layer on Poppy's display. Drag to draw, click to make a dot, choose a pen color, and use Clear to remove marks. Press Esc or the toolbar's close button to leave drawing mode and interact with the desktop again.

The drawer starts at 1120 × 500 logical pixels. Earlier default sizes migrate automatically and custom sizes are kept. On wide panels, Screen Time sits beside the Home cards. On narrow panels, it moves below the cards. Home scrolls when the selected sections need more height, with the mini-player above the scroll area. Battery information is confined to Home. GPU monitoring displays N/A when unavailable.

## Data and privacy

Settings, notes, clipboard history, screen-time data, shelf state, lyrics cache, and new captures live in `%LOCALAPPDATA%\Poppy`. Existing files in `~/.poppy` are copied on first use without removing the originals. The checkout's `config.json` supplies initial settings when no user settings exist. Existing shelf items continue referencing their original paths.

Use **Settings > About > Open data folder** to find your profile. Exit Poppy before copying the folder for backup or restoring it. Shelf entries referencing external files require those files at their original paths. The optional Spotify credential is tied to its Windows account and may need to be entered again on another computer.

Fresh profiles leave clipboard text recording, automatic image staging, and screen-time tracking off. Enable the first two in **Settings > Tools** or enable tracking in **Settings > Screen Time**. Recording respects Windows clipboard-history exclusion formats. Captures, notes, and history are stored locally with your Windows profile permissions. They have no extra application-level encryption. Screenshot alerts follow **Settings > Notifications**, including the preview and focus settings.

Clearing the shelf removes its entries, not the original files. Capture cleanup preserves files still staged on the shelf. Floating notes save on close and are restored after exiting Poppy with them open. Save failures leave note content available and display an error.

Weather stays off until you choose a city or explicitly enter **Auto-detect** in Settings. Weather uses HTTPS, and Auto-detect sends a request to an IP location provider. Lyrics providers receive track queries while lyrics are in use. Windows Data Protection encrypts the optional Spotify lyrics cookie in the active settings file for the current Windows account. Poppy sends Spotify credentials only on the original authenticated requests. Discord presence is optional.

## Build the installer

Use Windows x64, 64-bit Python 3.11, and Inno Setup 7.

```powershell
python -m venv build\release-env
.\build\release-env\Scripts\python.exe -m pip install --only-binary=:all: -r packaging\requirements.txt
.\build\release-env\Scripts\python.exe packaging\build.py --iscc "C:\Path\To\Inno Setup 7\ISCC.exe"
```

The build stages application code, default settings, branding, and sound assets. It verifies the frozen runtime before compiling the installer and writes the setup file and its SHA-256 checksum to `dist`. The installer includes a runtime version inventory and available third-party license notices. To sign both executables before generating the checksum, supply `--signtool`, `--signer-thumbprint`, and `--timestamp-url`. The signing key stays in your Windows certificate store or its configured provider.

### Publish an update

1. Update `APP_VERSION` in `core/__init__.py`, run the tests, and build from the commit you intend to tag. Use a Git tag such as `v0.1.1` that matches the app version. [Semantic Versioning](https://semver.org/)
2. Sign the app and installer with your publisher certificate and an RFC 3161 timestamp. Generate the installer checksum after signing it. [Microsoft signing and timestamps](https://learn.microsoft.com/windows/win32/seccrypto/time-stamping-authenticode-signatures)
3. Test a clean install, an upgrade with an existing profile, and uninstall. Create a GitHub release draft for the tag, add release notes, and attach the matching `Poppy-Setup-<version>-x64.exe` and `.exe.sha256` files before publishing. Use a prerelease for test builds. [GitHub releases](https://docs.github.com/repositories/releasing-projects-on-github/managing-releases-in-a-repository)
4. For automatic installation, use a signed package with a managed update channel such as Microsoft Store or MSIX App Installer, or design an updater that verifies signed metadata and artifacts before installing. Test interrupted updates, failed verification, and recovery before enabling it. [MSIX update settings](https://learn.microsoft.com/windows/msix/app-installer/update-settings) · [The Update Framework](https://theupdateframework.io/)

## Tests

```powershell
python -m pytest tests -q
```

Tests use temporary data folders and stub background app integrations. Live-provider checks are separate:

```powershell
python -m pytest tests -m live_service --live-services
```

For tests or a separate development profile, set `POPPY_DATA_DIR` to a dedicated folder. Legacy data is not imported when this override is set.

Native focus behavior, multi-monitor placement, capture exclusion, and hardware support depend on the target Windows device.
