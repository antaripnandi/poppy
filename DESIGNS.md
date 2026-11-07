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
- Use a short direct tab transition. Do not restore rubber stretching or decorative spring keyframes.
- The 316 × 108 hover player gives the artwork the full left column. Stack track text, three playback buttons, and a thin playback timeline on the right. The speaker opens a vertical volume slider. Keep player selection, mute and sound output in the context menu. Elide by available pixels and keep full metadata in tooltips. Artwork and metadata open the configured tab. Center the content during expansion and retain the hover delay and leave grace period. Without a media session, show the clock in the closed pill and keep the hover card available with an idle message, disabled playback controls, and working system volume. If media ends while the card is open, switch to the idle state in place.
- The compact artwork scales with the pill and uses a rounded image crop. The docked notch's top corners flare toward the screen edge. The painter and click-through mask use the same outline.
- Volume keys, matched Windows brightness notifications, and pill scrolling show transient level feedback inside the existing pill. Use a Fluent icon, a neutral animated track, and the percentage or mute state. Retarget the fill from its current position on repeated input and restore the normal pill after one second. Shift + scroll adjusts brightness on displays that support it. Only hide a recognized native brightness popup when the compact indicator can replace it.

## Visual treatment

- Flat dark surfaces, muted secondary text and restrained borders. Avoid ornamental badges, nested cards and large uppercase headings.
- Segoe UI: 12px controls, 13px file titles, 14px notes, 20px track title. Keep long text bounded and provide full-text tooltips where it is truncated.
- Home keeps playback in a compact row above the four draggable cards. Use 36px artwork, track and artist, direct transport controls and one source selector when multiple sessions are available. System controls use icon and percentage sliders with text actions. The Music page uses larger artwork and a separate lyrics column. Optional artwork tint adapts to Light and Dark modes.
- Music centers artwork and metadata in vertical player layouts; Flat and Paper retain their horizontal identity. Center playback controls above a separate volume row. Use a borderless player surface, native Segoe UI typography, slim neutral timelines and quiet source buttons. Preserve keyboard focus indicators, seek behavior and full metadata in tooltips.
- Use normal desktop transport buttons, elapsed/total timeline, volume control and an explicit Lyrics toggle. Avoid a phone widget silhouette.
- Player buttons switch actual sessions; all sessions remain accessible through the player selector.
- Keyboard focus must remain visible. Icon controls need accessible names and tooltips. Unsupported actions stay hidden or disabled.

## Settings

- No emoji in labels, descriptions or navigation. Use plain names and explain actual behavior.
- Preserve existing settings and all seven original themes. Charcoal, Sage and Slate are additional flat, muted presets.
- Appearance separates nine layout themes, mode (Dark / Light / Follow Windows) and ten color palettes. Keep style, display, dimensions, corner radius and offset controls. Hover color can follow artwork, use a fixed color, or match the layout. Music has a separate background and session-button preference.
- Layout themes change arrangements, not just color: Classic balances columns; Minimal uses a narrow summary/player column, smaller artwork and flat surfaces; Soft places notes beside the clock and uses rounded cards. Music always keeps the player on the left and lyrics on the right across all themes. Apply surface treatment and page spacing across the panel. Show a small Home arrangement preview in Settings because the main panel collapses while Settings is open.
- Flat borrows alignment and low visual noise from Linear: divider lines, underline tabs and thin controls. Paper borrows Things' reading-focused treatment: an open page, serif clock, text actions and plain editors. Instrument borrows Ableton's functional controls: header strips, fixed-width readings and segmented meters. These designs change controls and surfaces, with reversible authored styles; do not reduce them to card reordering.
- Deck uses icon tabs, tinted cards, and side-by-side artwork and transport. Daily moves tabs and the Home player to the bottom, uses serif typography and an open page, and presents document actions as rows. Console uses monospaced readouts, segmented controls, a seek ruler, and timestamped lyrics. Apply the shared typography, controls, spacing and surfaces to all tabs and keep the real page widgets when switching designs.
- The Home preview is an arrangement editor: drag sections with a visible preview and drop target, or move the focused section with Alt + arrows. Keep all four sections present, retain a separate order per design, and reset only the selected design. Preview live, save on Done, cancel on close. Rearranging must preserve the actual editors, playback and shelf content.
- Home section switches control the mini-player, four cards and Screen Time. Apply visibility on Done. Pack visible cards in saved order and keep the live widgets for hidden cards. Screen Time uses the existing tracking setting and shows up to five ranked app durations.
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
