from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import duckdb
import numpy as np
import pandas as pd

from crypto_strategy_lab.data import DatasetKind
from crypto_strategy_lab.data.source_identity import SourceSignature
from crypto_strategy_lab.data_lake_config import DataConfig, ResearchRunConfig
from crypto_strategy_lab.gui.completed_run_research import research_seed_from_manifest
from crypto_strategy_lab.research_warmup import strategy_warmup_period
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
                "research_signal_candle_open_time": trade_time,
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
            "atr": np.full(len(times), 2.0),
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
            "sr_4h_completed_candle_time": times.floor("4h"),
            "sr_4h_long_support_zone_low": np.full(len(times), 112.0),
            "sr_4h_long_support_zone_high": np.full(len(times), 113.0),
            "sr_4h_long_resistance_zone_low": np.full(len(times), 124.0),
            "sr_4h_long_resistance_zone_high": np.full(len(times), 125.0),
            "sr_4h_long_nearest_support_bar_index": np.full(len(times), 10),
            "sr_4h_long_nearest_resistance_bar_index": np.full(len(times), 20),
            "sr_4h_long_nearest_support_distance_atr": np.full(len(times), 1.5),
            "sr_4h_long_nearest_resistance_distance_atr": np.full(len(times), 2.0),
            "sr_4h_long_nearest_support_distance_price": np.full(len(times), 3.0),
            "sr_4h_long_nearest_resistance_distance_price": np.full(len(times), 4.0),
            "sr_4h_long_near_support": np.zeros(len(times), dtype=bool),
            "sr_4h_long_near_resistance": np.zeros(len(times), dtype=bool),
            "sr_4h_long_inside_support_zone": np.zeros(len(times), dtype=bool),
            "sr_4h_long_inside_resistance_zone": np.zeros(len(times), dtype=bool),
            "sr_4h_long_structure_conflict": np.zeros(len(times), dtype=bool),
            "sr_4h_long_support_test_count": np.where(
                np.arange(len(times)) >= 300, 2, 1
            ),
            "sr_4h_long_resistance_test_count": np.ones(len(times)),
            "sr_4h_long_support_rejection_atr": np.full(len(times), 0.75),
            "sr_4h_long_resistance_rejection_atr": np.full(len(times), 0.40),
            "sr_4h_long_bars_since_support_test": np.full(len(times), 3),
            "sr_4h_long_bars_since_resistance_test": np.full(len(times), 8),
            "sr_4h_long_support_held": np.arange(len(times)) >= 301,
            "sr_4h_long_resistance_held": np.zeros(len(times), dtype=bool),
            "sr_4h_long_confirmation_rating": np.full(
                len(times), "STRONG", dtype=object
            ),
            "sr_4h_long_room_in_direction_atr": np.full(len(times), 2.0),
            "sr_4h_short_room_in_direction_atr": np.full(len(times), 1.5),
            "sr_4h_long_support_state": np.where(
                np.arange(len(times)) >= 301,
                "SUPPORT_HELD",
                np.where(
                    np.arange(len(times)) >= 300,
                    "SUPPORT_TESTING",
                    "APPROACHING_SUPPORT",
                ),
            ),
            "sr_4h_long_resistance_state": np.full(
                len(times), "APPROACHING_RESISTANCE", dtype=object
            ),
        }
    )

    rule_trace = pd.DataFrame(
        [
            {
                "strategy_index": 300,
                "strategy_candle_open_time": trade_time,
                "decision_available_at": times[301],
                "market_regime": "BULL",
                "source_side": "LONG",
                "strategy_profile_key": "bull_long",
                "signal_strategy": "MTF_SR_REACTION",
                "rule_kind": "REQUIRED",
                "group_id": "entry-1",
                "group_name": "4H Support Bounce — Long",
                "group_enabled": True,
                "group_evaluated": True,
                "group_matched": True,
                "condition_id": "entry-adx",
                "condition_order": 1,
                "condition_evaluated": True,
                "evidence": "ADX",
                "timeframe_minutes": None,
                "operator": "GTE",
                "expected_value": "20.0",
                "expected_value2": "0.0",
                "actual_value": 24.0,
                "evidence_available": True,
                "condition_passed": True,
                "filter_passed": True,
                "filter_reason": "Strategy profile bull_long passed",
            },
            {
                "strategy_index": 300,
                "strategy_candle_open_time": trade_time,
                "decision_available_at": times[301],
                "market_regime": "BULL",
                "source_side": "LONG",
                "strategy_profile_key": "bull_long",
                "signal_strategy": "MTF_SR_REACTION",
                "rule_kind": "VETO",
                "group_id": "veto-1",
                "group_name": "Weak momentum veto",
                "group_enabled": True,
                "group_evaluated": True,
                "group_matched": False,
                "condition_id": "veto-state",
                "condition_order": 1,
                "condition_evaluated": True,
                "evidence": "MR_STATE",
                "timeframe_minutes": None,
                "operator": "IS",
                "expected_value": "ABOVE_MEAN",
                "expected_value2": None,
                "actual_value": 3.0,
                "evidence_available": True,
                "condition_passed": False,
                "filter_passed": True,
                "filter_reason": "Strategy profile bull_long passed",
            },
        ]
    )

    run_dir = tmp_path / "BTCUSDT_15m_run"
    artifacts = run_dir / "artifacts"
    trades_path = artifacts / "trades.parquet"
    signals_path = artifacts / "signals.parquet"
    context_path = artifacts / "feature_context.parquet"
    rule_trace_path = artifacts / "rule_trace.parquet"
    sr_zones_path = artifacts / "sr_zones.parquet"
    zone_rows = []
    for strategy_index, timestamp in enumerate(times):
        for zone_id, structure, low_value, high_value, nearest in (
            ("SUPPORT:10", "SUPPORT", 112.0, 113.0, True),
            ("SUPPORT:5", "SUPPORT", 106.0, 107.0, False),
            ("RESISTANCE:20", "RESISTANCE", 124.0, 125.0, True),
            ("RESISTANCE:25", "RESISTANCE", 130.0, 131.0, False),
        ):
            zone_rows.append(
                {
                    "strategy_index": strategy_index,
                    "strategy_candle_open_time": timestamp,
                    "decision_available_at": timestamp + pd.Timedelta(minutes=15),
                    "sr_timeframe": "4h",
                    "sr_timeframe_minutes": 240,
                    "sr_completed_candle_time": timestamp.floor("4h"),
                    "zone_id": zone_id,
                    "structure": structure,
                    "zone_low": low_value,
                    "zone_high": high_value,
                    "anchor_price": low_value,
                    "pivot_bar_index": int(zone_id.split(":")[1]),
                    "confirmed_at_index": int(zone_id.split(":")[1]) + 2,
                    "source_bar_indices_json": json.dumps(
                        [int(zone_id.split(":")[1])]
                    ),
                    "source_count": 1,
                    "touch_count": 2 if nearest else 1,
                    "validation_rejection_atr": 0.8 if nearest else 0.5,
                    "state": (
                        "SUPPORT_HELD"
                        if structure == "SUPPORT"
                        and nearest
                        and strategy_index >= 301
                        else "SUPPORT_TESTING"
                        if structure == "SUPPORT"
                        and nearest
                        and strategy_index >= 300
                        else "APPROACHING_SUPPORT"
                        if structure == "SUPPORT"
                        else "APPROACHING_RESISTANCE"
                    ),
                    "tested": bool(nearest and strategy_index >= 300),
                    "held": bool(
                        nearest
                        and structure == "SUPPORT"
                        and strategy_index >= 301
                    ),
                    "rejection_atr": (
                        0.7 if nearest and strategy_index >= 300 else None
                    ),
                    "test_count": (
                        2
                        if nearest and strategy_index >= 300
                        else 1
                        if nearest
                        else 0
                    ),
                    "bars_since_test": (
                        max(0, strategy_index - 300)
                        if nearest and strategy_index >= 300
                        else None
                    ),
                    "last_test_index": (
                        300 if nearest and strategy_index >= 300 else None
                    ),
                    "distance_price": abs(float(close[strategy_index]) - low_value),
                    "distance_atr": abs(float(close[strategy_index]) - low_value) / 8.0,
                    "near": bool(nearest),
                    "inside": False,
                    "nearest": bool(nearest),
                }
            )
    sr_zones = pd.DataFrame(zone_rows)
    _write_parquet(trades_path, trades)
    _write_parquet(signals_path, signals)
    _write_parquet(context_path, context)
    _write_parquet(rule_trace_path, rule_trace)
    _write_parquet(sr_zones_path, sr_zones)

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
            "sr_zones": {"path": "artifacts/sr_zones.parquet"},
            "rule_trace": {"path": "artifacts/rule_trace.parquet"},
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



