from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import duckdb
import numpy as np
import pandas as pd

from crypto_strategy_lab.data_lake_config import DataConfig, ResearchRunConfig
from crypto_strategy_lab.strategy_visualizer import (
    CompletedRunVisualizer,
    LIGHTWEIGHT_CHARTS_VERSION,
    build_visualizer_html,
    trade_stop_target,
)


def _write_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.register("frame", frame)
        escaped = str(path).replace("'", "''")
        connection.execute(f"COPY frame TO '{escaped}' (FORMAT PARQUET)")


def _fixture(tmp_path: Path):
    times = pd.date_range("2026-01-01", periods=480, freq="15min", tz="UTC")
    close = np.linspace(100.0, 130.0, len(times))
    market = pd.DataFrame(
        {
            "period_start": times,
            "open": close - 0.2,
            "high": close + 0.7,
            "low": close - 0.8,
            "close": close,
            "volume": np.full(len(times), 100.0),
        }
    )

    trade_time = times[300]
    exit_time = times[308]
    trades = pd.DataFrame(
        [
            {
                "pair_id": 7,
                "side": "LONG",
                "entry_time": trade_time,
                "strategy_entry_time": trade_time,
                "entry_price": float(close[300]),
                "strategy_entry_price": float(close[300]),
                "exit_time": exit_time,
                "long_original_sl": float(close[300] - 2.0),
                "long_tp": float(close[300] + 4.0),
                "long_exit_price": float(close[308]),
                "long_exit_reason": "TP",
                "pair_net_r": 1.9,
                "pair_net_pnl": 19.0,
                "strategy_profile_key": "bull_long",
                "signal_strategy": "MTF_SR_REACTION",
                "entry_filter_reason": "Strategy profile passed",
                "market_regime": "BULL",
                "adx": 24.0,
                "plus_di": 31.0,
                "minus_di": 18.0,
                "di_ratio": 1.72,
            }
        ]
    )
    signals = pd.DataFrame(
        [
            {
                "signal_id": "reject-1",
                "strategy_index": 298,
                "candle_open_time": times[298],
                "decision_available_at": times[299],
                "side": "LONG",
                "profile": "bull_long",
                "decision": "REJECT",
                "reason_code": "ADX below threshold",
                "proposed_entry": float(close[298]),
                "proposed_stop": None,
                "proposed_target": None,
            },
            {
                "signal_id": "enter-7",
                "strategy_index": 300,
                "candle_open_time": times[300],
                "decision_available_at": times[301],
                "side": "LONG",
                "profile": "bull_long",
                "decision": "ENTER",
                "reason_code": "ENTERED",
                "proposed_entry": float(close[300]),
                "proposed_stop": float(close[300] - 2.0),
                "proposed_target": float(close[300] + 4.0),
            },
        ]
    )
    context = pd.DataFrame(
        {
            "strategy_index": range(len(times)),
            "strategy_candle_open_time": times,
            "decision_available_at": times + pd.Timedelta(minutes=15),
            "close": close,
            "adx": np.full(len(times), 24.0),
            "plus_di": np.full(len(times), 31.0),
            "minus_di": np.full(len(times), 18.0),
            "di_spread": np.full(len(times), 13.0),
            "di_ratio": np.full(len(times), 31.0 / 18.0),
            "session_vwap": close - 0.5,
            "bb_middle": close - 0.2,
            "bb_upper": close + 2.0,
            "bb_lower": close - 2.0,
            "market_regime": np.full(len(times), "BULL", dtype=object),
            "mean_reversion_state": np.full(
                len(times), "NEAR_MEAN", dtype=object
            ),
            "mean_reversion_motion": np.full(
                len(times), "TOWARD_MEAN", dtype=object
            ),
            "sr_4h_long_support_zone_low": close - 4.0,
            "sr_4h_long_support_zone_high": close - 3.0,
            "sr_4h_long_resistance_zone_low": close + 5.0,
            "sr_4h_long_resistance_zone_high": close + 6.0,
            "sr_4h_long_support_state": np.full(
                len(times), "SUPPORT_HELD", dtype=object
            ),
            "sr_4h_long_resistance_state": np.full(
                len(times), "APPROACHING_RESISTANCE", dtype=object
            ),
        }
    )

    run_dir = tmp_path / "BTCUSDT_15m_run"
    artifacts = run_dir / "artifacts"
    trades_path = artifacts / "trades.parquet"
    signals_path = artifacts / "signals.parquet"
    context_path = artifacts / "feature_context.parquet"
    _write_parquet(trades_path, trades)
    _write_parquet(signals_path, signals)
    _write_parquet(context_path, context)

    config = ResearchRunConfig(
        data=DataConfig(
            strategy_timeframe_minutes=15,
            intrabar_timeframe_minutes=1,
            use_intrabar_data=True,
            intrabar_missing_policy="ERROR",
        )
    )
    manifest = {
        "run_id": "visualizer-test-run",
        "request": {
            "market": "futures_um",
            "symbol": "BTCUSDT",
            "start": times[0].isoformat(),
            "end": (times[-1] + pd.Timedelta(minutes=15)).isoformat(),
            "requested_strategy_interval": "15m",
            "requested_intrabar_interval": "1m",
            "effective_intrabar_interval": "1m",
        },
        "research": {
            "request": {
                "symbol": "BTCUSDT",
                "start": times[0].isoformat(),
                "end": (times[-1] + pd.Timedelta(minutes=15)).isoformat(),
                "strategy_interval": "15m",
                "intrabar_interval": "1m",
            }
        },
        "config": config.to_dict(),
        "artifacts": {
            "trades": {"path": "artifacts/trades.parquet"},
            "signals": {"path": "artifacts/signals.parquet"},
            "feature_context": {"path": "artifacts/feature_context.parquet"},
        },
    }

    class CompletedRuns:
        @staticmethod
        def artifact_path(root, raw_manifest, name):
            return Path(root) / raw_manifest["artifacts"][name]["path"]

    class Store:
        def __init__(self):
            self.calls = []

        def load_dataset(self, request, dataset, *, interval=None):
            self.calls.append((request, dataset, interval))
            starts = market["period_start"]
            return market[
                (starts >= pd.Timestamp(request.start))
                & (starts < pd.Timestamp(request.end))
            ].copy()

    service = SimpleNamespace(completed_runs=CompletedRuns(), store=Store())
    return service, run_dir, manifest, market


