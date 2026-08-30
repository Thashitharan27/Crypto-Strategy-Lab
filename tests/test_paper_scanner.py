from datetime import datetime, timedelta, timezone
import json
import threading

import pytest

from crypto_strategy_lab.paper_scanner import (
    CompletedOpportunityScan, OpportunityCandidate, PaperAuditLog, PaperScannerConfig,
    PaperScannerRunner, PaperStateError, PaperStateStore, StrategyDecisionRow,
    TransientScanError,
)


NOW = datetime(2025, 1, 1, 12, tzinfo=timezone.utc)


class Scanner:
    def __init__(self, scan=None, errors=()):
        self.scan, self.errors, self.calls = scan, list(errors), 0

    def run_opportunity_scan(self):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return self.scan


class Rows:
    def __init__(self, rows): self.rows = rows
    def completed_rows(self, candidate, decision_at): return self.rows


class Evaluator:
    def __init__(self, side="LONG"): self.side, self.calls = side, 0
    def evaluate_entry(self, row):
        self.calls += 1
        return self.side


def fixtures(tmp_path, *, completed=NOW - timedelta(seconds=5), rows=None, side="LONG",
             scanner=None, stop=None, store=None):
    candidate = OpportunityCandidate("BTCUSDT", 1, 2, "model", 3, .8, 100.0)
    scan = CompletedOpportunityScan("run-1", NOW, completed, [candidate])
    row = StrategyDecisionRow("BTCUSDT", "15M", "native", NOW - timedelta(minutes=15),
                              NOW - timedelta(minutes=1), NOW - timedelta(seconds=30), "lake:v1")
    scanner = scanner or Scanner(scan)
    store = store or PaperStateStore(tmp_path / "state.json")
    runner = PaperScannerRunner(PaperScannerConfig(retry_backoff=timedelta(0)), scanner,
                                Rows(rows if rows is not None else [row]), Evaluator(side), store,
                                PaperAuditLog(tmp_path / "audit.jsonl", lambda: NOW),
                                clock=lambda: NOW, stop_event=stop)
    return runner, scanner, row


def test_entry_duplicate_restart_and_new_candle(tmp_path):
    runner, _, row = fixtures(tmp_path)
    first = runner.run_once()
    assert first.status == "completed" and len(first.entries) == 1
    assert runner.run_once().duplicates_suppressed == 1
    restarted, _, _ = fixtures(tmp_path)
    assert restarted.run_once().duplicates_suppressed == 1
    newer = StrategyDecisionRow(**{**row.__dict__, "candle_timestamp": NOW})
    fresh, _, _ = fixtures(tmp_path, rows=[newer])
    assert len(fresh.run_once().entries) == 1
    assert len(PaperStateStore(tmp_path / "state.json").load().paper_entries) == 2


def test_stale_discovery_and_strategy_emit_nothing(tmp_path):
    stale_scan, _, _ = fixtures(tmp_path / "a", completed=NOW - timedelta(hours=1))
    assert stale_scan.run_once().status == "stale_discovery"
    _, _, row = fixtures(tmp_path / "seed")
    stale_row = StrategyDecisionRow(**{**row.__dict__, "candle_completed_at": NOW - timedelta(hours=3),
                                      "prepared_available_at": NOW - timedelta(hours=3)})
    stale, _, _ = fixtures(tmp_path / "b", rows=[stale_row])
    result = stale.run_once()
    assert result.status == "stale_strategy" and result.entries == ()


def test_future_incomplete_and_research_unavailable_are_not_evaluated(tmp_path):
    _, _, row = fixtures(tmp_path / "seed")
    future = StrategyDecisionRow(**{**row.__dict__, "candle_completed_at": NOW + timedelta(seconds=1)})
    research = StrategyDecisionRow(**{**row.__dict__,
                                      "required_research_available_at": [NOW + timedelta(seconds=1)]})
    runner, _, _ = fixtures(tmp_path, rows=[future, research])
    assert runner.run_once().entries == ()


def test_native_veto_emits_nothing(tmp_path):
    runner, _, _ = fixtures(tmp_path, side=None)
    assert runner.run_once().entries == ()


def test_only_transient_errors_retry_and_retry_is_bounded(tmp_path):
    scan = CompletedOpportunityScan("run", NOW, NOW, [])
    transient = Scanner(scan, [TransientScanError("temporary")])
    runner, _, _ = fixtures(tmp_path / "a", scanner=transient)
    assert runner.run_once().status == "completed" and transient.calls == 2
    permanent = Scanner(scan, [ValueError("bad")])
    runner, _, _ = fixtures(tmp_path / "b", scanner=permanent)
    assert runner.run_once().status == "failed" and permanent.calls == 1
    bounded = Scanner(scan, [TransientScanError("x")] * 5)
    runner, _, _ = fixtures(tmp_path / "c", scanner=bounded)
    assert runner.run_once().status == "failed" and bounded.calls == 3


def test_cancellation_interrupts_retry_and_scheduler(tmp_path):
    stop = threading.Event()
    scanner = Scanner(errors=[TransientScanError("x")])
    runner, _, _ = fixtures(tmp_path, scanner=scanner, stop=stop)
    stop.set()
    assert runner.run_once().status == "cancelled"
    runner.run_forever()
    assert scanner.calls == 0


def test_corrupt_and_unsupported_state_fail_closed(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("not json")
    with pytest.raises(PaperStateError): fixtures(tmp_path)
    path.write_text(json.dumps({"version": 99}))
    with pytest.raises(PaperStateError): fixtures(tmp_path)


def test_persistence_failure_does_not_publish_or_mutate_duplicate_set(tmp_path, monkeypatch):
    store = PaperStateStore(tmp_path / "state.json")
    runner, _, _ = fixtures(tmp_path, store=store)
    monkeypatch.setattr(store, "save", lambda state: (_ for _ in ()).throw(PaperStateError("disk")))
    result = runner.run_once()
    assert result.status == "persistence_failed" and result.entries == ()
    assert runner.state.emitted_signal_ids == [] and not store.path.exists()


def test_record_is_explicitly_paper_and_requires_no_broker(tmp_path):
    runner, _, _ = fixtures(tmp_path)
    record = runner.run_once().entries[0]
    assert record.execution_mode == "PAPER"
    assert not hasattr(runner, "broker") and not hasattr(runner, "order_client")
