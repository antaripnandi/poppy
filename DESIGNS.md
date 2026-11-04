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
- Default expanded size: 960 × 560 logical pixels. Respect custom dimensions. Earlier untouched defaults migrate once through `normalize_appearance`.
- Clamp sizes to the display. Home must fit all four cards without an outer scroll area. Size the window to the loaded cards, including player buttons and shelf preview; tighten vertical padding on shorter screens. Music keeps player controls outside a dedicated lyrics viewport. Other pages keep static controls outside scrollable collections.
- Use a short direct tab transition. Do not restore rubber stretching or decorative spring keyframes.
- Hover preview uses a compact 420 × 72 player with 44px rounded artwork, one title row, a quieter artist/source row and tightly grouped previous/play/next controls. Keep the source selector out of the title. Elide by available pixels with full metadata in tooltips. Artwork and metadata open the default tab, which is Home unless configured otherwise. Transport buttons act without opening the drawer. Debounce hover entry, retain a leave grace period and use a short fade that stops cleanly when the state changes. With no media session, the idle pill shows the clock and skips the hover preview.

## Visual treatment

- Flat dark surfaces, muted secondary text and restrained borders. Avoid ornamental badges, nested cards and large uppercase headings.
- Segoe UI: 12px controls, 13px file titles, 14px notes, 20px track title. Keep long text bounded and provide full-text tooltips where it is truncated.
- Home shows 48px artwork with the track title and artist. The dedicated Music page uses larger artwork and a separate lyrics column. Optional artwork tint adapts to Light and Dark modes.
- Music centers artwork and metadata in vertical player layouts; Flat and Paper retain their horizontal identity. Center playback controls above a separate volume row. Use a borderless player surface, native Segoe UI typography, slim neutral timelines and quiet source buttons. Preserve keyboard focus indicators, seek behavior and full metadata in tooltips.
- Use normal desktop transport buttons, elapsed/total timeline, volume control and an explicit Lyrics toggle. Avoid a phone widget silhouette.
- Player buttons switch actual sessions; all sessions remain accessible through the player selector.
- Keyboard focus must remain visible. Icon controls need accessible names and tooltips. Unsupported actions stay hidden or disabled.

## Settings

- No emoji in labels, descriptions or navigation. Use plain names and explain actual behavior.
- Preserve existing settings and all seven original themes. Charcoal, Sage and Slate are additional flat, muted presets.
- Appearance separates six layout themes (Classic / Minimal / Soft / Flat / Paper / Instrument), mode (Dark / Light / Follow Windows) and color palette. Keep style, display, dimensions, corner radius and offset controls. Music controls artwork tint and session buttons.
- Layout themes change arrangements, not just color: Classic balances columns; Minimal uses a narrow summary/player column, smaller artwork and flat surfaces; Soft places notes beside the clock and uses rounded cards. Music always keeps the player on the left and lyrics on the right across all themes. Apply surface treatment and page spacing across the panel. Show a small Home arrangement preview in Settings because the main panel collapses while Settings is open.
- Flat borrows alignment and low visual noise from Linear: divider lines, underline tabs and thin controls. Paper borrows Things' reading-focused treatment: an open page, serif clock, text actions and plain editors. Instrument borrows Ableton's functional controls: header strips, fixed-width readings and segmented meters. These designs change controls and surfaces, with reversible authored styles; do not reduce them to card reordering.
- The Home preview is an arrangement editor: drag sections with a visible preview and drop target, or move the focused section with Alt + arrows. Keep all four sections present, retain a separate order per design, and reset only the selected design. Preview live, save on Done, cancel on close. Rearranging must preserve the actual editors, playback and shelf content.
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
