"""Streaming facade for deterministic causal candidate selection.

The proven candidate-selection logic remains in
``walk_forward_candidate_engine_impl``.  This facade keeps the causal rule
semantics and outcome firewall unchanged while making large 15m scans bounded:

* DuckDB rows are delivered in small pandas batches instead of one huge frame;
* a pending teacher boundary stops scanning as soon as market time reaches it,
  even when no ENTRY rule currently matches;
* accelerated callers can resume a scan from an exact (time, signal, side)
  checkpoint without skipping same-timestamp opportunities.
"""
from __future__ import annotations

from pathlib import Path
import threading
from typing import Any

import duckdb
import pandas as pd

from . import walk_forward_candidate_engine_impl as _impl

for _name in dir(_impl):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_impl, _name)

CANDIDATE_FETCH_CHUNK_ROWS = 4096
SCAN_CHECKPOINT_TYPE = "CANDIDATE_SCAN_CURSOR_V1"

_ORIGINAL_NEXT_TEACHER = _impl._next_teacher
_ORIGINAL_MAX_EVENT_TIME = _impl._max_event_time
_ORIGINAL_GET_NEXT_CANDIDATE = _impl.get_next_walk_forward_candidate
_SCAN_CONTEXT = threading.local()


def _clear_scan_context() -> None:
    _SCAN_CONTEXT.active = False
    _SCAN_CONTEXT.teacher_time = None
    _SCAN_CONTEXT.scan_key = None
    _SCAN_CONTEXT.last_stream = None


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
    required = ("entry_time", "research_signal_index", "side")
    if any(payload.get(name) in (None, "") for name in required):
        return None
    side = str(payload["side"]).upper()
    if side not in {"LONG", "SHORT"}:
        return None
    return {
        "entry_time": _as_utc(payload["entry_time"]),
        "research_signal_index": int(payload["research_signal_index"]),
        "side": side,
    }


def _tracking_next_teacher(*args, **kwargs):
    teacher = _ORIGINAL_NEXT_TEACHER(*args, **kwargs)
    if getattr(_SCAN_CONTEXT, "active", False):
        _SCAN_CONTEXT.teacher_time = teacher[1] if teacher is not None else None
    return teacher


