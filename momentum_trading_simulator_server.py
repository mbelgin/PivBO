#!/usr/bin/env python3
# Momentum Trading Simulator — local Flask server
# Usage: python momentum_trading_simulator_server.py
# Then open http://localhost:5051/ in browser

import csv
import io
import os
import json
import sys
import uuid
import zipfile
import threading
import time
import signal
import socket
import subprocess
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from flask import Flask, jsonify, send_from_directory, request, Response, send_file

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=SCRIPT_DIR, static_url_path="")

# Path configuration
STOCKS_DIRS = [
    os.path.join(SCRIPT_DIR, "collected_stocks"),
]

# SPY benchmark data source (UI "VS" overlay)
SPY_HIST_CSV = os.path.join(SCRIPT_DIR, "SPY Historical Data.csv")
_SPY_BARS_CACHE = None

# Simulation storage
SIMULATIONS_DIR = os.path.join(SCRIPT_DIR, "simulations")
TEMPLATES_DIR = os.path.join(SCRIPT_DIR, "templates")
ANALYSES_DIR = os.path.join(SCRIPT_DIR, "analyses")
_TICKER_RANGES_CACHE = None

def _normalize_date_maybe(raw):
    s = str(raw or "").strip()
    if not s:
        return ""
    # Already ISO-like
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    # MM/DD/YYYY -> YYYY-MM-DD
    if len(s) >= 10 and s[2] == "/" and s[5] == "/":
        mm = s[0:2]
        dd = s[3:5]
        yyyy = s[6:10]
        if mm.isdigit() and dd.isdigit() and yyyy.isdigit():
            return f"{yyyy}-{mm}-{dd}"
    return s

def _parse_float_maybe(x):
    try:
        if x is None:
            return None
        s = str(x).strip()
        if not s:
            return None
        # tolerate thousands separators
        s = s.replace(",", "")
        v = float(s)
        return v
    except (ValueError, TypeError):
        return None

def _parse_volume_maybe(x):
    """
    Parse volume like:
    - 52.00M
    - 1.23B
    - 450K
    - plain numeric
    """
    try:
        if x is None:
            return 0.0
        s = str(x).strip()
        if not s:
            return 0.0
        s = s.replace(",", "")
        if s.lower() == "nan":
            return 0.0

        mult = 1.0
        last = s[-1].upper()
        if last == "M":
            mult = 1e6
            s = s[:-1]
        elif last == "B":
            mult = 1e9
            s = s[:-1]
        elif last == "K":
            mult = 1e3
            s = s[:-1]

        v = float(s)
        return v * mult
    except (ValueError, TypeError):
        return 0.0

