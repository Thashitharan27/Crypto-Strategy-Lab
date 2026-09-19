from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from crypto_strategy_lab.causal_experiment import CausalExperimentStore
from crypto_strategy_lab.data_lake_config import ResearchRunConfig
from crypto_strategy_lab.run_manifest import file_sha256
from crypto_strategy_lab.walk_forward_candidate_engine import (
    _ema_stack,
    _price_vs_ema,
    _safe_context,
    get_next_walk_forward_candidate,
)


EXPERIMENT_ID = "BTCUSDT_1D_WF_CANDIDATE_TEST"
REFERENCE_RUN = "BTCUSDT_1d_reference"


class FakeReports:
    def __init__(self, run_dir: Path, manifest: dict):
        self.run_dir = run_dir
        self.manifest = manifest

    def get_run_manifest(self, run: str) -> dict:
        if run != REFERENCE_RUN:
            raise ValueError(f"unknown run: {run}")
        return self.manifest

    def resolve_run(self, run: str) -> Path:
        if run != REFERENCE_RUN:
            raise ValueError(f"unknown run: {run}")
        return self.run_dir


def _config() -> dict:
    config = ResearchRunConfig().to_dict()
    config["data"]["strategy_timeframe_minutes"] = 1440
    config["data"]["intrabar_timeframe_minutes"] = 1
    config["data"]["use_intrabar_data"] = True
    config["features"]["market_regime_method"] = "ASSET_RETURN"
    config["features"]["enable_support_resistance_analysis"] = True
    config["execution"]["risk_per_leg"] = 0.01
    for values in config["execution"]["profiles"].values():
        values["stop_loss_multiple"] = 1.0
        values["reward_risk_ratio"] = 1.0
    return config


def _definition() -> dict:
    return {
        "symbol": "BTCUSDT",
        "strategy_timeframe": "1d",
        "intrabar_timeframe": "1m",
        "strategy": "DI_DIRECTION",
        "stop_loss": {"type": "ATR", "multiple": 1.0},
        "take_profit": {"type": "R", "multiple": 1.0},
        "regime_method": "ASSET_RETURN",
        "risk_model": "FIXED_FRACTIONAL",
        "reference_run": REFERENCE_RUN,
        "initial_equity": 1000.0,
        "risk_pct": 1.0,
    }


def _catalog(path: Path, run_dir: Path) -> dict:
    return {
        "path": str(path.relative_to(run_dir)).replace("\\", "/"),
        "sha256": file_sha256(path),
        "format": "parquet",
    }


def _write_reference(
    tmp_path: Path,
    *,
    samples: pd.DataFrame,
    context: pd.DataFrame,
    teacher_trades: pd.DataFrame | None = None,
) -> tuple[SimpleNamespace, FakeReports, CausalExperimentStore, dict]:
    project = tmp_path / "project"
    output = tmp_path / "output"
    run_dir = output / REFERENCE_RUN
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True)
    project.mkdir(parents=True)

    samples_path = artifacts / "research_sampling_trades.parquet"
    context_path = artifacts / "feature_context.parquet"
    samples.to_parquet(samples_path, index=False)
    context.to_parquet(context_path, index=False)
    artifact_map = {
        "research_sampling_trades": _catalog(samples_path, run_dir),
        "feature_context": _catalog(context_path, run_dir),
    }
    if teacher_trades is not None:
        trades_path = artifacts / "trades.parquet"
        teacher_trades.to_parquet(trades_path, index=False)
        artifact_map["trades"] = _catalog(trades_path, run_dir)

    manifest = {
        "run_id": REFERENCE_RUN,
        "request": {"symbol": "BTCUSDT"},
        "config": _config(),
        "artifacts": artifact_map,
        "research": {
            "strategy_research_sampling": {
                "mode": "EVERY_VIABLE_ENTRY",
                "selected_rows": len(samples),
            }
        },
    }
    control = SimpleNamespace(project_root=project, output_root=output)
    reports = FakeReports(run_dir, manifest)
    store = CausalExperimentStore(project / "walk_forward_experiments")
    head = store.create(EXPERIMENT_ID, _definition(), "create:candidate-test")
    return control, reports, store, head


def _append_rule(store, head, event_type, rule_id, family, conditions, operation):
    payload = {
        "rule_id": rule_id,
        "rule_version": "1",
        "effective_from": "2025-01-01T00:00:00Z",
        "reason": "test causal rule",
        "evidence_source": "TEACHER" if family == "ENTRY" else "PROSPECTIVE_WF",
        "profile": "bull_long",
        "conditions": conditions,
    }
    return store.append_event(
        EXPERIMENT_ID,
        event_type,
        payload,
        operation,
        head["sequence"],
        head["state_hash"],
        effective_market_time="2025-01-01T00:00:00Z",
    )


