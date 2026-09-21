from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import duckdb
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


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    with duckdb.connect(":memory:") as connection:
        connection.register("frame", frame)
        escaped = str(path).replace("'", "''")
        connection.execute(f"COPY frame TO '{escaped}' (FORMAT PARQUET)")


def _read_parquet(path: Path) -> pd.DataFrame:
    escaped = str(path).replace("'", "''")
    with duckdb.connect(":memory:") as connection:
        return connection.execute(
            f"SELECT * FROM read_parquet('{escaped}')"
        ).fetchdf()


def _reference(tmp_path: Path, reward_risk_ratio: float) -> tuple[dict, Path]:
    run_dir = tmp_path / "reference"
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True)
    trades_path = artifacts / "trades.parquet"
    trades = pd.DataFrame(
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
    )
    _write_parquet(trades, trades_path)
    samples_path = artifacts / "research_sampling_trades.parquet"
    opposite_exit = (
        "2025-01-03T03:30:00Z"
        if reward_risk_ratio == 1.0
        else "2025-01-03T06:00:00Z"
    )
    samples = pd.DataFrame(
        [
            {
                "research_signal_index": 42,
                "research_sample_id": "wf-42-short-short",
                "research_sampling_mode": "WALK_FORWARD",
                "walk_forward_candidate_id": "wf-42-short",
                "walk_forward_candidate_source": True,
                "strategy_profile_key": "sideways_short",
                "side": "SHORT",
                "entry_time": "2025-01-01T00:00:00Z",
                "exit_time": "2025-01-01T04:00:00Z",
                "pair_net_r": 0.98,
            },
            {
                "research_signal_index": 42,
                "research_sample_id": "wf-42-short-long",
                "research_sampling_mode": "WALK_FORWARD",
                "walk_forward_candidate_id": "wf-42-short",
                "walk_forward_candidate_source": False,
                "strategy_profile_key": "sideways_long",
                "side": "LONG",
                "entry_time": "2025-01-01T00:00:00Z",
                "exit_time": "2025-01-01T02:00:00Z",
                "pair_net_r": -1.0,
            },
            {
                "research_signal_index": 43,
                "research_sample_id": "wf-43-short-short",
                "research_sampling_mode": "WALK_FORWARD",
                "walk_forward_candidate_id": "wf-43-short",
                "walk_forward_candidate_source": True,
                "strategy_profile_key": "sideways_short",
                "side": "SHORT",
                "entry_time": "2025-01-02T00:00:00Z",
                "exit_time": "2025-01-02T04:00:00Z",
                "pair_net_r": 0.97,
            },
            {
                "research_signal_index": 43,
                "research_sample_id": "wf-43-short-long",
                "research_sampling_mode": "WALK_FORWARD",
                "walk_forward_candidate_id": "wf-43-short",
                "walk_forward_candidate_source": False,
                "strategy_profile_key": "sideways_long",
                "side": "LONG",
                "entry_time": "2025-01-02T00:00:00Z",
                "exit_time": "2025-01-02T03:00:00Z",
                "pair_net_r": -1.0,
            },
            {
                "research_signal_index": 44,
                "research_sample_id": "wf-44-long-long",
                "research_sampling_mode": "WALK_FORWARD",
                "walk_forward_candidate_id": "wf-44-long",
                "walk_forward_candidate_source": True,
                "strategy_profile_key": "bull_long",
                "side": "LONG",
                "entry_time": "2025-01-03T00:00:00Z",
                "exit_time": "2025-01-03T04:00:00Z",
                "pair_net_r": -1.119,
            },
            {
                "research_signal_index": 44,
                "research_sample_id": "wf-44-long-short",
                "research_sampling_mode": "WALK_FORWARD",
                "walk_forward_candidate_id": "wf-44-long",
                "walk_forward_candidate_source": False,
                "strategy_profile_key": "bull_short",
                "side": "SHORT",
                "entry_time": "2025-01-03T00:00:00Z",
                "exit_time": opposite_exit,
                "pair_net_r": 2.85 if reward_risk_ratio == 3.0 else 0.98,
            },
            {
                "research_signal_index": 45,
                "research_sample_id": "wf-45-long-long",
                "research_sampling_mode": "WALK_FORWARD",
                "walk_forward_candidate_id": "wf-45-long",
                "walk_forward_candidate_source": True,
                "strategy_profile_key": "bull_long",
                "side": "LONG",
                "entry_time": "2025-01-04T00:00:00Z",
                "exit_time": "2025-01-04T04:00:00Z",
                "pair_net_r": 0.96,
            },
            {
                "research_signal_index": 45,
                "research_sample_id": "wf-45-long-short",
                "research_sampling_mode": "WALK_FORWARD",
                "walk_forward_candidate_id": "wf-45-long",
                "walk_forward_candidate_source": False,
                "strategy_profile_key": "bull_short",
                "side": "SHORT",
                "entry_time": "2025-01-04T00:00:00Z",
                "exit_time": "2025-01-04T02:00:00Z",
                "pair_net_r": -1.0,
            },
        ]
    )
    episode_map = {
        "wf-42-short": ("episode-000001", 1, 2),
        "wf-43-short": ("episode-000001", 2, 2),
        "wf-44-long": ("episode-000002", 1, 1),
        "wf-45-long": ("episode-000003", 1, 1),
    }
    samples["research_episode_id"] = samples["walk_forward_candidate_id"].map(
        lambda value: episode_map[str(value)][0]
    )
    samples["research_episode_entry_number"] = samples[
        "walk_forward_candidate_id"
    ].map(lambda value: episode_map[str(value)][1])
    samples["research_episode_viable_entries"] = samples[
        "walk_forward_candidate_id"
    ].map(lambda value: episode_map[str(value)][2])
    _write_parquet(samples, samples_path)
    manifest = {
        "config": {
            "execution": {
                "profiles": {
                    "sideways_short": {"reward_risk_ratio": reward_risk_ratio},
                    "bull_long": {"reward_risk_ratio": reward_risk_ratio},
                }
            }
        },
        "artifacts": {
            "trades": _catalog(trades_path, run_dir),
            "research_sampling_trades": _catalog(samples_path, run_dir),
        },
        "research": {"strategy_research_sampling": {"mode": "WALK_FORWARD"}},
    }
    return manifest, run_dir


