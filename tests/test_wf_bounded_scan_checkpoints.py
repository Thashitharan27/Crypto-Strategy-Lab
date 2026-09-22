from types import SimpleNamespace

import duckdb
import pandas as pd

from crypto_strategy_lab.causal_experiment import CausalExperimentStore
from crypto_strategy_lab import walk_forward_orchestrator as orchestrator
from crypto_strategy_lab.walk_forward_candidate_engine import (
    SCAN_CHECKPOINT_TYPE,
    _StreamingCandidateRows,
)


def _write_parquet(connection, frame, table_name, path):
    connection.register(table_name, frame)
    escaped = str(path).replace("'", "''")
    connection.execute(f"COPY {table_name} TO '{escaped}' (FORMAT PARQUET)")


def _parquets(tmp_path, rows):
    samples_path = tmp_path / "samples.parquet"
    context_path = tmp_path / "context.parquet"
    samples = pd.DataFrame(
        {
            "research_signal_index": [row[0] for row in rows],
            "strategy_profile_key": ["bull_long"] * len(rows),
            "side": [row[2] for row in rows],
            "entry_time": pd.to_datetime([row[1] for row in rows], utc=True),
            "adx": [20.0 + index for index in range(len(rows))],
            "walk_forward_candidate_id": [
                f"wf-{row[0]}-{str(row[2]).lower()}" for row in rows
            ],
            "walk_forward_candidate_source": [True] * len(rows),
            "research_sample_id": [f"sample-{row[0]}-{row[2]}" for row in rows],
        }
    )
    unique_context = {}
    for row in rows:
        signal_index, timestamp, _side = row[:3]
        decision_time = row[3] if len(row) > 3 else timestamp
        unique_context.setdefault(signal_index, decision_time)
    context_items = list(unique_context.items())
    context = pd.DataFrame(
        {
            "strategy_index": [item[0] for item in context_items],
            "decision_available_at": pd.to_datetime(
                [item[1] for item in context_items], utc=True
            ),
            "adx": [20.0 + index for index in range(len(context_items))],
            "unused_wide_context": [
                "x" * 1000 for _ in range(len(context_items))
            ],
        }
    )
    with duckdb.connect(":memory:") as connection:
        _write_parquet(connection, samples, "samples", samples_path)
        _write_parquet(connection, context, "context", context_path)
    return samples_path, context_path



def test_stream_projects_only_requested_rule_columns(tmp_path):
    samples_path, context_path = _parquets(
        tmp_path,
        [
            (1, "2025-01-01T00:00:00Z", "LONG"),
            (2, "2025-01-02T00:00:00Z", "LONG"),
        ],
    )
    stream = _StreamingCandidateRows(
        samples_path,
        context_path,
        None,
        10,
        required_columns={"adx"},
    )
    rows = list(stream.iterrows())

    assert len(rows) == 2
    assert "adx" in rows[0][1].index
    assert "__ctx_adx" in rows[0][1].index
    assert "__ctx_unused_wide_context" not in rows[0][1].index
    assert "__wf_prev_adx" not in rows[0][1].index


def test_stream_adds_previous_adx_only_when_rule_requires_it(tmp_path):
    samples_path, context_path = _parquets(
        tmp_path,
        [
            (1, "2025-01-01T00:00:00Z", "LONG"),
            (2, "2025-01-02T00:00:00Z", "LONG"),
        ],
    )
    stream = _StreamingCandidateRows(
        samples_path,
        context_path,
        None,
        10,
        required_columns={"adx", "__wf_prev_adx"},
    )
    rows = list(stream.iterrows())

    assert len(rows) == 2
    assert "__wf_prev_adx" in rows[0][1].index

def test_stream_stops_at_teacher_market_boundary(tmp_path):
    samples_path, context_path = _parquets(
        tmp_path,
        [
            (1, "2025-01-01T00:00:00Z", "LONG"),
            (2, "2025-01-02T00:00:00Z", "LONG"),
            (3, "2025-01-03T00:00:00Z", "LONG"),
        ],
    )
    stream = _StreamingCandidateRows(
        samples_path,
        context_path,
        None,
        100,
        teacher_time=pd.Timestamp("2025-01-02T00:00:00Z"),
    )
    rows = list(stream.iterrows())

    assert [int(series["research_signal_index"]) for _, series in rows] == [1]
    assert stream.teacher_boundary_reached is True
    assert stream.limit_exhausted_before_teacher is False
    assert stream.last_cursor["research_signal_index"] == 1


def test_stream_cursor_resumes_exactly_after_same_timestamp_key(tmp_path):
    timestamp = "2025-01-01T00:00:00Z"
    samples_path, context_path = _parquets(
        tmp_path,
        [
            (1, timestamp, "LONG"),
            (2, timestamp, "LONG"),
            (2, timestamp, "SHORT"),
            (3, timestamp, "LONG"),
        ],
    )
    stream = _StreamingCandidateRows(
        samples_path,
        context_path,
        pd.Timestamp(timestamp),
        100,
        scan_key={
            "decision_available_at": timestamp,
            "entry_time": timestamp,
            "research_signal_index": 2,
            "side": "LONG",
        },
    )
    rows = list(stream.iterrows())

    assert [
        (int(series["research_signal_index"]), str(series["side"]).upper())
        for _, series in rows
    ] == [(2, "SHORT"), (3, "LONG")]