def _samples() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "research_sample_id": "s10",
                "research_signal_index": 10,
                "research_sampling_mode": "EVERY_VIABLE_ENTRY",
                "strategy_profile_key": "bull_long",
                "side": "LONG",
                "entry_time": "2025-01-02T00:00:00Z",
                "signal_available_at": "2025-01-02T00:00:00Z",
                "signal_close_price": 100.0,
                "ema_50": 95.0,
                "ema_100": 90.0,
                "ema_200": 80.0,
                "rsi": 45.0,
                "pair_net_r": -1.0,
                "exit_time": "2025-01-02T12:00:00Z",
            },
            {
                "research_sample_id": "s11",
                "research_signal_index": 11,
                "research_sampling_mode": "EVERY_VIABLE_ENTRY",
                "strategy_profile_key": "bull_long",
                "side": "LONG",
                "entry_time": "2025-01-03T00:00:00Z",
                "signal_available_at": "2025-01-03T00:00:00Z",
                "signal_close_price": 110.0,
                "ema_50": 100.0,
                "ema_100": 90.0,
                "ema_200": 80.0,
                "rsi": 85.0,
                "pair_net_r": -1.0,
                "exit_time": "2025-01-03T12:00:00Z",
            },
            {
                "research_sample_id": "s12",
                "research_signal_index": 12,
                "research_sampling_mode": "EVERY_VIABLE_ENTRY",
                "strategy_profile_key": "bull_long",
                "side": "LONG",
                "entry_time": "2025-01-04T00:00:00Z",
                "signal_available_at": "2025-01-04T00:00:00Z",
                "signal_close_price": 120.0,
                "ema_50": 105.0,
                "ema_100": 95.0,
                "ema_200": 85.0,
                "rsi": 55.0,
                "pair_net_r": 1.0,
                "exit_time": "2025-01-04T12:00:00Z",
            },
        ]
    )


def _context() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "strategy_index": 9,
                "strategy_candle_open_time": "2025-01-01T00:00:00Z",
                "decision_available_at": "2025-01-01T00:00:00Z",
                "adx": 20.0,
                "plus_di": 25.0,
                "minus_di": 15.0,
                "close": 99.0,
                "atr": 5.0,
                "atr_pct": 0.05,
                "session_vwap": 98.0,
                "close_location": 0.7,
                "mean_reversion_state": "NEAR_MEAN",
            },
            {
                "strategy_index": 10,
                "strategy_candle_open_time": "2025-01-02T00:00:00Z",
                "decision_available_at": "2025-01-02T00:00:00Z",
                "adx": 25.0,
                "plus_di": 28.0,
                "minus_di": 14.0,
                "close": 100.0,
                "atr": 5.0,
                "atr_pct": 0.05,
                "session_vwap": 99.0,
                "close_location": 0.7,
                "mean_reversion_state": "NEAR_MEAN",
            },
            {
                "strategy_index": 11,
                "strategy_candle_open_time": "2025-01-03T00:00:00Z",
                "decision_available_at": "2025-01-03T00:00:00Z",
                "adx": 35.0,
                "plus_di": 30.0,
                "minus_di": 15.0,
                "close": 110.0,
                "atr": 5.0,
                "atr_pct": 0.045,
                "session_vwap": 108.0,
                "close_location": 0.8,
                "mean_reversion_state": "ABOVE_MEAN",
            },
            {
                "strategy_index": 12,
                "strategy_candle_open_time": "2025-01-04T00:00:00Z",
                "decision_available_at": "2025-01-04T00:00:00Z",
                "adx": 40.0,
                "plus_di": 32.0,
                "minus_di": 16.0,
                "close": 120.0,
                "atr": 5.0,
                "atr_pct": 0.04,
                "session_vwap": 118.0,
                "close_location": 0.85,
                "mean_reversion_state": "ABOVE_MEAN",
            },
        ]
    )



