"""PAPER-only scheduling around the opportunity scanner and native strategy engine.

The adapters in this module are deliberately application boundaries: market discovery is
owned by the opportunity scanner and entry semantics are owned by the supplied native
strategy evaluator.  This module contains no exchange, broker, or order API.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence


UTC = timezone.utc


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("paper scanner timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


class TransientScanError(RuntimeError):
    """An explicitly retryable scanner/API failure."""


class PaperStateError(RuntimeError):
    """State is unavailable, corrupt, unsupported, or could not be committed."""


@dataclass(frozen=True)
class PaperScannerConfig:
    scan_interval: timedelta = timedelta(minutes=5)
    max_discovery_age: timedelta = timedelta(minutes=3)
    max_strategy_age: timedelta = timedelta(hours=2)
    retry_count: int = 2
    retry_backoff: timedelta = timedelta(seconds=2)

    def __post_init__(self) -> None:
        for name in ("scan_interval", "max_discovery_age", "max_strategy_age"):
            if getattr(self, name).total_seconds() <= 0:
                raise ValueError(f"{name} must be positive")
        if self.retry_count < 0 or self.retry_backoff.total_seconds() < 0:
            raise ValueError("retry_count and retry_backoff must be non-negative")


@dataclass(frozen=True)
class OpportunityCandidate:
    symbol: str
    final_rank: int
    discovery_rank: int | None = None
    opportunity_model: str | None = None
    opportunity_rank: int | None = None
    opportunity_score: float | None = None
    reference_price: float | None = None


@dataclass(frozen=True)
class CompletedOpportunityScan:
    run_id: str
    decision_at: datetime
    completed_at: datetime
    final_candidates: Sequence[OpportunityCandidate]


@dataclass(frozen=True)
class StrategyDecisionRow:
    symbol: str
    interval: str
    profile_key: str
    candle_timestamp: datetime
    candle_completed_at: datetime
    prepared_available_at: datetime
    source_identity: str
    values: Mapping[str, Any] = field(default_factory=dict)
    required_research_available_at: Sequence[datetime] = field(default_factory=tuple)

    def is_causal_at(self, decision_at: datetime) -> bool:
        cutoff = _utc(decision_at)
        times = (self.candle_completed_at, self.prepared_available_at, *self.required_research_available_at)
        return all(_utc(value) <= cutoff for value in times)

    @property
    def availability(self) -> datetime:
        return max(_utc(v) for v in (self.candle_completed_at, self.prepared_available_at,
                                     *self.required_research_available_at))


class OpportunityScanner(Protocol):
    def run_opportunity_scan(self) -> CompletedOpportunityScan: ...


class StrategyRows(Protocol):
    def completed_rows(self, candidate: OpportunityCandidate,
                       decision_at: datetime) -> Iterable[StrategyDecisionRow]: ...


class NativeStrategyEvaluator(Protocol):
    def evaluate_entry(self, row: StrategyDecisionRow) -> str | None: ...


@dataclass(frozen=True)
class PaperEntry:
    signal_id: str
    source_scan_run_id: str
    scanner_decision_timestamp: str
    strategy_signal_candle_timestamp: str
    symbol: str
    strategy_interval: str
    strategy_profile_key: str
    final_side: str
    final_candidate_rank: int
    discovery_rank: int | None
    opportunity_model: str | None
    opportunity_rank: int | None
    opportunity_score: float | None
    reference_price: float | None
    strategy_source_identity: str
    created_at: str
    execution_mode: str = "PAPER"


@dataclass(frozen=True)
class PaperScanCycleResult:
    status: str
    scan_run_id: str | None = None
    entries: tuple[PaperEntry, ...] = ()
    duplicates_suppressed: int = 0
    evaluated_candidates: int = 0
    message: str | None = None


@dataclass
class PaperScannerState:
    version: int = 1
    emitted_signal_ids: list[str] = field(default_factory=list)
    paper_entries: list[PaperEntry] = field(default_factory=list)
    last_completed_cycle: dict[str, Any] | None = None
    last_successful_scan_run_id: str | None = None


class PaperStateStore:
    """Versioned state using write/fsync/replace/fsync atomic commits."""

    VERSION = 1

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> PaperScannerState:
        if not self.path.exists():
            return PaperScannerState()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.get("version") != self.VERSION:
                raise PaperStateError(f"unsupported paper state version: {raw.get('version')!r}")
            entries = [PaperEntry(**item) for item in raw.get("paper_entries", [])]
            ids = list(raw.get("emitted_signal_ids", []))
            if set(ids) != {item.signal_id for item in entries} or len(ids) != len(set(ids)):
                raise PaperStateError("paper state duplicate invariant is invalid")
            return PaperScannerState(self.VERSION, ids, entries,
                                     raw.get("last_completed_cycle"), raw.get("last_successful_scan_run_id"))
        except PaperStateError:
            raise
        except Exception as exc:
            raise PaperStateError(f"cannot load paper state: {exc}") from exc

    def save(self, state: PaperScannerState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(state)
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent,
                                             prefix=f".{self.path.name}.", delete=False) as handle:
                temp_name = handle.name
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
            temp_name = None
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except Exception as exc:
            if temp_name:
                Path(temp_name).unlink(missing_ok=True)
            raise PaperStateError(f"cannot persist paper state: {exc}") from exc


class PaperAuditLog:
    def __init__(self, path: str | Path, clock: Callable[[], datetime] | None = None):
        self.path = Path(path)
        self.clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()

    def write(self, event: str, **fields: Any) -> None:
        record = {"timestamp": _iso(self.clock()), "event": event, **fields}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def signal_identity(row: StrategyDecisionRow, side: str) -> str:
    semantic = "|".join((row.symbol.upper(), row.interval.strip().lower(), row.profile_key,
                         side.upper(), _iso(row.candle_timestamp)))
    return sha256(semantic.encode("utf-8")).hexdigest()


class PaperScannerRunner:
    def __init__(self, config: PaperScannerConfig, scanner: OpportunityScanner,
                 rows: StrategyRows, evaluator: NativeStrategyEvaluator,
                 state_store: PaperStateStore, audit: PaperAuditLog,
                 *, clock: Callable[[], datetime] | None = None,
                 stop_event: threading.Event | None = None):
        self.config, self.scanner, self.rows, self.evaluator = config, scanner, rows, evaluator
        self.state_store, self.audit = state_store, audit
        self.clock = clock or (lambda: datetime.now(UTC))
        self.stop_event = stop_event or threading.Event()
        self.state = state_store.load()  # corrupt state prevents the runtime from starting

    def stop(self) -> None:
        self.stop_event.set()

    def _scan_with_retry(self) -> CompletedOpportunityScan:
        for attempt in range(self.config.retry_count + 1):
            if self.stop_event.is_set():
                raise InterruptedError("paper scanner cancelled")
            try:
                return self.scanner.run_opportunity_scan()
            except TransientScanError as exc:
                if attempt >= self.config.retry_count:
                    raise
                self.audit.write("scan_retry", attempt=attempt + 1, error=str(exc))
                delay = self.config.retry_backoff.total_seconds() * (2 ** attempt)
                if self.stop_event.wait(delay):
                    raise InterruptedError("paper scanner cancelled during retry") from exc

    def run_once(self) -> PaperScanCycleResult:
        self.audit.write("scan_started")
        try:
            scan = self._scan_with_retry()
        except InterruptedError as exc:
            self.audit.write("scan_cancelled", error=str(exc))
            return PaperScanCycleResult("cancelled", message=str(exc))
        except Exception as exc:
            self.audit.write("scan_failure", error=str(exc), transient=isinstance(exc, TransientScanError))
            return PaperScanCycleResult("failed", message=str(exc))

        now, decision_at = _utc(self.clock()), _utc(scan.decision_at)
        self.audit.write("scan_completed", run_id=scan.run_id, candidates=len(scan.final_candidates))
        if now - _utc(scan.completed_at) > self.config.max_discovery_age:
            self.audit.write("stale_discovery", run_id=scan.run_id)
            return self._finish(PaperScanCycleResult("stale_discovery", scan.run_id))

        pending: list[PaperEntry] = []
        duplicates = evaluated = stale_rows = 0
        known = set(self.state.emitted_signal_ids)
        for candidate in scan.final_candidates:
            evaluated += 1
            causal = [row for row in self.rows.completed_rows(candidate, decision_at)
                      if row.symbol.upper() == candidate.symbol.upper() and row.is_causal_at(decision_at)]
            if not causal:
                self.audit.write("no_strategy_entry", symbol=candidate.symbol, reason="no_causal_completed_row")
                continue
            row = max(causal, key=lambda value: _utc(value.candle_timestamp))
            self.audit.write("candidate_evaluated", symbol=candidate.symbol,
                             candle=_iso(row.candle_timestamp))
            if decision_at - row.availability > self.config.max_strategy_age:
                stale_rows += 1
                self.audit.write("stale_strategy_data", symbol=candidate.symbol,
                                 candle=_iso(row.candle_timestamp))
                continue
            side = self.evaluator.evaluate_entry(row)
            if side is None or side.upper() not in {"LONG", "SHORT"}:
                self.audit.write("no_strategy_entry", symbol=candidate.symbol, reason="native_evaluator_veto")
                continue
            sid = signal_identity(row, side)
            if sid in known:
                duplicates += 1
                self.audit.write("duplicate_suppressed", signal_id=sid)
                continue
            entry = PaperEntry(sid, scan.run_id, _iso(decision_at), _iso(row.candle_timestamp),
                               candidate.symbol.upper(), row.interval.strip().lower(), row.profile_key,
                               side.upper(), candidate.final_rank, candidate.discovery_rank,
                               candidate.opportunity_model, candidate.opportunity_rank,
                               candidate.opportunity_score, candidate.reference_price,
                               row.source_identity, _iso(now))
            pending.append(entry)
            known.add(sid)
            self.audit.write("signal_pending", signal_id=sid)

        status = "stale_strategy" if stale_rows and not pending else "completed"
        result = PaperScanCycleResult(status, scan.run_id, tuple(pending), duplicates, evaluated)
        # Entries become observable only after IDs and records are durably committed together.
        candidate_state = PaperScannerState(self.state.version, self.state.emitted_signal_ids +
                                            [e.signal_id for e in pending],
                                            self.state.paper_entries + pending,
                                            {"status": result.status, "run_id": scan.run_id,
                                             "completed_at": _iso(now)}, scan.run_id)
        try:
            self.state_store.save(candidate_state)
        except PaperStateError as exc:
            self.audit.write("state_persistence_failure", error=str(exc))
            return PaperScanCycleResult("persistence_failed", scan.run_id, message=str(exc),
                                        evaluated_candidates=evaluated)
        self.state = candidate_state
        for entry in pending:
            self.audit.write("signal_emitted", signal_id=entry.signal_id)
            self.audit.write("paper_entry_recorded", signal_id=entry.signal_id)
        self.audit.write("cycle_completed", run_id=scan.run_id, entries=len(pending))
        return result

    def _finish(self, result: PaperScanCycleResult) -> PaperScanCycleResult:
        state = PaperScannerState(self.state.version, list(self.state.emitted_signal_ids),
                                  list(self.state.paper_entries),
                                  {"status": result.status, "run_id": result.scan_run_id,
                                   "completed_at": _iso(self.clock())}, self.state.last_successful_scan_run_id)
        try:
            self.state_store.save(state)
        except PaperStateError as exc:
            self.audit.write("state_persistence_failure", error=str(exc))
            return PaperScanCycleResult("persistence_failed", result.scan_run_id, message=str(exc))
        self.state = state
        self.audit.write("cycle_completed", run_id=result.scan_run_id, status=result.status)
        return result

    def run_forever(self) -> None:
        self.audit.write("runtime_started")
        try:
            while not self.stop_event.is_set():
                self.run_once()
                if self.stop_event.wait(self.config.scan_interval.total_seconds()):
                    break
        finally:
            self.audit.write("runtime_stopped")