def _resolved(pair_id: int | str, when: str) -> dict:
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


def _set_opposite_net_r(
    manifest: dict,
    run_dir: Path,
    candidate_id: str,
    net_r: float,
) -> None:
    samples_path = run_dir / "artifacts" / "research_sampling_trades.parquet"
    samples = _read_parquet(samples_path)
    mask = (
        samples["walk_forward_candidate_id"].astype(str).eq(candidate_id)
        & ~samples["walk_forward_candidate_source"].astype(bool)
    )
    assert int(mask.sum()) == 1
    samples.loc[mask, "pair_net_r"] = float(net_r)
    _write_parquet(samples, samples_path)
    manifest["artifacts"]["research_sampling_trades"] = _catalog(samples_path, run_dir)


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
    assert boundary["paired_opposite_side"] == "SHORT"
    assert boundary["paired_opposite_net_r"] == 0.98
    assert _resolved_at == pd.Timestamp("2025-01-03T04:00:00Z")


def test_paired_teacher_loss_loss_is_skipped_before_chatgpt_review(tmp_path):
    manifest, run_dir = _reference(tmp_path, 3.0)
    _set_opposite_net_r(manifest, run_dir, "wf-44-long", -1.3027)

    teacher = next_teacher_for_learning(
        manifest,
        run_dir,
        _events_through_pair_3(),
        include_losses=True,
    )

    assert teacher is not None
    boundary, resolved_at = teacher
    assert boundary["pair_id"] == 5
    assert boundary["result"] == "WIN"
    assert resolved_at == pd.Timestamp("2025-01-04T04:00:00Z")


def test_paired_teacher_loss_breakeven_is_skipped_before_chatgpt_review(tmp_path):
    manifest, run_dir = _reference(tmp_path, 3.0)
    _set_opposite_net_r(manifest, run_dir, "wf-44-long", 0.0)

    teacher = next_teacher_for_learning(
        manifest,
        run_dir,
        _events_through_pair_3(),
        include_losses=True,
    )

    assert teacher is not None
    boundary, _resolved_at = teacher
    assert boundary["pair_id"] == 5
    assert boundary["result"] == "WIN"


