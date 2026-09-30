from types import SimpleNamespace

import pytest

from crypto_strategy_lab import walk_forward_edge_lifecycle as edge


def _policy():
    return {
        "enabled": True,
        "initial_state": "LIVE",
        "live_lookback_trades": 3,
        "live_min_trades": 3,
        "suspend_expectancy_r": 0.0,
        "suspend_net_r": -1.0,
        "shadow_lookback_trades": 3,
        "shadow_min_trades": 3,
        "recover_expectancy_r": 0.25,
        "recover_net_r": 1.0,
    }


def _event(sequence, candidate_id, net_r):
    return {
        "sequence": sequence,
        "event_type": "TRADE_RESOLVED",
        "effective_market_time": f"2024-01-{sequence:02d}T00:00:00+00:00",
        "payload": {
            "candidate_id": candidate_id,
            "ledger": "RESEARCH",
            "net_r": net_r,
        },
    }


class _FakeStore:
    def __init__(self, definition, events):
        self.definition = definition
        self.events = events

    def read_fast(self, experiment_id, recent_events=0):
        return {
            "sequence": 99,
            "state_hash": "a" * 64,
            "manifest": {"definition": self.definition},
        }

    def indexed_events(self, experiment_id, event_types=None):
        return list(self.events)


def test_policy_requires_explicit_thresholds_and_hysteresis():
    with pytest.raises(ValueError, match="missing required fields"):
        edge.normalize_edge_lifecycle_policy({"enabled": True})

    bad = _policy()
    bad["recover_expectancy_r"] = bad["suspend_expectancy_r"]
    with pytest.raises(ValueError, match="hysteresis"):
        edge.normalize_edge_lifecycle_policy(bad)


def test_single_strategy_live_shadow_recovery_is_causal(monkeypatch, tmp_path):
    definition = {
        "strategy": "EMA_CROSS",
        "symbol": "BTCUSDT",
        "strategy_timeframe": "4h",
        "risk_model": {"initial_equity": 1000.0, "risk_per_trade": 0.01},
        "edge_lifecycle_policy": _policy(),
    }
    events = [
        _event(1, "c1", -1.0),
        _event(2, "c2", -1.0),
        _event(3, "c3", -1.0),  # trigger suspension after this LIVE loss
        _event(4, "c4", 1.0),
        _event(5, "c5", 1.0),
        _event(6, "c6", 1.0),  # trigger recovery after this SHADOW win
        _event(7, "c7", 1.0),  # first trade back in LIVE
    ]
    fake = _FakeStore(definition, events)
    monkeypatch.setattr(edge, "CausalExperimentStore", lambda _root: fake)

    result = edge.summarize_walk_forward_edge_lifecycle(
        SimpleNamespace(project_root=tmp_path),
        object(),
        experiment_id="wf-test",
    )

    assert result["current_capital_state"] == "LIVE"
    assert [row["capital_state"] for row in result["trade_states"]] == [
        "LIVE", "LIVE", "LIVE", "SHADOW", "SHADOW", "SHADOW", "LIVE"
    ]
    assert [item["reason"] for item in result["transitions"]] == [
        "EDGE_DECAY_CONFIRMED",
        "EDGE_RECOVERY_CONFIRMED",
    ]
    assert result["transitions"][0]["effective_after_candidate_id"] == "c3"
    assert result["transitions"][1]["effective_after_candidate_id"] == "c6"
    assert result["performance"]["continuous_strategy"]["net_r"] == 1.0
    assert result["performance"]["edge_managed_live"]["net_r"] == -2.0
    assert result["performance"]["shadow_only"]["net_r"] == 3.0
    assert result["performance"]["capital_gate_effect"]["profits_missed_r"] == 3.0


def test_policy_absence_does_not_invent_thresholds(monkeypatch, tmp_path):
    fake = _FakeStore(
        {"strategy": "EMA_CROSS", "symbol": "BTCUSDT", "strategy_timeframe": "4h"},
        [],
    )
    monkeypatch.setattr(edge, "CausalExperimentStore", lambda _root: fake)
    result = edge.summarize_walk_forward_edge_lifecycle(
        SimpleNamespace(project_root=tmp_path),
        object(),
        experiment_id="wf-disabled",
    )
    assert result["enabled"] is False
    assert "not invented" in result["reason"]