def test_market_source_verification_uses_same_causal_warmup_window(tmp_path):
    _service, _run_dir, manifest, _market = _fixture(tmp_path)
    seed = research_seed_from_manifest(manifest)

    identities = ["warmup-partition-a", "visible-partition-b"]
    source_path = tmp_path / "source_archives.parquet"
    _write_parquet(
        source_path,
        pd.DataFrame(
            {
                "dataset": ["klines", "klines"],
                "interval": ["15m", "15m"],
                "canonical_partition_identity": identities,
            }
        ),
    )
    expected_signature = SourceSignature.from_canonical_identities(
        DatasetKind.KLINES, identities
    )
    requested_start = pd.Timestamp(seed.request.period_start)
    earliest_start = requested_start - pd.Timedelta(days=365)

    class Catalog:
        @staticmethod
        def coverage(*_args, **_kwargs):
            return SimpleNamespace(first_period=earliest_start.to_pydatetime())

    class Store:
        raw_root = tmp_path
        catalog = Catalog()

        def __init__(self):
            self.seen_request = None

        def canonical_source_identity(self, request, dataset, *, interval=None):
            self.seen_request = request
            assert dataset == DatasetKind.KLINES
            assert interval == "15m"
            return expected_signature

    store = Store()
    service = SimpleNamespace(store=store)

    assert (
        CompletedRunVisualizer._verify_market_source(service, seed, source_path)
        is True
    )
    expected_start = requested_start - strategy_warmup_period(seed.config)
    assert pd.Timestamp(store.seen_request.start) == expected_start
    assert pd.Timestamp(store.seen_request.start) < requested_start


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
    assert payload["run"]["srZoneInventoryAvailable"] is True
    assert 60 <= len(payload["candles"]) <= 120
    assert payload["selectedTrade"]["Side"] == "LONG"
    assert payload["selectedTrade"]["Stop"] < payload["selectedTrade"]["Entry"]
    assert payload["selectedTrade"]["Target"] > payload["selectedTrade"]["Entry"]
    assert any(line["kind"] == "entry" for line in payload["priceLines"])
    assert any(line["kind"] == "stop" for line in payload["priceLines"])
    assert any(line["kind"] == "target" for line in payload["priceLines"])

    overlay_names = {item["name"] for item in payload["overlays"]}
    assert {"EMA 50", "EMA 100", "EMA 200", "VWAP"} <= overlay_names
    assert not any(item.get("kind") == "sr" for item in payload["overlays"])

    zone_names = {item["name"] for item in payload["srZones"]}
    assert {"4H Support", "4H Resistance"} <= zone_names
    assert len(payload["srZones"]) >= 4
    assert all(zone.get("inventoryFull") for zone in payload["srZones"])
    assert sum(zone["activeAtEntry"] for zone in payload["srZones"]) >= 4
    assert sum(zone["nearestAtEntry"] for zone in payload["srZones"]) == 2
    assert payload["selectedTradeCandleTime"] is not None
    assert payload["srEvents"]

    assert any(marker["kind"] == "enter" for marker in payload["markers"])
    assert not any(marker["kind"] == "reject" for marker in payload["markers"])
    assert any(marker["kind"] == "exit" for marker in payload["markers"])

    contexts = list(payload["candleContext"].values())
    assert any(item.get("4H Support") == "SUPPORT_HELD" for item in contexts)
    assert service.store.calls
    request, _dataset, interval = service.store.calls[-1]
    assert interval == "15m"
    assert pd.Timestamp(request.start) > pd.Timestamp(manifest["request"]["start"])



