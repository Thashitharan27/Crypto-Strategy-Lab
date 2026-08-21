"""Profile Data Lake v2 preparation without changing production semantics.

The execution benchmark reports preparation as one number. This tool decomposes
that number into market-dataset loads, canonical-to-engine OHLCV conversion,
feature-cache access, and intrabar index construction while also collecting a
cProfile ranking for the complete ``load_backtest_bundle`` call.

Instrumentation is installed only for the duration of this process and restored
before exit. Production data/loading code is not modified by the profiler.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import contextmanager
import cProfile
from datetime import datetime
import json
from pathlib import Path
import pstats
import sys
import time
from typing import Callable, Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from crypto_strategy_lab.data import DataRequest, MarketDataStore
from crypto_strategy_lab.data import backtest_service as backtest_service_module
from crypto_strategy_lab.data.backtest_service import BacktestDataBundle, load_backtest_bundle
from crypto_strategy_lab.data_lake_config import load_data_lake_config


Event = dict[str, object]


def _utc(value: str) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.to_pydatetime()


def _rows(value) -> int | None:
    try:
        return int(len(value))
    except (TypeError, AttributeError):
        return None


def _record(
    events: list[Event],
    *,
    category: str,
    name: str,
    started: float,
    rows: int | None = None,
    **metadata,
) -> None:
    event: Event = {
        "category": category,
        "name": name,
        "seconds": float(time.perf_counter() - started),
    }
    if rows is not None:
        event["rows"] = int(rows)
    event.update({key: value for key, value in metadata.items() if value is not None})
    events.append(event)


def _summarize_events(events: list[Event], total_seconds: float) -> dict[str, object]:
    """Aggregate non-overlapping instrumentation events and residual overhead."""
    category_seconds: dict[str, float] = defaultdict(float)
    category_calls: dict[str, int] = defaultdict(int)
    for event in events:
        category = str(event["category"])
        category_seconds[category] += float(event["seconds"])
        category_calls[category] += 1

    measured = float(sum(category_seconds.values()))
    residual = max(0.0, float(total_seconds) - measured)
    return {
        "category_seconds": {
            key: float(value)
            for key, value in sorted(category_seconds.items(), key=lambda item: item[1], reverse=True)
        },
        "category_calls": dict(sorted(category_calls.items())),
        "instrumented_seconds": measured,
        "unattributed_seconds": residual,
    }


def _profile_rows(profile: cProfile.Profile, sort_key: str, limit: int) -> list[dict[str, object]]:
    stats = pstats.Stats(profile)
    rows: list[dict[str, object]] = []
    for (filename, line, function), values in stats.stats.items():
        primitive_calls, total_calls, self_seconds, cumulative_seconds, _callers = values
        rows.append(
            {
                "function": function,
                "file": str(Path(filename)),
                "line": int(line),
                "primitive_calls": int(primitive_calls),
                "total_calls": int(total_calls),
                "self_seconds": float(self_seconds),
                "cumulative_seconds": float(cumulative_seconds),
            }
        )
    key = "cumulative_seconds" if sort_key == "cumulative" else "self_seconds"
    rows.sort(key=lambda row: float(row[key]), reverse=True)
    return rows[:limit]


@contextmanager
def _instrument_preparation(store: MarketDataStore, events: list[Event]) -> Iterator[None]:
    """Temporarily time the major preparation boundaries used by the real bundle loader."""
    original_load_dataset = store.load_dataset
    original_legacy = backtest_service_module._legacy_from_canonical
    original_cached_feature = backtest_service_module._cached_feature
    original_cached_multisource = backtest_service_module._cached_multisource_feature
    original_intrabar_index = backtest_service_module.as_searchsorted_intrabar

    def timed_load_dataset(request, dataset, *, interval=None):
        started = time.perf_counter()
        frame = original_load_dataset(request, dataset, interval=interval)
        _record(
            events,
            category="dataset_load",
            name=f"{dataset.value}:{interval or '-'}",
            started=started,
            rows=_rows(frame),
            dataset=dataset.value,
            interval=interval,
            request_start=request.start.isoformat(),
            request_end=request.end.isoformat(),
        )
        return frame

    def timed_legacy(canonical, interval, label):
        started = time.perf_counter()
        frame = original_legacy(canonical, interval, label)
        _record(
            events,
            category="legacy_conversion",
            name=label,
            started=started,
            rows=_rows(frame),
            interval=interval,
        )
        return frame

    def timed_cached_feature(store_arg, request, canonical, provider, parameters, feature_frames=None):
        started = time.perf_counter()
        frame = original_cached_feature(
            store_arg,
            request,
            canonical,
            provider,
            parameters,
            feature_frames,
        )
        _record(
            events,
            category="feature_cache",
            name=provider.definition.name,
            started=started,
            rows=_rows(frame),
            cache_hit=bool(frame.attrs.get("feature_cache_hit", False)),
        )
        return frame

    def timed_cached_multisource(store_arg, request, datasets, provider, parameters=None):
        started = time.perf_counter()
        frame = original_cached_multisource(
            store_arg,
            request,
            datasets,
            provider,
            parameters,
        )
        _record(
            events,
            category="research_feature_cache",
            name=provider.definition.name,
            started=started,
            rows=_rows(frame),
            cache_hit=bool(frame.attrs.get("feature_cache_hit", False)),
        )
        return frame

    def timed_intrabar_index(frame):
        started = time.perf_counter()
        wrapped = original_intrabar_index(frame)
        _record(
            events,
            category="intrabar_index",
            name="as_searchsorted_intrabar",
            started=started,
            rows=_rows(wrapped),
            index_mode=getattr(wrapped, "intrabar_index_mode", None),
            iteration_mode=getattr(wrapped, "intrabar_iteration_mode", None),
        )
        return wrapped

    store.load_dataset = timed_load_dataset
    backtest_service_module._legacy_from_canonical = timed_legacy
    backtest_service_module._cached_feature = timed_cached_feature
    backtest_service_module._cached_multisource_feature = timed_cached_multisource
    backtest_service_module.as_searchsorted_intrabar = timed_intrabar_index
    try:
        yield
    finally:
        store.load_dataset = original_load_dataset
        backtest_service_module._legacy_from_canonical = original_legacy
        backtest_service_module._cached_feature = original_cached_feature
        backtest_service_module._cached_multisource_feature = original_cached_multisource
        backtest_service_module.as_searchsorted_intrabar = original_intrabar_index


def _load_bundle(store, request, config, *, intrabar_start, include_agg_trades) -> BacktestDataBundle:
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Profile Crypto Strategy Lab Data Lake v2 preparation stages"
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--raw-root", required=True, type=Path)
    parser.add_argument("--cache-root", type=Path, default=Path("cache"))
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--intrabar-start")
    parser.add_argument("--include-agg-trades", action="store_true")
    parser.add_argument("--top", type=int, default=30, help="Functions to show per cProfile ranking")
    parser.add_argument("--output", type=Path, help="Optional JSON output path")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.top < 1:
        raise SystemExit("--top must be at least 1")

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

    events: list[Event] = []
    profile = cProfile.Profile()
    preparation_started = time.perf_counter()
    with _instrument_preparation(store, events):
        profile.enable()
        bundle = _load_bundle(
            store,
            request,
            config,
            intrabar_start=intrabar_start,
            include_agg_trades=args.include_agg_trades,
        )
        profile.disable()
    preparation_seconds = time.perf_counter() - preparation_started

    result = {
        "profile_contract": "data_lake_preparation_profile_v1",
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
        "include_agg_trade_flow": bool(args.include_agg_trades),
        "preparation_seconds_profiled": float(preparation_seconds),
        "stage_summary": _summarize_events(events, preparation_seconds),
        "events": sorted(events, key=lambda event: float(event["seconds"]), reverse=True),
        "strategy_rows": len(bundle.strategy),
        "intrabar_rows": len(bundle.intrabar) if bundle.intrabar is not None else 0,
        "intrabar_index_mode": getattr(bundle.intrabar, "intrabar_index_mode", None),
        "intrabar_iteration_mode": getattr(bundle.intrabar, "intrabar_iteration_mode", None),
        "feature_cache_hits": {
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
        },
        "top_by_cumulative": _profile_rows(profile, "cumulative", args.top),
        "top_by_self": _profile_rows(profile, "self", args.top),
    }

    text = json.dumps(result, indent=2, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
