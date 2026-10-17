"""Isolated coordinator tests; no network, market data or persisted runs."""
from concurrent.futures import Future
from threading import Event
from unittest.mock import Mock

import pytest

from crypto_strategy_lab.browser_guarded_jobs import GuardedRunJobs


def test_disabled_by_default_does_not_invoke_native_runner():
    app = Mock()
    jobs = GuardedRunJobs(app)
    with pytest.raises(PermissionError, match="disabled"):
        jobs.submit("a", object(), object())
    app.run.assert_not_called()
    jobs.close()


def test_delegates_to_native_run_and_records_result():
    app = Mock()
    app.run.return_value = {"result": 1}
    jobs = GuardedRunJobs(app, enabled=True)
    request, config = object(), object()
    future = jobs.submit("job-1", request, config)
    assert future.result(timeout=5) == {"result": 1}
    assert jobs.result("job-1") is future
    app.run.assert_called_once_with(request, config)
    jobs.close()


def test_rejects_parallel_jobs_and_duplicate_ids():
    entered, release = Event(), Event()
    def blocked(*args):
        entered.set()
        assert release.wait(5)
    app = Mock()
    app.run.side_effect = blocked
    jobs = GuardedRunJobs(app, enabled=True)
    try:
        first = jobs.submit("one", object(), object())
        assert entered.wait(5)
        with pytest.raises(RuntimeError, match="already active"):
            jobs.submit("two", object(), object())
        with pytest.raises(ValueError, match="Duplicate"):
            jobs.submit("one", object(), object())
        assert app.run.call_count == 1
    finally:
        release.set()
        first.result(timeout=5)
        jobs.close()


def test_failure_is_retained_and_new_job_can_run():
    app = Mock()
    app.run.side_effect = [ValueError("injected failure"), "ok"]
    jobs = GuardedRunJobs(app, enabled=True)
    try:
        first = jobs.submit("failed", None, None)
        with pytest.raises(ValueError, match="injected failure"):
            first.result(timeout=5)
        # Callback on Future is synchronous before result() returns for worker.
        assert jobs.submit("new", None, None).result(timeout=5) == "ok"
    finally:
        jobs.close()


def test_rejects_invalid_ids_and_closed_jobs():
    app = Mock()
    jobs = GuardedRunJobs(app, enabled=True)
    for request_id in ("", "../bad", "contains space", "é"):
        with pytest.raises(ValueError):
            jobs.submit(request_id, None, None)
    jobs.close()
    with pytest.raises(RuntimeError, match="closed"):
        jobs.submit("good", None, None)
    app.run.assert_not_called()


def test_status_reports_running_completed_and_failed_without_native_details():
    entered, release = Event(), Event()
    def slow(*args):
        entered.set()
        assert release.wait(5)
        return {"secret": "not for status"}
    app = Mock()
    app.run.side_effect = slow
    jobs = GuardedRunJobs(app, enabled=True)
    try:
        future = jobs.submit("running", None, None)
        assert entered.wait(5)
        assert jobs.status("running") == {"request_id": "running", "status": "RUNNING"}
        with pytest.raises(KeyError):
            jobs.status("unknown")
        release.set()
        assert future.result(timeout=5) == {"secret": "not for status"}
        assert jobs.status("running") == {"request_id": "running", "status": "COMPLETED"}
    finally:
        release.set()
        jobs.close()

    failed_app = Mock()
    failed_app.run.side_effect = RuntimeError("private native failure")
    failed = GuardedRunJobs(failed_app, enabled=True)
    try:
        future = failed.submit("failure", None, None)
        with pytest.raises(RuntimeError):
            future.result(timeout=5)
        assert failed.status("failure") == {"request_id": "failure", "status": "FAILED"}
    finally:
        failed.close()


def test_native_progress_is_bounded_scoped_and_previous_observer_restored():
    app = Mock()
    original = Mock()
    app.progress_callback = original
    def run(request, config):
        app.progress_callback({"kind": "stage", "phase": "preparing", "detail": "private path"})
        app.progress_callback({"kind": "partition", "detail": "private raw candles"})
        return "done"
    app.run.side_effect = run
    jobs = GuardedRunJobs(app, enabled=True)
    try:
        assert jobs.submit("progress", None, None).result(timeout=5) == "done"
        assert jobs.progress("progress") == {"phase": "preparing"}
        assert jobs.progress("progress") == {"phase": "preparing"}
        assert app.progress_callback is original
        assert original.call_count == 2
        with pytest.raises(KeyError):
            jobs.progress("not-found")
    finally:
        jobs.close()


def test_native_progress_observer_restored_after_exception():
    app = Mock()
    app.progress_callback = None
    def broken(request, config):
        app.progress_callback({"kind": "stage", "phase": "failed"})
        raise RuntimeError("native failure private data")
    app.run.side_effect = broken
    jobs = GuardedRunJobs(app, enabled=True)
    try:
        with pytest.raises(RuntimeError):
            jobs.submit("failure", None, None).result(timeout=5)
        assert jobs.progress("failure") == {"phase": "failed"}
        assert app.progress_callback is None
    finally:
        jobs.close()
