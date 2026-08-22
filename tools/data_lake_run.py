"""Run one backtest directly from Binance Data Lake v2.

Strategy JSON contains strategy settings only. Market data and versioned causal
feature blocks are prepared/cached before the production simulator starts.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from crypto_strategy_lab.data import DataRequest, MarketDataStore
from crypto_strategy_lab.data.backtest_service import load_backtest_bundle
from crypto_strategy_lab.data_lake_config import load_data_lake_config
from crypto_strategy_lab.data_lake_production_engine import DataLakeProductionBacktestEngine
from crypto_strategy_lab.prepared_backtest import from_data_lake_bundle
from crypto_strategy_lab.features.market_regime import structural_regime_values


def _utc(value: str) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.to_pydatetime()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Crypto Strategy Lab directly from Data Lake v2")
    parser.add_argument("--config", required=True, type=Path, help="Data Lake strategy configuration JSON")
    parser.add_argument("--raw-root", required=True, type=Path)
    parser.add_argument("--cache-root", type=Path, default=Path("cache"))
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True, help="Inclusive UTC data start")
    parser.add_argument("--end", required=True, help="Exclusive UTC data end")
    parser.add_argument("--output-dir", type=Path, default=Path("output") / "data_lake_v2")
    parser.add_argument(
        "--include-agg-trades",
        action="store_true",
        help="Load heavy Binance aggTrades archives and attach causal trade-flow research",
    )
    return parser


def _feature_manifest(frame: pd.DataFrame | None) -> dict | None:
    if frame is None:
        return None
    return {
        "name": frame.attrs.get("feature_name"),
        "version": frame.attrs.get("feature_version"),
        "rows": len(frame),
        "cache_hit": bool(frame.attrs.get("feature_cache_hit", False)),
        "cache_key": frame.attrs.get("feature_cache_key"),
        "effective_warmup_bars": frame.attrs.get("effective_warmup_bars"),
    }


def main() -> int:
    args = build_parser().parse_args()
    config = load_data_lake_config(args.config)
    strategy_interval = f"{int(config.strategy_timeframe_minutes)}m"
    intrabar_interval = (
        f"{int(config.intrabar_timeframe_minutes)}m" if config.use_intrabar_data else None
    )
    request = DataRequest(
        symbol=args.symbol,
        start=_utc(args.start),
        end=_utc(args.end),
        strategy_interval=strategy_interval,
        intrabar_interval=intrabar_interval,
    )

    store = MarketDataStore(args.raw_root, args.cache_root)
    bundle = load_backtest_bundle(
        store,
        request,
        market_regime_method=config.market_regime_method,
        structural_regime_sma_days=config.structural_regime_sma_days,
        structural_regime_slope_lookback_days=config.structural_regime_slope_lookback_days,
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
        include_agg_trade_flow=bool(args.include_agg_trades),
    )
    prepared, intrabar = from_data_lake_bundle(bundle)
    regimes = None
    if config.market_regime_method != "ASSET_RETURN":
        regimes = structural_regime_values(prepared.timestamp, bundle.structural_benchmark, sma_days=config.structural_regime_sma_days, slope_lookback_days=config.structural_regime_slope_lookback_days)
    engine = DataLakeProductionBacktestEngine.from_prepared(prepared, intrabar, config, market_regime_values=regimes)
    trades = engine.run()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = args.output_dir / f"{request.symbol}_{request.strategy_interval}_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=False)
    trades.to_csv(run_dir / "trade_list.csv", index=False)

    directional_manifest = _feature_manifest(bundle.technical_features)
    directional_manifest.update(
        atr_period=bundle.technical_features.attrs.get("atr_period"),
        adx_period=bundle.technical_features.attrs.get("adx_period"),
        di_pressure_lookback=bundle.technical_features.attrs.get("di_pressure_lookback"),
    )
    context_manifest = _feature_manifest(bundle.context_features)
    context_manifest.update(
        bb_period=bundle.context_features.attrs.get("bb_period"),
        bb_stddevs=bundle.context_features.attrs.get("bb_stddevs"),
        mean_reversion_period=bundle.context_features.attrs.get("mean_reversion_period"),
        mean_reversion_mean_type=bundle.context_features.attrs.get("mean_reversion_mean_type"),
        mean_reversion_bb_stddevs=bundle.context_features.attrs.get("mean_reversion_bb_stddevs"),
        mean_reversion_rsi_period=bundle.context_features.attrs.get("mean_reversion_rsi_period"),
        mean_reversion_rsi_oversold=bundle.context_features.attrs.get("mean_reversion_rsi_oversold"),
        mean_reversion_rsi_overbought=bundle.context_features.attrs.get("mean_reversion_rsi_overbought"),
    )
    manifest = {
        "data_source": "binance_data_lake_v2",
        "config_contract": "data_lake_strategy_v2",
        "production_engine": "DataLakeProductionBacktestEngine.from_prepared",
        "raw_root": str(args.raw_root.resolve()),
        "cache_root": str(args.cache_root.resolve()),
        "config_path": str(args.config.resolve()),
        "request": {
            "symbol": request.symbol,
            "start": request.start.isoformat(),
            "end": request.end.isoformat(),
            "strategy_interval": request.strategy_interval,
            "intrabar_interval": request.intrabar_interval,
        },
        "research_options": {
            "include_agg_trade_flow": bool(args.include_agg_trades),
        },
        "market_regime_method": config.market_regime_method,
        "features": {
            "core_directional": directional_manifest,
            "production_market_context": context_manifest,
            "support_resistance": _feature_manifest(bundle.support_resistance_features),
            "research": {
                name: _feature_manifest(frame)
                for name, frame in sorted(bundle.research_features.items())
            },
        },
        "structural_benchmark_symbol": bundle.structural_benchmark_symbol,
        "structural_benchmark_interval": bundle.structural_benchmark_interval,
        "strategy_rows": len(bundle.strategy),
        "intrabar_rows": len(bundle.intrabar) if bundle.intrabar is not None else 0,
        "benchmark_rows": len(bundle.structural_benchmark) if bundle.structural_benchmark is not None else 0,
        "trade_rows": len(trades),
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({**manifest, "run_dir": str(run_dir.resolve())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
