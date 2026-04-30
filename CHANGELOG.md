# PivBO release notes

Curated user-facing release notes for each tagged version. The auto-generated
GitHub Release body is the download-link page; this file is the durable
human-readable history that lives in the repo.

The newest version is at the top.

## Unreleased

- **Pinned start date in Surprise Me**. Optional date input under the
  Surprise filters. Leave it blank for the existing behavior (random
  start within the eligible window). Set it and the simulation pins to
  the first bar on or after that date for a randomly chosen ticker that
  has enough warmup before AND the requested years of history after.
  Start button auto-disables with an inline message when start date plus
  min years exceeds today.
- **Auto-uncheck "Use first available bar"** in Pick a Ticker mode when
  the user picks a date in the calendar. Removes the gotcha where the
  picked date was silently ignored because the checkbox stayed on.
- **Secondary chart vertical pan, restored**. Click-drag the chart body
  up or down on chart2 to shift the visible price range. Horizontal
  position stays locked to the main chart. Works in BOTH chart view and
  sim mode (was previously regressed when an unrelated bug masked itself
  as a pan issue).
- **Fix: cold launch no longer auto-restores the last simulation**. Boot
  used to fall back to `localStorage.bm_active_sim_id` when no
  sessionStorage entry was present, silently re-loading whichever sim was
  active when you last closed the app. The result: the app appeared to
  open in chart view but was actually mid-sim — equity pane visible,
  left-pane ticker list hidden by `sim-active`, sim panel populated. Now
  cold launches always land on the home page; only an in-tab refresh
  (sessionStorage survives `Ctrl+R`, dies on tab close) resumes the
  active sim. Pick a saved sim from the Simulations list to resume after
  reopening the app.
- **Fix: Ctrl+F no longer hijacked into "Flatten all"**. The sim playback
  shortcut for `F` (flatten open positions) was matching on the bare key
  even when Ctrl, Cmd, or Alt was held, so Ctrl+F (browser find-in-page)
  triggered a flatten attempt and the "No open positions" toast in places
  like the Saved Simulations analysis view. Same applied to `N` (new
  trade) vs Ctrl+N. Both shortcuts now require no modifiers.
- **Arrow drawing tool, properly bounded with a visible tip**. The toolbar's
  arrow tool (Alt+R) used to draw an unbounded ray that extended several
  screen-widths past the second click, putting the tip far off-screen so
  the arrow looked like a plain line going nowhere. Now it draws a regular
  bounded arrow from the first click to the second, with a filled
  arrowhead at the tip. The "Extended Line" tool (Alt+A) still extends in
  both directions for trend-line use.
- **Fix: fullscreen teal flash during sim load**. The "Start Simulation"
  button briefly bloated to cover the entire viewport in solid accent
  color while the data fetch was in flight. Caused by the button's
  loading-state class colliding with an unrelated bare `.loading` rule
  intended for the chart-data overlay (`position:absolute; inset:0; ...`).
  The rule is now scoped to its actual target so only the chart overlay
  gets it; buttons keep their native size when entering loading state.
- **Fix: secondary chart bars not rendering in Chart view**. Picking a
  ticker on the main chart updated the main view but never refreshed the
  secondary, so the secondary stayed frozen on stale or empty data. Sim
  mode wasn't affected because the per-bar advance path already re-aligns
  the secondary on every step. Chart view now does the same after a
  ticker pick.

## v0.0.4 (2026-04-26)

- **Compare report: dual-R sections**. Side-by-side Adjusted R and Simple R
  blocks with the same metrics (Total / Expectancy / Profit Factor / Max
  Drawdown / Sharpe per trade / Max win-loss). Equal column widths across
  any number of sims, no editorial star markers on either mode.
- **Compare report: hover legend**. Crossing the cursor over the equity
  chart shows a per-sim chip with color swatch, sim name, trade index,
  equity dollars, and signed P/L for that point. Up to 5 sims; chips
  flex-wrap on narrow widths.
- **Compare report: Export dropdown** with PDF / CSV / JSON, matching the
  Analysis report. CSV emits section header rows and rounds numeric
  values to 2 decimals; JSON is the same shape the HTML and PDF
  renderers consume.
- **Compare equity curves by trade index**. Sims of different durations no
  longer get visually compressed into a small slice of the chart. The
  x-axis is now trade index (0 = start, 1 = after first trade, ...) so
  curve shapes are directly comparable. PDF and HTML both updated.