def test_malformed_teacher_loss_pair_is_not_silently_skipped(tmp_path):
    manifest, run_dir = _reference(tmp_path, 3.0)
    samples_path = run_dir / "artifacts" / "research_sampling_trades.parquet"
    samples = _read_parquet(samples_path)
    duplicate = samples.loc[
        samples["research_sample_id"].astype(str).eq("wf-44-long-short")
    ].copy()
    duplicate["research_sample_id"] = "wf-44-long-short-duplicate"
    _write_parquet(pd.concat([samples, duplicate], ignore_index=True), samples_path)
    manifest["artifacts"]["research_sampling_trades"] = _catalog(samples_path, run_dir)

    try:
        next_teacher_for_learning(
            manifest,
            run_dir,
            _events_through_pair_3(),
            include_losses=True,
        )
    except ValueError as exc:
        assert "no unique immutable opposite row" in str(exc)
    else:
        raise AssertionError("malformed paired teacher loss must require inspection")


def test_teacher_winner_does_not_expose_unresolved_opposite_result(tmp_path):
    manifest, run_dir = _reference(tmp_path, 3.0)

    teacher = next_teacher_for_learning(
        manifest,
        run_dir,
        [],
        include_losses=True,
    )

    assert teacher is not None
    boundary, _resolved_at = teacher
    assert boundary["result"] == "WIN"
    assert boundary["research_episode_id"] == "episode-000001"
    assert boundary["research_episode_entry_number"] == 1
    assert boundary["research_episode_viable_entries"] == 2
    assert "paired_opposite_net_r" not in boundary
    assert "paired_opposite_side" not in boundary
    assert "opposite_pair_net_r" not in boundary
    assert "opposite_side" not in boundary


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
    assert _resolved_at == pd.Timestamp("2025-01-03T06:00:00Z")
    assert boundary["paired_opposite_resolution_time"] == "2025-01-03T06:00:00+00:00"


def test_overlapping_teacher_observation_does_not_invalidate_paired_flip_evidence(tmp_path):
    manifest, run_dir = _reference(tmp_path, 3.0)
    events = [
        *_events_through_pair_3(),
        _resolved(99, "2025-01-03T05:00:00Z"),
    ]

    teacher = next_teacher_for_learning(
        manifest,
        run_dir,
        events,
        include_losses=True,
    )

    assert teacher is not None
    boundary, resolved_at = teacher
    assert boundary["pair_id"] == 4
    assert pd.Timestamp(boundary["entry_time"]) == pd.Timestamp("2025-01-03T00:00:00Z")
    assert boundary["result"] == "LOSS"
    assert resolved_at == pd.Timestamp("2025-01-03T06:00:00Z")
    assert boundary["paired_opposite_resolution_time"] == "2025-01-03T06:00:00+00:00"


def test_overlap_only_walk_forward_source_row_remains_teacher_evidence(tmp_path):
    manifest, run_dir = _reference(tmp_path, 3.0)
    samples_path = run_dir / "artifacts" / "research_sampling_trades.parquet"
    samples = _read_parquet(samples_path)
    overlap = pd.DataFrame(
        [
            {
                "research_signal_index": 445,
                "research_sample_id": "wf-445-short-short",
                "research_sampling_mode": "WALK_FORWARD",
                "walk_forward_candidate_id": "wf-445-short",
                "walk_forward_candidate_source": True,
                "strategy_profile_key": "sideways_short",
                "side": "SHORT",
                "entry_time": "2025-01-03T00:30:00Z",
                "exit_time": "2025-01-03T03:00:00Z",
                "pair_net_r": 0.95,
            },
            {
                "research_signal_index": 445,
                "research_sample_id": "wf-445-short-long",
                "research_sampling_mode": "WALK_FORWARD",
                "walk_forward_candidate_id": "wf-445-short",
                "walk_forward_candidate_source": False,
                "strategy_profile_key": "sideways_long",
                "side": "LONG",
                "entry_time": "2025-01-03T00:30:00Z",
                "exit_time": "2025-01-03T05:00:00Z",
                "pair_net_r": -1.0,
            },
        ]
    )
    _write_parquet(pd.concat([samples, overlap], ignore_index=True), samples_path)
    manifest["artifacts"]["research_sampling_trades"] = _catalog(samples_path, run_dir)

    teacher = next_teacher_for_learning(
        manifest,
        run_dir,
        _events_through_pair_3(),
        include_losses=True,
    )

    assert teacher is not None
    boundary, resolved_at = teacher
    assert boundary["pair_id"] == "wf-445-short"
    assert boundary["walk_forward_candidate_id"] == "wf-445-short"
    assert boundary["result"] == "WIN"
    assert boundary["teacher_observation_source"] == "WALK_FORWARD_SOURCE_ROW"
    assert boundary["portfolio_overlap_suppression_applies"] is False
    assert resolved_at == pd.Timestamp("2025-01-03T03:00:00Z")

    events = [
        *_events_through_pair_3(),
        _resolved("wf-445-short", "2025-01-03T03:00:00Z"),
    ]
    next_teacher = next_teacher_for_learning(
        manifest,
        run_dir,
        events,
        include_losses=True,
    )
    assert next_teacher is not None
    next_boundary, next_resolved_at = next_teacher
    assert next_boundary["pair_id"] == 4
    assert next_boundary["result"] == "LOSS"
    assert next_resolved_at == pd.Timestamp("2025-01-03T06:00:00Z")


