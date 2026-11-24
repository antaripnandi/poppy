# Poppy design guide

Poppy is a small daily utility. Keep controls readable, show real state, and leave room for the user's work.

## References and their use

- Keep Poppy's desktop dashboard and separate player/lyrics layout. The Android reference is a source of hierarchy ideas, not a layout to copy. Do not invent playlists, recommendations, favorites or unsupported controls.
- [MediaMate](https://wouter01.github.io/MediaMate/) informs the compact media surface and system controls.
- [NotchNook Classic](https://getnotchnook.com/classic/press/) informs temporary file staging and dragging files into another app.
- [Raycast Notes](https://www.raycast.com/core-features/notes) informs the quiet editor and floating notes.

## Navigation and sizing

- Home is the default front page. Every enabled page has a directly visible tab; do not introduce a More overflow menu.
- Keep-open, keep-awake, screen-capture exclusion, float-tab and annotation are direct buttons below the content. Settings stays in the header.
- Default expanded size is 1120 × 500 logical pixels. Respect custom dimensions. Earlier default sizes migrate through `normalize_appearance`.
- Clamp sizes to the display. At 1000 pixels and wider, put Screen Time beside the Home cards. On narrow panels, place it below them. Fit the main cards first and scroll any overflow, keeping the mini-player above it. Music keeps player controls outside a dedicated lyrics viewport. Other pages keep static controls outside scrollable collections.
- Switch tabs directly. Show selection through text contrast and weight, and keep the keyboard focus outline.
- The 316 × 108 hover player gives the artwork the full left column. Stack track text, three playback buttons, and a thin playback timeline on the right. The speaker opens a vertical volume slider. Keep player selection, mute and sound output in the context menu. Elide by available pixels and keep full metadata in tooltips. Artwork and metadata open the configured tab. Center the content during expansion and retain the hover delay and leave grace period. Without a media session, show the clock in the closed pill and keep the hover card available with an idle message, disabled playback controls, and working system volume. If media ends while the card is open, switch to the idle state in place.
- The compact artwork scales with the pill and uses a rounded image crop. The docked notch's top corners flare toward the screen edge. Leave room in the click-through mask for antialiased edge pixels.
- Volume keys, matched Windows brightness notifications, and pill scrolling show transient level feedback inside the existing pill. Use a Fluent icon, a neutral animated track, and the percentage or mute state. Retarget the fill from its current position on repeated input and restore the normal pill after one second. Shift + scroll adjusts brightness on displays that support it. Only hide a recognized native brightness popup when the compact indicator can replace it.

## Visual treatment and hierarchy

- Single unified Bento dashboard with 4-tier visual hierarchy ladder:
  - **Tier 1 (100% #ffffff)**: Primary focal points (clock digits, active track title, active toggle state).
  - **Tier 2 (70–80% rgba(255,255,255,0.75))**: Secondary metadata (artist name, formatted date, live weather, telemetry readouts).
  - **Tier 3 (40–45% rgba(255,255,255,0.45))**: Tertiary & interactive labels (inactive tabs, secondary action text, empty state hints).
  - **Tier 4 (25–30% rgba(255,255,255,0.08))**: Restrained borders, card fills (`rgba(255,255,255,0.04)`), subtle dividers.
- Tactile Squircle Action Tiles (`SquircleTileButton`):
  - $2 \times 4$ tactile squircle action buttons in Control Center: Keep Awake, Microphone, Focus, Screen Snip, Color Picker, Calculator, Bluetooth, and Lock PC.
  - Fluent glyph centered above Segoe UI 9px semi-bold label. Responsive hover feedback, press state, and checked accent glow.
- Compact Capsule Sliders (`CapsuleSlider`):
  - Inline Volume and Brightness capsule sliders with numeric percentage indicators and smooth wheel / drag response.
  - Audio gear button provides quick access to App Mixer, Mute, and Sound Output without visual clutter.
- Mini Media Player:
  - Breadcrumb track metadata (`Track Title` · `Artist`), centered transport controls (prev, play/pause, next), and player dropdown.
- Shelf & Quick Calc:
  - Staged file preview with thumbnail, filename, size, and Copy/Pin actions + smooth inline `Calculate...` math bar with safe AST evaluation.
- Bottom Utility Dock:
  - Floating rounded dock capsule below content for direct utilities (Keep-open, keep-awake, exclude capture, float tab, draw/annotate).

## Settings and customization

- No emoji in labels, descriptions or navigation. Use plain names and explain actual behavior.
- Single unified layout theme (`Classic`): Consolidates previous layout variants into one cohesive, high-craft design system.
- Appearance supports mode (Dark / Light / Follow Windows) and ten color palettes. Retains style, display, dimensions, corner radius and offset controls.
- The Home arrangement editor retains dynamic section dragging and reordering for all 4 Bento cards (`clock`, `controls`, `notes`, `shelf`).
- Home section switches control the mini-player, four cards and Screen Time. Pack visible cards in saved order and keep live widgets for hidden cards.
- Geometry previews are coalesced; they must not reapply global styles or rebuild Home. Release applies the final slider value. Wheel input over Settings fields scrolls the page without modifying values; numeric entries accept exact values.
- Appearance previews live. Done saves atomically; closing cancels unsaved changes and restores the saved appearance. Preserve unknown configuration keys.
- Wrap Settings descriptions and allow vertical scrolling. Use keyboard-accessible selectors. Preserve Qt pseudo-selectors when compiling Light styles and retain authored source styles for reversible mode changes. Artwork and user content must remain intact.

## Files and notes

- Shelf rows use a preview, filename, size and relevant actions. Pin applies to images; Open applies to other files. Copy works for both. Removing an entry keeps the original file.
- Notes use a spacious plain-text editor. Floating copy keeps the source text and creates a separately saved note. Saved notes remain reopenable.
- Keep failure messages visible. Do not replace reliable saves with decorative status animations.

## Rendering and verification

- Collection scroll areas enforce their minimum content height, support pixel and wheel-notch input, and avoid horizontal overflow. Recent conversions, agenda, clipboard and shelf scroll within their lists.
- Preserve `LyricLineWidget` and `SpotifyLyricsWidget` interfaces and minimum lyric row heights. Lyrics layouts use `SetMinimumSize` so scroll areas do not compress baselines.
- Qt stylesheets do not support CSS `line-height`. Use real font metrics and adequate layout space.
- Hidden stacked pages must not impose their minimum size on the window. Retain the rounded native click-through mask. No detached telemetry labels may be shown over the closed pill. Battery belongs only on Home.
- Preview with Windows fonts loaded and an isolated data directory. Check long titles, multiple players, lyrics, an empty and populated shelf, each Settings page and display scaling.
- Screen drawing must paint a nonzero-alpha input layer: Windows passes mouse input through fully transparent pixels. Keep the desktop visible, use the selected monitor's logical geometry, collapse the panel before drawing, and provide Escape and a visible close button. Closing must release the overlay and permit a clean reopen.