def test_walk_forward_context_replaces_raw_sr_with_trade_relative_v2_units():
    config = _config()
    config["data"]["strategy_timeframe_minutes"] = 15
    config["execution"]["risk_mode"] = "ATR"
    config["execution"]["atr_multiplier"] = 1.0
    profile = config["execution"]["profiles"]["bull_long"]
    profile["stop_loss_multiple"] = 1.0
    profile["reward_risk_ratio"] = 3.0

    row = {
        "signal_close_price": 1000.0,
        "atr_at_entry": 100.0,
        "atr": 100.0,
    }
    context = {
        "atr": 100.0,
        "sr_1h_long_nearest_support_price": 800.0,
        "sr_1h_long_nearest_support_distance_atr": 1.0,
        "sr_1h_long_nearest_support_distance_price": 200.0,
        "sr_1h_long_nearest_resistance_price": 1600.0,
        "sr_1h_long_nearest_resistance_distance_atr": 3.0,
        "sr_1h_long_nearest_resistance_distance_price": 600.0,
        "sr_1h_long_near_support": False,
        "sr_1h_long_near_resistance": False,
        "sr_1h_long_inside_support_zone": False,
        "sr_1h_long_inside_resistance_zone": False,
        "sr_1h_long_support_state": "APPROACHING_SUPPORT",
        "sr_1h_long_resistance_state": "APPROACHING_RESISTANCE",
        "sr_1h_long_support_held": False,
        "sr_1h_long_resistance_held": False,
        "sr_1h_long_support_zone_low": 750.0,
        "sr_1h_long_support_zone_high": 850.0,
        "sr_1h_long_resistance_zone_low": 1600.0,
        "sr_1h_long_resistance_zone_high": 1700.0,
        "sr_1d_long_nearest_support_price": 800.0,
        "sr_1d_long_nearest_support_distance_atr": 0.15,
        "sr_1d_long_nearest_support_distance_price": 200.0,
        "sr_1d_long_nearest_resistance_price": 1600.0,
        "sr_1d_long_nearest_resistance_distance_atr": 0.5,
        "sr_1d_long_nearest_resistance_distance_price": 600.0,
        "sr_1d_long_near_support": False,
        "sr_1d_long_near_resistance": False,
        "sr_1d_long_inside_support_zone": False,
        "sr_1d_long_inside_resistance_zone": False,
        "sr_1d_long_support_state": "APPROACHING_SUPPORT",
        "sr_1d_long_resistance_state": "APPROACHING_RESISTANCE",
        "sr_1d_long_support_held": False,
        "sr_1d_long_resistance_held": False,
        "sr_1d_long_support_zone_low": 750.0,
        "sr_1d_long_support_zone_high": 850.0,
        "sr_1d_long_resistance_zone_low": 1600.0,
        "sr_1d_long_resistance_zone_high": 1700.0,
    }

    safe = _safe_context(
        {**context, **row},
        context,
        direction="LONG",
        profile="bull_long",
        config=config,
    )

    sr = safe["support_resistance_trade_context_v2"]["timeframes"]
    assert sr["1H"]["opposing_distance_native_atr"] == 3.0
    assert sr["1D"]["opposing_distance_native_atr"] == 0.5
    assert sr["1H"]["opposing_distance_strategy_atr"] == 6.0
    assert sr["1D"]["opposing_distance_strategy_atr"] == 6.0
    assert sr["1H"]["opposing_room_r"] == 6.0
    assert sr["1D"]["opposing_room_r"] == 6.0
    assert sr["1H"]["opposing_room_target_multiple"] == 2.0
    assert sr["1D"]["opposing_room_target_multiple"] == 2.0
    assert sr["1H"]["target_path"] == "TARGET_BEFORE_OPPOSING_ZONE"
    assert sr["1D"]["target_path"] == "TARGET_BEFORE_OPPOSING_ZONE"
    assert "sr_1h_long_nearest_resistance_distance_atr" not in safe["feature_context"]
    assert "sr_1d_long_nearest_resistance_distance_atr" not in safe["feature_context"]


def test_ema_categorical_values_match_strategy_builder_contract():
    bullish = {"ema_50": 3.0, "ema_100": 2.0, "ema_200": 1.0, "close": 4.0}
    bearish = {"ema_50": 1.0, "ema_100": 2.0, "ema_200": 3.0, "close": 0.0}
    assert _ema_stack(bullish) == "BULLISH_STACK"
    assert _ema_stack(bearish) == "BEARISH_STACK"
    assert _price_vs_ema(bullish) == "ABOVE_ALL_EMAS"
    assert _price_vs_ema(bearish) == "BELOW_ALL_EMAS"