def test_sr_zones_never_connect_distinct_zone_identities():
    times = pd.date_range("2026-01-01", periods=6, freq="15min", tz="UTC")
    context = pd.DataFrame(
        {
            "strategy_candle_open_time": times,
            "sr_4h_long_support_zone_low": [90.0] * 6,
            "sr_4h_long_support_zone_high": [92.0] * 6,
            "sr_4h_long_nearest_support_bar_index": [10] * 6,
            "sr_4h_long_resistance_zone_low": [110.0, 110.0, 110.0, 130.0, 130.0, 130.0],
            "sr_4h_long_resistance_zone_high": [112.0, 112.0, 112.0, 132.0, 132.0, 132.0],
            "sr_4h_long_nearest_resistance_bar_index": [20, 20, 20, 35, 35, 35],
        }
    )

    overlays = CompletedRunVisualizer._sr_zones(
        context, "4h", times[0]
    )
    resistance = [
        item
        for item in overlays
        if item["name"] == "4H Resistance"
    ]

    assert len(resistance) == 2
    assert [item["zoneIdentity"] for item in resistance] == [
        ["pivot", 20],
        ["pivot", 35],
    ]
    assert (resistance[0]["low"], resistance[0]["high"]) == (110.0, 112.0)
    assert (resistance[1]["low"], resistance[1]["high"]) == (130.0, 132.0)
    assert resistance[0]["end"] <= resistance[1]["start"]


