"""Streaming facade for deterministic causal candidate selection.

The proven candidate-selection logic remains in
``walk_forward_candidate_engine_impl``.  Only the wide parquet join is changed:
rows are fetched from DuckDB in bounded chunks instead of materializing as many
as 250,000 joined rows in one pandas DataFrame.  Causal ordering, rule matching,
and the outcome firewall remain unchanged.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from . import walk_forward_candidate_engine_impl as _impl

for _name in dir(_impl):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_impl, _name)

CANDIDATE_FETCH_CHUNK_ROWS = 4096


class _StreamingCandidateRows:
    def __init__(
        self,
        samples_path: Path,
        context_path: Path,
        market_cursor: pd.Timestamp | None,
        limit: int,
        chunk_rows: int = CANDIDATE_FETCH_CHUNK_ROWS,
    ) -> None:
        self.samples_path = Path(samples_path)
        self.context_path = Path(context_path)
        self.market_cursor = market_cursor
        self.limit = int(limit)
        self.chunk_rows = int(chunk_rows)

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
            if self.market_cursor is not None:
                # >= is intentional. Seen identities are removed by the existing
                # engine, preserving another opportunity at the same timestamp.
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
            while True:
                batch = statement.fetchmany(self.chunk_rows)
                if not batch:
                    break
                frame = pd.DataFrame.from_records(batch, columns=columns)
                for _, series in frame.iterrows():
                    yield row_index, series
                    row_index += 1


def _candidate_rows(
    samples_path: Path,
    context_path: Path,
    cursor: pd.Timestamp | None,
    limit: int,
):
    """Return a DataFrame-compatible streaming row source for the proven engine."""
    return _StreamingCandidateRows(samples_path, context_path, cursor, limit)


# Functions in the implementation module resolve _candidate_rows from their own
# module globals.  Patch that one dependency so existing public APIs and tests
# keep using the proven candidate logic with bounded-memory row delivery.
_impl._candidate_rows = _candidate_rows
globals()["_candidate_rows"] = _candidate_rows
get_next_walk_forward_candidate = _impl.get_next_walk_forward_candidate
