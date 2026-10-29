"""Standalone Photon browser workspace. Public market data; no exchange orders."""
from __future__ import annotations

import argparse
import json
import re
import secrets
import threading
import time
import tempfile
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen

from .photon_structure import MODE, aggregate_closed, build_mapping, map_structure, valid_bar
from .photon_zones import attach_ranges, build_zones

INTERVALS = {"1m": 60, "15m": 900, "4h": 14400, "1d": 86400, "1w": 604800}
CACHE_DIR = Path(__file__).resolve().parents[1] / "cache" / "photon_browser"


def public_json(path, **params):
    with urlopen("https://fapi.binance.com/fapi/v1/" + path + "?" + urlencode(params), timeout=25) as response:
        return json.load(response)


def history(symbol, interval, start, end):
    """Page bounded history and exclude the unfinished candle from structure."""
    result = {}
    cursor = int(start * 1000)
    while cursor < end * 1000:
        rows = public_json("klines", symbol=symbol, interval=interval, startTime=cursor,
                           endTime=int(end * 1000) - 1, limit=1000)
        if not rows:
            break
        for row in rows:
            if row[6] < end * 1000:
                result[row[0]] = dict(time=row[0] // 1000, **{
                    key: float(row[i]) for i, key in enumerate(("open", "high", "low", "close"), 1)})
        next_cursor = int(rows[-1][0]) + INTERVALS[interval] * 1000
        if next_cursor <= cursor:
            raise ValueError("Binance history did not advance")
        cursor = next_cursor
        if len(rows) < 1000:
            break
    return list(result.values())