def test_existing_experiment_does_not_backfill_overlap_teacher_behind_teacher_cursor(tmp_path):
    manifest, run_dir = _reference(tmp_path, 3.0)
    samples_path = run_dir / "artifacts" / "research_sampling_trades.parquet"
    samples = _read_parquet(samples_path)
    overlap = pd.DataFrame(
        [
            {
                "research_signal_index": 445,
                "research_sample_id": "wf-445-short-short",
                "research_sampling_mode": "WALK_FORWARD",
                "walk_forward_candidate_id": "wf-445-short",
                "walk_forward_candidate_source": True,
                "strategy_profile_key": "sideways_short",
                "side": "SHORT",
                "entry_time": "2025-01-03T00:30:00Z",
                "exit_time": "2025-01-03T03:00:00Z",
                "pair_net_r": 0.95,
            },
            {
                "research_signal_index": 445,
                "research_sample_id": "wf-445-short-long",
                "research_sampling_mode": "WALK_FORWARD",
                "walk_forward_candidate_id": "wf-445-short",
                "walk_forward_candidate_source": False,
                "strategy_profile_key": "sideways_long",
                "side": "LONG",
                "entry_time": "2025-01-03T00:30:00Z",
                "exit_time": "2025-01-03T05:00:00Z",
                "pair_net_r": -1.0,
            },
        ]
    )
    _write_parquet(pd.concat([samples, overlap], ignore_index=True), samples_path)
    manifest["artifacts"]["research_sampling_trades"] = _catalog(samples_path, run_dir)

    events = [
        *_events_through_pair_3(),
        _resolved(4, "2025-01-03T06:00:00Z"),
    ]
    teacher = next_teacher_for_learning(
        manifest,
        run_dir,
        events,
        include_losses=True,
    )

    assert teacher is not None
    boundary, resolved_at = teacher
    assert boundary["pair_id"] == 5
    assert resolved_at == pd.Timestamp("2025-01-04T04:00:00Z")


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
            "walk_forward_candidate_id": candidate[
                "reference_walk_forward_candidate_id"
            ],
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
    assert updated["opposite_side_outcome"]["validation_code"] == "VERIFIED_WIN"
    assert updated["prior_teacher_loss_evidence_count"] == 0
    assert "same structural learning standard as ENTRY" in updated["review_rule"]
    assert "Repeated prior examples may strengthen confidence but are not required" in updated["review_rule"]


def test_teacher_loss_pair_lookup_mismatch_requires_inspection(monkeypatch):
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
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ValueError(
                "the frozen side has no unique immutable paired Walk Forward outcome; "
                "decision remains frozen and no outcome was revealed"
            )
        ),
    )

    packet = {
        "status": "TEACHER_REVIEW_REQUIRED",
        "teacher": {
            "pair_id": 4,
            "side": "SHORT",
            "strategy_profile_key": "sideways_short",
            "entry_time": "2020-06-01T00:45:00Z",
            "result": "WIN",
            "teacher_learning_mode": TEACHER_LOSS_FLIP_MODE,
        },
        "entry_context": {
            "trade_entry_context": {
                "research_sample_id": "wf-14594-short-short",
                "research_signal_index": 14594,
                "walk_forward_candidate_id": "wf-14594-short",
                "entry_time": "2020-06-01T00:45:00Z",
            }
        },
    }

    updated = orchestrator._decorate_teacher_loss_packet(
        SimpleNamespace(), object(), "BTCUSDT_15M_WF_TEST", packet
    )

    assert updated["status"] == "TEACHER_FLIP_VALIDATION_INCONSISTENCY"
    assert updated["inspection_required"] is True
    assert updated["flip_activation_allowed"] is False
    assert updated["validation_inconsistency"]["code"] == "PAIR_LOOKUP_MISMATCH"
    assert updated["validation_inconsistency"]["walk_forward_candidate_id"] == "wf-14594-short"
    assert "Do not record NO_CHANGE" in updated["review_rule"]


