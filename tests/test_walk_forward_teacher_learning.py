from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from crypto_strategy_lab.run_manifest import file_sha256
from crypto_strategy_lab.walk_forward_teacher_learning import (
    TEACHER_LOSS_FLIP_MODE,
    next_teacher_for_learning,
)


def _catalog(path: Path, run_dir: Path) -> dict:
    return {
        "path": str(path.relative_to(run_dir)).replace("\\", "/"),
        "sha256": file_sha256(path),
        "format": "parquet",
    }


def _reference(tmp_path: Path, reward_risk_ratio: float) -> tuple[dict, Path]:
    run_dir = tmp_path / "reference"
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True)
    trades_path = artifacts / "trades.parquet"
    pd.DataFrame(
        [
            {
                "pair_id": 2,
                "side": "SHORT",
                "strategy_profile_key": "sideways_short",
                "entry_time": "2025-01-01T00:00:00Z",
                "exit_time": "2025-01-01T04:00:00Z",
                "pair_net_r": 0.98,
            },
            {
                "pair_id": 3,
                "side": "SHORT",
                "strategy_profile_key": "sideways_short",
                "entry_time": "2025-01-02T00:00:00Z",
                "exit_time": "2025-01-02T04:00:00Z",
                "pair_net_r": 0.97,
            },
            {
                "pair_id": 4,
                "side": "LONG",
                "strategy_profile_key": "bull_long",
                "entry_time": "2025-01-03T00:00:00Z",
                "exit_time": "2025-01-03T04:00:00Z",
                "pair_net_r": -1.119,
            },
            {
                "pair_id": 5,
                "side": "LONG",
                "strategy_profile_key": "bull_long",
                "entry_time": "2025-01-04T00:00:00Z",
                "exit_time": "2025-01-04T04:00:00Z",
                "pair_net_r": 0.96,
            },
        ]
    ).to_parquet(trades_path, index=False)
    manifest = {
        "config": {
            "execution": {
                "profiles": {
                    "sideways_short": {"reward_risk_ratio": reward_risk_ratio},
                    "bull_long": {"reward_risk_ratio": reward_risk_ratio},
                }
            }
        },
        "artifacts": {"trades": _catalog(trades_path, run_dir)},
        "research": {"strategy_research_sampling": {"mode": "WALK_FORWARD"}},
    }
    return manifest, run_dir


def _resolved(pair_id: int, when: str) -> dict:
    return {
        "event_type": "TEACHER_RESOLVED",
        "effective_market_time": when,
        "payload": {"pair_id": pair_id, "result": "WIN"},
    }


def _events_through_pair_3() -> list[dict]:
    return [
        _resolved(2, "2025-01-01T04:00:00Z"),
        _resolved(3, "2025-01-02T04:00:00Z"),
    ]


def test_paired_teacher_loss_surfaces_before_later_winner_when_opted_in(tmp_path):
    manifest, run_dir = _reference(tmp_path, 1.0)

    teacher = next_teacher_for_learning(
        manifest,
        run_dir,
        _events_through_pair_3(),
        include_losses=True,
    )

    assert teacher is not None
    boundary, _resolved_at = teacher
    assert boundary["pair_id"] == 4
    assert boundary["result"] == "LOSS"
    assert boundary["pair_net_r"] == -1.119
    assert boundary["teacher_learning_mode"] == TEACHER_LOSS_FLIP_MODE


def test_default_remains_winner_only_when_loss_learning_is_disabled(tmp_path):
    manifest, run_dir = _reference(tmp_path, 1.0)

    teacher = next_teacher_for_learning(manifest, run_dir, _events_through_pair_3())

    assert teacher is not None
    boundary, _resolved_at = teacher
    assert boundary["pair_id"] == 5
    assert boundary["result"] == "WIN"


def test_three_r_teacher_loss_is_valid_paired_flip_evidence(tmp_path):
    manifest, run_dir = _reference(tmp_path, 3.0)

    teacher = next_teacher_for_learning(
        manifest,
        run_dir,
        _events_through_pair_3(),
        include_losses=True,
    )

    assert teacher is not None
    boundary, _resolved_at = teacher
    assert boundary["pair_id"] == 4
    assert boundary["result"] == "LOSS"
    assert boundary["teacher_learning_mode"] == TEACHER_LOSS_FLIP_MODE


def test_teacher_loss_packet_requires_verified_opposite_side_win(monkeypatch):
    from crypto_strategy_lab import walk_forward_orchestrator as orchestrator

    class FakeStore:
        def read(self, experiment_id, recent_events=0):
            return {
                "manifest": {"definition": {"reference_run": "BTCUSDT_4h_reference"}}
            }

    monkeypatch.setattr(orchestrator._impl, "_store", lambda control: FakeStore())
    monkeypatch.setattr(orchestrator._impl, "_events", lambda store, experiment_id: [])
    monkeypatch.setattr(
        orchestrator._impl,
        "_outcome_row_after_decision",
        lambda reports, reference_run, candidate, side: {
            "research_signal_index": candidate["research_signal_index"],
            "side": side,
            "result": "WIN",
            "net_r": 0.985,
        },
    )

    packet = {
        "status": "TEACHER_REVIEW_REQUIRED",
        "teacher": {
            "pair_id": 4,
            "side": "LONG",
            "strategy_profile_key": "bull_long",
            "entry_time": "2025-01-03T00:00:00Z",
            "result": "WIN",
            "teacher_learning_mode": TEACHER_LOSS_FLIP_MODE,
        },
        "entry_context": {
            "trade_entry_context": {
                "research_sample_id": "sample-4-long",
                "research_signal_index": 44,
                "walk_forward_candidate_id": "wf-44-long",
                "entry_time": "2025-01-03T00:00:00Z",
            }
        },
    }

    updated = orchestrator._decorate_teacher_loss_packet(
        SimpleNamespace(), object(), "BTCUSDT_4H_WF_TEST", packet
    )

    assert updated["status"] == "TEACHER_LOSS_REVIEW_REQUIRED"
    assert updated["teacher"]["result"] == "LOSS"
    assert updated["opposite_side_outcome"]["available"] is True
    assert updated["opposite_side_outcome"]["side"] == "SHORT"
    assert updated["flip_activation_allowed"] is True
    assert updated["prior_teacher_loss_evidence_count"] == 0