class LiveMarket:
    def __init__(self, symbol):
        if not re.fullmatch(r"[A-Z0-9]{5,24}", symbol):
            raise ValueError("Choose a valid Binance Futures symbol")
        self.symbol = symbol
        self.lock = threading.Lock()
        self.frames = {}
        self.mapping = None
        self.mapping_at = None
        self.minute_at = None
        self.start = int(time.time() // 86400 * 86400) - 60 * 86400

    def frame(self, interval, end):
        old = self.frames.get(interval, [])
        boundary = end - 730 * 86400 if interval == "1d" else end - 3 * 86400 if interval == "1m" else self.start
        cache = CACHE_DIR / f"{self.symbol}_{interval}.json"
        if interval not in self.frames:
            try:
                saved = json.loads(cache.read_text())
                old = sorted([b for b in saved if valid_bar(b) and boundary <= b["time"] < end], key=lambda b:b["time"])
            except (OSError, ValueError, TypeError, KeyError):
                old = []
        start = old[-1]["time"] if old else boundary
        fresh = history(self.symbol, interval, start, end)
        joined = {bar["time"]: bar for bar in old + fresh}
        # Keep the original warmup boundary stable during this server session.
        self.frames[interval] = [joined[t] for t in sorted(joined) if t >= boundary]
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", dir=CACHE_DIR, delete=False, suffix=".tmp") as handle:
                json.dump(self.frames[interval], handle, separators=(",", ":"))
                temporary = Path(handle.name)
            temporary.replace(cache)
        except OSError:
            pass  # Read-only installations can use the in-memory cache.
        return self.frames[interval]

    def payload(self, timeframe):
        if timeframe not in INTERVALS:
            raise ValueError("Unsupported chart timeframe")
        with self.lock:
            # Exchange time determines which candles have really closed.
            now = int(public_json("time")["serverTime"] // 1000)
            end = now // 900 * 900
            if self.mapping_at != end:
                bars = self.frame("15m", end)
                daily = self.frame("1d", now // 86400 * 86400)
                mapping = build_mapping(bars)
                for tf, native in (("1d", daily), ("1w", aggregate_closed(daily, 86400, 604800, 345600))):
                    guide = map_structure(native, INTERVALS[tf], qualification="CHOCH_PULLBACK")
                    attach_ranges(guide)
                    if tf == "1d":
                        zones = build_zones(bars, native, guide, tf)
                        # A daily zone born before available 15m history has
                        # unknown visits/invalidation. Do not call it fresh.
                        zones["zones"] = [z for z in zones["zones"] if bars and z["availableAt"] >= bars[0]["time"]]
                        known = {z["id"] for z in zones["zones"]}
                        zones["events"] = [e for e in zones["events"] if e.get("zoneId") in known]
                        guide["supplyDemand"] = zones
                    mapping["timeframes"][tf] = guide
                self.mapping, self.mapping_at = mapping, end
            mapping = self.mapping
            if timeframe == "1m":
                minute_end = now // 60 * 60
                if self.minute_at != minute_end:
                    minute = self.frame("1m", minute_end)
                    guide = map_structure(minute, 60, qualification="CHOCH_PULLBACK")
                    attach_ranges(guide)
                    guide["historyStart"] = minute[0]["time"] if minute else None
                    self.minute_guide, self.minute_at = guide, minute_end
                bars = self.frames["1m"]
                mapping = {**mapping, "timeframes": {**mapping["timeframes"], "1m": self.minute_guide}}
            elif timeframe == "15m":
                bars = self.frames["15m"]
            elif timeframe == "4h":
                bars = aggregate_closed(self.frames["15m"], target_seconds=14400)
            elif timeframe == "1d":
                bars = self.frames["1d"]
            else:
                bars = aggregate_closed(self.frames["1d"], 86400, 604800, 345600)
            return dict(run=dict(runId="photon-live-" + self.symbol, symbol=self.symbol,
                                 timeframe="15m", availableChartTimeframes=available()),
                        selectedTrade={}, selectedTradeIndex=None, selectedTradeCandleTime=None,
                        selectedTradeChartCandleTime=None, selectedTradeViewStart=bars[0]["time"] if bars else None,
                        selectedTradeViewEnd=bars[-1]["time"] if bars else None,
                        candles=bars, overlays=[], markers=[], chartTimeframe=timeframe,
                        fullRun=True, photonMapping=mapping, serverTime=now,
                        historyNote="15m/4H: 60-day initial warmup; daily/weekly: 730 days; 1m: 3 days. Earlier unavailable structure stays unknown.")


def available():
    return [dict(interval=tf, coverage="full") for tf in INTERVALS]


def browser_html(symbol, token):
    from .strategy_visualizer_browser_v2 import build_browser_visualizer_v2_html
    model = SimpleNamespace(seed=SimpleNamespace(request=SimpleNamespace(symbol=symbol, strategy_timeframe="15m"),
        config=SimpleNamespace(strategy=SimpleNamespace(profiles={"long": SimpleNamespace(entry_rules=[{"_strategy_direction_mode": MODE}])}))),
        trade_count=0, manifest={"run_id": "photon-live-" + symbol}, run_dir=Path("photon-live"))
    html = build_browser_visualizer_v2_html(model, token)
    assets = Path(__file__).with_name("photon_live_web")
    css = (assets / "workspace.css").read_text(encoding="utf-8")
    js = (assets / "workspace.js").read_text(encoding="utf-8")
    # Keep all replay/drawing ownership in the existing workspace. No Qt model is constructed.
    html = html.replace("<title>CSL · Chart workspace</title>", "<title>Photon · Binance Futures</title>")
    html = html.replace("</head>", "<style>" + css + "</style></head>")
    html = html.replace("const q = new URLSearchParams(params);", "const q = new URLSearchParams(params);q.set('symbol',boot.run.symbol);")
    html = html.replace("return cachedChartPayload(JSON.stringify([tradeIndex,timeframe]));",
                        "return getJson(api('/api/payload',{chart_timeframe:timeframe}));")
    html = html.replace("  load();\n})();", js + "\n  load();\n})();")
    html = html.replace("background:{type:'solid',color:'#131722'}", "background:{type:'solid',color:'#ffffff'}")
    html = html.replace("textColor:'#9598a1'", "textColor:'#131722'")
    html = html.replace("color:'#202430'", "color:'#f0f3f6'")
    html = html.replace("tf==='4h'?'#f8fafc'", "tf==='4h'?'#374151'")
    html = html.replace("tf==='4h'?'#e2e8f0'", "tf==='4h'?'#374151'")
    return html


def serve(port=8917, symbol="BTCUSDT", open_browser=True):
    token = secrets.token_urlsafe(24)
    markets = {}
    markets_lock = threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        server_version = "PhotonLive/1.0"
        def log_message(self, *_):
            pass
        def do_GET(self):
            origin = self.headers.get("Origin")
            host = self.headers.get("Host", "")
            expected = f"127.0.0.1:{self.server.server_address[1]}"
            if host != expected or origin not in (None, "http://" + expected):
                self.send_error(403)
                return
            parsed = urlsplit(self.path)
            prefix = "/session/" + token
            if parsed.path == "/":
                self.send_response(303)
                self.send_header("Location", prefix + "/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            query = parse_qs(parsed.query)
            chosen = query.get("symbol", [symbol])[0].upper()
            status = 200
            try:
                if not re.fullmatch(r"[A-Z0-9]{5,24}", chosen):
                    raise ValueError("Invalid symbol")
                if parsed.path.rstrip("/") == prefix:
                    body, kind = browser_html(chosen, token).encode(), "text/html"
                elif parsed.path == prefix + "/api/payload":
                    with markets_lock:
                        # Bound per-process memory when switching between many symbols.
                        if chosen not in markets:
                            if len(markets) >= 3:
                                markets.pop(next(iter(markets)))
                            markets[chosen] = LiveMarket(chosen)
                        market = markets[chosen]
                    body = json.dumps(market.payload(query.get("chart_timeframe", ["15m"])[0]), allow_nan=False).encode()
                    kind = "application/json"
                elif parsed.path == prefix + "/review-report":
                    from .visualizer_review_report import build_review_report_html
                    body = build_review_report_html(dict(runId="photon-live-" + chosen, symbol=chosen, timeframe="15m"), prefix).encode()
                    kind = "text/html"
                elif parsed.path == prefix + "/api/review-comparison":
                    body, kind = b'{"trades":[]}', "application/json"
                else:
                    self.send_error(404)
                    return
            except Exception as error:
                status, kind = 502, "application/json"
                body = json.dumps({"error": str(error)}).encode()
            self.send_response(status)
            for name, value in (("Content-Type", kind + "; charset=utf-8"), ("Content-Length", str(len(body))),
                                ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff")):
                self.send_header(name, value)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionError):
                pass  # Navigation can cancel an in-flight history request.
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        if not port:
            raise
        # Reopening the launcher reuses this standalone service, without
        # disturbing another unrelated service that happens to own the port.
        with urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
            if not response.headers.get("Server", "").startswith("PhotonLive/"):
                raise RuntimeError(f"Port {port} is in use; choose another --port")
            url = response.geturl()
        print("Photon browser already running: " + url, flush=True)
        if open_browser:
            webbrowser.open(url)
        return
    url = f"http://127.0.0.1:{server.server_address[1]}/session/{token}/"
    print("Photon browser: " + url, flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8917)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    serve(args.port, args.symbol.upper(), not args.no_browser)
