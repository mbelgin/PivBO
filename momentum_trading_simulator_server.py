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

            index.append({
                "id": sim.get("id", fname[:-5]),
                "name": sim.get("name", ""),
                "ticker": sim.get("ticker", ""),
                "created": sim.get("created", ""),
                "modified": sim.get("modified", ""),
                "startingCapital": sim.get("config", {}).get("startingCapital", 0),
                "currentCapital": sim.get("analytics", {}).get("currentCapital", 0),
                "totalTrades": sim.get("analytics", {}).get("totalTrades", 0),
                "isComplete": is_complete,
                "progress": round(progress, 1),
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
    if not index:
        index = _rebuild_sim_index()
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
                     "tradePrefs"):
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