def _load_spy_bars():
    global _SPY_BARS_CACHE
    if _SPY_BARS_CACHE is not None:
        return _SPY_BARS_CACHE

    if not os.path.exists(SPY_HIST_CSV):
        _SPY_BARS_CACHE = []
        return _SPY_BARS_CACHE

    bars = []
    try:
        with open(SPY_HIST_CSV, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Support both:
                # - Date, Price, Open, High, Low, Vol.
                # - DateTime, Open, High, Low, Close, Volume
                raw_date = row.get("Date") or row.get("DateTime")
                date_str = _normalize_date_maybe(raw_date)
                if not date_str:
                    continue
                o = _parse_float_maybe(row.get("Open"))
                h = _parse_float_maybe(row.get("High"))
                l = _parse_float_maybe(row.get("Low"))
                c = _parse_float_maybe(row.get("Close"))
                if c is None:
                    c = _parse_float_maybe(row.get("Price"))
                v = _parse_volume_maybe(row.get("Volume"))
                if not v:
                    v = _parse_volume_maybe(row.get("Vol."))
                if c is None or c <= 0:
                    continue
                if o is None or h is None or l is None:
                    continue
                bars.append({
                    "time": date_str,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": v,
                })
    except Exception:
        bars = []

    bars.sort(key=lambda x: x.get("time") or "")
    _SPY_BARS_CACHE = bars
    return _SPY_BARS_CACHE


def _resolve_index_html_path():
    for name in ("momentum_trading_simulator.html",):
        p = os.path.join(SCRIPT_DIR, name)
        if os.path.exists(p):
            return p
    return None


@app.route("/")
def index():
    html_path = _resolve_index_html_path()
    if not html_path:
        return f"momentum_trading_simulator.html not found in {SCRIPT_DIR}", 404
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()
    return Response(content, mimetype="text/html")


@app.route("/api/ohlcv")
def api_ohlcv():
    symbol = (request.args.get("symbol") or "").strip().upper()
    if not symbol:
        return jsonify({"error": "symbol required"}), 400

    # Special-case SPY: serve from SPY Historical Data.csv
    if symbol == "SPY":
        try:
            return jsonify(_load_spy_bars())
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # Search configured directories
    path = None
    for d in STOCKS_DIRS:
        for fname in [f"{symbol}.csv", f"{symbol.lower()}.csv"]:
            c = os.path.join(d, fname)
            if os.path.exists(c):
                path = c
                break
        if path:
            break

    if not path:
        return jsonify({"error": f"{symbol}.csv not found in any configured directory"}), 404

    bars = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                return jsonify([])
            # Detect CSV column layout
            if len(header) >= 2 and "date" in (header[1] or "").lower():
                fmt = "new"
            elif len(header) >= 1 and "date" in (header[0] or "").lower():
                fmt = "noindex"
            else:
                fmt = "old"
            for row in reader:
                try:
                    if fmt == "new":
                        # [idx, date, open, high, low, close, volume]
                        if len(row) < 7:
                            continue
                        t = row[1].strip()
                        o = float(row[2])
                        h = float(row[3])
                        l = float(row[4])
                        c = float(row[5])
                        v = float(row[6])
                    elif fmt == "noindex":
                        # [DateTime, Open, High, Low, Close, Volume]
                        if len(row) < 6:
                            continue
                        raw_t = row[0].strip()
                        if len(raw_t) == 10 and raw_t[2] == '/':
                            parts = raw_t.split('/')
                            t = f"{parts[2]}-{parts[0]:>02}-{parts[1]:>02}"
                        else:
                            t = raw_t
                        o = float(row[1])
                        h = float(row[2])
                        l = float(row[3])
                        c = float(row[4])
                        v = float(row[5])
                    else:
                        # [date, close, open, high, low, volume, ...]
                        if len(row) < 6:
                            continue
                        t = row[0].strip()
                        c = float(row[1])
                        o = float(row[2])
                        h = float(row[3])
                        l = float(row[4])
                        v = float(row[5])
                    if c <= 0:
                        continue
                    bars.append({"time": t, "open": o, "high": h, "low": l, "close": c, "volume": v})
                except (ValueError, IndexError):
                    continue
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    bars.sort(key=lambda x: x["time"])
    return jsonify(bars)


DRAWINGS_FILE = os.path.join(SCRIPT_DIR, "drawings.json")


@app.route("/api/drawings", methods=["GET", "POST"])
def api_drawings():
    if request.method == "GET":
        if not os.path.exists(DRAWINGS_FILE):
            return jsonify({})
        try:
            with open(DRAWINGS_FILE, "r", encoding="utf-8") as f:
                return jsonify(json.load(f))
        except Exception:
            return jsonify({})
    else:
        try:
            data = request.get_json(silent=True) or {}
            with open(DRAWINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500


# ==============================================
# TICKER RANGES
# ==============================================

def _load_ticker_ranges():
    global _TICKER_RANGES_CACHE
    if _TICKER_RANGES_CACHE is not None:
        return _TICKER_RANGES_CACHE

    ranges = {}
    for d in STOCKS_DIRS:
        if not os.path.isdir(d):
            continue
        for fname in os.listdir(d):
            if not fname.lower().endswith(".csv"):
                continue
            symbol = fname[:-4].upper()
            fpath = os.path.join(d, fname)
            try:
                first_date = None
                last_date = None
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    reader = csv.reader(f)
                    header = next(reader, None)
                    if not header:
                        continue
                    date_col = 1 if (len(header) >= 2 and "date" in (header[1] or "").lower()) else 0
                    for row in reader:
                        if len(row) <= date_col:
                            continue
                        dt = row[date_col].strip()
                        if not dt or len(dt) < 10:
                            continue
                        if first_date is None:
                            first_date = dt
                        last_date = dt
                if first_date and last_date:
                    ranges[symbol] = {"from": first_date[:10], "to": last_date[:10]}
            except Exception:
                continue

    _TICKER_RANGES_CACHE = ranges
    return _TICKER_RANGES_CACHE


@app.route("/api/ticker-ranges")
def api_ticker_ranges():
    if request.args.get("refresh"):
        global _TICKER_RANGES_CACHE
        _TICKER_RANGES_CACHE = None
    return jsonify(_load_ticker_ranges())


# ==============================================
# SIMULATIONS CRUD
# ==============================================

def _ensure_sim_dir():
    os.makedirs(SIMULATIONS_DIR, exist_ok=True)


def _sim_path(sim_id):
    return os.path.join(SIMULATIONS_DIR, f"{sim_id}.json")


def _load_sim_index():
    idx_path = os.path.join(SIMULATIONS_DIR, "index.json")
    if not os.path.exists(idx_path):
        return []
    try:
        with open(idx_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_sim_index(index):
    _ensure_sim_dir()
    idx_path = os.path.join(SIMULATIONS_DIR, "index.json")
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def _rebuild_sim_index():
    _ensure_sim_dir()
    index = []
    for fname in os.listdir(SIMULATIONS_DIR):
        if fname == "index.json" or not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(SIMULATIONS_DIR, fname), "r", encoding="utf-8") as f:
                sim = json.load(f)
            # Compute sim progress %
            cfg = sim.get("config") or {}
            ps = sim.get("playbackState") or {}
            cur_idx = ps.get("currentBarIndex", 0)
            is_complete = ps.get("isComplete", False)
            ticker = sim.get("ticker", "")
            bars = _read_ticker_bars(ticker) if ticker else []
            total = len(bars)
            start_idx = 0
            start_date = cfg.get("startDate")
            if start_date and not cfg.get("useFirstBar", True):
                for i, b in enumerate(bars):
                    if b.get("time", "") >= start_date:
                        start_idx = i
                        break
            sim_len = max(1, total - start_idx)
            progress = 100.0 if is_complete else min(100.0, max(0.0, (cur_idx - start_idx) / (sim_len - 1) * 100)) if sim_len > 1 else 100.0

            # Resolved bar dates for display — start bar is what the user
            # actually picked (or the first available bar); end is the last
            # bar in the ticker's data; currentBarDate is where an in-progress
            # sim is currently paused.
            start_date_resolved = bars[start_idx].get("time", "") if bars and 0 <= start_idx < total else ""
            end_date_resolved = bars[-1].get("time", "") if bars else ""
            cur_date_resolved = bars[cur_idx].get("time", "") if bars and 0 <= cur_idx < total else ""

            # Check analysis cache status
            cache_path = os.path.join(ANALYSES_DIR, f"{sim.get('id', fname[:-5])}.json")
            has_cache = os.path.exists(cache_path)
            cache_gen = None
            if has_cache:
                try:
                    with open(cache_path, "r", encoding="utf-8") as cf:
                        cache_gen = json.load(cf).get("generatedAt")
                except Exception:
                    pass
            last_opened = sim.get("lastOpenedAt", "")
            is_stale = bool(has_cache) and bool(last_opened) and cache_gen and cache_gen < last_opened

            index.append({
                "id": sim.get("id", fname[:-5]),
                "name": sim.get("name", ""),
                "ticker": sim.get("ticker", ""),
                "created": sim.get("created", ""),
                "modified": sim.get("modified", ""),
                "lastOpenedAt": last_opened,
                "startingCapital": sim.get("config", {}).get("startingCapital", 0),
                "currentCapital": sim.get("analytics", {}).get("currentCapital", 0),
                "totalTrades": sim.get("analytics", {}).get("totalTrades", 0),
                "isComplete": is_complete,
                "progress": round(progress, 1),
                "startDate": start_date_resolved,
                "endDate": end_date_resolved,
                "currentBarDate": cur_date_resolved,
                "hasAnalysis": has_cache,
                "analysisStale": is_stale,
            })
        except Exception:
            continue
    index.sort(key=lambda x: x.get("modified", ""), reverse=True)
    _save_sim_index(index)
    return index


@app.route("/api/simulations", methods=["GET"])
def api_simulations_list():
    _ensure_sim_dir()
    index = _load_sim_index()
    if not index or any("hasAnalysis" not in e or "startDate" not in e for e in index):
        index = _rebuild_sim_index()
    # Refresh analysis-cache status on every read (cheap file-stat check).
    # Without this the list stays stale until the next sim write.
    for entry in index:
        sid = entry.get("id")
        if not sid:
            continue
        cache_path = os.path.join(ANALYSES_DIR, f"{sid}.json")
        has_cache = os.path.exists(cache_path)
        cache_gen = None
        if has_cache:
            try:
                with open(cache_path, "r", encoding="utf-8") as cf:
                    cache_gen = json.load(cf).get("generatedAt")
            except Exception:
                pass
        entry["hasAnalysis"] = has_cache
        entry["analysisStale"] = bool(has_cache and entry.get("lastOpenedAt") and cache_gen and cache_gen < entry["lastOpenedAt"])
    return jsonify(index)


@app.route("/api/simulations", methods=["POST"])
def api_simulations_create():
    _ensure_sim_dir()
    data = request.get_json(silent=True) or {}
    sim_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    sim = {
        "id": sim_id,
        "name": data.get("name", "Untitled"),
        "ticker": data.get("ticker", ""),
        "created": now,
        "modified": now,
        "config": data.get("config", {
            "startingCapital": 100000,
            "startDate": None,
            "useFirstBar": True,
        }),
        "chartState": data.get("chartState", {}),
        "indicators": data.get("indicators", {}),
        "drawings": data.get("drawings", []),
        "playbackState": data.get("playbackState", {
            "currentBarIndex": 0,
            "isComplete": False,
        }),
        "pendingOrders": data.get("pendingOrders", []),
        "trades": data.get("trades", []),
        "analytics": data.get("analytics", {
            "currentCapital": data.get("config", {}).get("startingCapital", 100000),
            "totalPL": 0,
            "totalTrades": 0,
        }),
    }

    with open(_sim_path(sim_id), "w", encoding="utf-8") as f:
        json.dump(sim, f, ensure_ascii=False, indent=2)

    _rebuild_sim_index()
    return jsonify(sim), 201


@app.route("/api/simulations/<sim_id>", methods=["GET"])
def api_simulation_get(sim_id):
    path = _sim_path(sim_id)
    if not os.path.exists(path):
        return jsonify({"error": "Simulation not found"}), 404
    try:
        with open(path, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/simulations/<sim_id>", methods=["PUT"])
def api_simulation_update(sim_id):
    path = _sim_path(sim_id)
    if not os.path.exists(path):
        return jsonify({"error": "Simulation not found"}), 404
    data = request.get_json(silent=True) or {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            sim = json.load(f)
        for key in ("name", "ticker", "config", "chartState", "indicators",
                     "drawings", "playbackState", "pendingOrders", "trades", "analytics",
                     "tradePrefs", "notes"):
            if key in data:
                sim[key] = data[key]
        sim["modified"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sim, f, ensure_ascii=False, indent=2)
        _rebuild_sim_index()
        return jsonify(sim)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/simulations/<sim_id>", methods=["DELETE"])
def api_simulation_delete(sim_id):
    path = _sim_path(sim_id)
    if not os.path.exists(path):
        return jsonify({"error": "Simulation not found"}), 404
    try:
        os.remove(path)
        # Clean up any cached analysis
        apath = _analysis_path(sim_id)
        if os.path.exists(apath):
            try:
                os.remove(apath)
            except Exception:
                pass
        _rebuild_sim_index()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/simulations/export/<sim_id>")
def api_simulation_export(sim_id):
    path = _sim_path(sim_id)
    if not os.path.exists(path):
        return jsonify({"error": "Simulation not found"}), 404
    try:
        with open(path, "r", encoding="utf-8") as f:
            sim = json.load(f)

        lines = ["Trade#,Direction,EntryDate,AvgEntryPrice,ExitDate,AvgExitPrice,Shares,P/L($),P/L(R),HoldDays,Status"]
        for i, trade in enumerate(sim.get("trades", []), 1):
            direction = trade.get("direction", "")
            entries = trade.get("entries", [])
            exits = trade.get("exits", [])
            entry_date = entries[0]["date"] if entries else ""
            exit_date = exits[-1]["date"] if exits else ""
            total_shares = sum(e.get("shares", 0) for e in entries)
            avg_entry = sum(e["price"] * e["shares"] for e in entries) / total_shares if total_shares else 0
            exit_shares = sum(e.get("shares", 0) for e in exits)
            avg_exit = sum(e["price"] * e["shares"] for e in exits) / exit_shares if exit_shares else 0
            sign = 1 if direction == "long" else -1
            pl = sign * (avg_exit - avg_entry) * exit_shares if exits else 0
            risk_per_share = trade.get("riskPerShare")
            pl_r = ""
            if risk_per_share and risk_per_share != 0 and exits:
                pl_r = f"{pl / (abs(risk_per_share) * total_shares):.2f}R"
            hold_days = 0
            if entry_date and exit_date:
                try:
                    d0 = datetime.strptime(entry_date[:10], "%Y-%m-%d")
                    d1 = datetime.strptime(exit_date[:10], "%Y-%m-%d")
                    hold_days = (d1 - d0).days
                except Exception:
                    pass
            status = trade.get("status", "open")
            lines.append(f"{i},{direction},{entry_date},{avg_entry:.2f},{exit_date},{avg_exit:.2f},{total_shares},{pl:.2f},{pl_r},{hold_days},{status}")

        analytics = sim.get("analytics", {})
        lines.append("")
        lines.append("# Summary")
        for k, v in analytics.items():
            if not isinstance(v, dict):
                lines.append(f"# {k},{v}")

        csv_str = "\n".join(lines)
        return Response(csv_str, mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={sim.get('name', sim_id)}.csv"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==============================================
# ANALYSIS ENGINE
# ==============================================

def _ensure_analyses_dir():
    os.makedirs(ANALYSES_DIR, exist_ok=True)


def _analysis_path(sim_id):
    return os.path.join(ANALYSES_DIR, f"{sim_id}.json")


def _iso_now():
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _safe_div(a, b):
    try:
        if b == 0 or b is None:
            return None
        return a / b
    except Exception:
        return None


def _stdev(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    return var ** 0.5


def _days_between(iso_a, iso_b):
    try:
        a = datetime.strptime((iso_a or "")[:10], "%Y-%m-%d")
        b = datetime.strptime((iso_b or "")[:10], "%Y-%m-%d")
        return (b - a).days
    except Exception:
        return 0


def _analyze_trade(trade):
    """Extract closed-trade summary. Returns None for open/partial trades."""
    entries = trade.get("entries") or []
    exits = trade.get("exits") or []
    if not entries or not exits:
        return None
    total_shares = sum(e.get("shares", 0) for e in entries)
    exit_shares = sum(e.get("shares", 0) for e in exits)
    if total_shares <= 0:
        return None
    if exit_shares < total_shares - 1e-9:
        return None  # Not fully closed
    avg_entry = sum(e["price"] * e["shares"] for e in entries) / total_shares
    direction = trade.get("direction", "long")
    sign = 1 if direction == "long" else -1

    pl = 0.0
    for ex in exits:
        pl += sign * (ex["price"] - avg_entry) * ex["shares"]

    init_risk = trade.get("_initialRisk") or trade.get("riskPerShare") or 0
    dollar_risk = abs(init_risk) * total_shares if init_risk else 0
    r_mult = (pl / dollar_risk) if dollar_risk > 0 else None

    entry_date = entries[0]["date"]
    exit_date = exits[-1]["date"]
    exit_idx = max((e.get("_atIdx") or 0) for e in exits)
    entry_idx = trade.get("_createdAtIdx") or 0

    return {
        "id": trade.get("id"),
        "direction": direction,
        "entryDate": entry_date,
        "exitDate": exit_date,
        "avgEntry": avg_entry,
        "shares": total_shares,
        "pl": pl,
        "r": r_mult,
        "dollarRisk": dollar_risk,
        "holdDays": _days_between(entry_date, exit_date),
        "holdBars": max(0, exit_idx - entry_idx),
        "barExitIdx": exit_idx,
    }


def _compute_equity_curve(closed, starting_capital):
    """Build per-exit-event running balance. Events are ordered by exit _atIdx, then date."""
    events = []
    for tr in closed:
        events.append({"date": tr["exitDate"], "pl": tr["pl"], "r": tr["r"] or 0, "barIdx": tr["barExitIdx"]})
    events.sort(key=lambda e: (e["barIdx"], e["date"]))
    curve = [{"date": None, "balance": starting_capital, "pl": 0, "r": 0, "cumR": 0}]
    bal = starting_capital
    cum_r = 0.0
    for ev in events:
        bal += ev["pl"]
        cum_r += ev["r"]
        curve.append({"date": ev["date"], "balance": bal, "pl": ev["pl"], "r": ev["r"], "cumR": cum_r})
    return curve, events


def _drawdown(balances):
    """Return dict with maximal (largest $) and relative (largest %) drawdown.
    Per MT4: these may differ — the largest $ drop need not occur at the
    peak where the largest % drop occurs (that depends on peak magnitude).
    """
    if not balances:
        return {"maxAbs": 0.0, "maxAbsAtPeak": 0.0, "maxAbsPct": 0.0,
                "maxPct": 0.0, "maxPctAtPeak": 0.0, "maxPctAbs": 0.0}
    peak = balances[0]
    max_abs = 0.0
    peak_at_max_abs = peak
    max_pct = 0.0
    peak_at_max_pct = peak
    abs_at_max_pct = 0.0
    for b in balances:
        if b > peak:
            peak = b
        dd_abs = peak - b
        dd_pct = (dd_abs / peak) if peak > 0 else 0
        if dd_abs > max_abs:
            max_abs = dd_abs
            peak_at_max_abs = peak
        if dd_pct > max_pct:
            max_pct = dd_pct
            peak_at_max_pct = peak
            abs_at_max_pct = dd_abs
    return {
        "maxAbs": max_abs, "maxAbsAtPeak": peak_at_max_abs,
        "maxAbsPct": (max_abs / peak_at_max_abs * 100) if peak_at_max_abs > 0 else 0,
        "maxPct": max_pct * 100, "maxPctAtPeak": peak_at_max_pct, "maxPctAbs": abs_at_max_pct,
    }


def _consec_streaks(values_signed):
    """From a list of signed numbers (positive=win, negative=loss), compute streak stats."""
    max_win_len = 0
    max_loss_len = 0
    max_win_sum = 0.0
    max_win_sum_len = 0
    max_loss_sum = 0.0
    max_loss_sum_len = 0
    win_streaks = []
    loss_streaks = []

    cur_sign = 0
    cur_len = 0
    cur_sum = 0.0
    for v in values_signed:
        sgn = 1 if v > 0 else (-1 if v < 0 else 0)
        if sgn == cur_sign and sgn != 0:
            cur_len += 1
            cur_sum += v
        else:
            # Close previous streak
            if cur_sign > 0:
                win_streaks.append((cur_len, cur_sum))
            elif cur_sign < 0:
                loss_streaks.append((cur_len, cur_sum))
            cur_sign = sgn
            cur_len = 1 if sgn != 0 else 0
            cur_sum = v if sgn != 0 else 0
    # Flush
    if cur_sign > 0:
        win_streaks.append((cur_len, cur_sum))
    elif cur_sign < 0:
        loss_streaks.append((cur_len, cur_sum))

    for ln, s in win_streaks:
        if ln > max_win_len:
            max_win_len = ln
            max_win_sum_len = s
        if s > max_win_sum:
            max_win_sum = s
    for ln, s in loss_streaks:
        if ln > max_loss_len:
            max_loss_len = ln
            max_loss_sum_len = s
        if s < max_loss_sum:
            max_loss_sum = s

    avg_win_len = sum(ln for ln, _ in win_streaks) / len(win_streaks) if win_streaks else 0
    avg_loss_len = sum(ln for ln, _ in loss_streaks) / len(loss_streaks) if loss_streaks else 0
    return {
        "maxConsecWins": max_win_len,
        "maxConsecWinsProfit": max_win_sum_len,
        "maxConsecLosses": max_loss_len,
        "maxConsecLossesLoss": max_loss_sum_len,
        "largestConsecProfit": max_win_sum,
        "largestConsecLoss": max_loss_sum,
        "avgConsecWins": round(avg_win_len, 2),
        "avgConsecLosses": round(avg_loss_len, 2),
    }


def _daily_sharpe_trade_days(events, starting_capital, periods=252):
    """Sharpe over exit-days only (biased, high): group PL by date, return per day, annualized."""
    if not events:
        return None
    by_date = {}
    for e in events:
        d = (e["date"] or "")[:10]
        if not d:
            continue
        by_date.setdefault(d, 0.0)
        by_date[d] += e["pl"]
    if not by_date:
        return None
    dates = sorted(by_date.keys())
    returns = []
    bal = starting_capital
    for d in dates:
        pl = by_date[d]
        ret = pl / bal if bal > 0 else 0
        returns.append(ret)
        bal += pl
    sd = _stdev(returns)
    if sd == 0:
        return None
    mean = sum(returns) / len(returns)
    return (mean / sd) * (periods ** 0.5)


def _daily_sharpe_all_days(events, bars, start_idx, cur_idx, starting_capital, periods=252):
    """Canonical time-based Sharpe: return is 0 on days without exits. Annualized by √252."""
    if not events or not bars or start_idx is None or cur_idx is None:
        return None
    by_date = {}
    for e in events:
        d = (e["date"] or "")[:10]
        if not d:
            continue
        by_date.setdefault(d, 0.0)
        by_date[d] += e["pl"]
    returns = []
    bal = starting_capital
    for i in range(start_idx, min(cur_idx + 1, len(bars))):
        d = (bars[i].get("time") or "")[:10]
        pl = by_date.get(d, 0.0)
        ret = pl / bal if bal > 0 else 0
        returns.append(ret)
        bal += pl
    if not returns:
        return None
    sd = _stdev(returns)
    if sd == 0:
        return None
    mean = sum(returns) / len(returns)
    return (mean / sd) * (periods ** 0.5)


def _per_trade_sharpe(r_values, years):
    """Per-trade Sharpe in R: mean(R)/stdev(R), annualized by sqrt(trades_per_year)."""
    if not r_values or years is None or years <= 0:
        return None
    sd = _stdev(r_values)
    if sd == 0:
        return None
    mean = sum(r_values) / len(r_values)
    trades_per_year = len(r_values) / years
    return (mean / sd) * (trades_per_year ** 0.5)


def compute_analysis(sim):
    """Compute full analysis from sim JSON. Returns dict. Raises ValueError if insufficient."""
    trades = sim.get("trades") or []
    closed = []
    for t in trades:
        a = _analyze_trade(t)
        if a is not None:
            closed.append(a)
    if not closed:
        raise ValueError("No closed trades to analyze")

    # Sort by exit bar/date
    closed.sort(key=lambda c: (c["barExitIdx"], c["exitDate"]))

    starting_capital = float((sim.get("config") or {}).get("startingCapital") or 100000)
    curve, events = _compute_equity_curve(closed, starting_capital)

    balances = [pt["balance"] for pt in curve]
    final_balance = balances[-1]
    total_pl = final_balance - starting_capital

    wins = [c for c in closed if c["pl"] > 0]
    losses = [c for c in closed if c["pl"] < 0]
    breakeven = [c for c in closed if c["pl"] == 0]
    longs = [c for c in closed if c["direction"] == "long"]
    shorts = [c for c in closed if c["direction"] == "short"]
    long_wins = [c for c in longs if c["pl"] > 0]
    short_wins = [c for c in shorts if c["pl"] > 0]

    gross_profit = sum(c["pl"] for c in wins)
    gross_loss = sum(c["pl"] for c in losses)  # negative
    profit_factor = _safe_div(gross_profit, abs(gross_loss)) if gross_loss < 0 else None
    expected_payoff = total_pl / len(closed) if closed else 0

    # $ drawdown
    dd = _drawdown(balances)
    # "Absolute drawdown" (MT4 definition): initial - lowest-ever below initial
    lowest = min(balances) if balances else starting_capital
    abs_dd = starting_capital - lowest if lowest < starting_capital else 0

    # R-based drawdown: compute peak-to-trough of cumulative R series.
    cum_r_series = [pt["cumR"] for pt in curve]
    peak_r = cum_r_series[0] if cum_r_series else 0
    max_dd_r = 0
    for r in cum_r_series:
        if r > peak_r:
            peak_r = r
        r_dd = peak_r - r
        if r_dd > max_dd_r:
            max_dd_r = r_dd

    # Consecutive streaks ($ and R)
    streaks_dollar = _consec_streaks([c["pl"] for c in closed])
    r_series = [c["r"] for c in closed if c["r"] is not None]
    streaks_r = _consec_streaks(r_series) if r_series else None

    # R-based metrics
    total_r = sum(r_series) if r_series else 0
    expectancy_r = (total_r / len(r_series)) if r_series else None
    wins_r = [r for r in r_series if r > 0]
    losses_r = [r for r in r_series if r < 0]
    gross_r_wins = sum(wins_r) if wins_r else 0
    gross_r_losses = sum(losses_r) if losses_r else 0
    profit_factor_r = _safe_div(gross_r_wins, abs(gross_r_losses)) if gross_r_losses < 0 else None

    # Time/CAGR
    bars = _read_ticker_bars(sim.get("ticker", ""))
    config = sim.get("config") or {}
    playback = sim.get("playbackState") or {}
    start_idx = 0
    if bars and not config.get("useFirstBar", True) and config.get("startDate"):
        for i, b in enumerate(bars):
            if b.get("time", "") >= config.get("startDate"):
                start_idx = i
                break
    cur_idx = min(playback.get("currentBarIndex", 0), len(bars) - 1 if bars else 0)
    start_date_iso = (bars[start_idx]["time"] if bars and start_idx < len(bars) else None)
    cur_date_iso = (bars[cur_idx]["time"] if bars and cur_idx < len(bars) else None)
    years = _days_between(start_date_iso, cur_date_iso) / 365.25 if (start_date_iso and cur_date_iso) else None
    cagr = None
    if years and years > 0 and starting_capital > 0 and final_balance > 0:
        cagr = ((final_balance / starting_capital) ** (1 / years) - 1) * 100

    # Sharpe variants
    sharpe_daily_all = _daily_sharpe_all_days(events, bars, start_idx, cur_idx, starting_capital)
    sharpe_daily_trade_days = _daily_sharpe_trade_days(events, starting_capital)
    sharpe_trades = _per_trade_sharpe(r_series, years) if r_series else None

    progress = None
    total_bars = len(bars) - start_idx if bars else 0
    if total_bars > 0:
        progress = round(min(100.0, (cur_idx - start_idx) / max(1, total_bars - 1) * 100), 1)
    is_complete = bool(playback.get("isComplete"))

    return {
        "simId": sim.get("id"),
        "simName": sim.get("name", ""),
        "ticker": sim.get("ticker", ""),
        "notes": sim.get("notes", "") or "",
        "generatedAt": _iso_now(),
        "progress": 100.0 if is_complete else progress,
        "isComplete": is_complete,
        "simStartDate": start_date_iso,
        "simCurrentDate": cur_date_iso,
        "yearsElapsed": round(years, 3) if years is not None else None,
        "barsInTest": total_bars,
        "startingCapital": starting_capital,
        "finalBalance": round(final_balance, 2),

        # R-based (PRIMARY)
        "totalR": round(total_r, 2),
        "expectancyR": round(expectancy_r, 3) if expectancy_r is not None else None,
        "profitFactorR": round(profit_factor_r, 3) if profit_factor_r is not None else None,
        "maxR": max(r_series) if r_series else None,
        "minR": min(r_series) if r_series else None,
        "maxDrawdownR": round(max_dd_r, 2),
        "sharpeTradesR": round(sharpe_trades, 3) if sharpe_trades is not None else None,

        # $-based
        "totalNetProfit": round(total_pl, 2),
        "grossProfit": round(gross_profit, 2),
        "grossLoss": round(gross_loss, 2),
        "profitFactor": round(profit_factor, 3) if profit_factor is not None else None,
        "expectedPayoff": round(expected_payoff, 2),
        "absoluteDrawdown": round(abs_dd, 2),
        "maximalDrawdown": round(dd["maxAbs"], 2),
        "maximalDrawdownPct": round(dd["maxAbsPct"], 2),
        "relativeDrawdownPct": round(dd["maxPct"], 2),
        "relativeDrawdownAbs": round(dd["maxPctAbs"], 2),
        "cagrPct": round(cagr, 3) if cagr is not None else None,
        "sharpeDaily": round(sharpe_daily_all, 3) if sharpe_daily_all is not None else None,
        "sharpeDailyTradeDays": round(sharpe_daily_trade_days, 3) if sharpe_daily_trade_days is not None else None,

        # Counts
        "totalTrades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(breakeven),
        "winRatePct": round(len(wins) / len(closed) * 100, 2) if closed else 0,
        "longs": len(longs),
        "longWins": len(long_wins),
        "longWinRatePct": round(len(long_wins) / len(longs) * 100, 2) if longs else 0,
        "shorts": len(shorts),
        "shortWins": len(short_wins),
        "shortWinRatePct": round(len(short_wins) / len(shorts) * 100, 2) if shorts else 0,

        # Extremes
        "largestWin": round(max((c["pl"] for c in wins), default=0), 2),
        "largestLoss": round(min((c["pl"] for c in losses), default=0), 2),
        "avgWin": round(sum(c["pl"] for c in wins) / len(wins), 2) if wins else 0,
        "avgLoss": round(sum(c["pl"] for c in losses) / len(losses), 2) if losses else 0,
        "avgHoldDays": round(sum(c["holdDays"] for c in closed) / len(closed), 1) if closed else 0,

        # Streaks
        "streaksDollar": streaks_dollar,
        "streaksR": streaks_r,

        # Equity curve and trade table
        "equityCurve": [{"date": pt["date"], "balance": round(pt["balance"], 2), "pl": round(pt["pl"], 2), "r": round(pt["r"], 3) if pt["r"] else 0, "cumR": round(pt["cumR"], 2)} for pt in curve],
        "trades": [{
            "id": c["id"], "direction": c["direction"],
            "entryDate": c["entryDate"], "exitDate": c["exitDate"],
            "shares": c["shares"], "avgEntry": round(c["avgEntry"], 4),
            "pl": round(c["pl"], 2), "r": round(c["r"], 3) if c["r"] is not None else None,
            "holdDays": c["holdDays"], "holdBars": c["holdBars"],
        } for c in closed],
    }


def _get_analysis_cache(sim_id):
    p = _analysis_path(sim_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_analysis_cache(sim_id, analysis):
    _ensure_analyses_dir()
    with open(_analysis_path(sim_id), "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)


@app.route("/api/simulations/<sim_id>/touch", methods=["POST"])
def api_simulation_touch(sim_id):
    """Record that the user opened this simulation — invalidates stale analysis cache."""
    path = _sim_path(sim_id)
    if not os.path.exists(path):
        return jsonify({"error": "Simulation not found"}), 404
    try:
        with open(path, "r", encoding="utf-8") as f:
            sim = json.load(f)
        sim["lastOpenedAt"] = _iso_now()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sim, f, ensure_ascii=False, indent=2)
        _rebuild_sim_index()
        return jsonify({"ok": True, "lastOpenedAt": sim["lastOpenedAt"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/simulations/<sim_id>/analyze", methods=["GET", "POST"])
def api_simulation_analyze(sim_id):
    """Get analysis for a sim. Uses cache if fresh. Force recompute on POST."""
    path = _sim_path(sim_id)
    if not os.path.exists(path):
        return jsonify({"error": "Simulation not found"}), 404
    try:
        with open(path, "r", encoding="utf-8") as f:
            sim = json.load(f)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    last_opened = sim.get("lastOpenedAt", "")
    cache = _get_analysis_cache(sim_id)
    force = request.method == "POST" or request.args.get("force") == "1"
    is_fresh = cache and cache.get("generatedAt", "") >= last_opened

    if cache and is_fresh and not force:
        # Overlay current display metadata — name/ticker can change after rename
        # without invalidating the (deterministic) computed stats.
        cache["simName"] = sim.get("name", cache.get("simName", ""))
        cache["ticker"] = sim.get("ticker", cache.get("ticker", ""))

        cache["notes"] = sim.get("notes", cache.get("notes", "")) or ""
        cache["_fromCache"] = True
        return jsonify(cache)

    try:
        analysis = compute_analysis(sim)
    except ValueError as e:
        return jsonify({"error": str(e), "insufficient": True}), 422

    _save_analysis_cache(sim_id, analysis)
    _rebuild_sim_index()
    analysis["_fromCache"] = False
    return jsonify(analysis)


@app.route("/api/simulations/<sim_id>/analysis-status")
def api_analysis_status(sim_id):
    path = _sim_path(sim_id)
    if not os.path.exists(path):
        return jsonify({"error": "Simulation not found"}), 404
    try:
        with open(path, "r", encoding="utf-8") as f:
            sim = json.load(f)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    last_opened = sim.get("lastOpenedAt", "")
    cache = _get_analysis_cache(sim_id)
    return jsonify({
        "hasCache": bool(cache),
        "generatedAt": cache.get("generatedAt") if cache else None,
        "lastOpenedAt": last_opened,
        "isStale": bool(cache) and cache.get("generatedAt", "") < last_opened,
    })


@app.route("/api/simulations/compare", methods=["POST"])
def api_simulations_compare():
    body = request.get_json(silent=True) or {}
    ids = body.get("ids") or []
    if not ids or len(ids) < 2:
        return jsonify({"error": "need at least 2 simulation ids"}), 400
    if len(ids) > 5:
        return jsonify({"error": "maximum 5 simulations"}), 400
    analyses = []
    errors = []
    for sid in ids:
        path = _sim_path(sid)
        if not os.path.exists(path):
            errors.append({"id": sid, "error": "not found"})
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                sim = json.load(f)
            last_opened = sim.get("lastOpenedAt", "")
            cache = _get_analysis_cache(sid)
            if cache and cache.get("generatedAt", "") >= last_opened:
                # Overlay current display metadata on cached analysis
                cache["simName"] = sim.get("name", cache.get("simName", ""))
                cache["ticker"] = sim.get("ticker", cache.get("ticker", ""))

                cache["notes"] = sim.get("notes", cache.get("notes", "")) or ""
                analyses.append(cache)
            else:
                a = compute_analysis(sim)
                _save_analysis_cache(sid, a)
                _rebuild_sim_index()
                analyses.append(a)
        except ValueError as e:
            errors.append({"id": sid, "error": str(e), "insufficient": True})
        except Exception as e:
            errors.append({"id": sid, "error": str(e)})
    return jsonify({"analyses": analyses, "errors": errors})


# ==============================================
# PDF REPORT GENERATION
# ==============================================

# Dark-theme palette for equity charts (matches the UI).
_PDF_COLORS = {
    "bg":      "#0d1117",
    "panel":   "#161b22",
    "border":  "#30363d",
    "text":    "#e8f0f8",
    "muted":   "#8899aa",
    "accent":  "#00d4aa",
    "accent2": "#ff6b35",
    "green":   "#26a69a",
    "red":     "#ef5350",
    "yellow":  "#f5c842",
    "grid":    "#1f2933",
}


def _fmt_money(v):
    if v is None:
        return "—"
    sign = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1000:
        return f"{sign}${a:,.2f}"
    return f"{sign}${a:.2f}"


def _fmt_r(v):
    if v is None:
        return "—"
    return f"{'+' if v >= 0 else ''}{v:.2f}R"


def _fmt_pct(v, digits=2):
    if v is None:
        return "—"
    return f"{v:.{digits}f}%"


def _fmt_num(v, digits=2):
    if v is None:
        return "—"
    return f"{v:.{digits}f}"


def _render_equity_png(analysis, width_in=7.5, height_in=2.6):
    """Render the equity curve to a PNG (BytesIO) using matplotlib."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.dates import DateFormatter, AutoDateLocator
    import matplotlib.dates as mdates
    from datetime import datetime as _dt

    raw = [(p.get("date"), p.get("balance")) for p in (analysis.get("equityCurve") or []) if p.get("date")]
    # dedup by date: keep last balance for each date
    seen = {}
    for d, b in raw:
        seen[d] = b
    pts = sorted(seen.items())
    if not pts:
        return None

    dates = [_dt.strptime(d[:10], "%Y-%m-%d") for d, _ in pts]
    bals = [b for _, b in pts]
    cap = analysis.get("startingCapital") or bals[0]

    fig, ax = plt.subplots(figsize=(width_in, height_in), dpi=150)
    fig.patch.set_facecolor(_PDF_COLORS["bg"])
    ax.set_facecolor(_PDF_COLORS["bg"])

    # Fill green above / red below starting capital
    ax.fill_between(dates, bals, cap, where=[b >= cap for b in bals],
                    facecolor=_PDF_COLORS["green"], alpha=0.25, interpolate=True)
    ax.fill_between(dates, bals, cap, where=[b < cap for b in bals],
                    facecolor=_PDF_COLORS["red"], alpha=0.25, interpolate=True)
    # Curve line with color by segment
    for i in range(1, len(dates)):
        c = _PDF_COLORS["green"] if bals[i] >= cap else _PDF_COLORS["red"]
        ax.plot(dates[i - 1:i + 1], bals[i - 1:i + 1], color=c, linewidth=1.8, solid_capstyle="round")

    # Dashed baseline at starting capital
    ax.axhline(cap, color=_PDF_COLORS["muted"], linestyle="--", linewidth=0.8, alpha=0.6)

    # Style
    for spine in ax.spines.values():
        spine.set_edgecolor(_PDF_COLORS["border"])
        spine.set_linewidth(0.6)
    ax.tick_params(colors=_PDF_COLORS["muted"], labelsize=7)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax.xaxis.set_major_locator(AutoDateLocator(maxticks=8))
    ax.xaxis.set_major_formatter(DateFormatter("%b %Y"))
    ax.grid(True, axis="y", color=_PDF_COLORS["grid"], linestyle="-", linewidth=0.5, alpha=0.7)
    ax.set_axisbelow(True)

    # Last-value annotation
    last_val = bals[-1]
    color = _PDF_COLORS["green"] if last_val >= cap else _PDF_COLORS["red"]
    ax.annotate(f"${last_val:,.2f}", xy=(dates[-1], last_val),
                xytext=(6, 0), textcoords="offset points",
                color=color, fontsize=8, fontweight="bold",
                va="center", ha="left")

    fig.tight_layout(pad=0.5)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, facecolor=_PDF_COLORS["bg"])
    plt.close(fig)
    buf.seek(0)
    return buf


def _render_compare_equity_png(analyses, width_in=7.5, height_in=3.0):
    """Overlay equity curves (normalized to 100) for comparison."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.dates import AutoDateLocator, DateFormatter
    from datetime import datetime as _dt

    palette = ["#00d4aa", "#f5c842", "#ff6b35", "#60a5fa", "#c084fc"]
    fig, ax = plt.subplots(figsize=(width_in, height_in), dpi=150)
    fig.patch.set_facecolor(_PDF_COLORS["bg"])
    ax.set_facecolor(_PDF_COLORS["bg"])

    any_drawn = False
    for i, a in enumerate(analyses):
        raw = [(p.get("date"), p.get("balance")) for p in (a.get("equityCurve") or []) if p.get("date")]
        cap = a.get("startingCapital") or (raw[0][1] if raw else 100000)
        seen = {}
        for d, b in raw:
            seen[d] = b
        pts = sorted(seen.items())
        if not pts:
            continue
        any_drawn = True
        dates = [_dt.strptime(d[:10], "%Y-%m-%d") for d, _ in pts]
        norm = [(b / cap * 100) for _, b in pts]
        ax.plot(dates, norm, color=palette[i % len(palette)], linewidth=1.6,
                label=a.get("simName") or f"Sim {i + 1}")

    if not any_drawn:
        plt.close(fig)
        return None

    # 100 baseline
    ax.axhline(100, color=_PDF_COLORS["muted"], linestyle="--", linewidth=0.7, alpha=0.6)
    for spine in ax.spines.values():
        spine.set_edgecolor(_PDF_COLORS["border"])
        spine.set_linewidth(0.6)
    ax.tick_params(colors=_PDF_COLORS["muted"], labelsize=7)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.0f}"))
    ax.xaxis.set_major_locator(AutoDateLocator(maxticks=8))
    ax.xaxis.set_major_formatter(DateFormatter("%b %Y"))
    ax.grid(True, axis="y", color=_PDF_COLORS["grid"], linestyle="-", linewidth=0.5, alpha=0.7)
    ax.set_axisbelow(True)
    leg = ax.legend(loc="upper left", fontsize=7, frameon=True, facecolor=_PDF_COLORS["panel"],
                    edgecolor=_PDF_COLORS["border"], labelcolor=_PDF_COLORS["text"])
    for text in leg.get_texts():
        text.set_color(_PDF_COLORS["text"])

    fig.tight_layout(pad=0.5)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, facecolor=_PDF_COLORS["bg"])
    plt.close(fig)
    buf.seek(0)
    return buf


def _pdf_styles():
    """Centralized styles for the PDF reports."""
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.colors import HexColor
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

    base = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle("title", parent=base["Title"], fontName="Helvetica-Bold",
                                fontSize=18, textColor=HexColor("#0d1117"), spaceAfter=2, alignment=TA_LEFT),
        "subtitle": ParagraphStyle("subtitle", parent=base["Normal"], fontName="Helvetica",
                                   fontSize=9, textColor=HexColor("#555555"), spaceAfter=10, alignment=TA_LEFT),
        "h3": ParagraphStyle("h3", parent=base["Heading3"], fontName="Helvetica-Bold",
                             fontSize=10, textColor=HexColor("#00a684"), spaceBefore=12, spaceAfter=4,
                             alignment=TA_LEFT, textTransform="uppercase"),
        "cell_label": ParagraphStyle("cell_label", parent=base["Normal"], fontName="Helvetica",
                                     fontSize=7, textColor=HexColor("#555555"), alignment=TA_LEFT),
        "cell_value": ParagraphStyle("cell_value", parent=base["Normal"], fontName="Helvetica-Bold",
                                     fontSize=11, textColor=HexColor("#0d1117"), alignment=TA_LEFT, leading=13),
        "cell_value_primary": ParagraphStyle("cell_value_primary", parent=base["Normal"], fontName="Helvetica-Bold",
                                             fontSize=12, textColor=HexColor("#00a684"), alignment=TA_LEFT, leading=14),
        "cell_value_pos": ParagraphStyle("cell_value_pos", parent=base["Normal"], fontName="Helvetica-Bold",
                                         fontSize=11, textColor=HexColor("#0a8f7a"), alignment=TA_LEFT, leading=13),
        "cell_value_neg": ParagraphStyle("cell_value_neg", parent=base["Normal"], fontName="Helvetica-Bold",
                                         fontSize=11, textColor=HexColor("#c0413e"), alignment=TA_LEFT, leading=13),
        "banner": ParagraphStyle("banner", parent=base["Normal"], fontName="Helvetica",
                                 fontSize=9, textColor=HexColor("#8a6d00"), leading=12),
        "small": ParagraphStyle("small", parent=base["Normal"], fontName="Helvetica",
                                fontSize=7, textColor=HexColor("#777777"), leading=9),
        "footer": ParagraphStyle("footer", parent=base["Normal"], fontName="Helvetica",
                                 fontSize=7, textColor=HexColor("#888888"), alignment=TA_CENTER),
        "trade_cell": ParagraphStyle("trade_cell", parent=base["Normal"], fontName="Helvetica",
                                     fontSize=7.5, textColor=HexColor("#222222"), alignment=TA_RIGHT, leading=9),
        "trade_cell_left": ParagraphStyle("trade_cell_left", parent=base["Normal"], fontName="Helvetica",
                                          fontSize=7.5, textColor=HexColor("#222222"), alignment=TA_LEFT, leading=9),
        "trade_header": ParagraphStyle("trade_header", parent=base["Normal"], fontName="Helvetica-Bold",
                                       fontSize=7, textColor=HexColor("#ffffff"), alignment=TA_RIGHT, leading=9),
    }
    return styles


def _pdf_metric_grid(cells, cols=3, col_widths=None):
    """Build a grid of metric cells. Each cell = (label, value, value_style_name).
    Returns a reportlab Table.
    """
    from reportlab.platypus import Table, TableStyle, Paragraph
    from reportlab.lib.colors import HexColor
    from reportlab.lib.units import inch
    st = _pdf_styles()

    # Pad cells to complete grid
    while len(cells) % cols != 0:
        cells.append(("", "", "cell_value"))

    rows = []
    for i in range(0, len(cells), cols):
        row = []
        for j in range(cols):
            lbl, val, style = cells[i + j]
            style_obj = st.get(style) or st["cell_value"]
            inner = Table(
                [[Paragraph(lbl, st["cell_label"])], [Paragraph(str(val), style_obj)]],
                colWidths=[(col_widths[j] if col_widths else 2.3 * inch) - 0.1 * inch],
            )
            inner.setStyle(TableStyle([
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            row.append(inner)
        rows.append(row)

    t = Table(rows, colWidths=col_widths or [2.3 * inch] * cols)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#f7f7f8")),
        ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#d0d0d5")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, HexColor("#e2e2e7")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def _build_analysis_pdf(a):
    """Generate a professional PDF report for a single analysis. Returns BytesIO."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Image,
                                    Table, TableStyle, PageBreak, KeepTogether)
    from reportlab.lib.styles import ParagraphStyle

    st = _pdf_styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            leftMargin=0.55 * inch, rightMargin=0.55 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.5 * inch,
                            title=f"Analysis — {a.get('simName','')}")

    pos = (a.get("totalNetProfit") or 0) >= 0
    r_pos = (a.get("totalR") or 0) >= 0

    elements = []

    # ----- Header block -----
    progress_note = ""
    is_complete = a.get("isComplete") or (a.get("progress") or 0) >= 100
    if not is_complete:
        progress_note = f' <font color="#cc7700">(incomplete — {a.get("progress") or 0}%)</font>'

    title_bar = Table(
        [[Paragraph(f"<b>Analysis Report</b> — {a.get('simName','')}", st["title"]),
          Paragraph(f"<b>{a.get('ticker','')}</b>", ParagraphStyle('tk', parent=st['title'], textColor=HexColor('#00a684'), alignment=2, fontSize=16))]],
        colWidths=[5.5 * inch, 1.9 * inch])
    title_bar.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 1, HexColor("#00a684")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(title_bar)
    elements.append(Spacer(1, 4))

    subtitle = (f"Period: {a.get('simStartDate','?')} → {a.get('simCurrentDate','?')}  ·  "
                f"{a.get('barsInTest',0)} bars"
                f"{(', '+_fmt_num(a.get('yearsElapsed'),2)+' yr') if a.get('yearsElapsed') else ''}  ·  "
                f"{a.get('totalTrades',0)} closed trades"
                f"{progress_note}")
    elements.append(Paragraph(subtitle, st["subtitle"]))

    if not is_complete:
        banner = Table([[Paragraph(f"⚠ Simulation is incomplete ({a.get('progress') or 0}%). Metrics reflect closed trades only; open positions are excluded.", st["banner"])]],
                       colWidths=[7.4 * inch])
        banner.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), HexColor("#fff7d6")),
            ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#e0c460")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(banner)
        elements.append(Spacer(1, 6))

    # ----- Notes (if any) -----
    notes = (a.get("notes") or "").strip()
    if notes:
        elements.append(Paragraph("NOTES", st["h3"]))
        notes_style = ParagraphStyle("notes", fontName="Helvetica", fontSize=9,
                                     textColor=HexColor("#222222"), leading=12, leftIndent=0)
        notes_box = Table([[Paragraph(notes.replace("\n", "<br/>"), notes_style)]],
                          colWidths=[7.4 * inch])
        notes_box.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), HexColor("#f7f7f8")),
            ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#d0d0d5")),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        elements.append(notes_box)
        elements.append(Spacer(1, 6))

    # ----- R-based (primary) -----
    elements.append(Paragraph("HEADLINE (R-BASED)", st["h3"]))
    r_cells = [
        ("Total R", _fmt_r(a.get("totalR")), "cell_value_primary"),
        ("Expectancy", f"{_fmt_r(a.get('expectancyR'))}/trade", "cell_value_primary"),
        ("Profit Factor (R)", _fmt_num(a.get("profitFactorR"), 2), "cell_value_primary"),
        ("Max Drawdown (R)", f"-{_fmt_num(a.get('maxDrawdownR'), 2)}R", "cell_value_neg"),
        ("Sharpe (trade R)", _fmt_num(a.get("sharpeTradesR"), 2), "cell_value"),
        ("Max R Win / Loss", f"{_fmt_r(a.get('maxR'))} / {_fmt_r(a.get('minR'))}", "cell_value"),
    ]
    elements.append(_pdf_metric_grid(r_cells, cols=3, col_widths=[2.47 * inch] * 3))

    # ----- Dollar-based -----
    elements.append(Paragraph("DOLLAR-BASED (MT4 PARITY)", st["h3"]))
    d_cells = [
        ("Starting Capital", _fmt_money(a.get("startingCapital")), "cell_value"),
        ("Final Balance", _fmt_money(a.get("finalBalance")), "cell_value_pos" if pos else "cell_value_neg"),
        ("Total Net Profit", _fmt_money(a.get("totalNetProfit")), "cell_value_pos" if pos else "cell_value_neg"),
        ("Gross Profit", _fmt_money(a.get("grossProfit")), "cell_value_pos"),
        ("Gross Loss", _fmt_money(a.get("grossLoss")), "cell_value_neg"),
        ("Profit Factor ($)", _fmt_num(a.get("profitFactor"), 2), "cell_value"),
        ("Expected Payoff", _fmt_money(a.get("expectedPayoff")), "cell_value"),
        ("Absolute Drawdown", _fmt_money(a.get("absoluteDrawdown")), "cell_value_neg"),
        ("Maximal Drawdown", f"{_fmt_money(a.get('maximalDrawdown'))} ({_fmt_pct(a.get('maximalDrawdownPct'))})", "cell_value_neg"),
        ("Relative Drawdown", f"{_fmt_pct(a.get('relativeDrawdownPct'))} ({_fmt_money(a.get('relativeDrawdownAbs'))})", "cell_value_neg"),
        ("CAGR", _fmt_pct(a.get("cagrPct"), 2), "cell_value"),
        ("Sharpe (daily, √252)", _fmt_num(a.get("sharpeDaily"), 2), "cell_value"),
    ]
    elements.append(_pdf_metric_grid(d_cells, cols=3, col_widths=[2.47 * inch] * 3))

    # ----- Trade Counts -----
    elements.append(Paragraph("TRADE COUNTS", st["h3"]))
    wr = a.get("winRatePct") or 0
    lr = (100 - wr) if a.get("totalTrades") else 0
    c_cells = [
        ("Total Trades", str(a.get("totalTrades") or 0), "cell_value"),
        ("Profit Trades", f"{a.get('wins',0)} ({_fmt_pct(wr)})", "cell_value_pos"),
        ("Loss Trades", f"{a.get('losses',0)} ({_fmt_pct(lr)})", "cell_value_neg"),
        ("Long Positions (won %)", f"{a.get('longs',0)} ({_fmt_pct(a.get('longWinRatePct'))})", "cell_value"),
        ("Short Positions (won %)", f"{a.get('shorts',0)} ({_fmt_pct(a.get('shortWinRatePct'))})", "cell_value"),
        ("Avg Hold (days)", _fmt_num(a.get("avgHoldDays"), 1), "cell_value"),
        ("Largest Profit Trade", _fmt_money(a.get("largestWin")), "cell_value_pos"),
        ("Largest Loss Trade", _fmt_money(a.get("largestLoss")), "cell_value_neg"),
        ("Avg Profit Trade", _fmt_money(a.get("avgWin")), "cell_value_pos"),
        ("Avg Loss Trade", _fmt_money(a.get("avgLoss")), "cell_value_neg"),
        ("Breakeven", str(a.get("breakeven") or 0), "cell_value"),
        ("Bars in Test", str(a.get("barsInTest") or 0), "cell_value"),
    ]
    elements.append(_pdf_metric_grid(c_cells, cols=3, col_widths=[2.47 * inch] * 3))

    # ----- Streaks -----
    sd = a.get("streaksDollar") or {}
    elements.append(Paragraph("STREAKS", st["h3"]))
    s_cells = [
        ("Max Consec Wins", f"{sd.get('maxConsecWins',0)} ({_fmt_money(sd.get('maxConsecWinsProfit'))})", "cell_value_pos"),
        ("Max Consec Losses", f"{sd.get('maxConsecLosses',0)} ({_fmt_money(sd.get('maxConsecLossesLoss'))})", "cell_value_neg"),
        ("Largest Consec Profit", _fmt_money(sd.get("largestConsecProfit")), "cell_value_pos"),
        ("Largest Consec Loss", _fmt_money(sd.get("largestConsecLoss")), "cell_value_neg"),
        ("Avg Consec Wins", _fmt_num(sd.get("avgConsecWins"), 2), "cell_value"),
        ("Avg Consec Losses", _fmt_num(sd.get("avgConsecLosses"), 2), "cell_value"),
    ]
    elements.append(_pdf_metric_grid(s_cells, cols=3, col_widths=[2.47 * inch] * 3))

    # ----- Equity Curve -----
    elements.append(Paragraph("EQUITY CURVE", st["h3"]))
    eq_buf = _render_equity_png(a, width_in=7.4, height_in=2.6)
    if eq_buf:
        elements.append(Image(eq_buf, width=7.4 * inch, height=2.6 * inch))
    else:
        elements.append(Paragraph("No closed trades to plot.", st["small"]))

    # ----- Trade Log -----
    elements.append(PageBreak())
    elements.append(Paragraph("TRADE LOG", st["h3"]))

    trades = a.get("trades") or []
    if not trades:
        elements.append(Paragraph("No closed trades.", st["small"]))
    else:
        headers = ["#", "Dir", "Entry Date", "Exit Date", "Hold", "Shares", "Avg Entry", "P/L", "R"]
        data = [[Paragraph(h, st["trade_header"]) for h in headers]]
        for i, t in enumerate(trades, 1):
            pl = t.get("pl") or 0
            r = t.get("r")
            pos_t = pl >= 0
            pl_color = "#0a8f7a" if pos_t else "#c0413e"
            r_color = pl_color if r is not None and r >= 0 else "#c0413e" if r is not None else "#777777"
            dir_color = "#0a8f7a" if t.get("direction") == "long" else "#c0413e"
            row = [
                Paragraph(str(i), st["trade_cell"]),
                Paragraph(f'<font color="{dir_color}">{(t.get("direction") or "").upper()}</font>', st["trade_cell_left"]),
                Paragraph(t.get("entryDate") or "", st["trade_cell_left"]),
                Paragraph(t.get("exitDate") or "", st["trade_cell_left"]),
                Paragraph(f"{t.get('holdDays',0)}d", st["trade_cell"]),
                Paragraph(str(t.get("shares", 0)), st["trade_cell"]),
                Paragraph(f"${_fmt_num(t.get('avgEntry'), 2)}", st["trade_cell"]),
                Paragraph(f'<font color="{pl_color}"><b>{_fmt_money(pl)}</b></font>', st["trade_cell"]),
                Paragraph(f'<font color="{r_color}">{_fmt_r(r) if r is not None else "—"}</font>', st["trade_cell"]),
            ]
            data.append(row)

        col_widths = [0.35, 0.45, 0.95, 0.95, 0.5, 0.6, 0.8, 1.0, 0.7]
        col_widths = [c * inch for c in col_widths]
        tbl = Table(data, colWidths=col_widths, repeatRows=1)
        style_cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), HexColor("#0d1117")),
            ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#ffffff")),
            ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#d0d0d5")),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, HexColor("#e2e2e7")),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]
        # Alternating row backgrounds
        for i in range(1, len(data)):
            if i % 2 == 0:
                style_cmds.append(("BACKGROUND", (0, i), (-1, i), HexColor("#fafafb")))
        tbl.setStyle(TableStyle(style_cmds))
        elements.append(tbl)

    # Build PDF (with footer)
    def _page_footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(HexColor("#888888"))
        canvas.drawString(0.55 * inch, 0.3 * inch,
                          f"Analysis generated {(a.get('generatedAt') or '').replace('T',' ').replace('Z',' UTC')}")
        canvas.drawRightString(letter[0] - 0.55 * inch, 0.3 * inch, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(elements, onFirstPage=_page_footer, onLaterPages=_page_footer)
    buf.seek(0)
    return buf


def _build_compare_pdf(analyses):
    """Generate a professional comparison PDF for 2-5 analyses."""
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib.units import inch
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Image,
                                    Table, TableStyle, PageBreak)

    st = _pdf_styles()
    buf = io.BytesIO()
    pagesize = landscape(letter) if len(analyses) >= 4 else letter
    doc = SimpleDocTemplate(buf, pagesize=pagesize,
                            leftMargin=0.45 * inch, rightMargin=0.45 * inch,
                            topMargin=0.45 * inch, bottomMargin=0.45 * inch,
                            title=f"Compare — {len(analyses)} simulations")

    elements = []

    # ----- Header -----
    title_bar = Table([[Paragraph(f"<b>Comparison Report</b> — {len(analyses)} Simulations", st["title"])]],
                      colWidths=[pagesize[0] - 0.9 * inch])
    title_bar.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 1, HexColor("#00a684")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(title_bar)
    elements.append(Spacer(1, 4))
    elements.append(Paragraph(
        "Side-by-side with heatmap coloring (★ = primary R-based; green = best, red = worst)", st["subtitle"]))

    # ----- Metrics table with heatmap -----
    metrics = [
        # R-based
        ("r", "Total R", True, lambda a: a.get("totalR"), _fmt_r, True),
        ("r", "Expectancy (R)", True, lambda a: a.get("expectancyR"), _fmt_r, True),
        ("r", "Profit Factor (R)", True, lambda a: a.get("profitFactorR"), lambda v: _fmt_num(v, 2), True),
        ("r", "Max Drawdown (R)", False, lambda a: a.get("maxDrawdownR"), lambda v: f"-{_fmt_num(v, 2)}R", True),
        ("r", "Sharpe (trade R)", True, lambda a: a.get("sharpeTradesR"), lambda v: _fmt_num(v, 2), True),
        ("r", "Max R Win", True, lambda a: a.get("maxR"), _fmt_r, False),
        ("r", "Max R Loss", True, lambda a: a.get("minR"), _fmt_r, False),
        # Dollar
        ("d", "Starting Capital", None, lambda a: a.get("startingCapital"), _fmt_money, False),
        ("d", "Final Balance", True, lambda a: a.get("finalBalance"), _fmt_money, False),
        ("d", "Total Net Profit", True, lambda a: a.get("totalNetProfit"), _fmt_money, False),
        ("d", "Gross Profit", True, lambda a: a.get("grossProfit"), _fmt_money, False),
        ("d", "Gross Loss", True, lambda a: a.get("grossLoss"), _fmt_money, False),
        ("d", "Profit Factor ($)", True, lambda a: a.get("profitFactor"), lambda v: _fmt_num(v, 2), False),
        ("d", "Expected Payoff", True, lambda a: a.get("expectedPayoff"), _fmt_money, False),
        ("d", "Absolute Drawdown", False, lambda a: a.get("absoluteDrawdown"), _fmt_money, False),
        ("d", "Maximal Drawdown ($)", False, lambda a: a.get("maximalDrawdown"), _fmt_money, False),
        ("d", "Maximal Drawdown %", False, lambda a: a.get("maximalDrawdownPct"), lambda v: _fmt_pct(v, 2), False),
        ("d", "Relative Drawdown %", False, lambda a: a.get("relativeDrawdownPct"), lambda v: _fmt_pct(v, 2), False),
        ("d", "CAGR %", True, lambda a: a.get("cagrPct"), lambda v: _fmt_pct(v, 2), False),
        ("d", "Sharpe (daily, all)", True, lambda a: a.get("sharpeDaily"), lambda v: _fmt_num(v, 2), False),
        # Counts
        ("c", "Total Trades", None, lambda a: a.get("totalTrades"), str, False),
        ("c", "Profit Trades", True, lambda a: a.get("wins"), str, False),
        ("c", "Loss Trades", False, lambda a: a.get("losses"), str, False),
        ("c", "Win Rate %", True, lambda a: a.get("winRatePct"), lambda v: _fmt_pct(v, 2), False),
        ("c", "Long Positions", None, lambda a: a.get("longs"), str, False),
        ("c", "Long Win %", True, lambda a: a.get("longWinRatePct"), lambda v: _fmt_pct(v, 2), False),
        ("c", "Short Positions", None, lambda a: a.get("shorts"), str, False),
        ("c", "Short Win %", True, lambda a: a.get("shortWinRatePct"), lambda v: _fmt_pct(v, 2), False),
        ("c", "Avg Hold (d)", None, lambda a: a.get("avgHoldDays"), lambda v: _fmt_num(v, 1), False),
        ("c", "Largest Profit", True, lambda a: a.get("largestWin"), _fmt_money, False),
        ("c", "Largest Loss", True, lambda a: a.get("largestLoss"), _fmt_money, False),
        ("c", "Avg Profit", True, lambda a: a.get("avgWin"), _fmt_money, False),
        ("c", "Avg Loss", True, lambda a: a.get("avgLoss"), _fmt_money, False),
        # Streaks
        ("s", "Max Consec Wins", True, lambda a: (a.get("streaksDollar") or {}).get("maxConsecWins"), str, False),
        ("s", "Max Consec Losses", False, lambda a: (a.get("streaksDollar") or {}).get("maxConsecLosses"), str, False),
        ("s", "Largest Consec Profit", True, lambda a: (a.get("streaksDollar") or {}).get("largestConsecProfit"), _fmt_money, False),
        ("s", "Largest Consec Loss", True, lambda a: (a.get("streaksDollar") or {}).get("largestConsecLoss"), _fmt_money, False),
        ("s", "Avg Consec Wins", True, lambda a: (a.get("streaksDollar") or {}).get("avgConsecWins"), lambda v: _fmt_num(v, 2), False),
        ("s", "Avg Consec Losses", False, lambda a: (a.get("streaksDollar") or {}).get("avgConsecLosses"), lambda v: _fmt_num(v, 2), False),
    ]

    section_titles = {"r": "R-BASED (PRIMARY)", "d": "DOLLAR-BASED", "c": "TRADE COUNTS", "s": "STREAKS"}

    # Header row: ticker names
    headers = ["Metric"]
    for a in analyses:
        name = a.get("simName", "")
        ticker = a.get("ticker", "")
        complete = a.get("isComplete") or (a.get("progress") or 0) >= 100
        suffix = "" if complete else f" ({a.get('progress') or 0}%)"
        headers.append(f"{name} [{ticker}]{suffix}")

    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    hdr_style = ParagraphStyle("hdr", fontName="Helvetica-Bold", fontSize=8,
                               textColor=HexColor("#ffffff"), alignment=TA_CENTER, leading=10)
    metric_label_style = ParagraphStyle("ml", fontName="Helvetica", fontSize=8,
                                        textColor=HexColor("#333333"), leading=10)
    metric_label_primary = ParagraphStyle("mlp", fontName="Helvetica-Bold", fontSize=8,
                                          textColor=HexColor("#00a684"), leading=10)
    cell_style = ParagraphStyle("c", fontName="Helvetica-Bold", fontSize=8,
                                textColor=HexColor("#111111"), alignment=TA_CENTER, leading=10)

    rows = [[Paragraph(h, hdr_style) for h in headers]]

    # For cell color gradients
    def color_for(vals, idx, higher_better):
        if higher_better is None:
            return None
        finite = [v for v in vals if isinstance(v, (int, float))]
        if len(finite) < 2:
            return None
        mn, mx = min(finite), max(finite)
        if mn == mx:
            return None
        v = vals[idx]
        if not isinstance(v, (int, float)):
            return None
        t = (v - mn) / (mx - mn)
        if not higher_better:
            t = 1 - t
        # t=0 red, t=0.5 neutral, t=1 green
        if t >= 0.5:
            # green
            k = (t - 0.5) * 2  # 0..1
            r = int(247 - k * (247 - 200))
            g = int(247 - k * (247 - 230))
            b = int(248 - k * (248 - 200))
        else:
            k = (0.5 - t) * 2  # 0..1
            r = int(247 + k * (255 - 247))
            g = int(247 - k * (247 - 215))
            b = int(248 - k * (248 - 215))
        return HexColor(f"#{r:02x}{g:02x}{b:02x}")

    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#0d1117")),
        ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#ffffff")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#d0d0d5")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, HexColor("#e2e2e7")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]

    last_section = None
    row_idx = 1
    for sec, label, hb, extractor, fmt, primary in metrics:
        if sec != last_section:
            # Insert section header row
            title = section_titles.get(sec, sec)
            section_row = [Paragraph(f"<b>{title}</b>", ParagraphStyle("sec", fontName="Helvetica-Bold", fontSize=8, textColor=HexColor("#555555"), leading=10))]
            section_row.extend([Paragraph("", cell_style) for _ in analyses])
            rows.append(section_row)
            style_cmds.append(("BACKGROUND", (0, row_idx), (-1, row_idx), HexColor("#ececef")))
            style_cmds.append(("SPAN", (0, row_idx), (-1, row_idx)))
            row_idx += 1
            last_section = sec

        vals_raw = [extractor(a) for a in analyses]
        vals_for_heat = [v if isinstance(v, (int, float)) else None for v in vals_raw]
        cells_out = []
        for i, v in enumerate(vals_raw):
            if v is None or (isinstance(v, float) and (v != v)):  # None or NaN
                cell_txt = "—"
            else:
                try:
                    cell_txt = fmt(v)
                except Exception:
                    cell_txt = str(v)
            cells_out.append(Paragraph(cell_txt, cell_style))
            color = color_for(vals_for_heat, i, hb)
            if color is not None:
                style_cmds.append(("BACKGROUND", (1 + i, row_idx), (1 + i, row_idx), color))

        label_para = Paragraph(("★ " + label) if primary else label, metric_label_primary if primary else metric_label_style)
        rows.append([label_para] + cells_out)
        row_idx += 1

    # Column widths: first col wider for labels
    total_w = pagesize[0] - 0.9 * inch
    label_w = 1.7 * inch
    per_sim = (total_w - label_w) / len(analyses)
    col_widths = [label_w] + [per_sim] * len(analyses)

    tbl = Table(rows, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle(style_cmds))
    elements.append(tbl)
    elements.append(Spacer(1, 10))

    # ----- Overlay equity curves -----
    elements.append(Paragraph("EQUITY CURVES (NORMALIZED, START = 100)", st["h3"]))
    eq_buf = _render_compare_equity_png(analyses, width_in=min(9.5, (pagesize[0] - 0.9 * inch) / 72), height_in=3.0)
    if eq_buf:
        img_w = pagesize[0] - 0.9 * inch
        img_h = img_w / 9.5 * 3.0  # maintain aspect
        elements.append(Image(eq_buf, width=img_w, height=img_h))

    # ----- Per-sim notes -----
    noted = [a for a in analyses if (a.get("notes") or "").strip()]
    if noted:
        elements.append(Paragraph("NOTES", st["h3"]))
        notes_body_style = ParagraphStyle("notes_body", fontName="Helvetica", fontSize=9,
                                          textColor=HexColor("#222222"), leading=12)
        notes_hdr_style = ParagraphStyle("notes_hdr", fontName="Helvetica-Bold", fontSize=10,
                                         textColor=HexColor("#00a684"), leading=12)
        for a in noted:
            hdr = f"{a.get('simName','')} [{a.get('ticker','')}]"
            notes_tbl = Table(
                [[Paragraph(hdr, notes_hdr_style)],
                 [Paragraph((a.get("notes") or "").strip().replace("\n", "<br/>"), notes_body_style)]],
                colWidths=[pagesize[0] - 0.9 * inch]
            )
            notes_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 1), (-1, 1), HexColor("#f7f7f8")),
                ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#d0d0d5")),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LINEABOVE", (0, 1), (-1, 1), 0.25, HexColor("#e2e2e7")),
            ]))
            elements.append(notes_tbl)
            elements.append(Spacer(1, 6))

    def _page_footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(HexColor("#888888"))
        canvas.drawString(0.55 * inch, 0.3 * inch,
                          f"Comparison across {len(analyses)} simulations")
        canvas.drawRightString(pagesize[0] - 0.55 * inch, 0.3 * inch, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(elements, onFirstPage=_page_footer, onLaterPages=_page_footer)
    buf.seek(0)
    return buf


@app.route("/api/simulations/<sim_id>/analyze/pdf")
def api_analysis_pdf(sim_id):
    """Generate a PDF of the analysis for a single sim."""
    path = _sim_path(sim_id)
    if not os.path.exists(path):
        return jsonify({"error": "Simulation not found"}), 404
    try:
        with open(path, "r", encoding="utf-8") as f:
            sim = json.load(f)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    last_opened = sim.get("lastOpenedAt", "")
    cache = _get_analysis_cache(sim_id)
    if cache and cache.get("generatedAt", "") >= last_opened:
        cache["simName"] = sim.get("name", cache.get("simName", ""))
        cache["ticker"] = sim.get("ticker", cache.get("ticker", ""))

        cache["notes"] = sim.get("notes", cache.get("notes", "")) or ""
        analysis = cache
    else:
        try:
            analysis = compute_analysis(sim)
            _save_analysis_cache(sim_id, analysis)
            _rebuild_sim_index()
        except ValueError as e:
            return jsonify({"error": str(e), "insufficient": True}), 422

    try:
        buf = _build_analysis_pdf(analysis)
    except Exception as e:
        return jsonify({"error": f"PDF generation failed: {e}"}), 500
    safe_name = _safe_filename(analysis.get("simName") or sim_id)
    return send_file(buf, mimetype="application/pdf", as_attachment=True,
                     download_name=f"{safe_name}_analysis.pdf")


@app.route("/api/simulations/compare/pdf", methods=["POST"])
def api_compare_pdf():
    """Generate a PDF comparison of 2-5 sims."""
    body = request.get_json(silent=True) or {}
    ids = body.get("ids") or []
    if not ids or len(ids) < 2:
        return jsonify({"error": "need at least 2 simulation ids"}), 400
    if len(ids) > 5:
        return jsonify({"error": "maximum 5 simulations"}), 400
    analyses = []
    for sid in ids:
        path = _sim_path(sid)
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                sim = json.load(f)
            last_opened = sim.get("lastOpenedAt", "")
            cache = _get_analysis_cache(sid)
            if cache and cache.get("generatedAt", "") >= last_opened:
                cache["simName"] = sim.get("name", cache.get("simName", ""))
                cache["ticker"] = sim.get("ticker", cache.get("ticker", ""))

                cache["notes"] = sim.get("notes", cache.get("notes", "")) or ""
                analyses.append(cache)
            else:
                a = compute_analysis(sim)
                _save_analysis_cache(sid, a)
                _rebuild_sim_index()
                analyses.append(a)
        except Exception:
            continue
    if len(analyses) < 2:
        return jsonify({"error": "need at least 2 analyzable simulations"}), 400
    try:
        buf = _build_compare_pdf(analyses)
    except Exception as e:
        return jsonify({"error": f"PDF generation failed: {e}"}), 500
    return send_file(buf, mimetype="application/pdf", as_attachment=True,
                     download_name="comparison.pdf")


# ==============================================
# SIM DUPLICATE / IMPORT / BATCH EXPORT
# ==============================================

def _safe_filename(name):
    safe = "".join(c if c.isalnum() or c in " -_." else "_" for c in (name or "sim"))
    return safe.strip() or "sim"


@app.route("/api/simulations/<sim_id>/duplicate", methods=["POST"])
def api_simulation_duplicate(sim_id):
    path = _sim_path(sim_id)
    if not os.path.exists(path):
        return jsonify({"error": "Simulation not found"}), 404
    try:
        with open(path, "r", encoding="utf-8") as f:
            sim = json.load(f)
        data = request.get_json(silent=True) or {}
        new_name = data.get("name") or f"{sim.get('name', 'Untitled')} (copy)"
        new_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        sim["id"] = new_id
        sim["name"] = new_name
        sim["created"] = now
        sim["modified"] = now
        with open(_sim_path(new_id), "w", encoding="utf-8") as f:
            json.dump(sim, f, ensure_ascii=False, indent=2)
        _rebuild_sim_index()
        return jsonify(sim), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/simulations/export-batch", methods=["POST"])
def api_simulations_export_batch():
    data = request.get_json(silent=True) or {}
    ids = data.get("ids") or []
    if not ids:
        return jsonify({"error": "no ids provided"}), 400
    sims = []
    for sid in ids:
        p = _sim_path(sid)
        if not os.path.exists(p):
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                sims.append(json.load(f))
        except Exception:
            continue
    if not sims:
        return jsonify({"error": "no valid simulations found"}), 404
    if len(sims) == 1:
        s = sims[0]
        body = json.dumps(s, ensure_ascii=False, indent=2)
        fname = f"{_safe_filename(s.get('name', s.get('id')))}.json"
        return Response(body, mimetype="application/json",
                        headers={"Content-Disposition": f"attachment; filename={fname}"})
    # Multiple — zip them
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for s in sims:
            fname = f"{_safe_filename(s.get('name', s.get('id')))}.json"
            zf.writestr(fname, json.dumps(s, ensure_ascii=False, indent=2))
    buf.seek(0)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=f"simulations_{ts}.zip")


@app.route("/api/simulations/import", methods=["POST"])
def api_simulations_import():
    _ensure_sim_dir()
    if "file" not in request.files:
        return jsonify({"error": "no file uploaded"}), 400
    f = request.files["file"]
    fname = (f.filename or "").lower()
    imported = []
    existing_names = set()
    for sid in os.listdir(SIMULATIONS_DIR):
        if sid.endswith(".json") and sid != "index.json":
            try:
                with open(os.path.join(SIMULATIONS_DIR, sid), "r", encoding="utf-8") as rf:
                    existing_names.add(json.load(rf).get("name", ""))
            except Exception:
                pass

    def _ingest(sim):
        # Assign new id to avoid conflicts with existing sims
        new_id = str(uuid.uuid4())
        sim["id"] = new_id
        orig_name = sim.get("name", "Imported")
        name = orig_name
        n = 1
        while name in existing_names:
            n += 1
            name = f"{orig_name} ({n})"
        sim["name"] = name
        existing_names.add(name)
        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        sim["modified"] = now
        if not sim.get("created"):
            sim["created"] = now
        # Treat an import as an open — friend's first view should compute a fresh analysis
        sim["lastOpenedAt"] = now
        with open(_sim_path(new_id), "w", encoding="utf-8") as wf:
            json.dump(sim, wf, ensure_ascii=False, indent=2)
        imported.append({
            "id": new_id, "name": name,
            "ticker": sim.get("ticker", ""),
            "secondarySymbol": (sim.get("tradePrefs") or {}).get("secondarySymbol", ""),
            "startDate": (sim.get("config") or {}).get("startDate"),
            "currentBarIndex": (sim.get("playbackState") or {}).get("currentBarIndex", 0),
        })

    try:
        if fname.endswith(".zip"):
            data = f.read()
            with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
                for n in zf.namelist():
                    if not n.endswith(".json"):
                        continue
                    try:
                        sim = json.loads(zf.read(n).decode("utf-8"))
                        _ingest(sim)
                    except Exception:
                        continue
        elif fname.endswith(".json"):
            sim = json.loads(f.read().decode("utf-8"))
            _ingest(sim)
        else:
            return jsonify({"error": "file must be .json or .zip"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    _rebuild_sim_index()
    return jsonify({"imported": imported, "count": len(imported)})


# ==============================================
# TEMPLATES
# ==============================================

def _ensure_templates_dir():
    os.makedirs(TEMPLATES_DIR, exist_ok=True)


def _template_path(tid):
    return os.path.join(TEMPLATES_DIR, f"{tid}.json")


@app.route("/api/templates", methods=["GET"])
def api_templates_list():
    _ensure_templates_dir()
    items = []
    for fn in os.listdir(TEMPLATES_DIR):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(TEMPLATES_DIR, fn), "r", encoding="utf-8") as f:
                t = json.load(f)
            items.append({
                "id": t.get("id", fn[:-5]),
                "name": t.get("name", ""),
                "created": t.get("created", ""),
                "modified": t.get("modified", ""),
            })
        except Exception:
            continue
    items.sort(key=lambda x: x.get("modified", ""), reverse=True)
    return jsonify(items)


@app.route("/api/templates", methods=["POST"])
def api_templates_create():
    _ensure_templates_dir()
    data = request.get_json(silent=True) or {}
    tid = str(uuid.uuid4())
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    tpl = {
        "id": tid,
        "name": data.get("name", "Untitled"),
        "created": now,
        "modified": now,
        "chartState": data.get("chartState", {}),
        "indicators": data.get("indicators", {}),
        "tradePrefs": data.get("tradePrefs", {}),
        "secondary": data.get("secondary", {}),
    }
    with open(_template_path(tid), "w", encoding="utf-8") as f:
        json.dump(tpl, f, ensure_ascii=False, indent=2)
    return jsonify(tpl), 201


@app.route("/api/templates/<tid>", methods=["GET"])
def api_template_get(tid):
    p = _template_path(tid)
    if not os.path.exists(p):
        return jsonify({"error": "Template not found"}), 404
    with open(p, "r", encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.route("/api/templates/<tid>", methods=["PUT"])
def api_template_update(tid):
    p = _template_path(tid)
    if not os.path.exists(p):
        return jsonify({"error": "Template not found"}), 404
    with open(p, "r", encoding="utf-8") as f:
        existing = json.load(f)
    data = request.get_json(silent=True) or {}
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    existing["name"] = data.get("name", existing.get("name", "Untitled"))
    existing["modified"] = now
    existing["chartState"] = data.get("chartState", existing.get("chartState", {}))
    existing["indicators"] = data.get("indicators", existing.get("indicators", {}))
    existing["tradePrefs"] = data.get("tradePrefs", existing.get("tradePrefs", {}))
    existing["secondary"] = data.get("secondary", existing.get("secondary", {}))
    with open(p, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    return jsonify(existing)


@app.route("/api/templates/<tid>", methods=["DELETE"])
def api_template_delete(tid):
    p = _template_path(tid)
    if not os.path.exists(p):
        return jsonify({"error": "Template not found"}), 404
    os.remove(p)
    return jsonify({"ok": True})


# ==============================================
# YAHOO FINANCE DATA DOWNLOAD
# ==============================================
# Uses the public /v8/finance/chart endpoint (no API key).
# All OHLC values are stored as split-adjusted (matches Yahoo quote.close).

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"
YAHOO_UA = "Mozilla/5.0 (compatible; MomentumTradingSimulator/1.0)"

PRIMARY_STOCKS_DIR = STOCKS_DIRS[0]


def _yahoo_http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": YAHOO_UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _ts_to_iso(ts):
    return time.strftime("%Y-%m-%d", time.gmtime(int(ts)))


def _iso_to_ts(s):
    # s is YYYY-MM-DD — interpret as UTC midnight
    return int(datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def _yahoo_meta(symbol):
    """Fetch minimal metadata for a ticker (existence + date range + exchange)."""
    url = f"{YAHOO_CHART_URL}{urllib.parse.quote(symbol)}?range=1d&interval=1d"
    try:
        data = _yahoo_http_get(url, timeout=15)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"exists": False, "error": "not found"}
        return {"exists": False, "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"exists": False, "error": str(e)}

    chart = (data or {}).get("chart") or {}
    if chart.get("error"):
        err = chart["error"]
        return {"exists": False, "error": err.get("description") or err.get("code") or "unknown"}

    results = chart.get("result") or []
    if not results:
        return {"exists": False, "error": "no results"}

    meta = results[0].get("meta") or {}
    first = meta.get("firstTradeDate")
    last = meta.get("regularMarketTime")
    return {
        "exists": True,
        "symbol": meta.get("symbol") or symbol.upper(),
        "firstTradeDate": _ts_to_iso(first) if first else None,
        "lastDate": _ts_to_iso(last) if last else None,
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
        "currency": meta.get("currency"),
        "instrumentType": meta.get("instrumentType"),
    }


def _yahoo_fetch_bars(symbol, start_iso, end_iso):
    """
    Fetch daily bars [start_iso, end_iso] inclusive from Yahoo.
    Returns list of dicts {time, open, high, low, close, volume}.
    """
    p1 = _iso_to_ts(start_iso)
    # pad end by 1 day so same-day bar is included
    p2 = _iso_to_ts(end_iso) + 86400
    url = (
        f"{YAHOO_CHART_URL}{urllib.parse.quote(symbol)}"
        f"?period1={p1}&period2={p2}&interval=1d"
    )
    data = _yahoo_http_get(url, timeout=30)
    chart = (data or {}).get("chart") or {}
    if chart.get("error"):
        err = chart["error"]
        raise RuntimeError(err.get("description") or err.get("code") or "yahoo error")
    results = chart.get("result") or []
    if not results:
        return []
    res = results[0]
    ts = res.get("timestamp") or []
    ind = (res.get("indicators") or {}).get("quote") or [{}]
    q = ind[0] if ind else {}
    o = q.get("open") or []
    h = q.get("high") or []
    low = q.get("low") or []
    c = q.get("close") or []
    v = q.get("volume") or []

    bars = []
    for i, t in enumerate(ts):
        if i >= len(c) or c[i] is None:
            continue
        if i >= len(o) or i >= len(h) or i >= len(low):
            continue
        if o[i] is None or h[i] is None or low[i] is None:
            continue
        bars.append({
            "time": _ts_to_iso(t),
            "open": round(float(o[i]), 4),
            "high": round(float(h[i]), 4),
            "low":  round(float(low[i]), 4),
            "close": round(float(c[i]), 4),
            "volume": int(v[i]) if (i < len(v) and v[i] is not None) else 0,
        })
    return bars


def _ticker_csv_path(symbol):
    return os.path.join(PRIMARY_STOCKS_DIR, f"{symbol.upper()}.csv")


def _find_existing_ticker_csv(symbol):
    """Return path if a CSV for symbol exists in any configured dir, else None."""
    for d in STOCKS_DIRS:
        for fname in (f"{symbol.upper()}.csv", f"{symbol.lower()}.csv"):
            p = os.path.join(d, fname)
            if os.path.exists(p):
                return p
    return None


def _read_ticker_bars(symbol):
    """Read existing bars for a symbol (same parsing as /api/ohlcv). Returns list of dicts."""
    path = _find_existing_ticker_csv(symbol)
    if not path:
        return []
    bars = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                return []
            if len(header) >= 2 and "date" in (header[1] or "").lower():
                fmt = "new"
            elif "date" in (header[0] or "").lower():
                fmt = "noindex"
            else:
                fmt = "old"
            for row in reader:
                try:
                    if fmt == "new":
                        if len(row) < 7: continue
                        t = _normalize_date_maybe(row[1])
                        o, h, l, c, v = float(row[2]), float(row[3]), float(row[4]), float(row[5]), float(row[6])
                    elif fmt == "noindex":
                        if len(row) < 6: continue
                        t = _normalize_date_maybe(row[0])
                        o, h, l, c, v = float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])
                    else:
                        if len(row) < 6: continue
                        t = _normalize_date_maybe(row[0])
                        c, o, h, l, v = float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])
                    bars.append({"time": t, "open": o, "high": h, "low": l, "close": c, "volume": v})
                except (ValueError, IndexError):
                    continue
    except Exception:
        return []
    return bars


def _write_ticker_csv_new_format(path, bars):
    """Write bars in the 'new' format: Unnamed: 0,DateTime,Open,High,Low,Close,Volume."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Unnamed: 0", "DateTime", "Open", "High", "Low", "Close", "Volume"])
        for i, b in enumerate(bars):
            w.writerow([
                float(i), b["time"],
                round(float(b["open"]), 4),
                round(float(b["high"]), 4),
                round(float(b["low"]),  4),
                round(float(b["close"]),4),
                int(b["volume"]) if b["volume"] is not None else 0,
            ])


def _merge_bars(existing, new_bars):
    """Merge two bar lists by date. New bars override existing on date collisions."""
    by_date = {b["time"]: b for b in existing}
    for nb in new_bars:
        by_date[nb["time"]] = nb
    merged = [by_date[d] for d in sorted(by_date.keys())]
    return merged


def _download_and_save(symbol, start_iso, end_iso, mode="merge"):
    """
    Download bars from Yahoo and save to collected_stocks/{SYMBOL}.csv.
    Returns a summary dict.
    """
    symbol = symbol.upper()
    new_bars = _yahoo_fetch_bars(symbol, start_iso, end_iso)

    path = _find_existing_ticker_csv(symbol) or _ticker_csv_path(symbol)

    if mode == "overwrite" or not os.path.exists(path):
        final = new_bars
    else:
        existing = _read_ticker_bars(symbol)
        final = _merge_bars(existing, new_bars)

    if not final:
        return {"symbol": symbol, "bars_fetched": len(new_bars), "bars_total": 0, "first": None, "last": None, "written": False}

    _write_ticker_csv_new_format(path, final)
    # invalidate ranges cache so UI sees new bounds
    global _TICKER_RANGES_CACHE
    _TICKER_RANGES_CACHE = None

    return {
        "symbol": symbol,
        "path": os.path.relpath(path, SCRIPT_DIR),
        "bars_fetched": len(new_bars),
        "bars_total": len(final),
        "first": final[0]["time"],
        "last": final[-1]["time"],
        "written": True,
    }


@app.route("/api/data/check", methods=["POST"])
def api_data_check():
    """Check local data availability for a list of symbols."""
    body = request.get_json(silent=True) or {}
    symbols = body.get("symbols") or []
    results = {}
    for sym in symbols:
        sym = (sym or "").strip().upper()
        if not sym or sym in results:
            continue
        bars = _read_ticker_bars(sym)
        if bars:
            results[sym] = {"exists": True, "first": bars[0]["time"], "last": bars[-1]["time"], "bars": len(bars)}
        else:
            results[sym] = {"exists": False}
    return jsonify(results)


# ---------- HTTP endpoints ----------

@app.route("/api/yahoo/ping")
def api_yahoo_ping():
    return jsonify({"ok": True, "version": "yahoo-v1"})


@app.route("/api/yahoo/info")
def api_yahoo_info():
    symbol = (request.args.get("symbol") or "").strip().upper()
    if not symbol:
        return jsonify({"error": "symbol required"}), 400

    meta = _yahoo_meta(symbol)
    local_bars = _read_ticker_bars(symbol)
    local = None
    if local_bars:
        local = {
            "exists": True,
            "first": local_bars[0]["time"],
            "last": local_bars[-1]["time"],
            "bars": len(local_bars),
            "path": os.path.relpath(_find_existing_ticker_csv(symbol), SCRIPT_DIR),
        }
    else:
        local = {"exists": False}
    return jsonify({"symbol": symbol, "yahoo": meta, "local": local})


@app.route("/api/yahoo/download", methods=["POST"])
def api_yahoo_download():
    body = request.get_json(silent=True) or {}
    symbol = (body.get("symbol") or "").strip().upper()
    if not symbol:
        return jsonify({"error": "symbol required"}), 400
    start = (body.get("start") or "").strip()
    end = (body.get("end") or "").strip()
    mode = (body.get("mode") or "merge").strip().lower()

    if not start or not end:
        meta = _yahoo_meta(symbol)
        if not meta.get("exists"):
            return jsonify({"error": f"symbol not found on Yahoo: {meta.get('error') or symbol}"}), 404
        if not start: start = meta.get("firstTradeDate") or "2000-01-03"
        if not end:   end = meta.get("lastDate") or _ts_to_iso(time.time())

    try:
        summary = _download_and_save(symbol, start, end, mode=mode)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify(summary)


# ---------- Background "update all" job ----------

_JOBS = {}
_JOBS_LOCK = threading.Lock()


def _list_local_tickers():
    syms = set()
    for d in STOCKS_DIRS:
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            if f.lower().endswith(".csv"):
                syms.add(os.path.splitext(f)[0].upper())
    return sorted(syms)


def _job_update_all(job_id, symbols, throttle_sec=0.1):
    job = _JOBS[job_id]
    today_iso = _ts_to_iso(time.time())

    for i, sym in enumerate(symbols):
        if job["cancel"].is_set():
            job["status"] = "canceled"
            job["finished_at"] = time.time()
            return
        job["current"] = sym
        job["progress"] = i

        try:
            existing = _read_ticker_bars(sym)
            if existing:
                start = existing[-1]["time"]  # re-fetch last local bar (overwrites with fresh data)
            else:
                meta = _yahoo_meta(sym)
                if not meta.get("exists"):
                    job["errors"].append({"symbol": sym, "error": meta.get("error") or "not found"})
                    continue
                start = meta.get("firstTradeDate") or "2000-01-03"

            if start > today_iso:
                job["unchanged"].append(sym)
                continue

            summary = _download_and_save(sym, start, today_iso, mode="merge")
            new_count = max(0, summary["bars_total"] - len(existing))
            if new_count > 0:
                job["updated"].append({"symbol": sym, "new_bars": new_count, "last": summary["last"]})
            else:
                job["unchanged"].append(sym)
        except Exception as e:
            job["errors"].append({"symbol": sym, "error": str(e)})

        if throttle_sec > 0:
            time.sleep(throttle_sec)

    job["progress"] = len(symbols)
    job["current"] = None
    job["status"] = "done"
    job["finished_at"] = time.time()


@app.route("/api/yahoo/update_all", methods=["POST"])
def api_yahoo_update_all():
    body = request.get_json(silent=True) or {}
    # Optional: restrict to a subset
    only = body.get("symbols")
    if only and isinstance(only, list):
        symbols = [s.strip().upper() for s in only if s and isinstance(s, str)]
    else:
        symbols = _list_local_tickers()

    if not symbols:
        return jsonify({"error": "no tickers to update"}), 400

    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "status": "running",
        "total": len(symbols),
        "progress": 0,
        "current": None,
        "updated": [],
        "unchanged": [],
        "errors": [],
        "started_at": time.time(),
        "finished_at": None,
        "cancel": threading.Event(),
    }
    with _JOBS_LOCK:
        _JOBS[job_id] = job

    t = threading.Thread(target=_job_update_all, args=(job_id, symbols), daemon=True)
    t.start()
    return jsonify({"job_id": job_id, "total": len(symbols)})


def _job_to_json(job):
    return {
        "id": job["id"],
        "status": job["status"],
        "total": job["total"],
        "progress": job["progress"],
        "current": job["current"],
        "updated": job["updated"],
        "unchanged": job["unchanged"],
        "errors": job["errors"],
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
    }


@app.route("/api/yahoo/job/<job_id>")
def api_yahoo_job(job_id):
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404
    return jsonify(_job_to_json(job))


@app.route("/api/yahoo/job/<job_id>/cancel", methods=["POST"])
def api_yahoo_job_cancel(job_id):
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404
    job["cancel"].set()
    return jsonify({"ok": True})


PORT = 5051


def _pids_on_port(port):
    """Return PIDs (excluding self) listening on the given local port."""
    pids = set()
    try:
        if sys.platform == "win32":
            out = subprocess.check_output(
                ["netstat", "-ano", "-p", "TCP"],
                text=True, stderr=subprocess.DEVNULL,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and "LISTENING" in parts and (f":{port}" in parts[1]):
                    try:
                        pid = int(parts[-1])
                        if pid != os.getpid():
                            pids.add(pid)
                    except ValueError:
                        pass
        else:
            out = subprocess.check_output(
                ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
                text=True, stderr=subprocess.DEVNULL,
            )
            for tok in out.split():
                try:
                    pid = int(tok)
                    if pid != os.getpid():
                        pids.add(pid)
                except ValueError:
                    pass
    except Exception:
        pass
    return pids


def _kill_pid(pid):
    try:
        if sys.platform == "win32":
            subprocess.call(
                ["taskkill", "/F", "/PID", str(pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=0x08000000,
            )
        else:
            os.kill(pid, signal.SIGKILL)
    except Exception:
        pass


def _reap_stale_servers(port):
    """Kill anything currently holding the port so we start from a clean slate."""
    victims = _pids_on_port(port)
    if not victims:
        return
    print(f"[cleanup] killing stale listener(s) on :{port}: {sorted(victims)}")
    for pid in victims:
        _kill_pid(pid)
    # brief wait for the OS to release the socket
    for _ in range(20):
        if not _pids_on_port(port):
            break
        time.sleep(0.1)


def _cancel_all_jobs():
    try:
        with _JOBS_LOCK:
            for job in _JOBS.values():
                try: job["cancel"].set()
                except Exception: pass
    except Exception:
        pass


_SHUTDOWN_ONCE = threading.Event()
def _handle_shutdown_signal(signum, _frame):
    if _SHUTDOWN_ONCE.is_set():
        # second Ctrl+C → force exit immediately
        os._exit(130)
    _SHUTDOWN_ONCE.set()
    print(f"\n[shutdown] signal {signum} received — canceling jobs and exiting…")
    _cancel_all_jobs()
    # give daemon threads a moment, then hard-exit so no zombie remains
    def _finish():
        time.sleep(0.5)
        os._exit(0)
    threading.Thread(target=_finish, daemon=True).start()


if __name__ == "__main__":
    _ensure_sim_dir()
    _ensure_templates_dir()

    _reap_stale_servers(PORT)

    signal.signal(signal.SIGINT, _handle_shutdown_signal)
    try:
        signal.signal(signal.SIGTERM, _handle_shutdown_signal)
    except (AttributeError, ValueError):
        pass
    if sys.platform == "win32":
        try:
            signal.signal(signal.SIGBREAK, _handle_shutdown_signal)
        except (AttributeError, ValueError):
            pass

    print(f"Momentum Trading Simulator: http://localhost:{PORT}/   (PID {os.getpid()})")
    yahoo_routes = sorted(str(r) for r in app.url_map.iter_rules() if "/api/yahoo" in str(r))
    print(f"Yahoo data routes ({len(yahoo_routes)}):")
    for rt in yahoo_routes:
        print(f"  {rt}")
    try:
        app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
    except KeyboardInterrupt:
        pass
    finally:
        _cancel_all_jobs()
        # ensure the process truly exits even if werkzeug leaves threads behind
        os._exit(0)