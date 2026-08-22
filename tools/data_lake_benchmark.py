"""Benchmark the production Data Lake v2 execution path on local market data.

The tool intentionally skips report/export work so timings isolate the parts we
can optimize independently: catalog refresh, Data Lake/cache preparation, engine
construction, and stateful simulation. Repeated iterations also verify that the
core trade results remain identical while caches warm up.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from crypto_strategy_lab.data import DataRequest, MarketDataStore
from crypto_strategy_lab.data.backtest_service import BacktestDataBundle, load_backtest_bundle
from crypto_strategy_lab.data_lake_config import load_data_lake_config
from crypto_strategy_lab.data_lake_production_engine import DataLakeProductionBacktestEngine
from crypto_strategy_lab.prepared_backtest import from_data_lake_bundle


_FINGERPRINT_COLUMNS = (
    "pair_id",
    "trade_id",
    "result_type",
    "side",
    "strategy_candle_open_time",
    "strategy_entry_time",
    "entry_time",
    "exit_time",
    "long_exit_reason",
    "long_exit_source",
    "short_exit_reason",
    "short_exit_source",
    "pair_net_pnl",
    "pair_net_r",
    "equity_after_trade",
)


def _utc(value: str) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.to_pydatetime()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark Crypto Strategy Lab Data Lake v2 preparation and simulation"
    )
    parser.add_argument("--config", required=True, type=Path, help="Current Data Lake strategy JSON")
    parser.add_argument("--raw-root", required=True, type=Path)
    parser.add_argument("--cache-root", type=Path, default=Path("cache"))
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True, help="Inclusive UTC data start")
    parser.add_argument("--end", required=True, help="Exclusive UTC data end")
    parser.add_argument("--intrabar-start", help="Optional later inclusive UTC start for intrabar data")
    parser.add_argument("--iterations", type=int, default=2, help="Number of identical runs (default: 2)")
    parser.add_argument(
        "--skip-catalog-refresh",
        action="store_true",
        help="Use the existing Data Lake catalog instead of refreshing it once before timing runs",
    )
    parser.add_argument(
        "--include-agg-trades",
        action="store_true",
        help="Include the heavy optional aggTrades research feature in preparation timings",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON output path. The result is always printed to stdout.",
    )
    return parser


def _trade_fingerprint(trades: pd.DataFrame) -> str:
    """Return a stable hash of core execution results, independent of DataFrame attrs."""
    columns = [column for column in _FINGERPRINT_COLUMNS if column in trades.columns]
    if not columns:
        payload = f"rows={len(trades)};columns={','.join(map(str, trades.columns))}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
    normalized = trades.loc[:, columns].copy()
    for column in columns:
        normalized[column] = normalized[column].astype("string").fillna("<NA>")
    payload = normalized.to_csv(index=False, lineterminator="\n")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _feature_cache_hits(bundle: BacktestDataBundle) -> dict[str, object]:
    return {
        "core_directional": bool(bundle.technical_features.attrs.get("feature_cache_hit", False)),
        "production_market_context": bool(bundle.context_features.attrs.get("feature_cache_hit", False)),
        "support_resistance": (
            bool(bundle.support_resistance_features.attrs.get("feature_cache_hit", False))
            if bundle.support_resistance_features is not None
            else None
        ),
        "research": {
            name: bool(frame.attrs.get("feature_cache_hit", False))
            for name, frame in sorted(bundle.research_features.items())
        },
    }


def _load_bundle(store, request, config, *, intrabar_start, include_agg_trades):
    return load_backtest_bundle(
        store,
        request,
        market_regime_method=config.market_regime_method,
        structural_regime_sma_days=config.structural_regime_sma_days,
        structural_regime_slope_lookback_days=config.structural_regime_slope_lookback_days,
        refresh_catalog=False,
        intrabar_start=intrabar_start,
        atr_period=config.atr_period,
        adx_period=config.adx_period,
        di_pressure_lookback=config.di_pressure_lookback,
        bb_period=config.bb_period,
        bb_stddevs=config.bb_stddevs,
        mean_reversion_period=config.mean_reversion_period,
        mean_reversion_mean_type=getattr(config, "mean_reversion_mean_type", "SMA"),
        mean_reversion_bb_stddevs=getattr(config, "mean_reversion_bb_stddevs", 2.0),
        mean_reversion_rsi_period=getattr(config, "mean_reversion_rsi_period", 14),
        mean_reversion_rsi_oversold=getattr(config, "mean_reversion_rsi_oversold", 30.0),
        mean_reversion_rsi_overbought=getattr(config, "mean_reversion_rsi_overbought", 70.0),
        enable_support_resistance_analysis=config.enable_support_resistance_analysis,
        sr_timeframe_minutes=int(getattr(config, "sr_timeframe_minutes", 0) or 0),
        sr_pivot_left=config.sr_pivot_left,
        sr_pivot_right=config.sr_pivot_right,
        sr_lookback_bars=config.sr_lookback_bars,
        sr_zone_width_atr=config.sr_zone_width_atr,
        sr_near_distance_atr=config.sr_near_distance_atr,
        enable_sr_hold_confirmation=config.enable_sr_hold_confirmation,
        sr_hold_confirmation_bars=config.sr_hold_confirmation_bars,
        sr_hold_confirmation_atr=config.sr_hold_confirmation_atr,
        sr_break_tolerance_atr=config.sr_break_tolerance_atr,
        sr_break_basis=config.sr_break_basis,
        include_agg_trade_flow=bool(include_agg_trades),
    )


def _engine(bundle: BacktestDataBundle, config):
    prepared, intrabar = from_data_lake_bundle(bundle, config)
    return DataLakeProductionBacktestEngine.from_prepared(prepared, intrabar, config)


def _median(records: list[dict], key: str) -> float:
    return float(statistics.median(float(record[key]) for record in records))


def main() -> int:
    args = build_parser().parse_args()
    if args.iterations < 1:
        raise SystemExit("--iterations must be at least 1")

    config = load_data_lake_config(args.config)
    request = DataRequest(
        symbol=args.symbol,
        start=_utc(args.start),
        end=_utc(args.end),
        strategy_interval=f"{int(config.strategy_timeframe_minutes)}m",
        intrabar_interval=(
            f"{int(config.intrabar_timeframe_minutes)}m" if config.use_intrabar_data else None
        ),
    )
    intrabar_start = _utc(args.intrabar_start) if args.intrabar_start else None
    store = MarketDataStore(args.raw_root, args.cache_root)

    catalog_seconds = 0.0
    if not args.skip_catalog_refresh:
        started = time.perf_counter()
        store.refresh_catalog()
        catalog_seconds = time.perf_counter() - started

    records: list[dict[str, object]] = []
    fingerprints: list[str] = []
    for iteration in range(1, args.iterations + 1):
        total_started = time.perf_counter()

        prepare_started = time.perf_counter()
        bundle = _load_bundle(
            store,
            request,
            config,
            intrabar_start=intrabar_start,
            include_agg_trades=args.include_agg_trades,
        )
        preparation_seconds = time.perf_counter() - prepare_started

        init_started = time.perf_counter()
        engine = _engine(bundle, config)
        engine_init_seconds = time.perf_counter() - init_started

        simulation_started = time.perf_counter()
        trades = engine.run()
        simulation_seconds = time.perf_counter() - simulation_started
        total_seconds = time.perf_counter() - total_started

        fingerprint = _trade_fingerprint(trades)
        fingerprints.append(fingerprint)
        records.append(
            {
                "iteration": iteration,
                "preparation_seconds": preparation_seconds,
                "engine_init_seconds": engine_init_seconds,
                "simulation_seconds": simulation_seconds,
                "total_seconds": total_seconds,
                "strategy_rows": len(bundle.strategy),
                "intrabar_rows": len(bundle.intrabar) if bundle.intrabar is not None else 0,
                "trade_rows": len(trades),
                "intrabar_index_mode": getattr(bundle.intrabar, "intrabar_index_mode", None),
                "intrabar_iteration_mode": getattr(bundle.intrabar, "intrabar_iteration_mode", None),
                "feature_cache_hits": _feature_cache_hits(bundle),
                "trade_fingerprint": fingerprint,
            }
        )

    warm_records = records[1:] if len(records) > 1 else records
    result = {
        "benchmark_contract": "data_lake_execution_v1",
        "config_path": str(args.config.resolve()),
        "raw_root": str(args.raw_root.resolve()),
        "cache_root": str(args.cache_root.resolve()),
        "request": {
            "symbol": request.symbol,
            "start": request.start.isoformat(),
            "end": request.end.isoformat(),
            "strategy_interval": request.strategy_interval,
            "intrabar_interval": request.intrabar_interval,
            "intrabar_start": intrabar_start.isoformat() if intrabar_start else None,
        },
        "iterations": args.iterations,
        "catalog_refresh_seconds": catalog_seconds,
        "catalog_refresh_skipped": bool(args.skip_catalog_refresh),
        "include_agg_trade_flow": bool(args.include_agg_trades),
        "trade_fingerprints_identical": len(set(fingerprints)) <= 1,
        "warm_median_seconds": {
            "preparation": _median(warm_records, "preparation_seconds"),
            "engine_init": _median(warm_records, "engine_init_seconds"),
            "simulation": _median(warm_records, "simulation_seconds"),
            "total": _median(warm_records, "total_seconds"),
        },
        "runs": records,
    }

    text = json.dumps(result, indent=2, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["trade_fingerprints_identical"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
