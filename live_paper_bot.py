"""Live Binance USD-M Futures volatility scanner and paper trader.

This module intentionally supports public market-data endpoints only.  It has
no API-key handling and no real-order method, which makes accidental live
execution impossible.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BINANCE_FUTURES_PUBLIC_API = "https://fapi.binance.com"
STABLE_BASE_ASSETS = {"USDC", "FDUSD", "TUSD", "USDP", "DAI", "BUSD", "USDE", "USD1"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PaperBotConfig:
    paper_equity: float = 1000.0
    risk_per_trade: float = 0.005
    max_positions: int = 2
    leverage_cap: float = 2.0
    scan_interval_seconds: int = 300
    candle_interval: str = "5m"
    candle_limit: int = 120
    preliminary_candidates: int = 30
    selected_candidates: int = 5
    minimum_24h_quote_volume: float = 20_000_000.0
    maximum_spread_pct: float = 0.003
    minimum_listing_days: int = 30
    atr_period: int = 14
    stop_atr_multiple: float = 2.0
    target_atr_multiple: float = 3.0
    maximum_holding_candles: int = 72
    taker_fee: float = 0.0005
    slippage: float = 0.0005
    strategies: list[str] = field(default_factory=lambda: ["breakout", "trend", "mean_reversion"])
    output_dir: str = "paper_output"

    @classmethod
    def load(cls, path: Path | None) -> "PaperBotConfig":
        if path is None:
            config = cls()
        else:
            values = json.loads(path.read_text(encoding="utf-8"))
            config = cls(**values)
        config.validate()
        return config

    def validate(self) -> None:
        if self.paper_equity <= 0 or not 0 < self.risk_per_trade < 1:
            raise ValueError("paper_equity must be positive and risk_per_trade must be between 0 and 1")
        if self.max_positions < 1 or self.leverage_cap <= 0:
            raise ValueError("max_positions and leverage_cap must be positive")
        if self.candle_limit < 60 or self.atr_period < 2:
            raise ValueError("candle_limit must be at least 60 and atr_period at least 2")
        allowed = {"breakout", "trend", "mean_reversion"}
        if not self.strategies or not set(self.strategies) <= allowed:
            raise ValueError(f"strategies must be selected from {sorted(allowed)}")


class BinancePublicClient:
    """Small read-only client for Binance USD-M Futures public endpoints."""

    def __init__(self, base_url: str = BINANCE_FUTURES_PUBLIC_API, timeout: int = 15):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get(self, endpoint: str, **params: Any) -> Any:
        query = f"?{urlencode(params)}" if params else ""
        request = Request(f"{self.base_url}{endpoint}{query}", headers={"User-Agent": "volatility-paper-bot/1.0"})
        with urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def exchange_info(self) -> dict[str, Any]:
        return self.get("/fapi/v1/exchangeInfo")

    def tickers_24h(self) -> list[dict[str, Any]]:
        return self.get("/fapi/v1/ticker/24hr")

    def book_tickers(self) -> list[dict[str, Any]]:
        return self.get("/fapi/v1/ticker/bookTicker")

    def klines(self, symbol: str, interval: str, limit: int) -> list[list[Any]]:
        return self.get("/fapi/v1/klines", symbol=symbol, interval=interval, limit=limit)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _pstdev(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = _mean(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def completed_candles(rows: list[list[Any]], now_ms: int | None = None) -> list[dict[str, float]]:
    """Normalize Binance klines and discard the still-forming candle."""
    now_ms = now_ms or int(time.time() * 1000)
    candles = []
    for row in rows:
        if len(row) < 7 or int(row[6]) >= now_ms:
            continue
        candles.append({
            "open_time": int(row[0]), "open": _float(row[1]), "high": _float(row[2]),
            "low": _float(row[3]), "close": _float(row[4]), "volume": _float(row[5]),
            "close_time": int(row[6]), "quote_volume": _float(row[7]) if len(row) > 7 else 0.0,
        })
    return candles


def atr(candles: list[dict[str, float]], period: int) -> float:
    if len(candles) < period + 1:
        return 0.0
    true_ranges = []
    for previous, current in zip(candles[-period - 1:-1], candles[-period:]):
        true_ranges.append(max(current["high"] - current["low"], abs(current["high"] - previous["close"]), abs(current["low"] - previous["close"])))
    return _mean(true_ranges)


def volatility_metrics(candles: list[dict[str, float]], atr_period: int) -> dict[str, float]:
    if len(candles) < 50 or candles[-1]["close"] <= 0:
        return {}
    closes = [c["close"] for c in candles]
    returns = [math.log(b / a) for a, b in zip(closes[-25:-1], closes[-24:]) if a > 0 and b > 0]
    if len(returns) < 20:
        return {}
    realized = _pstdev(returns) * math.sqrt(12)  # approximate hourly volatility for 5m data
    atr_pct = atr(candles, atr_period) / closes[-1]
    recent_range = (max(c["high"] for c in candles[-12:]) - min(c["low"] for c in candles[-12:])) / closes[-1]
    prior_ranges = [(c["high"] - c["low"]) / c["close"] for c in candles[-36:-12] if c["close"] > 0]
    range_expansion = ((candles[-1]["high"] - candles[-1]["low"]) / closes[-1]) / max(_median(prior_ranges), 1e-9)
    volume_recent = sum(c["quote_volume"] for c in candles[-12:])
    volume_prior = sum(c["quote_volume"] for c in candles[-24:-12])
    volume_ratio = volume_recent / max(volume_prior, 1.0)
    return {"realized_volatility": realized, "atr_pct": atr_pct, "recent_range_pct": recent_range,
            "range_expansion": range_expansion, "volume_ratio": volume_ratio}


def _percentile_ranks(values: list[float]) -> list[float]:
    if len(values) == 1:
        return [1.0]
    ordered = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    for rank, index in enumerate(ordered):
        ranks[index] = rank / (len(values) - 1)
    return ranks


class VolatilityScanner:
    def __init__(self, client: BinancePublicClient, config: PaperBotConfig):
        self.client, self.config = client, config

    def scan(self) -> list[dict[str, Any]]:
        info = self.client.exchange_info()
        now_ms = int(time.time() * 1000)
        eligible = {
            item["symbol"]: item for item in info.get("symbols", [])
            if item.get("status") == "TRADING" and item.get("contractType") == "PERPETUAL"
            and item.get("quoteAsset") == "USDT" and item.get("baseAsset") not in STABLE_BASE_ASSETS
            and now_ms - int(item.get("onboardDate", 0)) >= self.config.minimum_listing_days * 86_400_000
        }
        books = {row["symbol"]: row for row in self.client.book_tickers() if row.get("symbol") in eligible}
        preliminary = []
        for row in self.client.tickers_24h():
            symbol = row.get("symbol")
            if symbol not in eligible or _float(row.get("quoteVolume")) < self.config.minimum_24h_quote_volume:
                continue
            bid, ask = _float(books.get(symbol, {}).get("bidPrice")), _float(books.get(symbol, {}).get("askPrice"))
            mid = (bid + ask) / 2
            spread = (ask - bid) / mid if mid > 0 and ask >= bid else 1.0
            if spread > self.config.maximum_spread_pct:
                continue
            high, low, last = _float(row.get("highPrice")), _float(row.get("lowPrice")), _float(row.get("lastPrice"))
            preliminary.append({"symbol": symbol, "quote_volume_24h": _float(row.get("quoteVolume")),
                                "spread_pct": spread, "preliminary_range": (high - low) / last if last > 0 else 0.0})
        preliminary.sort(key=lambda x: (x["preliminary_range"], math.log1p(x["quote_volume_24h"])), reverse=True)
        candidates = []
        for item in preliminary[:self.config.preliminary_candidates]:
            candles = completed_candles(self.client.klines(item["symbol"], self.config.candle_interval, self.config.candle_limit))
            metrics = volatility_metrics(candles, self.config.atr_period)
            if metrics:
                candidates.append({**item, **metrics, "candles": candles})
        if not candidates:
            return []
        components = ["realized_volatility", "atr_pct", "recent_range_pct", "range_expansion", "volume_ratio"]
        weights = [0.30, 0.25, 0.20, 0.10, 0.15]
        scores = [0.0] * len(candidates)
        for component, weight in zip(components, weights):
            ranks = _percentile_ranks([c[component] for c in candidates])
            scores = [score + weight * rank for score, rank in zip(scores, ranks)]
        for candidate, score in zip(candidates, scores):
            candidate["volatility_score"] = score
        candidates.sort(key=lambda x: x["volatility_score"], reverse=True)
        return candidates[:self.config.selected_candidates]


@dataclass
class Position:
    position_id: str
    strategy: str
    symbol: str
    side: str
    entry_time: str
    entry_price: float
    quantity: float
    stop_price: float
    target_price: float
    entry_fee: float
    bars_held: int = 0
    last_candle_time: int = 0


def strategy_signal(strategy: str, candles: list[dict[str, float]]) -> str | None:
    """Return LONG/SHORT from completed candles only."""
    if len(candles) < 55:
        return None
    closes = [c["close"] for c in candles]
    current = closes[-1]
    if strategy == "breakout":
        upper = max(c["high"] for c in candles[-21:-1])
        lower = min(c["low"] for c in candles[-21:-1])
        return "LONG" if current > upper else "SHORT" if current < lower else None
    if strategy == "trend":
        ema_fast = _ema(closes[-40:], 12)
        ema_slow = _ema(closes[-55:], 26)
        momentum = current / closes[-7] - 1
        return "LONG" if ema_fast > ema_slow and momentum > 0.003 else "SHORT" if ema_fast < ema_slow and momentum < -0.003 else None
    sample = closes[-31:-1]
    mean, std = _mean(sample), _pstdev(sample)
    zscore = (current - mean) / std if std > 0 else 0.0
    return "SHORT" if zscore >= 2.0 else "LONG" if zscore <= -2.0 else None


def _ema(values: list[float], period: int) -> float:
    alpha, value = 2 / (period + 1), values[0]
    for item in values[1:]:
        value = alpha * item + (1 - alpha) * value
    return value


class PaperBroker:
    def __init__(self, config: PaperBotConfig, output_dir: Path):
        self.config, self.output_dir = config, output_dir
        self.state_path = output_dir / "state.json"
        self.strategy_equity = {strategy: config.paper_equity for strategy in config.strategies}
        self.positions: list[Position] = []
        self.last_entry_candle: dict[str, int] = {}
        self._load()

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        saved_equity = state.get("strategy_equity")
        if saved_equity:
            self.strategy_equity.update({key: float(value) for key, value in saved_equity.items() if key in self.strategy_equity})
        else:
            self.strategy_equity = {strategy: float(state["equity"]) for strategy in self.config.strategies}
        self.positions = [Position(**row) for row in state.get("positions", [])]
        self.last_entry_candle = {key: int(value) for key, value in state.get("last_entry_candle", {}).items()}

    def save(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        payload = {"equity": self.equity, "strategy_equity": self.strategy_equity,
                   "positions": [asdict(p) for p in self.positions],
                   "last_entry_candle": self.last_entry_candle, "updated_at": utc_now()}
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self.state_path)

    @property
    def equity(self) -> float:
        """Average paper equity, retained as a convenient overall headline."""
        return _mean(list(self.strategy_equity.values()))

    @equity.setter
    def equity(self, value: float) -> None:
        self.strategy_equity = {strategy: float(value) for strategy in self.config.strategies}

    def process(self, candidates: list[dict[str, Any]], position_market_data: dict[str, dict[str, Any]] | None = None) -> None:
        by_symbol = {candidate["symbol"]: candidate for candidate in candidates}
        by_symbol.update(position_market_data or {})
        self._update_positions(by_symbol)
        for candidate in candidates:
            for strategy in self.config.strategies:
                if sum(position.strategy == strategy for position in self.positions) >= self.config.max_positions:
                    continue
                signal = strategy_signal(strategy, candidate["candles"])
                key = f"{strategy}:{candidate['symbol']}"
                candle_time = int(candidate["candles"][-1]["close_time"])
                if signal and self.last_entry_candle.get(key) != candle_time and not any(p.strategy == strategy and p.symbol == candidate["symbol"] for p in self.positions):
                    self._open(strategy, signal, candidate)
                    self.last_entry_candle[key] = candle_time
        self.save()

    def _open(self, strategy: str, side: str, candidate: dict[str, Any]) -> None:
        candle = candidate["candles"][-1]
        raw_price, distance = candle["close"], candidate["atr_pct"] * candle["close"] * self.config.stop_atr_multiple
        entry = raw_price * (1 + self.config.slippage if side == "LONG" else 1 - self.config.slippage)
        strategy_equity = self.strategy_equity[strategy]
        risk_budget = strategy_equity * self.config.risk_per_trade
        quantity = min(risk_budget / max(distance, 1e-12), strategy_equity * self.config.leverage_cap / entry)
        stop = entry - distance if side == "LONG" else entry + distance
        target_distance = distance * self.config.target_atr_multiple / self.config.stop_atr_multiple
        target = entry + target_distance if side == "LONG" else entry - target_distance
        fee = entry * quantity * self.config.taker_fee
        self.strategy_equity[strategy] -= fee
        position = Position(f"{int(time.time()*1000)}-{strategy}-{candidate['symbol']}", strategy, candidate["symbol"], side,
                            utc_now(), entry, quantity, stop, target, fee,
                            last_candle_time=int(candle["close_time"]))
        self.positions.append(position)
        self._append("trades.csv", {**asdict(position), "event": "OPEN", "exit_time": "", "exit_price": "", "reason": "", "net_pnl": "", "equity": self.strategy_equity[strategy]})

    def _update_positions(self, candidates: dict[str, dict[str, Any]]) -> None:
        remaining = []
        for position in self.positions:
            candidate = candidates.get(position.symbol)
            if not candidate:
                remaining.append(position)
                continue
            candle = candidate["candles"][-1]
            candle_time = int(candle["close_time"])
            if candle_time <= position.last_candle_time:
                remaining.append(position)
                continue
            position.last_candle_time = candle_time
            position.bars_held += 1
            stop_hit = candle["low"] <= position.stop_price if position.side == "LONG" else candle["high"] >= position.stop_price
            target_hit = candle["high"] >= position.target_price if position.side == "LONG" else candle["low"] <= position.target_price
            if stop_hit:
                self._close(position, position.stop_price, "STOP")
            elif target_hit:
                self._close(position, position.target_price, "TARGET")
            elif position.bars_held >= self.config.maximum_holding_candles:
                self._close(position, candle["close"], "TIMEOUT")
            else:
                remaining.append(position)
        self.positions = remaining

    def _close(self, position: Position, raw_price: float, reason: str) -> None:
        exit_price = raw_price * (1 - self.config.slippage if position.side == "LONG" else 1 + self.config.slippage)
        gross = (exit_price - position.entry_price) * position.quantity * (1 if position.side == "LONG" else -1)
        exit_fee = exit_price * position.quantity * self.config.taker_fee
        net = gross - exit_fee
        self.strategy_equity[position.strategy] += net
        self._append("trades.csv", {**asdict(position), "event": "CLOSE", "exit_time": utc_now(), "exit_price": exit_price,
                                    "reason": reason, "net_pnl": net - position.entry_fee, "equity": self.strategy_equity[position.strategy]})

    def _append(self, filename: str, row: dict[str, Any]) -> None:
        path = self.output_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        exists = path.exists()
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(row))
            if not exists:
                writer.writeheader()
            writer.writerow(row)


class PaperTradingBot:
    def __init__(self, config: PaperBotConfig, client: BinancePublicClient | None = None):
        self.config = config
        self.output_dir = Path(config.output_dir)
        self.scanner = VolatilityScanner(client or BinancePublicClient(), config)
        self.broker = PaperBroker(config, self.output_dir)

    def run_cycle(self) -> list[dict[str, Any]]:
        candidates = self.scanner.scan()
        recorded_at = utc_now()
        for rank, candidate in enumerate(candidates, 1):
            public = {key: value for key, value in candidate.items() if key != "candles"}
            self.broker._append("rankings.csv", {"recorded_at": recorded_at, "rank": rank, **public})
        # An open position must keep receiving candles even when its symbol is
        # no longer volatile enough to remain in the ranked top five.
        ranked_symbols = {candidate["symbol"] for candidate in candidates}
        position_market_data = {}
        for symbol in {position.symbol for position in self.broker.positions} - ranked_symbols:
            rows = self.scanner.client.klines(symbol, self.config.candle_interval, self.config.candle_limit)
            candles = completed_candles(rows)
            metrics = volatility_metrics(candles, self.config.atr_period)
            if metrics:
                position_market_data[symbol] = {"symbol": symbol, "candles": candles, **metrics}
        self.broker.process(candidates, position_market_data)
        return candidates

    def run_forever(self) -> None:
        print("Paper mode only: no real orders can be sent.")
        while True:
            started = time.monotonic()
            try:
                candidates = self.run_cycle()
                leaders = ", ".join(f"{c['symbol']} ({c['volatility_score']:.3f})" for c in candidates)
                equities = " ".join(f"{name}=${value:,.2f}" for name, value in self.broker.strategy_equity.items())
                print(f"[{utc_now()}] {equities} open={len(self.broker.positions)} leaders={leaders or 'none'}")
            except Exception as error:
                print(f"[{utc_now()}] scan failed: {error}")
            time.sleep(max(1, self.config.scan_interval_seconds - (time.monotonic() - started)))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Live Binance Futures volatility scanner and paper trader")
    parser.add_argument("--config", type=Path, help="JSON configuration file")
    parser.add_argument("--once", action="store_true", help="Run one scan cycle and exit")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    bot = PaperTradingBot(PaperBotConfig.load(args.config))
    if args.once:
        candidates = bot.run_cycle()
        print(json.dumps([{key: value for key, value in row.items() if key != "candles"} for row in candidates], indent=2))
    else:
        bot.run_forever()


if __name__ == "__main__":
    main()
