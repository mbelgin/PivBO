# Momentum Trading Simulator

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
- Drawings persist per-simulation (not leaked to global state)
- Optional secondary chart above the main chart, date-synced (e.g. overlay
  SPY on your trade ticker for market context)

**Simulation engine**
- Bar-by-bar playback with arrow keys (`←` / `→`)
- Jump to start / end
- Retreating past a trade's creation bar permanently undoes it
- Configurable stop-loss fill mode per simulation:
  - Strict (default) — any intrabar touch of SL triggers stop
  - Wick-forgiving — only stops if open or close crosses SL
  - Close-only — stops only if the bar closes past SL

**Trade management**
- Market + limit orders (limit orders can have a max gap%; stop-limit behavior)
- Stop loss with drag-to-adjust on the chart
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
- SPY benchmark overlay

## Quickstart

Requires Python 3.9+.

```bash
pip install -r requirements.txt
python momentum_trading_simulator_server.py
# open http://localhost:5051/
```

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
