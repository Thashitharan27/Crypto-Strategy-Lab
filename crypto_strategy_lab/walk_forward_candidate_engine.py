"""Streaming facade for deterministic causal candidate selection.

The proven candidate-selection logic remains in
``walk_forward_candidate_engine_impl``. This facade keeps the causal rule
semantics and outcome firewall unchanged while making large scans bounded:

* DuckDB rows are delivered in small pandas batches instead of one huge frame;
* a pending teacher boundary stops scanning as soon as market time reaches it,
  even when no ENTRY rule currently matches;
* accelerated callers can resume a scan from an exact
  (decision_available_at, entry_time, signal, side) checkpoint without skipping
  same-decision-time opportunities;
* teacher losses are considered only inside an explicit teacher-loss FLIP
  policy, and paired losses become due only after both immutable sides resolve.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from pathlib import Path
import threading
from typing import Any

import duckdb
import pandas as pd

from . import walk_forward_candidate_engine_impl as _impl
from .walk_forward_teacher_learning import next_teacher_for_learning

for _name in dir(_impl):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_impl, _name)

CANDIDATE_FETCH_CHUNK_ROWS = 4096
SCAN_CHECKPOINT_TYPE = "CANDIDATE_SCAN_CURSOR_V1"

_ORIGINAL_NEXT_TEACHER = _impl._next_teacher
_ORIGINAL_MAX_EVENT_TIME = _impl._max_event_time
_ORIGINAL_GET_NEXT_CANDIDATE = _impl.get_next_walk_forward_candidate
_SCAN_CONTEXT = threading.local()
_TEACHER_POLICY_CONTEXT = threading.local()


def _clear_scan_context() -> None:
    _SCAN_CONTEXT.active = False
    _SCAN_CONTEXT.teacher_time = None
    _SCAN_CONTEXT.minimum_time = None
    _SCAN_CONTEXT.stop_before_time = None
    _SCAN_CONTEXT.scan_key = None
    _SCAN_CONTEXT.last_stream = None


def _teacher_loss_flip_enabled() -> bool:
    return bool(getattr(_TEACHER_POLICY_CONTEXT, "enabled", False))


@contextmanager
def teacher_loss_flip_policy(enabled: bool):
    """Temporarily select whether paired teacher losses participate in chronology."""
    marker = object()
    previous = getattr(_TEACHER_POLICY_CONTEXT, "enabled", marker)
    _TEACHER_POLICY_CONTEXT.enabled = bool(enabled)
    try:
        yield
    finally:
        if previous is marker:
            try:
                delattr(_TEACHER_POLICY_CONTEXT, "enabled")
            except AttributeError:
                pass
        else:
            _TEACHER_POLICY_CONTEXT.enabled = previous


def _as_utc(value: Any) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        raise ValueError("scan cursor timestamp is missing")
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def _scan_checkpoint(event: dict[str, Any] | None) -> dict[str, Any] | None:
    if not event or event.get("event_type") != "CHECKPOINT_CREATED":
        return None
    payload = event.get("payload") or {}
    if payload.get("checkpoint_type") != SCAN_CHECKPOINT_TYPE:
        return None
    # New checkpoints persist the causal decision watermark. Older checkpoints
    # used entry_time only; treat those as legacy and fall back to the event-time
    # watermark rather than resuming with an incompatible sort key.
    required = (
        "decision_available_at",
        "entry_time",
        "research_signal_index",
        "side",
    )
    if any(payload.get(name) in (None, "") for name in required):
        return None
    side = str(payload["side"]).upper()
    if side not in {"LONG", "SHORT"}:
        return None
    return {
        "decision_available_at": _as_utc(payload["decision_available_at"]),
        "entry_time": _as_utc(payload["entry_time"]),
        "research_signal_index": int(payload["research_signal_index"]),
        "side": side,
    }


def _tracking_next_teacher(*args, **kwargs):
    teacher = next_teacher_for_learning(
        *args,
        **kwargs,
        include_losses=_teacher_loss_flip_enabled(),
        minimum_entry_time=(
            getattr(_SCAN_CONTEXT, "minimum_time", None)
            if getattr(_SCAN_CONTEXT, "active", False)
            else None
        ),
    )
    if getattr(_SCAN_CONTEXT, "active", False):
        _SCAN_CONTEXT.teacher_time = teacher[1] if teacher is not None else None
    return teacher


def _tracking_max_event_time(events: list[dict[str, Any]]) -> pd.Timestamp | None:
    if not getattr(_SCAN_CONTEXT, "active", False):
        return _ORIGINAL_MAX_EVENT_TIME(events)

    checkpoint = _scan_checkpoint(events[-1] if events else None)
    if checkpoint is None:
        _SCAN_CONTEXT.scan_key = None
        return _ORIGINAL_MAX_EVENT_TIME(events)

    base_cursor = _ORIGINAL_MAX_EVENT_TIME(events[:-1])
    checkpoint_time = checkpoint["decision_available_at"]
    if base_cursor is not None and checkpoint_time < base_cursor:
        _SCAN_CONTEXT.scan_key = None
        return base_cursor

    _SCAN_CONTEXT.scan_key = checkpoint
    if base_cursor is None or checkpoint_time > base_cursor:
        return checkpoint_time
    return base_cursor


class _StreamingCandidateRows:
    def __init__(
        self,
        samples_path: Path,
        context_path: Path,
        market_cursor: pd.Timestamp | None,
        limit: int,
        chunk_rows: int = CANDIDATE_FETCH_CHUNK_ROWS,
        *,
        teacher_time: pd.Timestamp | None = None,
        stop_before_time: pd.Timestamp | None = None,
        scan_key: dict[str, Any] | None = None,
        required_columns: set[str] | None = None,
    ) -> None:
        self.samples_path = Path(samples_path)
        self.context_path = Path(context_path)
        self.market_cursor = market_cursor
        self.limit = int(limit)
        self.chunk_rows = int(chunk_rows)
        self.teacher_time = teacher_time
        self.stop_before_time = stop_before_time
        self.scan_key = scan_key
        self.required_columns = (
            None if required_columns is None else set(required_columns)
        )
        self.rows_yielded = 0
        self.teacher_boundary_reached = False
        self.time_boundary_reached = False
        self.limit_exhausted_before_teacher = False
        self.last_cursor: dict[str, Any] | None = None

    def iterrows(self):
        with duckdb.connect(":memory:") as connection:
            sample_columns = _impl._columns(connection, self.samples_path)
            context_columns = _impl._columns(connection, self.context_path)
            required_samples = {
                "research_signal_index",
                "strategy_profile_key",
                "side",
                "entry_time",
                "walk_forward_candidate_id",
                "walk_forward_candidate_source",
            }
            required_context = {"strategy_index", "decision_available_at"}
            missing_samples = required_samples - set(sample_columns)
            missing_context = required_context - set(context_columns)
            if missing_samples:
                raise ValueError(
                    "Walk Forward paired artifact is missing candidate identity columns: "
                    + ", ".join(sorted(missing_samples))
                )
            if missing_context:
                raise ValueError(
                    "feature-context artifact is missing causal identity columns: "
                    + ", ".join(sorted(missing_context))
                )

            sample_select, context_select, needs_prev_adx = _impl._projection_parts(
                sample_columns,
                context_columns,
                self.required_columns,
            )
            select_items = [*sample_select, *context_select]
            if needs_prev_adx:
                select_items.append("prev.adx AS __wf_prev_adx")

            where = ""
            params: list[Any] = []
            if self.scan_key is not None:
                decision_cursor = _as_utc(
                    self.scan_key["decision_available_at"]
                ).to_pydatetime()
                entry_cursor = _as_utc(self.scan_key["entry_time"]).to_pydatetime()
                cursor_index = int(self.scan_key["research_signal_index"])
                cursor_side = str(self.scan_key["side"]).upper()
                where = """
                    WHERE (
                        CAST(c.decision_available_at AS TIMESTAMPTZ) > ?
                        OR (
                            CAST(c.decision_available_at AS TIMESTAMPTZ) = ?
                            AND (
                                CAST(t.entry_time AS TIMESTAMPTZ) > ?
                                OR (
                                    CAST(t.entry_time AS TIMESTAMPTZ) = ?
                                    AND (
                                        CAST(t.research_signal_index AS BIGINT) > ?
                                        OR (
                                            CAST(t.research_signal_index AS BIGINT) = ?
                                            AND UPPER(CAST(t.side AS VARCHAR)) > ?
                                        )
                                    )
                                )
                            )
                        )
                    )
                """
                params.extend(
                    [
                        decision_cursor,
                        decision_cursor,
                        entry_cursor,
                        entry_cursor,
                        cursor_index,
                        cursor_index,
                        cursor_side,
                    ]
                )
            elif self.market_cursor is not None:
                where = "WHERE CAST(c.decision_available_at AS TIMESTAMPTZ) >= ?"
                params.append(self.market_cursor.to_pydatetime())

            source_filter = (
                "COALESCE(CAST(t.walk_forward_candidate_source AS BOOLEAN), FALSE)"
            )
            if where:
                where = where.replace("WHERE", f"WHERE {source_filter} AND", 1)
            else:
                where = f"WHERE {source_filter}"

            prev_join = ""
            if needs_prev_adx:
                prev_join = f"""
                LEFT JOIN read_parquet('{_impl._quote(self.context_path)}') prev
                  ON CAST(prev.strategy_index AS BIGINT)=CAST(c.strategy_index AS BIGINT)-1
                """

            sql = f"""
                SELECT {', '.join(select_items)}
                FROM read_parquet('{_impl._quote(self.samples_path)}') t
                JOIN read_parquet('{_impl._quote(self.context_path)}') c
                  ON CAST(t.research_signal_index AS BIGINT)=CAST(c.strategy_index AS BIGINT)
                {prev_join}
                {where}
                ORDER BY CAST(c.decision_available_at AS TIMESTAMPTZ),
                         CAST(t.entry_time AS TIMESTAMPTZ),
                         CAST(t.research_signal_index AS BIGINT),
                         UPPER(CAST(t.side AS VARCHAR))
                LIMIT {self.limit}
            """
            statement = connection.execute(sql, params)
            columns = [str(item[0]) for item in statement.description]
            row_index = 0
            stop = False
            while not stop:
                batch = statement.fetchmany(self.chunk_rows)
                if not batch:
                    break
                frame = pd.DataFrame.from_records(batch, columns=columns)
                for _, series in frame.iterrows():
                    raw_decision_time = series.get("__ctx_decision_available_at")
                    if pd.isna(raw_decision_time):
                        raw_decision_time = series.get("signal_available_at")
                    if pd.isna(raw_decision_time):
                        raw_decision_time = series.get("entry_time")
                    decision_time = _as_utc(raw_decision_time)
                    teacher_due = (
                        self.teacher_time is not None
                        and decision_time >= self.teacher_time
                    )
                    time_due = (
                        self.stop_before_time is not None
                        and decision_time >= self.stop_before_time
                    )
                    if time_due and (
                        not teacher_due
                        or self.teacher_time is None
                        or self.stop_before_time <= self.teacher_time
                    ):
                        self.time_boundary_reached = True
                        stop = True
                        break
                    if teacher_due:
                        self.teacher_boundary_reached = True
                        stop = True
                        break

                    entry_time = _as_utc(series["entry_time"])
                    self.last_cursor = {
                        "decision_available_at": decision_time.isoformat(),
                        "entry_time": entry_time.isoformat(),
                        "research_signal_index": int(series["research_signal_index"]),
                        "side": str(series["side"]).upper(),
                    }
                    self.rows_yielded += 1
                    yield row_index, series
                    row_index += 1

            if not self.teacher_boundary_reached and self.rows_yielded >= self.limit:
                self.limit_exhausted_before_teacher = True


def _candidate_rows(
    samples_path: Path,
    context_path: Path,
    cursor: pd.Timestamp | None,
    limit: int,
    required_columns: set[str] | None = None,
):
    minimum_time = (
        getattr(_SCAN_CONTEXT, "minimum_time", None)
        if getattr(_SCAN_CONTEXT, "active", False)
        else None
    )
    if minimum_time is not None and (cursor is None or cursor < minimum_time):
        cursor = minimum_time
    stream = _StreamingCandidateRows(
        samples_path,
        context_path,
        cursor,
        limit,
        teacher_time=(
            getattr(_SCAN_CONTEXT, "teacher_time", None)
            if getattr(_SCAN_CONTEXT, "active", False)
            else None
        ),
        stop_before_time=(
            getattr(_SCAN_CONTEXT, "stop_before_time", None)
            if getattr(_SCAN_CONTEXT, "active", False)
            else None
        ),
        scan_key=(
            getattr(_SCAN_CONTEXT, "scan_key", None)
            if getattr(_SCAN_CONTEXT, "active", False)
            else None
        ),
        required_columns=required_columns,
    )
    if getattr(_SCAN_CONTEXT, "active", False):
        _SCAN_CONTEXT.last_stream = stream
    return stream


def get_next_walk_forward_candidate(*args, **kwargs) -> dict[str, Any]:
    """Run the proven scanner with bounded teacher-aware resumable delivery."""
    policy_marker = object()
    requested_policy = kwargs.pop("teacher_loss_flip_enabled", policy_marker)
    requested_stop_before = kwargs.pop("stop_before_time", None)
    policy = (
        teacher_loss_flip_policy(bool(requested_policy))
        if requested_policy is not policy_marker
        else nullcontext()
    )
    with policy:
        _clear_scan_context()
        _SCAN_CONTEXT.active = True
        _SCAN_CONTEXT.stop_before_time = (
            _as_utc(requested_stop_before)
            if requested_stop_before is not None
            else None
        )
        try:
            control = kwargs.get("control") or (args[0] if len(args) > 0 else None)
            experiment_id = str(
                kwargs.get("experiment_id") or (args[2] if len(args) > 2 else "")
            ).strip()
            if control is not None and experiment_id:
                store = CausalExperimentStore(
                    Path(control.project_root) / "walk_forward_experiments"
                )
                readback = store.read_fast(experiment_id, recent_events=0)
                operation_id = str(kwargs.get("operation_id") or "").strip()
                replay = (
                    store.indexed_operation(experiment_id, operation_id)
                    if operation_id
                    else None
                )
                if replay is not None:
                    return _ORIGINAL_GET_NEXT_CANDIDATE(*args, **kwargs)

                expected_sequence = kwargs.get("expected_sequence")
                expected_state_hash = kwargs.get("expected_state_hash")
                if expected_sequence is not None and int(readback["sequence"]) != int(expected_sequence):
                    raise ValueError(
                        "walk-forward experiment changed since it was read; read the verified chain head again"
                    )
                if expected_state_hash is not None and str(readback["state_hash"]) != str(expected_state_hash).strip().lower():
                    raise ValueError(
                        "walk-forward experiment changed since it was read; read the verified chain head again"
                    )
                definition = (readback.get("manifest") or {}).get("definition") or {}
                protocol = definition.get("research_protocol") or {}
                if str(protocol.get("mode", "")).upper() == "BOOTSTRAP_THEN_WF":
                    raw_start = protocol.get("walk_forward_start")
                    if raw_start in (None, ""):
                        raise ValueError("bootstrap protocol has no walk_forward_start")
                    _SCAN_CONTEXT.minimum_time = _as_utc(raw_start)
                    phase = str(((readback.get("derived_state") or {}).get("phase") or "")).upper()
                    if phase == "BOOTSTRAP_RESEARCH":
                        return {
                            "contract": CANDIDATE_CONTEXT_CONTRACT,
                            "status": "BOOTSTRAP_RESEARCH_REQUIRED",
                            "experiment_id": experiment_id,
                            "sequence": int(readback["sequence"]),
                            "state_hash": str(readback["state_hash"]),
                            "bootstrap_start": protocol.get("bootstrap_start"),
                            "walk_forward_start": protocol.get("walk_forward_start"),
                            "candidate_not_captured": True,
                            "outcome_exposed": False,
                        }
            result = _ORIGINAL_GET_NEXT_CANDIDATE(*args, **kwargs)
            stream = getattr(_SCAN_CONTEXT, "last_stream", None)
            if stream is None:
                return result

            scan = dict(result.get("scan") or {})
            scan["bounded_scan_rows"] = int(stream.limit)
            scan["scan_projection_columns"] = (
                None
                if stream.required_columns is None
                else len(stream.required_columns)
            )
            scan["full_context_hydration"] = (
                "ALL_ROWS" if stream.required_columns is None else "MATCH_ONLY"
            )
            scan["teacher_boundary_reached"] = bool(stream.teacher_boundary_reached)
            scan["time_boundary_reached"] = bool(stream.time_boundary_reached)
            if stream.last_cursor is not None:
                scan["scan_cursor"] = dict(stream.last_cursor)

            if stream.time_boundary_reached:
                experiment_id = str(
                    result.get("experiment_id") or kwargs.get("experiment_id") or ""
                )
                expected_sequence = int(
                    kwargs.get("expected_sequence", result.get("sequence"))
                )
                expected_state_hash = str(
                    kwargs.get("expected_state_hash", result.get("state_hash"))
                )
                return {
                    "contract": result.get("contract", CANDIDATE_CONTEXT_CONTRACT),
                    "status": "TIME_BOUNDARY_DUE_FIRST",
                    "experiment_id": experiment_id,
                    "sequence": expected_sequence,
                    "state_hash": expected_state_hash,
                    "boundary_time": _SCAN_CONTEXT.stop_before_time.isoformat(),
                    "candidate_not_captured": True,
                    "scan": scan,
                    "outcome_exposed": False,
                }

            if (
                result.get("status") == "TEACHER_DUE_FIRST"
                and stream.limit_exhausted_before_teacher
                and not stream.teacher_boundary_reached
            ):
                experiment_id = str(
                    result.get("experiment_id") or kwargs.get("experiment_id") or ""
                )
                expected_sequence = int(
                    kwargs.get("expected_sequence", result.get("sequence"))
                )
                expected_state_hash = str(
                    kwargs.get("expected_state_hash", result.get("state_hash"))
                )
                return {
                    "contract": result.get("contract", CANDIDATE_CONTEXT_CONTRACT),
                    "status": "NO_ELIGIBLE_CANDIDATE_IN_SCAN",
                    "experiment_id": experiment_id,
                    "sequence": expected_sequence,
                    "state_hash": expected_state_hash,
                    "scan": scan,
                    "teacher_pending": True,
                    "outcome_exposed": False,
                }

            updated = dict(result)
            updated["scan"] = scan
            return updated
        finally:
            _clear_scan_context()


_impl._candidate_rows = _candidate_rows
_impl._next_teacher = _tracking_next_teacher
_impl._max_event_time = _tracking_max_event_time
_impl.get_next_walk_forward_candidate = get_next_walk_forward_candidate

globals()["_candidate_rows"] = _candidate_rows
globals()["_next_teacher"] = _tracking_next_teacher