def test_completed_run_visualizer_builds_bounded_causal_payload(tmp_path):
    service, run_dir, manifest, _market = _fixture(tmp_path)
    model = CompletedRunVisualizer.load(service, run_dir, manifest)

    assert model.trade_count == 1
    assert "LONG" in model.trade_label(0)
    payload = model.build_payload(
        trade_index=0,
        visible_candles=120,
        show_rejections=False,
    )

    assert payload["run"]["symbol"] == "BTCUSDT"
    assert payload["run"]["timeframe"] == "15m"
    assert 60 <= len(payload["candles"]) <= 120
    assert payload["selectedTrade"]["Side"] == "LONG"
    assert payload["selectedTrade"]["Stop"] < payload["selectedTrade"]["Entry"]
    assert payload["selectedTrade"]["Target"] > payload["selectedTrade"]["Entry"]
    assert any(line["kind"] == "entry" for line in payload["priceLines"])
    assert any(line["kind"] == "stop" for line in payload["priceLines"])
    assert any(line["kind"] == "target" for line in payload["priceLines"])

    overlay_names = {item["name"] for item in payload["overlays"]}
    assert {"EMA 50", "EMA 100", "EMA 200", "VWAP"} <= overlay_names
    assert "4H Support low" in overlay_names
    assert "4H Resistance high" in overlay_names

    assert any(marker["kind"] == "enter" for marker in payload["markers"])
    assert not any(marker["kind"] == "reject" for marker in payload["markers"])
    assert any(marker["kind"] == "exit" for marker in payload["markers"])

    contexts = list(payload["candleContext"].values())
    assert any(item.get("4H Support") == "SUPPORT_HELD" for item in contexts)
    assert service.store.calls
    request, _dataset, interval = service.store.calls[-1]
    assert interval == "15m"
    assert pd.Timestamp(request.start) > pd.Timestamp(manifest["request"]["start"])


def test_rejected_signal_markers_are_explicit_opt_in(tmp_path):
    service, run_dir, manifest, _market = _fixture(tmp_path)
    model = CompletedRunVisualizer.load(service, run_dir, manifest)

    payload = model.build_payload(
        trade_index=0,
        visible_candles=120,
        show_rejections=True,
    )

    reject = [marker for marker in payload["markers"] if marker["kind"] == "reject"]
    assert len(reject) == 1
    assert "ADX below threshold" in reject[0]["text"]


def test_trade_stop_target_prefers_original_entry_structure():
    stop, target = trade_stop_target(
        {
            "side": "SHORT",
            "short_original_sl": 105.0,
            "short_sl": 101.0,
            "short_tp": 94.0,
            "short_tp1_price": 97.0,
        }
    )
    assert stop == 105.0
    assert target == 94.0


def test_visualizer_html_pins_lightweight_charts_and_preserves_attribution():
    html = build_visualizer_html(
        {
            "candles": [],
            "overlays": [],
            "markers": [],
            "priceLines": [],
            "candleContext": {},
        }
    )

    assert f"lightweight-charts@{LIGHTWEIGHT_CHARTS_VERSION}" in html
    assert "CandlestickSeries" in html
    assert "createSeriesMarkers" in html
    assert "attributionLogo: true" in html
    assert "tradingview.com" in html
    assert "no strategy re-evaluation" in html


def test_active_app_composes_strategy_visualizer():
    import app

    source = inspect.getsource(app.main)
    assert "apply_strategy_visualizer_workspace(window)" in source
