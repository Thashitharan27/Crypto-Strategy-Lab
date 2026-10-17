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