- **Linux AppImage with embedded icon**. The AppImage now bundles the
  PivBO icon at standard sizes so desktop launchers and taskbars show
  the right artwork instead of a generic AppImage placeholder. Website
  Linux tile re-enabled with a direct download link.
- **Limit-order retreat un-fill**. When a limit order placed at bar A
  filled at bar F, retreating past F used to drop the trade entirely.
  Now: retreating into the [A, F) window restores the trade to the
  pending order it filled from, so the user sees the same waiting-to-
  fill state they had at that point in the original timeline. Past A,
  the order finally disappears.
- **Equity-pane hover tooltip**. Move the cursor over the equity curve
  to see the equity value at any past trade point with a vertical
  guideline + small floating tip showing $value and signed delta from
  starting capital. No persistent UI; tip and line hide on mouseleave.
- **Compact CAPITAL / STATISTICS sections** in the sim right rail.
  Tighter padding, smaller h3 + value font, denser row gap. About a
  third more vertical room for the trade-history list on laptop
  screens, no fields dropped.
- **Max DD from peak** added to the Statistics box. Reports both the
  percentage drop from the running max and the dollar amount, e.g.
  "-12.3% (-$1,230)".
- **Open trades highlighted in the trade history**. A 3px accent-color
  left border + subtle accent-tinted background mark open trades so
  they stand out from the closed-trade scroll.
- **Dual-R analysis reports**. The HTML analysis report now shows
  Adjusted and Simple R aggregates side by side (Total / Expectancy
  per trade / Profit factor / Max win / Max loss), and the Trade Log
  table gets a second R column. Both modes are computed for every
  trade regardless of the user's display preference.
- **adjR / R live UI labels** that follow the user's chosen R-multiple
  display mode. Adjusted: "Total adjR", "5.2adjR". Simple: "Total R",
  "5.2R". On-chart R-level lines (1R / 2R / 3R) intentionally stay
  plain "R" since they mark price levels, not P/L attributions.
- **Collapsible right-rail sections**. Capital / Statistics / Notes
  each get a chevron-prefixed clickable header; click toggles the
  section closed or open. Collapsed state persists per section in
  localStorage. Trade form and trade history are intentionally NOT
  collapsible — they're always-on workflow surfaces.
- **Self-healing Mark-of-the-Web on Windows launch**. The pythonnet
  `Failed to resolve Python.Runtime.Loader.Initialize` crash that hit
  some Windows users (winget OR direct download) was caused by
  Zone.Identifier ADS on the bundled `Python.Runtime.dll`. The launcher
  now strips Zone.Identifier from every bundled `.dll/.pyd/.exe`
  early in `__main__.py`, before any import transitively pulls in
  pythonnet. Equivalent of running `Get-ChildItem ... | Unblock-File`
  on the install dir but happens automatically on every launch. No-op
  on macOS/Linux. Becomes a cheap defensive no-op once SignPath signing
  ships.
- **Listen-on-LAN preference in the web UI**. Already exposed in the
  desktop launcher window; now also a toggle in Preferences → Server,
  marked "(takes effect after restart)." Same underlying pref key
  (`listenOnLan`), so toggling it in the web UI lights up the launcher's
  switch on next launch and vice versa.
- **Flex open-bar SL default in Preferences → Trading**. New checkbox
  pre-sets the New Simulation modal's "Flexed opening-bar SL" each time
  it opens. Per-sim override still works.
- **Stop Server button removed from Preferences → Server**. It was a
  one-way trip with no path back from a closed browser tab. Use the
  launcher's own Stop / Start, or Quit-App to shut down the whole stack.
- **MA-driven stop-loss as an exit strategy**. New `SL→MA` row in the
  open-trade card (under the existing SL row): pick a period, SMA or EMA,
  and an unsigned tolerance %. Click Apply and the trade's SL value is
  re-evaluated each bar against the chosen MA, with the tolerance applied
  in whichever direction hurts the trade. The existing red SL line on the
  chart tracks the MA value bar-by-bar; no separate overlay is drawn (add
  the MA as a regular indicator if you want to see it). Apply disables
  with a why-tooltip when the prospective level would instantly stop the
  trade. Last-used period / type / tolerance persist across trades and
  sessions. Manual Set or B/E reverts the trade to fixed-price SL. R is
  unaffected — still anchored to initial risk frozen at entry.
