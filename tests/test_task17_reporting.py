"""Blocking contract tests for Task-17 provenance and passive result artifacts."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from crypto_strategy_lab.data.binance.klines import KlineArchiveAdapter
from crypto_strategy_lab.data.schemas import ArchiveRecord, DatasetKind, MarketKind
from crypto_strategy_lab.data.source_identity import canonical_partition_identity
from crypto_strategy_lab.data_lake_config import ResearchRunConfig
from crypto_strategy_lab.feature_research import _trade_fingerprint, _write_parquet_atomic
from crypto_strategy_lab.research_adapters import _signal_frame, _strategy_rule_trace_frame
from crypto_strategy_lab.research_reporting import (
    _validate_research_artifacts,
    _validate_rule_trace_artifact,
    _validate_signal_artifact,
    _validate_sr_zone_artifact,
)
from crypto_strategy_lab.run_manifest import (
    RUN_MANIFEST_CONTRACT,
    RUN_MANIFEST_VERSION,
    RunArtifactError,
    canonical_sha256,
    config_hashes,
    load_completed_manifest,
    selected_source_snapshot,
    source_record,
)


def test_hash_scopes_exclude_reporting_and_separate_strategy_execution():
    base = ResearchRunConfig()
    first = config_hashes(base, "1m")
    changed_report = replace(
        base, reporting=replace(base.reporting, run_name="presentation")
    )
    second = config_hashes(changed_report, "1m")
    assert first["strategy_hash"] == second["strategy_hash"]
    assert first["execution_hash"] == second["execution_hash"]

    changed_execution = replace(
        base, execution=replace(base.execution, taker_fee=base.execution.taker_fee + 0.001)
    )
    execution = config_hashes(changed_execution, "1m")
    assert execution["strategy_hash"] == first["strategy_hash"]
    assert execution["execution_hash"] != first["execution_hash"]

    changed_data_semantics = replace(
        base,
        data=replace(base.data, intrabar_missing_policy="WARN_AND_CONTINUE"),
    )
    assert config_hashes(changed_data_semantics, "1m")["execution_hash"] != first[
        "execution_hash"
    ]
    assert config_hashes(base, "5m")["execution_hash"] != first["execution_hash"]


def test_selected_snapshot_is_deterministic_and_sensitive_to_contributors():
    class Record:
        exchange = "binance"
        market = "futures_um"
        dataset = "klines"
        symbol = "BTCUSDT"
        interval = "1m"
        frequency = "monthly"
        period_start = None
        period_end = None
        size_bytes = 10
        mtime_ns = 20
        fingerprint = "one"

    rows, digest = selected_source_snapshot([Record(), Record()])
    assert len(rows) == 1
    assert selected_source_snapshot([Record()])[1] == digest
    Record.fingerprint = "two"
    assert selected_source_snapshot([Record()])[1] != digest


def test_selected_snapshot_normalizes_equivalent_source_instants_to_utc():
    instant = datetime(2026, 1, 1, tzinfo=timezone.utc)
    sri_lanka = timezone(timedelta(hours=5, minutes=30))
    common = {
        "exchange": "binance",
        "market": "futures_um",
        "dataset": "klines",
        "symbol": "BTCUSDT",
        "interval": "1m",
        "frequency": "monthly",
        "size_bytes": 10,
        "mtime_ns": 20,
        "fingerprint": "same-archive",
    }
    utc_record = SimpleNamespace(
        **common,
        period_start=instant,
        period_end=instant + timedelta(days=1),
    )
    local_record = SimpleNamespace(
        **common,
        period_start=instant.astimezone(sri_lanka),
        period_end=(instant + timedelta(days=1)).astimezone(sri_lanka),
    )

    utc_row = source_record(utc_record)
    local_row = source_record(local_record)
    assert utc_row["period_start"] == "2026-01-01T00:00:00+00:00"
    assert utc_row == local_row
    assert selected_source_snapshot([utc_record])[1] == selected_source_snapshot(
        [local_record]
    )[1]


def test_source_record_uses_real_canonical_partition_identity(tmp_path: Path):
    record = ArchiveRecord(
        raw_root=tmp_path,
        path=tmp_path / "BTCUSDT-1m-2026-01.zip",
        market=MarketKind.FUTURES_UM,
        dataset=DatasetKind.KLINES,
        symbol="BTCUSDT",
        interval="1m",
        frequency="monthly",
        period_start=None,
        period_end=None,
        size_bytes=123,
        mtime_ns=456,
        fingerprint="raw-fingerprint",
    )
    expected = canonical_partition_identity(
        record, KlineArchiveAdapter().canonical_contract()
    )
    assert source_record(record)["canonical_partition_identity"] == expected


def test_incomplete_wrong_or_incompatible_research_manifest_is_not_completed(tmp_path: Path):
    with pytest.raises(RunArtifactError):
        load_completed_manifest(tmp_path)
    (tmp_path / "run_manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RunArtifactError):
        load_completed_manifest(tmp_path)

    manifest = {
        "run_manifest_contract": RUN_MANIFEST_CONTRACT,
        "run_manifest_version": RUN_MANIFEST_VERSION,
        "run_status": "COMPLETED",
        "research": {"artifact_contract": "future", "artifact_version": 999},
    }
    (tmp_path / "run_manifest.json").write_text(
        __import__("json").dumps(manifest), encoding="utf-8"
    )
    with pytest.raises(RunArtifactError, match="research"):
        load_completed_manifest(tmp_path)
    assert len(canonical_sha256({"stable": True})) == 64


def _research_frames():
    # PreparedBacktestFrame stores canonical UTC instants in datetime64[ns]
    # without a timezone tag.  Keep the fixture faithful to that contract so
    # cross-type TIMESTAMP/TIMESTAMPTZ comparisons cannot hide in UTC CI.
    times = pd.to_datetime(
        ["2026-01-01T00:00:00Z", "2026-01-01T04:00:00Z"], utc=True
    ).tz_localize(None)
    available = times + pd.Timedelta(hours=4)
    context = pd.DataFrame(
        {
            "strategy_index": [0, 1],
            "strategy_candle_open_time": times,
            "decision_available_at": available,
            "plus_di": [30.0, 20.0],
        }
    )
    trades = pd.DataFrame(
        {
            "pair_id": [1],
            "side": ["LONG"],
            "entry_time": [available[1]],
            "exit_time": [available[1] + pd.Timedelta(hours=1)],
            "pair_net_pnl": [10.0],
            "pair_net_r": [1.0],
            "research_signal_index": [1],
            "research_signal_candle_open_time": [times[1]],
            "research_signal_available_at": [available[1]],
            "plus_di": [20.0],
        }
    )
    return trades, context


def test_research_semantics_are_validated_before_completion(tmp_path: Path):
    trades, context = _research_frames()
    trades_path = tmp_path / "trades.parquet"
    context_path = tmp_path / "context.parquet"
    _write_parquet_atomic(trades, trades_path)
    _write_parquet_atomic(context, context_path)
    research = {
        "artifact_contract": "feature_research_v1",
        "artifact_version": 1,
        "request": {"strategy_interval": "4h"},
        "trade_row_count": 1,
        "feature_context_row_count": 2,
        "trade_columns": list(trades.columns),
        "feature_context_columns": list(context.columns),
        "trade_context_parity_columns": ["plus_di"],
        "trade_fingerprint": _trade_fingerprint(trades),
    }
    _validate_research_artifacts(trades_path, context_path, research)

    broken = trades.copy()
    broken.loc[0, "research_signal_available_at"] = broken.loc[
        0, "research_signal_available_at"
    ] + pd.Timedelta(minutes=1)
    _write_parquet_atomic(broken, trades_path)
    with pytest.raises(ValueError, match="causal"):
        _validate_research_artifacts(trades_path, context_path, research)


def test_sr_zone_artifact_requires_exact_causal_attachment(tmp_path: Path):
    _trades, context = _research_frames()
    zones = pd.DataFrame(
        [
            {
                "strategy_index": 1,
                "strategy_candle_open_time": context.loc[
                    1, "strategy_candle_open_time"
                ],
                "decision_available_at": context.loc[1, "decision_available_at"],
                "sr_timeframe": "4h",
                "sr_timeframe_minutes": 240,
                "sr_completed_candle_time": context.loc[
                    1, "decision_available_at"
                ],
                "zone_id": "SUPPORT:7",
                "structure": "SUPPORT",
                "zone_low": 95.0,
                "zone_high": 96.0,
                "anchor_price": 95.0,
                "pivot_bar_index": 7,
                "confirmed_at_index": 9,
                "source_bar_indices_json": "[7]",
                "source_count": 1,
                "touch_count": 2,
                "validation_rejection_atr": 0.8,
                "state": "SUPPORT_HELD",
                "tested": True,
                "held": True,
                "rejection_atr": 0.7,
                "test_count": 2,
                "bars_since_test": 1,
                "last_test_index": 10,
                "distance_price": 4.0,
                "distance_atr": 1.0,
                "near": False,
                "inside": False,
                "nearest": True,
            }
        ]
    )
    # Simulate the v8.0 mixed physical timestamp representation: the
    # feature-context contract is UTC-naive TIMESTAMP while zone rows are
    # TIMESTAMPTZ. Validation must remain host-timezone independent.
    for column in (
        "strategy_candle_open_time",
        "decision_available_at",
        "sr_completed_candle_time",
    ):
        zones[column] = pd.to_datetime(zones[column], utc=True)

    context_path = tmp_path / "context.parquet"
    zones_path = tmp_path / "sr_zones.parquet"
    _write_parquet_atomic(context, context_path)
    _write_parquet_atomic(zones, zones_path)
    _validate_sr_zone_artifact(zones_path, context_path, expected_rows=1)

    future = zones.copy()
    future.loc[0, "sr_completed_candle_time"] = (
        future.loc[0, "decision_available_at"] + pd.Timedelta(minutes=1)
    )
    _write_parquet_atomic(future, zones_path)
    with pytest.raises(
        ValueError, match="future_sr_completed_candle=1"
    ):
        _validate_sr_zone_artifact(zones_path, context_path, expected_rows=1)


def test_signal_frame_uses_same_run_rejections_and_exact_causal_rows(tmp_path: Path):
    trades, context = _research_frames()
    prepared = SimpleNamespace(
        timestamp=context["strategy_candle_open_time"].to_numpy(),
        decision_available_at=context["decision_available_at"].to_numpy(),
    )
    skipped = [
        {
            "strategy_candle_open_time": context.loc[0, "strategy_candle_open_time"],
            "strategy_entry_price": 100.0,
            "plus_di": 10.0,
            "minus_di": 25.0,
            "entry_filter_reason": "rejected by profile",
        }
    ]
    signals = _signal_frame(prepared, trades, skipped)
    assert list(signals["decision"]) == ["REJECT", "ENTER"]
    assert list(signals["strategy_index"]) == [0, 1]
    assert signals.loc[0, "side"] == "SHORT"
    assert signals.loc[1, "side"] == "LONG"
    assert str(signals["candle_open_time"].dtype) == "datetime64[ns]"
    assert str(signals["decision_available_at"].dtype) == "datetime64[ns]"

    signals_path = tmp_path / "signals.parquet"
    context_path = tmp_path / "context.parquet"
    _write_parquet_atomic(signals, signals_path)
    _write_parquet_atomic(context, context_path)
    _validate_signal_artifact(signals_path, context_path, trade_rows=1)



def test_rule_trace_artifact_requires_exact_prepared_candle_attachment(tmp_path: Path):
    _trades, context = _research_frames()
    trace = _strategy_rule_trace_frame(
        [
            {
                "strategy_index": 1,
                "strategy_candle_open_time": context.loc[1, "strategy_candle_open_time"],
                "decision_available_at": context.loc[1, "decision_available_at"],
                "market_regime": "BULL",
                "source_side": "LONG",
                "strategy_profile_key": "bull_long",
                "signal_strategy": "DI",
                "rule_kind": "REQUIRED",
                "group_id": "entry-1",
                "group_name": "Trend entry",
                "group_enabled": True,
                "group_evaluated": True,
                "group_matched": True,
                "condition_id": "adx-1",
                "condition_order": 1,
                "condition_evaluated": True,
                "evidence": "ADX",
                "timeframe_minutes": None,
                "operator": "GTE",
                "expected_value": 20.0,
                "expected_value2": 0.0,
                "actual_value": 24.0,
                "evidence_available": True,
                "condition_passed": True,
                "filter_passed": True,
                "filter_reason": "passed",
            }
        ]
    )
    trace_path = tmp_path / "rule_trace.parquet"
    context_path = tmp_path / "context.parquet"
    _write_parquet_atomic(trace, trace_path)
    _write_parquet_atomic(context, context_path)
    _validate_rule_trace_artifact(trace_path, context_path)

    broken = trace.copy()
    broken.loc[0, "strategy_candle_open_time"] = (
        pd.Timestamp(broken.loc[0, "strategy_candle_open_time"])
        + pd.Timedelta(minutes=1)
    )
    _write_parquet_atomic(broken, trace_path)
    with pytest.raises(ValueError, match="causal attachment"):
        _validate_rule_trace_artifact(trace_path, context_path)


def test_signal_frame_refuses_nearest_timestamp_reconstruction():
    trades, context = _research_frames()
    prepared = SimpleNamespace(
        timestamp=context["strategy_candle_open_time"].to_numpy(),
        decision_available_at=context["decision_available_at"].to_numpy(),
    )
    skipped = [
        {
            "strategy_candle_open_time": context.loc[0, "strategy_candle_open_time"]
            + pd.Timedelta(minutes=1),
            "plus_di": 20.0,
            "minus_di": 10.0,
            "entry_filter_reason": "bad timestamp",
        }
    ]
    with pytest.raises(ValueError, match="exact prepared strategy row"):
        _signal_frame(prepared, trades.iloc[0:0], skipped)
