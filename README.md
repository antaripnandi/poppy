# Poppy

Poppy is a Windows desktop utility that puts a media player, system controls, and everyday tools in a notch at the top of your screen. Hover for the compact player or click to open a dashboard with your music, notes, files, and system stats.

## What you can do

| Area | Features |
| --- | --- |
| **Home** | See the clock, current track, CPU and GPU usage, memory, battery, notes, and staged files. Choose which cards appear and drag to reorder them. |
| **Music and sound** | Control playback, seek when supported, and follow synced lyrics. Switch media sources or audio output, adjust volume per app, and optionally control Spotify's own playback volume. |
| **Files and clipboard** | Drag files onto the pill to stage them on the Shelf, then drag them into another app. Keep clipboard history, stage screenshots, and get alerts when files finish downloading in a watched folder. |
| **Notes and focus** | Keep a scratchpad or floating notes, run focus sessions, use a countdown or stopwatch, and track screen time by app. Keep Awake can temporarily prevent Windows from sleeping. |
| **Desktop tools** | Search commands, switch virtual desktops, draw on the screen, or move a tab into a resizable floating window. |
| **Voice typing** | Dictate into a focused field or copy to the clipboard. Supports hold-to-talk and spoken edits to selected text. Enable it with your own provider key. [Voice typing setup and shortcuts](docs/voice-typing.md) |

## Install

Download the x64 installer from [GitHub Releases](https://github.com/antaripnandi/poppy/releases). Poppy supports Windows 10 version 1809 or later and Windows 11 on x64. It installs for your Windows account without administrator rights.

Close any running copy from the tray before installing. You can install a newer version over the existing one. The installer and source checkout share the same local profile, which is also kept when you uninstall. To check for an update, use **Settings → About** or the tray menu. Scheduled checks can be turned off in About.

## Using Poppy

- **Hover** over the pill for playback controls. The hover card still opens when nothing is playing and lets you adjust system volume. **Click** to open Home, or change the starting tab with **Open to**. Press **Esc** to close the drawer.
- **Scroll** over the pill for volume or **Shift + scroll** for brightness on a supported display. **Settings → Behavior → Pill level feedback** controls whether Poppy shows these adjustments in the pill.
- **Open App mixer** on Home or choose **Apps** from the hover volume popup. Adjust or mute apps with an audio session on the default Windows output. You can pin an app so it rises to the top when it has a session.
- **Drop files** on the pill to stage them. To monitor downloads, enable **Settings → Tools → Download alerts**, then open **Shelf → Downloads** to see activity. Alerts are based on files in the watched folder.
- **Open Commands** from the drawer footer or press **Ctrl + Shift + Space** while Poppy has focus. Search tabs, actions, and Start menu shortcuts. Use **Ctrl + 1** through **Ctrl + 9** to switch tabs.
- **Float a tab** from the drawer footer to keep working in a separate window. Closing it returns the view to the drawer.

### Make it yours

Choose from nine layouts, light or dark mode, and several color palettes under **Settings → Appearance**. Set the pill or notch shape, size, display, and hover-player color. Reorder the Home cards separately for each layout.

Under **Settings → Tools**, choose which tabs are visible and which optional features are enabled. Search Settings with **Ctrl + F**, and click **Done** to save. Turn on **Launch at login** if you want Poppy to start with Windows.

### Connect Spotify playback volume

The Spotify row in App mixer controls Windows app volume by default. Connecting Spotify lets that same row control the active Spotify device's playback volume.

Create a Web API app in the [Spotify Developer dashboard](https://developer.spotify.com/dashboard), register `http://127.0.0.1:43821/callback` as a redirect URI, and enter the public Client ID in **Settings → Music → Connect Spotify**. Spotify requires Premium for playback-volume access. Disconnect in Settings to remove the saved account tokens.

## Data and privacy

Settings, notes, clipboard history, screen time, shelf state, lyrics cache, and captures are saved in `%LOCALAPPDATA%\Poppy`. Use **Settings → About → Open data folder** to find it. Close Poppy before backing it up or restoring it. Files staged on the Shelf are referenced by path, so keep the originals if you want those entries to stay usable.

Clipboard text recording, automatic screenshot staging, and screen-time tracking start off. Notes, captures, and history use your Windows profile permissions. Optional Spotify credentials and voice provider keys use Windows Data Protection. Weather stays off until you choose a city or enable IP-based location lookup. Lyrics and voice typing contact the providers needed for those features. [Voice typing data and providers](docs/voice-typing.md#providers-and-privacy)

## Development

Poppy uses Python 3.11 and PySide6. Keep the checkout directory named `poppy` when running from source.

```powershell
python -m pip install -r requirements.txt
python main.py
python -m pytest tests -q
```

Set `POPPY_DATA_DIR` to a separate directory for an isolated development profile. To run tests that contact live providers, use `python -m pytest tests -m live_service --live-services`. See the [design guide](DESIGNS.md) for layout and interaction conventions. Poppy was inspired by [NotchX](https://github.com/Navneet035/NotchX).

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

## License

Poppy's source is available under the [MIT License](LICENSE). Bundled third-party components carry their own licenses.
