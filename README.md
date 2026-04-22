# PivotBreakout (PivBo)

_Formerly known as Momentum Trading Simulator._

A self-hosted, bar-by-bar trading simulator for studying momentum setups on
historical US equity data. Runs entirely on your own machine, offline.

Built for traders who want to replay charts one bar at a time, place trades,
manage positions, and evaluate their edge — without paying for a platform,
subscribing to data, or sending any activity to the cloud.

## Features

**Charting**
- Candlestick + OHLC modes, daily / weekly / monthly timeframes
- Configurable EMA / SMA overlays
- ADR(x) and ATR(x) indicators in the crosshair info bar (editable periods)
- Log / linear price scale
- Drawing tools: h-line, line, ray, segment, text, measure, note
- Optional secondary chart above the main chart, date-synced (e.g. overlay
  QQQ on your trade ticker for market context)

**Simulation engine**
- Bar-by-bar playback with arrow keys (`←` / `→`)
- Jump to start / end
- Retreating past a trade's creation bar permanently undoes it
- Stop-loss fill: strict touch of the bar's low/high (long/short) triggers
  the stop, filling at SL or at the open if the bar gapped past SL
- Optional "Flexed opening-bar SL" toggle: on the bar a trade enters,
  only the bar's close is used to check SL and any fill is capped at SL —
  prevents impossible fills when the bar opens past SL, rallies to trigger
  your entry, dips back, then closes above SL

**Trade management**
- Market + limit orders (limit orders can have a max gap%; stop-limit behavior)
- Stop loss with drag-to-adjust on the chart (pre-entry)
- Partial close via quick fractions (1/4, 1/3, 1/2, 3/4, ALL) or manual shares
- Reverse position, flatten all (`F`)
- Position sizing from risk% of current equity (auto-computes shares)
- R-multiple stats use the risk frozen at entry (immune to SL moves)

**Analytics**
- Realized / unrealized / total P/L in $, % of starting capital, and R
- Batting average, average win, average loss, total R
- Trade history with indexed + dated cards

**Saved simulations**
- JSON file per simulation in `simulations/`
- Rename, Save As (duplicate), bulk delete, bulk export (ZIP), import
- Templates: save current chart/indicator/secondary-chart config as a reusable
  preset for new simulations

**Data**
- Local daily CSVs in `collected_stocks/`
- Optional Yahoo Finance download integration for fetching / updating tickers

## Quickstart

This guide assumes you've never used a terminal before. Follow it line by line.

### 1. Install the two tools you need

You only need to do this once.

1. **Python** (version 3.9 or newer): download and install from
   [python.org/downloads](https://www.python.org/downloads/). On Windows, during
   the install, tick the box that says **"Add Python to PATH"**.
2. **Git**: download and install from
   [git-scm.com/downloads](https://git-scm.com/downloads). Accept all the
   default settings.

### 2. Open a terminal

- **Windows**: press the Windows key, type `cmd`, press Enter.
- **macOS**: press `Cmd + Space`, type `Terminal`, press Enter.
- **Linux**: you already know.

A black (or white) window opens with a blinking cursor. This is where you
type commands. Each line below is one command: type it, then press Enter.

### 3. First time only: download the project

Pick a folder where the project will live, for example your Documents folder.
Change into it:

```bash
cd Documents
```

Then download the project:

```bash
git clone https://bitbucket.org/mbelgin/momentum_trading_simulator.git pivbo
cd pivbo
```

You now have a new folder called `pivbo` with all the code inside.

### 4. Install the project's dependencies

Still in the terminal, still inside the project folder, run:

```bash
pip install -r requirements.txt
```

This downloads the few Python packages the simulator uses. You only need to
do this once (and again if `requirements.txt` ever changes).

### 5. Run the simulator

```bash
python pivbo_server.py
```

Leave this terminal window open. Now open your web browser and go to:

```
http://localhost:5051/
```

That's it. You can start clicking around.

To stop the server, click back into the terminal window and press `Ctrl + C`.

### Coming back later (updating to the latest version)

Next time you want to run the simulator, open your terminal and:

```bash
cd Documents/pivbo
git pull
pip install -r requirements.txt
python pivbo_server.py
```

`git pull` downloads any updates since you last ran it. The
`pip install -r requirements.txt` line is only needed if dependencies
changed (running it when nothing changed is harmless).

## Data format

Stock CSVs live in `collected_stocks/`. Each file is named `{SYMBOL}.csv`.
The server supports a couple of column layouts; the Yahoo downloader writes
a consistent format:

```
index,date,open,high,low,close,volume
0,2020-01-02,74.06,75.15,73.80,75.09,135480400
...
```

Add your own CSVs directly to `collected_stocks/`, or use the in-app Yahoo
downloader (⬇ Data button on the chart) to fetch/update.

## Acknowledgments

This project was inspired by and started as a fork of
**[big_movers](https://github.com/willhjw/big_movers)** by Will Hu — a
self-hosted charting tool built around the Qullamaggie breakout methodology.
The simulator grew from that foundation into a full trading-practice
platform: bar-by-bar playback, order types, trade management, analytics,
persistence, templates, and date-synced multi-chart layouts.

Charts are rendered with [TradingView's lightweight-charts](https://github.com/tradingview/lightweight-charts) (v3.8).

## Disclaimer

This is a simulator. Historical results are not predictive of live outcomes.
Data may be incomplete or inaccurate; verify independently before making any
actual trading decisions.

## License

MIT. See [LICENSE](LICENSE).
