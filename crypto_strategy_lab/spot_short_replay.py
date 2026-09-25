"""Replay short futures proceeds against an existing BTC spot allocation.

Uses completed Every Viable Entry outcomes. Portfolio values are observed at
trade exits; this is not an intratrade mark-to-market or margin simulation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import math

import duckdb
import pandas as pd

from crypto_strategy_lab.portfolio_replay import inspect_resilience_run
from crypto_strategy_lab.run_manifest import RunArtifactError, atomic_json


def replay_spot_short(
    run_dir: Path | str,
    *,
    initial_btc: float = 1.0,
    initial_cash: float = 1000.0,
    futures_risk_usdt: float = 50.0,
    spot_fee_percent: float = 0.1,
    output_root: Path | str = "output/data_lake_v2",
) -> tuple[dict, pd.DataFrame, Path]:
    """Buy BTC with net short wins; sell BTC to fund net short losses.

    A completed trade's net R is scaled to the chosen fixed USDT risk. Only
    nonoverlapping SHORT rows are accepted. A loss sells enough spot to fund
    the loss, including the spot sale fee; if BTC is exhausted, cash pays the
    remainder. Futures collateral, liquidation and funding beyond source net R
    are not simulated.
    """
    for name, value, allow_zero in (
        ("Initial BTC", initial_btc, False),
        ("Initial cash", initial_cash, True),
        ("Futures risk", futures_risk_usdt, False),
        ("Spot fee percentage", spot_fee_percent, True),
    ):
        if not math.isfinite(value) or value < 0 or (not allow_zero and value == 0):
            raise ValueError(f"{name} must be finite and positive" + (" or zero" if allow_zero else ""))
    if not 0 <= spot_fee_percent < 100:
        raise ValueError("Spot fee percentage must be below 100%")

    metadata = inspect_resilience_run(run_dir)
    if metadata["symbol"] != "BTCUSDT":
        raise ValueError("Spot/short replay requires a BTCUSDT completed run")
    with duckdb.connect() as con:
        frame = con.execute("SELECT * FROM read_parquet(?)", [str(metadata["samples_path"])]).fetchdf()
    required = {"side", "entry_time", "exit_time", "entry_price", "exit_price", "pair_net_r", "research_sample_id"}
    missing = required - set(frame.columns)
    if missing:
        raise RunArtifactError(f"Spot/short replay requires trade columns: {', '.join(sorted(missing))}")
    frame = frame.loc[frame["side"].astype(str).str.upper().eq("SHORT")].copy()
    if frame.empty:
        raise ValueError("The completed run contains no short candidates")
    for column in ("entry_time", "exit_time"):
        frame[column] = pd.to_datetime(frame[column], utc=True, errors="raise")
    for column in ("entry_price", "exit_price", "pair_net_r"):
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    if (frame["exit_time"] < frame["entry_time"]).any():
        raise RunArtifactError("Exit precedes entry in short candidates")
    if (frame[["entry_price", "exit_price"]] <= 0).any().any() or not frame[["entry_price", "exit_price", "pair_net_r"]].apply(lambda c: c.map(math.isfinite)).all().all():
        raise RunArtifactError("Short candidates contain invalid prices or net R")
    frame = frame.sort_values(["entry_time", "exit_time", "research_sample_id"], kind="stable")

    btc = float(initial_btc)
    cash = float(initial_cash)
    fee = spot_fee_percent / 100.0
    opening_price = float(frame.iloc[0]["entry_price"])
    opening_value = cash + btc * opening_price
    baseline_cash = cash
    last_exit = None
    rows = []
    accepted = skipped_overlap = 0
    total_futures_pnl = total_spot_fees = 0.0
    for row in frame.itertuples(index=False):
        if last_exit is not None and row.entry_time < last_exit:
            skipped_overlap += 1
            continue
        pnl = float(row.pair_net_r) * futures_risk_usdt
        price = float(row.exit_price)
        btc_change = spot_fee = unfunded = 0.0
        if pnl > 0:
            # Spend exactly the futures proceeds, including the purchase fee.
            btc_change = pnl / (price * (1.0 + fee))
            spot_fee = pnl - btc_change * price
            btc += btc_change
        elif pnl < 0:
            needed = -pnl
            sold = min(btc, needed / (price * (1.0 - fee)))
            btc_change = -sold
            btc -= sold
            proceeds = sold * price * (1.0 - fee)
            spot_fee = sold * price * fee
            unfunded = max(0.0, needed - proceeds)
            cash -= unfunded
        baseline_cash += pnl
        total_futures_pnl += pnl
        total_spot_fees += spot_fee
        accepted += 1
        last_exit = row.exit_time
        portfolio_value = cash + btc * price
        buy_hold_value = initial_cash + initial_btc * price
        rows.append({
            "sample_id": str(row.research_sample_id),
            "entry_time": row.entry_time, "exit_time": row.exit_time,
            "entry_price": float(row.entry_price), "exit_price": price,
            "net_r": float(row.pair_net_r), "futures_pnl_usdt": pnl,
            "spot_btc_change": btc_change, "spot_fee_usdt": spot_fee,
            "unfunded_from_spot_usdt": unfunded,
            "btc_balance": btc, "cash_balance_usdt": cash,
            "portfolio_value_usdt": portfolio_value,
            "buy_hold_value_usdt": buy_hold_value,
            "buy_hold_plus_shorts_value_usdt": baseline_cash + initial_btc * price,
        })
    if not rows:
        raise ValueError("No eligible short trade was available")
    ledger = pd.DataFrame(rows)
    final = ledger.iloc[-1]
    summary = {
        "source_run_id": metadata["run_id"], "source_run_dir": str(metadata["run_dir"]),
        "mode": "EXIT_SNAPSHOT_SPOT_SHORT_V1", "initial_btc": initial_btc,
        "initial_cash_usdt": initial_cash, "futures_risk_usdt": futures_risk_usdt,
        "spot_fee_percent": spot_fee_percent, "opening_price": opening_price,
        "opening_value_usdt": opening_value, "accepted_shorts": accepted,
        "skipped_overlapping_shorts": skipped_overlap,
        "futures_net_pnl_usdt": total_futures_pnl,
        "spot_fees_usdt": total_spot_fees,
        "ending_btc": float(btc), "ending_cash_usdt": float(cash),
        "last_exit_price": float(final["exit_price"]),
        "ending_value_usdt": float(final["portfolio_value_usdt"]),
        "buy_hold_value_usdt": float(final["buy_hold_value_usdt"]),
        "buy_hold_plus_shorts_value_usdt": float(final["buy_hold_plus_shorts_value_usdt"]),
        "limitations": "Valued only at accepted trade exits; no intratrade drawdown, spot price path, futures margin/liquidation, or new trades after the last exit. Source net R includes the source run's futures execution costs; scaling R assumes fixed risk and does not recompute fee tiers or position size.",
    }
    root = Path(output_root).resolve() / "spot_short_replays"
    root.mkdir(parents=True, exist_ok=True)
    output = root / f"{metadata['run_id']}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    output.mkdir()
    ledger.to_csv(output / "ledger.csv", index=False)
    atomic_json(output / "summary.json", summary)
    return summary, ledger, output