def test_sr_zones_legacy_fallback_still_breaks_when_zone_boundaries_change():
    times = pd.date_range("2026-01-01", periods=4, freq="15min", tz="UTC")
    context = pd.DataFrame(
        {
            "strategy_candle_open_time": times,
            "sr_4h_long_support_zone_low": [90.0] * 4,
            "sr_4h_long_support_zone_high": [92.0] * 4,
            "sr_4h_long_resistance_zone_low": [110.0, 110.0, 130.0, 130.0],
            "sr_4h_long_resistance_zone_high": [112.0, 112.0, 132.0, 132.0],
        }
    )

    overlays = CompletedRunVisualizer._sr_zones(
        context, "4h", times[0]
    )
    resistance = [
        item
        for item in overlays
        if item["name"] == "4H Resistance"
    ]
    assert len(resistance) == 2
    assert [(item["low"], item["high"]) for item in resistance] == [
        (110.0, 112.0),
        (130.0, 132.0),
    ]


def test_sr_inspector_reads_persisted_multitimeframe_context(tmp_path):
    service, run_dir, manifest, _market = _fixture(tmp_path)
    model = CompletedRunVisualizer.load(service, run_dir, manifest)

    snapshot = model.sr_inspector_at(pd.Timestamp("2026-01-04 03:00:00+00:00"))

    assert snapshot["status"] == "AVAILABLE"
    four_hour = next(
        item for item in snapshot["timeframes"] if item["key"] == "4h"
    )
    assert four_hour["supportZoneLow"] == 112.0
    assert four_hour["supportZoneHigh"] == 113.0
    assert four_hour["resistanceZoneLow"] == 124.0
    assert four_hour["supportDistanceNativeAtr"] == 1.5
    assert four_hour["supportDistanceStrategyAtr"] == 1.5
    assert four_hour["resistanceDistanceStrategyAtr"] == 2.0
    assert four_hour["roomLongNativeAtr"] == 2.0
    assert four_hour["roomShortNativeAtr"] == 1.5
    assert four_hour["structureConflict"] is False
    assert four_hour["completedCandleTime"].endswith("+00:00")
    assert snapshot["zoneInventoryAvailable"] is True
    zones = [item for item in snapshot["zones"] if item["key"] == "4h"]
    assert len(zones) == 4
    assert sum(item["nearest"] for item in zones) == 2
    assert {item["structure"] for item in zones} == {"SUPPORT", "RESISTANCE"}


