"""Rebuildable fast index for causal walk-forward event streams.

The append-only JSONL chain remains authoritative.  This sidecar exists only to
avoid reparsing and reverifying the complete chain on every hot-path operation.
Any external JSONL size/mtime change invalidates the sidecar and forces a full
verified rebuild before it can be used again.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4


INDEX_SCHEMA_VERSION = 1
CHECKPOINT_INTERVAL_EVENTS = 250


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    temp = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


class CausalEventIndex:
    """SQLite projection of one authoritative causal JSONL event stream."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.path = self.directory / "event_index.sqlite3"
        self.head_path = self.directory / "head.json"
        self.checkpoint_path = self.directory / "checkpoint.json"

    @staticmethod
    def _signature(events_path: Path) -> tuple[int, int]:
        stat = events_path.stat()
        return int(stat.st_size), int(stat.st_mtime_ns)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        self._init_schema(connection)
        return connection

    @staticmethod
    def _init_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY,
                event_type TEXT NOT NULL,
                operation_id TEXT NOT NULL UNIQUE,
                effective_market_time TEXT,
                candidate_id TEXT,
                rule_id TEXT,
                rule_version TEXT,
                reference_sample_id TEXT,
                research_signal_index INTEGER,
                source_side TEXT,
                resulting_state_hash TEXT NOT NULL,
                event_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_type_sequence
                ON events(event_type, sequence);
            CREATE INDEX IF NOT EXISTS idx_events_candidate_sequence
                ON events(candidate_id, sequence);
            CREATE INDEX IF NOT EXISTS idx_events_rule_sequence
                ON events(rule_id, rule_version, sequence);
            CREATE TABLE IF NOT EXISTS candidates (
                candidate_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                last_sequence INTEGER NOT NULL
            );
            """
        )

    @staticmethod
    def _event_values(event: dict[str, Any]) -> tuple[Any, ...]:
        payload = event.get("payload") or {}
        signal_index = payload.get("research_signal_index")
        try:
            signal_index = int(signal_index) if signal_index not in (None, "") else None
        except (TypeError, ValueError):
            signal_index = None
        return (
            int(event["sequence"]),
            str(event.get("event_type", "")),
            str(event.get("operation_id", "")),
            event.get("effective_market_time"),
            str(payload.get("candidate_id", "")).strip() or None,
            str(payload.get("rule_id", "")).strip() or None,
            str(payload.get("rule_version", "")).strip() or None,
            str(payload.get("reference_sample_id", "")).strip() or None,
            signal_index,
            str(payload.get("source_side", "")).strip().upper() or None,
            str(event["resulting_state_hash"]),
            json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )

    @staticmethod
    def _candidate_transition(event: dict[str, Any]) -> tuple[str, str] | None:
        payload = event.get("payload") or {}
        candidate_id = str(payload.get("candidate_id", "")).strip()
        if not candidate_id:
            return None
        state = {
            "CANDIDATE_CONTEXT_CAPTURED": "ENTRY_CONTEXT_CAPTURED",
            "FEATURE_CONTEXT_INVALID": "INVALID",
            "DECISION_FROZEN": "DECISION_FROZEN",
            "OUTCOME_REVEALED": "OUTCOME_REVEALED",
            "TRADE_RESOLVED": "COMPLETE",
        }.get(str(event.get("event_type", "")))
        return (candidate_id, state) if state else None

    @staticmethod
    def _write_meta(connection: sqlite3.Connection, values: dict[str, Any]) -> None:
        connection.executemany(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            [
                (
                    str(key),
                    json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                )
                for key, value in values.items()
            ],
        )

    @staticmethod
    def _read_meta(connection: sqlite3.Connection) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for row in connection.execute("SELECT key, value FROM meta"):
            result[str(row["key"])] = json.loads(row["value"])
        return result

    def is_current(self, events_path: Path, definition_sha256: str) -> bool:
        if not self.path.is_file():
            return False
        try:
            size, mtime_ns = self._signature(events_path)
            with self._connect() as connection:
                meta = self._read_meta(connection)
                last = connection.execute(
                    "SELECT sequence, resulting_state_hash FROM events ORDER BY sequence DESC LIMIT 1"
                ).fetchone()
            return (
                last is not None
                and int(meta.get("schema_version", -1)) == INDEX_SCHEMA_VERSION
                and str(meta.get("definition_sha256", "")) == str(definition_sha256)
                and int(meta.get("events_file_size", -1)) == size
                and int(meta.get("events_file_mtime_ns", -1)) == mtime_ns
                and int(meta.get("sequence", 0)) == int(last["sequence"])
                and str(meta.get("state_hash", "")) == str(last["resulting_state_hash"])
                and len(str(meta.get("state_hash", ""))) == 64
                and isinstance(meta.get("derived_state"), dict)
            )
        except (OSError, sqlite3.Error, ValueError, TypeError, json.JSONDecodeError):
            return False

    def rebuild(
        self,
        *,
        events_path: Path,
        definition_sha256: str,
        events: list[dict[str, Any]],
        sequence: int,
        state_hash: str,
        derived_state: dict[str, Any],
    ) -> None:
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(str(self.path) + suffix).unlink(missing_ok=True)
            except OSError:
                pass
        size, mtime_ns = self._signature(events_path)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for event in events:
                connection.execute(
                    """
                    INSERT INTO events(
                        sequence,event_type,operation_id,effective_market_time,
                        candidate_id,rule_id,rule_version,reference_sample_id,
                        research_signal_index,source_side,resulting_state_hash,event_json
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    self._event_values(event),
                )
                transition = self._candidate_transition(event)
                if transition:
                    candidate_id, state = transition
                    connection.execute(
                        """
                        INSERT INTO candidates(candidate_id,state,last_sequence)
                        VALUES (?,?,?)
                        ON CONFLICT(candidate_id) DO UPDATE SET
                            state=excluded.state,
                            last_sequence=excluded.last_sequence
                        """,
                        (candidate_id, state, int(event["sequence"])),
                    )
            self._write_meta(
                connection,
                {
                    "schema_version": INDEX_SCHEMA_VERSION,
                    "definition_sha256": definition_sha256,
                    "events_file_size": size,
                    "events_file_mtime_ns": mtime_ns,
                    "sequence": int(sequence),
                    "state_hash": str(state_hash),
                    "derived_state": deepcopy(derived_state),
                },
            )
            connection.commit()
        self._write_head(sequence, state_hash, size, mtime_ns)
        self.write_checkpoint(sequence, state_hash, derived_state)

    def snapshot(self) -> dict[str, Any]:
        with self._connect() as connection:
            meta = self._read_meta(connection)
        return {
            "sequence": int(meta["sequence"]),
            "state_hash": str(meta["state_hash"]),
            "derived_state": deepcopy(meta["derived_state"]),
        }

    def recent_events(self, limit: int) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT event_json FROM events ORDER BY sequence DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [json.loads(row["event_json"]) for row in reversed(rows)]

    def events(
        self,
        *,
        event_types: set[str] | frozenset[str] | None = None,
        candidate_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if event_types:
            ordered = sorted(str(value) for value in event_types)
            clauses.append("event_type IN (" + ",".join("?" for _ in ordered) + ")")
            params.extend(ordered)
        if candidate_id not in (None, ""):
            clauses.append("candidate_id = ?")
            params.append(str(candidate_id))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT event_json FROM events" + where + " ORDER BY sequence",
                params,
            ).fetchall()
        return [json.loads(row["event_json"]) for row in rows]

    def operation(self, operation_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT event_json FROM events WHERE operation_id = ?",
                (str(operation_id),),
            ).fetchone()
        return json.loads(row["event_json"]) if row is not None else None

    def open_candidate(self) -> tuple[str, str] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT candidate_id, state FROM candidates
                WHERE state NOT IN ('INVALID','COMPLETE')
                ORDER BY last_sequence
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return str(row["candidate_id"]), str(row["state"])

    def candidate_state(self, candidate_id: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state FROM candidates WHERE candidate_id = ?",
                (str(candidate_id),),
            ).fetchone()
        return str(row["state"]) if row is not None else "UNSEEN"

    def seen_candidate_keys(self) -> tuple[set[str], set[tuple[int, str]]]:
        samples: set[str] = set()
        identities: set[tuple[int, str]] = set()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT reference_sample_id, research_signal_index, source_side
                FROM events
                WHERE event_type = 'CANDIDATE_CONTEXT_CAPTURED'
                """
            ).fetchall()
        for row in rows:
            if row["reference_sample_id"]:
                samples.add(str(row["reference_sample_id"]))
            if row["research_signal_index"] is not None and row["source_side"] in {"LONG", "SHORT"}:
                identities.add((int(row["research_signal_index"]), str(row["source_side"])))
        return samples, identities

    def max_effective_market_time(self) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT effective_market_time FROM events
                WHERE effective_market_time IS NOT NULL
                ORDER BY effective_market_time DESC
                LIMIT 1
                """
            ).fetchone()
        return str(row["effective_market_time"]) if row is not None else None

    def latest_effective_time_for_type(self, event_type: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT effective_market_time FROM events
                WHERE event_type = ? AND effective_market_time IS NOT NULL
                ORDER BY effective_market_time DESC
                LIMIT 1
                """,
                (str(event_type),),
            ).fetchone()
        return str(row["effective_market_time"]) if row is not None else None

    def record_appended(
        self,
        *,
        event: dict[str, Any],
        derived_state: dict[str, Any],
        events_path: Path,
        definition_sha256: str,
        force_checkpoint: bool = False,
    ) -> None:
        self.record_batch_appended(
            events=[event],
            derived_state=derived_state,
            events_path=events_path,
            definition_sha256=definition_sha256,
            force_checkpoint=force_checkpoint,
        )

    def record_batch_appended(
        self,
        *,
        events: list[dict[str, Any]],
        derived_state: dict[str, Any],
        events_path: Path,
        definition_sha256: str,
        force_checkpoint: bool = False,
    ) -> None:
        if not events:
            return
        size, mtime_ns = self._signature(events_path)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for event in events:
                connection.execute(
                    """
                    INSERT INTO events(
                        sequence,event_type,operation_id,effective_market_time,
                        candidate_id,rule_id,rule_version,reference_sample_id,
                        research_signal_index,source_side,resulting_state_hash,event_json
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    self._event_values(event),
                )
                transition = self._candidate_transition(event)
                if transition:
                    candidate_id, state = transition
                    connection.execute(
                        """
                        INSERT INTO candidates(candidate_id,state,last_sequence)
                        VALUES (?,?,?)
                        ON CONFLICT(candidate_id) DO UPDATE SET
                            state=excluded.state,
                            last_sequence=excluded.last_sequence
                        """,
                        (candidate_id, state, int(event["sequence"])),
                    )
            last = events[-1]
            self._write_meta(
                connection,
                {
                    "schema_version": INDEX_SCHEMA_VERSION,
                    "definition_sha256": definition_sha256,
                    "events_file_size": size,
                    "events_file_mtime_ns": mtime_ns,
                    "sequence": int(last["sequence"]),
                    "state_hash": str(last["resulting_state_hash"]),
                    "derived_state": deepcopy(derived_state),
                },
            )
            connection.commit()
        sequence = int(events[-1]["sequence"])
        state_hash = str(events[-1]["resulting_state_hash"])
        self._write_head(sequence, state_hash, size, mtime_ns)
        if force_checkpoint or sequence % CHECKPOINT_INTERVAL_EVENTS == 0:
            self.write_checkpoint(sequence, state_hash, derived_state)

    def _write_head(self, sequence: int, state_hash: str, size: int, mtime_ns: int) -> None:
        _atomic_write_json(
            self.head_path,
            {
                "schema_version": INDEX_SCHEMA_VERSION,
                "sequence": int(sequence),
                "state_hash": str(state_hash),
                "events_file_size": int(size),
                "events_file_mtime_ns": int(mtime_ns),
            },
        )

    def write_checkpoint(
        self, sequence: int, state_hash: str, derived_state: dict[str, Any]
    ) -> None:
        _atomic_write_json(
            self.checkpoint_path,
            {
                "schema_version": INDEX_SCHEMA_VERSION,
                "sequence": int(sequence),
                "state_hash": str(state_hash),
                "derived_state": deepcopy(derived_state),
            },
        )
