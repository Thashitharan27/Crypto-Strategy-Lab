"""Delta-neutral Binance perpetual funding carry backtest.

This module models a spot-long + USD-M perpetual-short hedge using funding
settlement events already stored in Crypto Strategy Lab's Binance Data Lake.
It is deliberately independent from the directional strategy engine.

Assumptions:
- spot and perpetual notional are matched 1:1 at entry;
- BTC price risk is therefore approximately hedged while the pair remains open;
- positive funding is received by the short, negative funding is paid;
- entry/exit trading fees are charged on both legs;
- no leverage, liquidation, borrowing, tax, or exchange-failure modeling;
- funding is applied only at recorded Binance settlement events.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from pathlib import Path

import pandas as pd

from crypto_strategy_lab.data.query import DataRequest
from crypto_strategy_lab.data.schemas import DatasetKind, MarketKind
from crypto_strategy_lab.data.store import MarketDataStore
from crypto_strategy_lab.run_manifest import atomic_json


@dataclass(frozen=True)
class FundingCarryConfig:
    initial_capital_usdt: float = 10_000.0
    minimum_funding_rate: float = 0.0
    entry_fee_percent_per_leg: float = 0.05
    exit_fee_percent_per_leg: float = 0.05
    close_on_negative_funding: bool = False

    def validate(self) -> None:
        for name, value in (
            ("initial_capital_usdt", self.initial_capital_usdt),
            ("minimum_funding_rate", self.minimum_funding_rate),
            ("entry_fee_percent_per_leg", self.entry_fee_percent_per_leg),
            ("exit_fee_percent_per_leg", self.exit_fee_percent_per_leg),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.initial_capital_usdt <= 0:
            raise ValueError("initial_capital_usdt must be positive")
        if self.entry_fee_percent_per_leg < 0 or self.exit_fee_percent_per_leg < 0:
            raise ValueError("fees must not be negative")


def _timestamp(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def backtest_funding_carry(
    store: MarketDataStore,
    *,
    symbol: str,
    start,
    end,
    config: FundingCarryConfig = FundingCarryConfig(),
    output_root: Path | str = "output/data_lake_v2",
) -> tuple[dict, pd.DataFrame, Path]:
    """Backtest spot-long + perpetual-short funding carry over a fixed period."""

    config.validate()
    start_ts, end_ts = _timestamp(start), _timestamp(end)
    request = DataRequest(
        symbol=symbol,
        start=start_ts.to_pydatetime(),
        end=end_ts.to_pydatetime(),
        strategy_interval="1d",
        datasets=(DatasetKind.FUNDING_RATE,),
        market=MarketKind.FUTURES_UM,
    )
    funding = store.load_dataset(request, DatasetKind.FUNDING_RATE)
    if funding.empty:
        raise ValueError(f"No funding-rate events for {symbol} in selected period")
    funding = funding.sort_values("event_time", kind="stable").copy()
    funding["funding_rate"] = pd.to_numeric(funding["funding_rate"], errors="raise")
    if not funding["funding_rate"].map(math.isfinite).all():
        raise ValueError("Funding-rate data contains non-finite values")

    capital = float(config.initial_capital_usdt)
    fee_entry = config.entry_fee_percent_per_leg / 100.0
    fee_exit = config.exit_fee_percent_per_leg / 100.0
    in_position = False
    notional = 0.0
    cumulative_funding = 0.0
    cumulative_fees = 0.0
    entries = exits = 0
    rows: list[dict] = []

    for event in funding.itertuples(index=False):
        rate = float(event.funding_rate)
        timestamp = pd.Timestamp(event.event_time)

        if not in_position and rate >= config.minimum_funding_rate:
            # One unit of total capital supports equal spot and short legs.
            # Each leg uses half the capital notional, keeping gross exposure at 1x.
            notional = capital / 2.0
            entry_cost = notional * fee_entry * 2.0
            capital -= entry_cost
            cumulative_fees += entry_cost
            entries += 1
            in_position = True

        funding_pnl = 0.0
        if in_position:
            # Binance positive funding means longs pay shorts.
            funding_pnl = notional * rate
            capital += funding_pnl
            cumulative_funding += funding_pnl

            should_close = config.close_on_negative_funding and rate < 0.0
            if should_close:
                exit_cost = notional * fee_exit * 2.0
                capital -= exit_cost
                cumulative_fees += exit_cost
                exits += 1
                in_position = False
                notional = 0.0

        rows.append(
            {
                "event_time": timestamp,
                "funding_rate": rate,
                "position_open": in_position,
                "hedged_leg_notional_usdt": notional,
                "funding_pnl_usdt": funding_pnl,
                "cumulative_funding_usdt": cumulative_funding,
                "cumulative_fees_usdt": cumulative_fees,
                "equity_usdt": capital,
            }
        )

    if in_position:
        exit_cost = notional * fee_exit * 2.0
        capital -= exit_cost
        cumulative_fees += exit_cost
        exits += 1
        rows[-1]["position_open"] = False
        rows[-1]["cumulative_fees_usdt"] = cumulative_fees
        rows[-1]["equity_usdt"] = capital

    ledger = pd.DataFrame(rows)
    days = max((end_ts - start_ts).total_seconds() / 86400.0, 1e-9)
    total_return = capital / config.initial_capital_usdt - 1.0
    annualized = (1.0 + total_return) ** (365.25 / days) - 1.0 if total_return > -1 else -1.0
    peak = ledger["equity_usdt"].cummax()
    drawdown = ledger["equity_usdt"] / peak - 1.0

    summary = {
        "mode": "BINANCE_PERPETUAL_FUNDING_CARRY_V1",
        "symbol": symbol.upper(),
        "start": start_ts.isoformat(),
        "end": end_ts.isoformat(),
        "initial_capital_usdt": config.initial_capital_usdt,
        "ending_equity_usdt": float(capital),
        "total_return_percent": float(total_return * 100.0),
        "annualized_return_percent": float(annualized * 100.0),
        "maximum_drawdown_percent": float(drawdown.min() * 100.0),
        "funding_events": int(len(funding)),
        "positive_funding_events": int((funding["funding_rate"] > 0).sum()),
        "negative_funding_events": int((funding["funding_rate"] < 0).sum()),
        "funding_received_net_usdt": float(cumulative_funding),
        "trading_fees_usdt": float(cumulative_fees),
        "entries": int(entries),
        "exits": int(exits),
        "minimum_funding_rate": config.minimum_funding_rate,
        "close_on_negative_funding": config.close_on_negative_funding,
        "entry_fee_percent_per_leg": config.entry_fee_percent_per_leg,
        "exit_fee_percent_per_leg": config.exit_fee_percent_per_leg,
        "limitations": (
            "Delta-neutral funding carry only. Does not model spot/perpetual basis "
            "mark-to-market, futures liquidation, borrowing, collateral yield, "
            "slippage, tax, exchange insolvency, or dated-quarterly futures basis."
        ),
    }

    root = Path(output_root).resolve() / "funding_carry_replays"
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = root / f"{symbol.upper()}_{stamp}"
    output.mkdir()
    ledger.to_csv(output / "ledger.csv", index=False)
    atomic_json(output / "summary.json", summary)
    return summary, ledger, output
