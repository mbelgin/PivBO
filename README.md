# PivBO — PivotBreakout

A bar-by-bar trading simulator for studying momentum setups on historical
US equity data. Runs entirely on your own machine, offline. No account,
no subscription, no data sent to the cloud.

Built for traders who want to replay charts one bar at a time, place
trades, manage positions, and evaluate their edge — including head-to-head
against a friend in Duel Mode.

## Download and install

Pick the file for your operating system from the [latest release][rel]:

- **Windows** — `PivBO-windows.zip`
- **macOS** — `PivBO-macos.zip`
- **Linux** — `PivBO-x86_64.AppImage`

Each download is a self-contained bundle. No Python, no terminal, no
separate installer.

[rel]: https://github.com/mbelgin/PivBO/releases/latest

### Windows

1. Download `PivBO-windows.zip`.
2. Right-click the zip → **Extract All** to any folder (Desktop, Documents, a USB stick — it doesn't matter).
3. Open the extracted folder, double-click **`PivBO.exe`**.
4. The first time you run it, Windows may show a blue "Windows protected
   your PC" screen. Click **More info**, then **Run anyway**. This only
   happens the first time.
5. A small PivBO window opens and your browser launches the app at
   `http://localhost:5051/`.

To uninstall, just delete the extracted folder.

### macOS

1. Download `PivBO-macos.zip`.
2. Double-click to unzip (Finder does this automatically).
3. Drag **PivBO.app** into your **Applications** folder (or leave it in
   Downloads — it runs from anywhere).
4. The first time you launch it, macOS will say "PivBO cannot be
   opened because the developer cannot be verified." Close that dialog,
   then **right-click** (or Control-click) PivBO → **Open** → **Open**
   in the confirmation dialog. This only happens the first time.
5. The app window opens and your browser launches the interface.

### Linux

1. Download `PivBO-x86_64.AppImage`.
2. Make it executable:
   - In your file manager: right-click → **Properties** → **Permissions**
     → tick **Allow executing as program**.
   - Or in a terminal: `chmod +x PivBO-x86_64.AppImage`.
3. Double-click (or `./PivBO-x86_64.AppImage` in a terminal).

## First-launch setup

On the very first launch, PivBO fetches a bundle of historical chart
data for ~930 US tickers. You'll see a small **"One-time Download"**
banner at the top of the interface showing progress. You can use the
app normally while it runs — tickers become available as each file
lands. The download is a few minutes on a typical connection.

The data is stored per user:
- **Windows**: `%APPDATA%\PivBO\`
- **macOS**: `~/Library/Application Support/PivBO/`
- **Linux**: `~/.local/share/PivBO/`

Re-installing or upgrading never touches this folder. Any tickers
you've downloaded additional history for are preserved.

## What's inside

**Charting**
- Candlestick + OHLC, daily / weekly / monthly timeframes
- Configurable EMA / SMA overlays (add, remove, color)
- ADR(x), ATR(x) in the crosshair info bar (editable periods)
- Log / linear price scale
- Drawing tools: horizontal line, line, ray, segment, text, measure, note
- Optional secondary chart above the main one, date-synced (e.g. QQQ
  overlay while you trade an individual name)
- Optional volume pane
- Optional equity curve pane during simulations

**Simulation engine**
- Bar-by-bar playback with arrow keys: `→` advances, `←` retreats
- Jump to start / end
- Retreating past a trade's creation bar permanently undoes it
- Stop-loss fill logic matches real brokers: strict touch of the bar's
  low/high triggers, filling at SL or at the open on a gap
- Optional "Flex open-bar SL" for same-bar entries, so an unrealistic
  fill can't appear when a bar opens past SL, rallies to trigger entry,
  and closes above SL

**Trade management**
- Market and limit orders (limits can carry a max-gap%, stop-limit style)
- Drag-to-adjust stop loss on the chart
- Partial close via quick fractions (¼, ⅓, ½, ¾, ALL) or manual shares
- Flatten all (`F`), reverse position
- Position sizing from risk% of current equity, shares auto-computed
- R-multiples use the risk frozen at entry — moving your SL later
  doesn't skew your stats

**Analytics**
- Realized / unrealized / total P/L in $, % of starting capital, and R
- Batting average, average win, average loss, total R
- Per-trade cards with indexed + dated entries and exits
- HTML + PDF analysis and compare reports

**Saved simulations**
- One JSON per sim, browsable from the Simulations page
- Rename, duplicate, bulk delete, export to ZIP, import from ZIP
- Templates: save a chart/indicator/secondary-chart layout as a preset
  for new simulations

**Duel Mode (1v1, remote)**
- Enter the same duel with a friend on their own machine
- Both players see the same ticker at the same bar
- Per-bar decision timer, honor code, live opponent equity curve
- Post-duel compare report with both sides' stats

**Data**
- Local compressed CSVs, auto-populated on first launch
- Yahoo Finance download integration for fetching / updating individual
  tickers from inside the app

## Stopping the app

- **Windows / macOS**: close the PivBO launcher window (it'll stop the
  server cleanly).
- **Linux AppImage**: close the launcher window or the terminal you
  ran it from.

If you close only the browser tab, the app is still running in the
background — you can reopen it at `http://localhost:5051/` anytime.

## Reporting bugs / requesting features

Open an issue on [github.com/mbelgin/PivBO/issues][iss]. Include:

- Your OS (Windows / macOS / Linux version)
- What you were trying to do
- What happened instead
- A screenshot if the bug is visual

[iss]: https://github.com/mbelgin/PivBO/issues

## Acknowledgments

Inspired by and originally forked from
**[big_movers](https://github.com/willhjw/big_movers)** by Will Hu — a
self-hosted charting tool built around the Qullamaggie breakout
methodology. PivBO grew from that foundation into a full
trading-practice platform.

Charts are rendered with
[TradingView's lightweight-charts](https://github.com/tradingview/lightweight-charts).
Duel Mode relies on the public
[HiveMQ](https://www.hivemq.com/mqtt/public-mqtt-broker/) MQTT broker
for peer-to-peer messaging.

## Disclaimer

This is a simulator. Historical results are not predictive of live
outcomes. Data may be incomplete or inaccurate; verify independently
before making any actual trading decisions.

## License

MIT. See [LICENSE](LICENSE).