def test_stream_keeps_candidate_entered_before_teacher_but_decidable_after_teacher(tmp_path):
    samples_path, context_path = _parquets(
        tmp_path,
        [
            (
                7,
                "2025-07-01T04:00:00Z",
                "LONG",
                "2025-07-01T08:00:00Z",
            ),
        ],
    )

    # A teacher resolved at 06:00. The candidate entered at 04:00, but its
    # decision was not causally available until 08:00. An entry-time cursor
    # would incorrectly drop this prospective opportunity.
    stream = _StreamingCandidateRows(
        samples_path,
        context_path,
        pd.Timestamp("2025-07-01T06:00:00Z"),
        10,
    )
    rows = list(stream.iterrows())

    assert len(rows) == 1
    assert int(rows[0][1]["research_signal_index"]) == 7
    assert stream.last_cursor["decision_available_at"] == "2025-07-01T08:00:00+00:00"
    assert stream.last_cursor["entry_time"] == "2025-07-01T04:00:00+00:00"

def test_stream_marks_bounded_slice_exhausted_before_future_teacher(tmp_path):
    samples_path, context_path = _parquets(
        tmp_path,
        [
            (1, "2025-01-01T00:00:00Z", "LONG"),
            (2, "2025-01-02T00:00:00Z", "LONG"),
            (3, "2025-01-03T00:00:00Z", "LONG"),
        ],
    )
    stream = _StreamingCandidateRows(
        samples_path,
        context_path,
        None,
        2,
        teacher_time=pd.Timestamp("2025-02-01T00:00:00Z"),
    )
    rows = list(stream.iterrows())

    assert len(rows) == 2
    assert stream.limit_exhausted_before_teacher is True
    assert stream.teacher_boundary_reached is False
    assert stream.last_cursor["research_signal_index"] == 2


def _definition():
    return {
        "symbol": "BTCUSDT",
        "strategy_timeframe": "15m",
        "strategy": "DI_DIRECTION",
        "stop_loss": {"type": "ATR", "multiple": 2.0},
        "take_profit": {"type": "R", "multiple": 3.0},
        "regime_method": "ASSET_RETURN",
        "risk_model": "FIXED_FRACTIONAL",
        "reference_run": "BTCUSDT_15m_reference",
        "initial_equity": 1000.0,
        "risk_pct": 1.0,
    }


def test_accelerated_orchestrator_persists_resumable_checkpoint(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    control = SimpleNamespace(project_root=project)
    store = CausalExperimentStore(project / "walk_forward_experiments")
    head = store.create("BTCUSDT_15M_WF_TEST", _definition(), "create:test")
    observed = {}

    def fake_advance(*args, **kwargs):
        observed["max_scan_rows"] = kwargs["max_scan_rows"]
        return {
            "contract": "causal_walk_forward_orchestrator_v1",
            "status": "NO_MORE_ACTION_IN_SCAN",
            "experiment_id": "BTCUSDT_15M_WF_TEST",
            "sequence": head["sequence"],
            "state_hash": head["state_hash"],
            "scan": {
                "rows_scanned": 4096,
                "scan_cursor": {
                    "decision_available_at": "2025-01-05T04:00:00+00:00",
                    "entry_time": "2025-01-05T00:00:00+00:00",
                    "research_signal_index": 8123,
                    "side": "SHORT",
                },
            },
            "outcome_exposed": False,
        }

    monkeypatch.setattr(orchestrator, "_ORIGINAL_ADVANCE_WALK_FORWARD", fake_advance)
    result = orchestrator.advance_walk_forward(
        control,
        None,
        experiment_id="BTCUSDT_15M_WF_TEST",
        operation_id="advance:test",
        expected_sequence=head["sequence"],
        expected_state_hash=head["state_hash"],
    )

    assert observed["max_scan_rows"] == orchestrator.ACCELERATED_SCAN_ROWS
    assert result["status"] == "SCAN_CHECKPOINTED"
    assert result["next_required_event"] == "ADVANCE_WALK_FORWARD"
    assert result["sequence"] == 2

    readback = store.read("BTCUSDT_15M_WF_TEST", recent_events=2)
    event = readback["recent_events"][-1]
    assert event["event_type"] == "CHECKPOINT_CREATED"
    assert event["payload"]["checkpoint_type"] == SCAN_CHECKPOINT_TYPE
    assert event["payload"]["research_signal_index"] == 8123
    assert event["payload"]["side"] == "SHORT"
    assert event["payload"]["decision_available_at"] == "2025-01-05T04:00:00+00:00"
    assert event["effective_market_time"] == "2025-01-05T04:00:00+00:00"
