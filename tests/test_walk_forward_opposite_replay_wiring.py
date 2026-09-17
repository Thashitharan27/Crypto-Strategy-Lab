from types import SimpleNamespace

import pandas as pd

from crypto_strategy_lab.walk_forward_opposite_replay import _simulate_simple_one_r
from mcp_server import control_server


def test_simple_one_r_replay_resolves_short_target_from_one_minute_bars():
    frame = pd.DataFrame(
        {
            "period_start": pd.to_datetime(
                ["2026-01-01T00:00:00Z", "2026-01-01T00:01:00Z"], utc=True
            ),
            "high": [100.2, 100.1],
            "low": [99.8, 98.9],
        }
    )
    outcome = _simulate_simple_one_r(
        frame,
        side="SHORT",
        entry_price=100.0,
        stop_distance=1.0,
        slippage=0.0,
        tie_policy="PESSIMISTIC",
        entry_fee_rate=0.0,
        exit_fee_rate=0.0,
    )
    assert outcome is not None
    assert outcome["result"] == "WIN"
    assert outcome["exit_reason"] == "TP"
    assert outcome["exit_time"] == "2026-01-01T00:01:00+00:00"


def test_teacher_loss_packet_falls_back_to_immutable_replay(monkeypatch):
    base = {
        "status": "TEACHER_LOSS_REVIEW_REQUIRED",
        "teacher": {
            "pair_id": "4",
            "side": "LONG",
            "strategy_profile_key": "bull_long",
            "resolution_time": "2026-01-02T00:00:00+00:00",
        },
        "entry_context": {"trade_entry_context": {"entry_time": "2026-01-01T00:00:00+00:00"}},
        "opposite_side_outcome": {
            "available": False,
            "side": "SHORT",
            "reason": "no unique immutable Every Viable Entry outcome",
        },
        "flip_activation_allowed": False,
    }
    monkeypatch.setattr(
        control_server,
        "_ORIGINAL_TEACHER_LOSS_DECORATOR",
        lambda control, reports, experiment_id, result: dict(base),
    )
    fake_store = SimpleNamespace(
        read=lambda experiment_id, recent_events=0: {
            "manifest": {"definition": {"reference_run": "BTCUSDT_4h_reference"}}
        }
    )
    monkeypatch.setattr(
        control_server._wf_orchestrator._impl,
        "_store",
        lambda control: fake_store,
    )
    monkeypatch.setattr(
        control_server,
        "_replay_opposite_one_r",
        lambda *args, **kwargs: {
            "available": True,
            "side": "SHORT",
            "source": "IMMUTABLE_1M_INTRABAR_REPLAY",
            "outcome": {"result": "WIN", "net_r": 0.99},
        },
    )

    result = control_server._decorate_teacher_loss_with_replay(
        SimpleNamespace(), object(), "BTCUSDT_4H_WF_TEST", {}
    )

    assert result["opposite_side_outcome"]["available"] is True
    assert result["opposite_side_outcome"]["source"] == "IMMUTABLE_1M_INTRABAR_REPLAY"
    assert result["flip_activation_allowed"] is True


def test_teacher_loss_packet_keeps_unique_eve_fast_path(monkeypatch):
    base = {
        "status": "TEACHER_LOSS_REVIEW_REQUIRED",
        "teacher": {"side": "LONG"},
        "opposite_side_outcome": {
            "available": True,
            "side": "SHORT",
            "outcome": {"result": "WIN"},
        },
        "flip_activation_allowed": True,
    }
    monkeypatch.setattr(
        control_server,
        "_ORIGINAL_TEACHER_LOSS_DECORATOR",
        lambda control, reports, experiment_id, result: dict(base),
    )

    def should_not_run(*args, **kwargs):
        raise AssertionError("1m replay should not run when EVE already has a unique opposite outcome")

    monkeypatch.setattr(control_server, "_replay_opposite_one_r", should_not_run)
    result = control_server._decorate_teacher_loss_with_replay(
        SimpleNamespace(), object(), "BTCUSDT_4H_WF_TEST", {}
    )
    assert result["opposite_side_outcome"]["available"] is True
    assert result["flip_activation_allowed"] is True