def _tracking_max_event_time(events: list[dict[str, Any]]) -> pd.Timestamp | None:
    if not getattr(_SCAN_CONTEXT, "active", False):
        return _ORIGINAL_MAX_EVENT_TIME(events)

    # A scan checkpoint is valid only while it is the newest event. Any teacher,
    # review, rule or trade event after it changes the causal state and therefore
    # intentionally invalidates the old scan cursor.
    checkpoint = _scan_checkpoint(events[-1] if events else None)
    if checkpoint is None:
        _SCAN_CONTEXT.scan_key = None
        return _ORIGINAL_MAX_EVENT_TIME(events)

    base_cursor = _ORIGINAL_MAX_EVENT_TIME(events[:-1])
    checkpoint_time = checkpoint["entry_time"]
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
        scan_key: dict[str, Any] | None = None,
    ) -> None:
        self.samples_path = Path(samples_path)
        self.context_path = Path(context_path)
        self.market_cursor = market_cursor
        self.limit = int(limit)
        self.chunk_rows = int(chunk_rows)
        self.teacher_time = teacher_time
        self.scan_key = scan_key
        self.rows_yielded = 0
        self.teacher_boundary_reached = False
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
            }
            required_context = {"strategy_index", "decision_available_at"}
            missing_samples = required_samples - set(sample_columns)
            missing_context = required_context - set(context_columns)
            if missing_samples:
                raise ValueError(
                    "Every Viable Entry artifact is missing candidate identity columns: "
                    + ", ".join(sorted(missing_samples))
                )
            if missing_context:
                raise ValueError(
                    "feature-context artifact is missing causal identity columns: "
                    + ", ".join(sorted(missing_context))
                )

            context_select = []
            for name in context_columns:
                escaped = name.replace('"', '""')
                alias = ("__ctx_" + name).replace('"', "")
                context_select.append(f'c."{escaped}" AS "{alias}"')

            where = ""
            params: list[Any] = []
            if self.scan_key is not None:
                cursor_time = _as_utc(self.scan_key["entry_time"]).to_pydatetime()
                cursor_index = int(self.scan_key["research_signal_index"])
                cursor_side = str(self.scan_key["side"]).upper()
                # Exact keyset continuation preserves rows sharing the checkpoint
                # timestamp instead of skipping or repeatedly rescanning them.
                where = """
                    WHERE (
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
                """
                params.extend(
                    [cursor_time, cursor_time, cursor_index, cursor_index, cursor_side]
                )
            elif self.market_cursor is not None:
                # >= remains intentional for ordinary causal events. Existing
                # captured identities are removed by the proven engine, preserving
                # another opportunity at the same timestamp.
                where = "WHERE CAST(t.entry_time AS TIMESTAMPTZ) >= ?"
                params.append(self.market_cursor.to_pydatetime())

            sql = f"""
                SELECT t.*, {', '.join(context_select)}, prev.adx AS __wf_prev_adx
                FROM read_parquet('{_impl._quote(self.samples_path)}') t
                JOIN read_parquet('{_impl._quote(self.context_path)}') c
                  ON CAST(t.research_signal_index AS BIGINT)=CAST(c.strategy_index AS BIGINT)
                LEFT JOIN read_parquet('{_impl._quote(self.context_path)}') prev
                  ON CAST(prev.strategy_index AS BIGINT)=CAST(c.strategy_index AS BIGINT)-1
                {where}
                ORDER BY CAST(t.entry_time AS TIMESTAMPTZ),
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
                    if (
                        self.teacher_time is not None
                        and decision_time >= self.teacher_time
                    ):
                        self.teacher_boundary_reached = True
                        stop = True
                        break

                    entry_time = _as_utc(series["entry_time"])
                    self.last_cursor = {
                        "entry_time": entry_time.isoformat(),
                        "research_signal_index": int(series["research_signal_index"]),
                        "side": str(series["side"]).upper(),
                    }
                    self.rows_yielded += 1
                    yield row_index, series
                    row_index += 1

            if (
                not self.teacher_boundary_reached
                and self.rows_yielded >= self.limit
            ):
                self.limit_exhausted_before_teacher = True


def _candidate_rows(
    samples_path: Path,
    context_path: Path,
    cursor: pd.Timestamp | None,
    limit: int,
):
    """Return a DataFrame-compatible bounded streaming row source."""
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
        scan_key=(
            getattr(_SCAN_CONTEXT, "scan_key", None)
            if getattr(_SCAN_CONTEXT, "active", False)
            else None
        ),
    )
    if getattr(_SCAN_CONTEXT, "active", False):
        _SCAN_CONTEXT.last_stream = stream
    return stream


def get_next_walk_forward_candidate(*args, **kwargs) -> dict[str, Any]:
    """Run the proven scanner with bounded teacher-aware resumable delivery."""
    _clear_scan_context()
    _SCAN_CONTEXT.active = True
    try:
        result = _ORIGINAL_GET_NEXT_CANDIDATE(*args, **kwargs)
        stream = getattr(_SCAN_CONTEXT, "last_stream", None)
        if stream is None:
            return result

        scan = dict(result.get("scan") or {})
        scan["bounded_scan_rows"] = int(stream.limit)
        scan["teacher_boundary_reached"] = bool(stream.teacher_boundary_reached)
        if stream.last_cursor is not None:
            scan["scan_cursor"] = dict(stream.last_cursor)

        # The implementation historically returned TEACHER_DUE_FIRST after any
        # finite scan whenever a future teacher existed. If the bounded scan hit
        # its row limit before reaching that teacher in market time, returning the
        # teacher would skip unseen prospective opportunities. Convert only that
        # case into a resumable no-match result; the orchestrator will persist the
        # exact cursor and continue on the next short MCP request.
        if (
            result.get("status") == "TEACHER_DUE_FIRST"
            and stream.limit_exhausted_before_teacher
            and not stream.teacher_boundary_reached
        ):
            experiment_id = str(result.get("experiment_id") or kwargs.get("experiment_id") or "")
            expected_sequence = int(kwargs.get("expected_sequence", result.get("sequence")))
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


# Functions in the implementation module resolve these helpers from their own
# module globals. Patch only the delivery/cursor boundary; rule matching,
# candidate capture and outcome access remain in the proven implementation.
_impl._candidate_rows = _candidate_rows
_impl._next_teacher = _tracking_next_teacher
_impl._max_event_time = _tracking_max_event_time
_impl.get_next_walk_forward_candidate = get_next_walk_forward_candidate

globals()["_candidate_rows"] = _candidate_rows