def test_teacher_review_packet_uses_exact_source_identity_instead_of_window_scan(
    monkeypatch, tmp_path
):
    from crypto_strategy_lab import walk_forward_orchestrator_impl as orchestrator_impl

    observed = {}

    class Reports:
        def get_run_manifest(self, run):
            assert run == "BTCUSDT_15m_reference"
            return {"research": {"strategy_research_sampling": {"mode": "WALK_FORWARD"}}}

        def resolve_run(self, run):
            assert run == "BTCUSDT_15m_reference"
            return tmp_path

    monkeypatch.setattr(
        orchestrator_impl,
        "_verified",
        lambda *args, **kwargs: (
            object(),
            {
                "manifest": {
                    "definition": {"reference_run": "BTCUSDT_15m_reference"}
                }
            },
            [],
        ),
    )
    monkeypatch.setattr(
        orchestrator_impl,
        "materialize_walk_forward_strategy",
        lambda *args, **kwargs: {
            "active_rule_versions": [],
            "rule_counts": {"ENTRY": 0, "VETO": 0, "FLIP": 0},
            "groups_by_profile": {"bull_long": []},
            "materialized_config": {},
        },
    )
    monkeypatch.setattr(
        orchestrator_impl,
        "_artifact",
        lambda manifest, run_dir, name: tmp_path / f"{name}.parquet",
    )
    monkeypatch.setattr(
        orchestrator_impl,
        "_sampling_mode",
        lambda manifest: "WALK_FORWARD",
    )

    def detail(samples_path, context_path, signal_index, side):
        observed["signal_index"] = signal_index
        observed["side"] = side
        return pd.Series(
            {
                "research_signal_index": 44,
                "walk_forward_candidate_id": "wf-44-long",
                "strategy_profile_key": "bull_long",
                "side": "LONG",
                "entry_time": "2025-01-03T00:00:00Z",
                "__ctx_strategy_index": 44,
                "__ctx_decision_available_at": "2025-01-03T00:00:00Z",
            }
        )

    monkeypatch.setattr(orchestrator_impl, "_candidate_detail_row", detail)
    monkeypatch.setattr(
        orchestrator_impl,
        "_candidate_rows",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("time-window teacher scan should not run")
        ),
    )
    monkeypatch.setattr(
        orchestrator_impl,
        "_safe_context",
        lambda row, context, **kwargs: {
            "trade_entry_context": {
                "research_signal_index": row["research_signal_index"],
                "walk_forward_candidate_id": row["walk_forward_candidate_id"],
            }
        },
    )
    monkeypatch.setattr(
        orchestrator_impl,
        "_rule_decision",
        lambda *args, **kwargs: {"entry_allowed": False},
    )

    packet = orchestrator_impl._teacher_review_packet(
        SimpleNamespace(),
        Reports(),
        experiment_id="BTCUSDT_15M_WF_TEST",
        expected_sequence=3,
        expected_state_hash="a" * 64,
        teacher_boundary={
            "pair_id": "wf-44-long",
            "walk_forward_candidate_id": "wf-44-long",
            "research_signal_index": 44,
            "strategy_profile_key": "bull_long",
            "side": "LONG",
            "entry_time": "2025-01-03T00:00:00Z",
            "pair_net_r": 0.98,
        },
    )

    assert observed == {"signal_index": 44, "side": "LONG"}
    assert packet["status"] == "TEACHER_REVIEW_REQUIRED"
    assert packet["entry_context"]["trade_entry_context"]["research_signal_index"] == 44
    assert packet["entry_context"]["trade_entry_context"]["walk_forward_candidate_id"] == "wf-44-long"
