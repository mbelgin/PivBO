# PivBO release notes

Curated user-facing release notes for each tagged version. The auto-generated
GitHub Release body is the download-link page; this file is the durable
human-readable history that lives in the repo.

The newest version is at the top.

## Unreleased

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