def test_scanner_applies_entry_veto_flip_and_never_returns_outcome(tmp_path):
    control, reports, store, head = _write_reference(
        tmp_path, samples=_samples(), context=_context()
    )
    head = _append_rule(
        store, head, "ENTRY_LEARNED", "ENTRY_001", "ENTRY",
        [{"indicator": "ADX", "condition": "GTE", "value": 30}],
        "rule:entry",
    )
    head = _append_rule(
        store, head, "VETO_LEARNED", "VETO_001", "VETO",
        [{"indicator": "RSI", "condition": "GTE", "value": 80}],
        "rule:veto",
    )
    head = _append_rule(
        store, head, "FLIP_LEARNED", "FLIP_001", "FLIP",
        [{"indicator": "ADX", "condition": "GTE", "value": 40}],
        "rule:flip",
    )

    result = get_next_walk_forward_candidate(
        control,
        reports,
        experiment_id=EXPERIMENT_ID,
        operation_id="candidate:next:1",
        expected_sequence=head["sequence"],
        expected_state_hash=head["state_hash"],
    )
    assert result["status"] == "CANDIDATE_CAPTURED"
    candidate = result["candidate"]
    assert candidate["research_signal_index"] == 12
    assert candidate["source_side"] == "LONG"
    assert candidate["rule_effective_side"] == "SHORT"
    assert candidate["matched_entry_groups"] == ["ENTRY_001"]
    assert candidate["matched_flip_groups"] == ["FLIP_001"]
    assert result["outcome_exposed"] is False
    flat = str(candidate).lower()
    assert "pair_net_r" not in flat
    assert "exit_time" not in flat
    assert store.read(EXPERIMENT_ID)["derived_state"]["candidate_states"]["12-long"] == "ENTRY_CONTEXT_CAPTURED"

    replay = get_next_walk_forward_candidate(
        control,
        reports,
        experiment_id=EXPERIMENT_ID,
        operation_id="candidate:next:1",
        expected_sequence=head["sequence"],
        expected_state_hash=head["state_hash"],
    )
    assert replay["idempotent_replay"] is True
    assert replay["candidate"]["candidate_id"] == "12-long"


def test_scanner_blocks_advancing_while_candidate_is_unresolved(tmp_path):
    control, reports, store, head = _write_reference(
        tmp_path, samples=_samples(), context=_context()
    )
    head = _append_rule(
        store, head, "ENTRY_LEARNED", "ENTRY_001", "ENTRY",
        [{"indicator": "ADX", "condition": "GTE", "value": 30}],
        "rule:entry",
    )
    first = get_next_walk_forward_candidate(
        control, reports, experiment_id=EXPERIMENT_ID,
        operation_id="candidate:first", expected_sequence=head["sequence"],
        expected_state_hash=head["state_hash"],
    )
    with pytest.raises(ValueError, match="finish or invalidate"):
        get_next_walk_forward_candidate(
            control, reports, experiment_id=EXPERIMENT_ID,
            operation_id="candidate:second", expected_sequence=first["sequence"],
            expected_state_hash=first["state_hash"],
        )


def test_scanner_returns_teacher_boundary_before_later_candidate(tmp_path):
    teachers = pd.DataFrame(
        [
            {
                "pair_id": 593,
                "side": "LONG",
                "strategy_profile_key": "bull_long",
                "entry_time": "2025-01-01T00:00:00Z",
                "exit_time": "2025-01-02T12:00:00Z",
                "pair_net_r": 1.0,
            }
        ]
    )
    control, reports, store, head = _write_reference(
        tmp_path, samples=_samples(), context=_context(), teacher_trades=teachers
    )
    head = _append_rule(
        store, head, "ENTRY_LEARNED", "ENTRY_001", "ENTRY",
        [{"indicator": "ADX", "condition": "GTE", "value": 30}],
        "rule:entry",
    )
    result = get_next_walk_forward_candidate(
        control, reports, experiment_id=EXPERIMENT_ID,
        operation_id="candidate:teacher-guard", expected_sequence=head["sequence"],
        expected_state_hash=head["state_hash"],
    )
    assert result["status"] == "TEACHER_DUE_FIRST"
    assert result["teacher_boundary"]["pair_id"] == 593
    assert result["candidate_not_captured"] is True
    assert store.read(EXPERIMENT_ID)["derived_state"]["candidate_states"] == {}


def test_scanner_rejects_stale_chain_head(tmp_path):
    control, reports, store, head = _write_reference(
        tmp_path, samples=_samples(), context=_context()
    )
    head = _append_rule(
        store, head, "ENTRY_LEARNED", "ENTRY_001", "ENTRY",
        [{"indicator": "ADX", "condition": "GTE", "value": 30}],
        "rule:entry",
    )
    with pytest.raises(ValueError, match="changed since it was read"):
        get_next_walk_forward_candidate(
            control, reports, experiment_id=EXPERIMENT_ID,
            operation_id="candidate:stale", expected_sequence=head["sequence"] - 1,
            expected_state_hash=head["state_hash"],
        )