def test_sr_lifecycle_events_come_from_persisted_test_and_hold_transitions(tmp_path):
    service, run_dir, manifest, _market = _fixture(tmp_path)
    model = CompletedRunVisualizer.load(service, run_dir, manifest)
    payload = model.build_payload(trade_index=0, visible_candles=120)

    four_hour = [
        event
        for event in payload["srEvents"]
        if event["timeframe"] == "4h" and event["structure"] == "support"
    ]
    assert any(event["event"] == "test" for event in four_hour)
    assert any(event["event"] == "held" for event in four_hour)


def test_rule_inspector_reads_exact_decision_time_trace(tmp_path):
    service, run_dir, manifest, _market = _fixture(tmp_path)
    model = CompletedRunVisualizer.load(service, run_dir, manifest)

    trace = model.rule_inspector_at(pd.Timestamp("2026-01-04 03:00:00+00:00"))

    assert trace["status"] == "AVAILABLE"
    assert trace["profile"] == "bull_long"
    assert trace["side"] == "LONG"
    assert trace["filterPassed"] is True
    assert len(trace["rows"]) == 2

    entry = next(row for row in trace["rows"] if row["type"] == "ENTRY")
    assert entry["groupStatus"] == "MATCHED"
    assert entry["actual"] == "24"
    assert entry["requirement"] == ">= 20.0"
    assert entry["conditionStatus"] == "PASS"

    veto = next(row for row in trace["rows"] if row["type"] == "VETO")
    assert veto["groupStatus"] == "CLEAR"
    assert veto["actual"] == "NEAR_MEAN"
    assert veto["requirement"] == "is ABOVE_MEAN"
    assert veto["conditionStatus"] == "FAIL"


def test_visualizer_falls_back_to_nearest_context_without_zone_inventory(tmp_path):
    service, run_dir, manifest, _market = _fixture(tmp_path)
    manifest["artifacts"].pop("sr_zones")
    model = CompletedRunVisualizer.load(service, run_dir, manifest)

    payload = model.build_payload(trade_index=0, visible_candles=120)

    assert payload["run"]["srZoneInventoryAvailable"] is False
    assert payload["srZones"]
    assert all(not zone.get("inventoryFull", False) for zone in payload["srZones"])
    snapshot = model.sr_inspector_at(
        pd.Timestamp("2026-01-04 03:00:00+00:00")
    )
    assert snapshot["zoneInventoryAvailable"] is False
    assert snapshot["zones"] == []


def test_legacy_run_does_not_reverse_engineer_missing_rule_trace(tmp_path):
    service, run_dir, manifest, _market = _fixture(tmp_path)
    manifest["artifacts"].pop("rule_trace")
    model = CompletedRunVisualizer.load(service, run_dir, manifest)

    trace = model.rule_inspector_at(pd.Timestamp("2026-01-04 03:00:00+00:00"))

    assert trace["status"] == "LEGACY_UNAVAILABLE"
    assert "Re-run" in trace["message"]
    assert trace["rows"] == []


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
    assert "qtwebchannel/qwebchannel.js" in html
    assert "strategyBridge.selectCandle" in html
    assert 'id="zone-layer"' in html
    assert "priceToCoordinate" in html
    assert "timeToCoordinate" in html
    assert "S/R SNAPSHOT" in html


def test_active_app_composes_strategy_visualizer():
    import app

    source = inspect.getsource(app.main)
    assert "apply_strategy_visualizer_workspace(window)" in source