- **Close-only checkbox on SL→MA row**. Optional. When checked, a bar
  that wicks past the MA-driven SL but closes back on the right side
  does NOT stop the trade. The stop fires only on a close past the SL,
  exiting at that close price. Useful for trend-following exits that
  shouldn't react to noise wicks into the average. Persists with the
  trade and as a last-used preference. Re-Apply commits a change.
- **R-multiple display mode preference (Adjusted vs Simple)**. Preferences →
  Trading → "R-multiple display." Adjusted (default) is today's behavior:
  total realized $ P/L ÷ initial $ risk, partial closes weighted by share
  fraction, reflects actual money. Simple is the new mode: per-share R at
  the trade's final exit price, independent of partial-close timing or
  sizing, reflects "the R the setup ran to." Both modes always pin the
  denominator to the initial risk so SL movement never affects R.
- **"Update now" button on the update banner**. The banner that appears at
  launch when a newer version is available now has a prominent yellow CTA
  button that links straight to the GitHub release page, alongside the
  existing dismiss button.
- **Updates preferences moved to About tab** (was under Management). The
  About panel is the natural home for version/update settings.
- **Min-price filter for Surprise Me**. New "Min price ($)" input on the
  New Simulation modal in Surprise Me mode, default $5. Filters out penny
  stocks at the chosen start bar (per-bar check, not ticker-wide, because
  a ticker may have been a penny stock years ago and a $50 stock today).
- **Window-resize fix**. Dragging the OS window taller now correctly grows
  the chart back to fill the available space. Previously the chart would
  shrink when the window shrank but stay small when the window grew back,
  because `.main`'s grid row was content-sized. Adding
  `grid-template-rows: minmax(0, 1fr)` lets the chart container actually
  fill the row.
- **eq-pane resize handle fix**. Same root cause as the window-resize bug.
  The handle now drags cleanly: top edge follows the cursor, bottom edge
  stays anchored at the window bottom, chart-wrap absorbs the difference.

## v0.0.3 (2026-04-25)

- **Listen on local network** switch in the launcher window. Toggle binds
  the Waitress server to `0.0.0.0` instead of `127.0.0.1`, exposing PivBO
  to other devices on the same Wi-Fi. The status bar shows both the
  loopback URL and the auto-detected LAN address. Choice persists in
  `preferences.json`. Caution line warns against enabling on public Wi-Fi.
- **Working in-app update check**. `/api/updates/check` now actually
  queries the GitHub Releases API and compares the installed version to
  the latest published tag. Cached for 10 minutes to avoid hammering
  GitHub. The Preferences → Updates → "Check for updates now" button
  surfaces real results. A "Check on launch" toggle silently runs the
  same check at startup and shows a small yellow banner if a newer
  version is available.
- **Launcher window controls left-aligned**. Cosmetic but matches typical
  Windows control-panel layouts better than the prior centered layout.
- **Subtitle reads "Open Source bar-by-bar trading simulator"** instead
  of just "bar-by-bar trading simulator."
- **Gear icon on the landing page** for direct access to Preferences
  without navigating into the Chart view first.
- **Linux AppImage now bundles the GTK3 runtime**. Previous releases
  built but crashed at startup on user systems with "Namespace Gdk not
  available." `linuxdeploy_plugins = ["DEPLOY_GTK_VERSION=3 gtk"]` and a
  `travertino<0.5` pin in `pyproject.toml` make the AppImage portable.
- Source `__version__` no longer drifts from released tags.
  `pivbo/__init__.py` is now bumped after each release tag and committed,
  so dev runs (`python pivbo_server.py` from source) report the same
  version a winget user sees.

## v0.0.2 (earlier 2026-04)

- macOS universal2 build (Intel + Apple Silicon, single zip).
- Windows winget catalog entry: `winget install PivBO`.
- Path-resolution fix for symlink/alias launches (winget portable shim,
  homebrew alias). Server now uses `os.path.realpath(__file__)` and
  changes CWD to the install root on startup so resources load even when
  the launcher exe is invoked through a shim.
- Per-sim Notes field, skip-to-MA start option, vol-pane value fixes.

## v0.0.1 (initial release)

- Bar-by-bar simulator on historical US equities.
- Drag-to-adjust stops, partial closes via fraction buttons, R-multiples
  with risk frozen at entry.
- 1v1 Duel Mode over public MQTT.
- Saved sims with rename / duplicate / delete / export / import.
- Analysis and Compare reports with PDF export.
- Templates for chart layouts.
- Yahoo Finance ticker download integration.
- Direct download as portable zip for Windows / macOS, AppImage for Linux.
