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


def test_cancel_running_native_job_never_claims_cancellation():
    entered, release = Event(), Event()
    def run(*args):
        entered.set()
        assert release.wait(5)
        return "completed"
    app = Mock()
    app.run.side_effect = run
    jobs = GuardedRunJobs(app, enabled=True)
    try:
        future = jobs.submit("active", None, None)
        assert entered.wait(5)
        assert jobs.cancel("active") == {
            "request_id": "active", "status": "CANCELLATION_UNAVAILABLE"
        }
        assert not future.cancelled()
        release.set()
        assert future.result(timeout=5) == "completed"
        assert jobs.cancel("active") == {
            "request_id": "active", "status": "COMPLETED"
        }
    finally:
        release.set()
        jobs.close()


def test_cancel_unknown_job_rejected_without_native_action():
    app = Mock()
    jobs = GuardedRunJobs(app, enabled=True)
    try:
        with pytest.raises(KeyError):
            jobs.cancel("unknown")
        app.run.assert_not_called()
    finally:
        jobs.close()


def test_progress_does_not_disclose_freeform_native_stage_diagnostics():
    app = Mock()
    def run(request, config):
        app.progress_callback({"kind": "stage", "phase": "loading"})
        app.progress_callback({"kind": "stage", "phase": "/private/secret/config.json"})
        app.progress_callback({"kind": "stage", "phase": "SECRET_TOKEN=abc"})
        app.progress_callback({"kind": "stage", "phase": "x" * 120})
        app.progress_callback({"kind": "stage", "phase": 123})
        return "done"
    app.run.side_effect = run
    jobs = GuardedRunJobs(app, enabled=True)
    try:
        jobs.submit("redacted", None, None).result(timeout=5)
        assert jobs.progress("redacted") == {"phase": "loading"}
        assert "private" not in str(jobs.progress("redacted"))
        assert "SECRET" not in str(jobs.progress("redacted"))
    finally:
        jobs.close()


def test_durable_claim_blocks_replay_across_coordinator_restart(tmp_path):
    app = Mock()
    app.run.return_value = "ok"
    first = GuardedRunJobs(app, enabled=True, execution_root=tmp_path)
    try:
        from crypto_strategy_lab.data_lake_config import ResearchRunConfig
        assert first.submit("stable-id", object(), ResearchRunConfig()).result(timeout=10) == "ok"
    finally:
        first.close()
    second = GuardedRunJobs(app, enabled=True, execution_root=tmp_path)
    try:
        with pytest.raises(ValueError, match="Duplicate"):
            second.submit("stable-id", object(), ResearchRunConfig())
        assert app.run.call_count == 1
        assert (tmp_path / ".guarded-request-stable-id.claim").is_dir()
    finally:
        second.close()


def test_interrupted_request_claim_is_not_replayed(tmp_path):
    (tmp_path / ".guarded-request-interrupted.claim").mkdir()
    app = Mock()
    jobs = GuardedRunJobs(app, enabled=True, execution_root=tmp_path)
    try:
        with pytest.raises(ValueError, match="Duplicate"):
            jobs.submit("interrupted", None, None)
        app.run.assert_not_called()
    finally:
        jobs.close()


def test_invalid_execution_root_never_creates_request_claim(tmp_path):
    app = Mock()
    jobs = GuardedRunJobs(app, enabled=True, execution_root=tmp_path / "missing")
    try:
        with pytest.raises(ValueError, match="Unsafe guarded execution root"):
            jobs.submit("unsafe", None, None)
        assert not (tmp_path / "missing").exists()
        app.run.assert_not_called()
    finally:
        jobs.close()


def test_separate_coordinators_cannot_run_different_ids_concurrently(tmp_path):
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig
    entered, release = Event(), Event()
    app_one = Mock()
    app_two = Mock()
    def blocking_run(*_):
        entered.set()
        assert release.wait(10)
        return "ok"
    app_one.run.side_effect = blocking_run
    first = GuardedRunJobs(app_one, enabled=True, execution_root=tmp_path)
    second = GuardedRunJobs(app_two, enabled=True, execution_root=tmp_path)
    try:
        future = first.submit("first", None, ResearchRunConfig())
        assert entered.wait(10)
        with pytest.raises(RuntimeError, match="already owned"):
            second.submit("second", None, ResearchRunConfig())
        assert not (tmp_path / ".guarded-request-second.claim").exists()
        app_two.run.assert_not_called()
        release.set()
        assert future.result(timeout=10) == "ok"
        assert not (tmp_path / ".guarded-native-worker.lock").exists()
        assert second.submit("second", None, ResearchRunConfig()).result(timeout=10) is app_two.run.return_value
    finally:
        release.set()
        first.close()
        second.close()


def test_stale_native_worker_claim_requires_manual_reconciliation(tmp_path):
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig
    (tmp_path / ".guarded-native-worker.lock").mkdir()
    app = Mock()
    jobs = GuardedRunJobs(app, enabled=True, execution_root=tmp_path)
    try:
        with pytest.raises(RuntimeError, match="already owned"):
            jobs.submit("new-id", None, ResearchRunConfig())
        assert not (tmp_path / ".guarded-request-new-id.claim").exists()
        assert (tmp_path / ".guarded-native-worker.lock").is_dir()
        app.run.assert_not_called()
    finally:
        jobs.close()


def test_native_failure_releases_worker_claim_without_reusing_request_id(tmp_path):
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig
    app = Mock()
    app.run.side_effect = [RuntimeError("native failed"), "ok"]
    jobs = GuardedRunJobs(app, enabled=True, execution_root=tmp_path)
    try:
        with pytest.raises(RuntimeError, match="native failed"):
            jobs.submit("failed", None, ResearchRunConfig()).result(timeout=10)
        assert not (tmp_path / ".guarded-native-worker.lock").exists()
        assert jobs.submit("new-id", None, ResearchRunConfig()).result(timeout=10) == "ok"
        with pytest.raises(ValueError, match="Duplicate"):
            jobs.submit("failed", None, ResearchRunConfig())
    finally:
        jobs.close()


def test_pre_start_cancel_releases_worker_but_retains_request_claim(tmp_path):
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig

    app = Mock()
    jobs = GuardedRunJobs(app, enabled=True, execution_root=tmp_path)
    # Deterministically emulate the worker not having started yet.
    pending = Future()
    jobs._executor.submit = Mock(return_value=pending)
    try:
        assert jobs.submit("pending", None, ResearchRunConfig()) is pending
        assert (tmp_path / ".guarded-native-worker.lock").is_dir()
        assert jobs.cancel("pending") == {
            "request_id": "pending", "status": "CANCELLED"
        }
        assert not (tmp_path / ".guarded-native-worker.lock").exists()
        assert (tmp_path / ".guarded-request-pending.claim").is_dir()
        with pytest.raises(ValueError, match="Duplicate"):
            jobs.submit("pending", None, ResearchRunConfig())
        app.run.assert_not_called()
    finally:
        jobs.close()


def test_restarted_coordinator_reports_only_verified_request_claim_as_unverified(tmp_path):
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig

    app = Mock()
    app.run.return_value = "ok"
    first = GuardedRunJobs(app, enabled=True, execution_root=tmp_path)
    try:
        assert first.submit("previous", None, ResearchRunConfig()).result(timeout=10) == "ok"
    finally:
        first.close()

    second = GuardedRunJobs(app, enabled=True, execution_root=tmp_path)
    try:
        assert second.status("previous") == {
            "request_id": "previous", "status": "RECOVERY_UNVERIFIED",
        }
        with pytest.raises(KeyError):
            second.cancel("previous")
        with pytest.raises(KeyError):
            second.progress("previous")
        with pytest.raises(ValueError, match="Duplicate"):
            second.submit("previous", None, ResearchRunConfig())
        with pytest.raises(KeyError):
            second.status("never-claimed")
        assert app.run.call_count == 1
    finally:
        second.close()


def test_recovery_status_rejects_symlinked_or_invalid_request_claim(tmp_path):
    claim = tmp_path / ".guarded-request-previous.claim"
    other = tmp_path / "other"
    other.mkdir()
    try:
        claim.symlink_to(other, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable")
    jobs = GuardedRunJobs(Mock(), enabled=True, execution_root=tmp_path)
    try:
        with pytest.raises(KeyError):
            jobs.status("previous")
        with pytest.raises(KeyError):
            jobs.status("../other")
    finally:
        jobs.close()


def test_disabled_coordinator_does_not_expose_persisted_request_claim(tmp_path):
    (tmp_path / ".guarded-request-previous.claim").mkdir()
    jobs = GuardedRunJobs(Mock(), execution_root=tmp_path)
    try:
        with pytest.raises(PermissionError, match="disabled"):
            jobs.status("previous")
    finally:
        jobs.close()


def test_completed_job_exposes_only_native_verified_output_folder(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig
    import crypto_strategy_lab.browser_guarded_recovery_verify as verifier

    root = tmp_path.resolve()
    output = root / "native-output"
    output.mkdir()
    app = Mock()
    app.run.return_value = SimpleNamespace(output_dir=output)
    jobs = GuardedRunJobs(app, enabled=True, execution_root=root)
    checked = []
    def verify(root_path, folder):
        checked.append((root_path, folder))
        return {"run_id": folder, "status": "ARTIFACTS_VERIFIED"}
    monkeypatch.setattr(verifier, "verify_recovered_run", verify)
    try:
        jobs.submit("request-A", object(), ResearchRunConfig()).result(timeout=10)
        assert jobs.status("request-A") == {
            "request_id": "request-A", "status": "COMPLETED",
            "verified_run_folder_id": "native-output",
        }
        assert checked == [(root, "native-output")]
    finally:
        jobs.close()


def test_completed_job_never_maps_unverified_or_outside_native_output(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig
    import crypto_strategy_lab.browser_guarded_recovery_verify as verifier

    root = tmp_path.resolve()
    output = root / "native-output"
    output.mkdir()
    external = root.parent / "different-root" / "native-output"
    candidates = (None, external, root / "bad.name", output)
    monkeypatch.setattr(verifier, "verify_recovered_run",
                        lambda *_: {"status": "RECOVERY_UNVERIFIED"})
    for idx, candidate in enumerate(candidates):
        app = Mock()
        app.run.return_value = SimpleNamespace(output_dir=candidate)
        jobs = GuardedRunJobs(app, enabled=True, execution_root=root)
        try:
            request_id = f"request-{idx}"
            jobs.submit(request_id, object(), ResearchRunConfig()).result(timeout=10)
            assert jobs.status(request_id) == {
                "request_id": request_id, "status": "COMPLETED",
            }
        finally:
            jobs.close()


def test_completed_job_restart_never_reconstructs_verified_folder_mapping(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig
    import crypto_strategy_lab.browser_guarded_recovery_verify as verifier

    root = tmp_path.resolve()
    output = root / "native-output"
    output.mkdir()
    monkeypatch.setattr(verifier, "verify_recovered_run",
                        lambda *_: {"status": "ARTIFACTS_VERIFIED"})
    app = Mock()
    app.run.return_value = SimpleNamespace(output_dir=output)
    first = GuardedRunJobs(app, enabled=True, execution_root=root)
    try:
        first.submit("request-A", object(), ResearchRunConfig()).result(timeout=10)
        assert first.status("request-A")["verified_run_folder_id"] == "native-output"
    finally:
        first.close()
    second = GuardedRunJobs(app, enabled=True, execution_root=root)
    try:
        assert second.status("request-A") == {
            "request_id": "request-A", "status": "RECOVERY_UNVERIFIED",
        }
    finally:
        second.close()


def test_real_process_termination_preserves_unverified_claim_and_stale_worker_lock(tmp_path):
    """Kill a fixture worker process, then inspect its exact persistent isolated root.

    This tests durable fail-closed ownership across an actual process kill;
    it does not certify a real Windows browser/UI/native run or authorize replay.
    """
    import os
    from pathlib import Path
    import subprocess
    import sys
    import time

    root = tmp_path.resolve()
    entered = root / "native-entered.marker"
    child = r"""
import pathlib
import sys
import time

from crypto_strategy_lab.browser_guarded_jobs import GuardedRunJobs
from crypto_strategy_lab.data_lake_config import ResearchRunConfig

root, entered = map(pathlib.Path, sys.argv[1:3])

class BlockingNative:
    progress_callback = None

    def run(self, request, config):
        entered.write_text("started", encoding="ascii")
        while True:
            time.sleep(0.1)

jobs = GuardedRunJobs(BlockingNative(), enabled=True, execution_root=root)
jobs.submit("killed-request", object(), ResearchRunConfig())
while True:
    time.sleep(0.1)
"""
    repo = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(repo), env.get("PYTHONPATH", "")]
    )
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", child, str(root), str(entered)],
        cwd=repo, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 15
        while not entered.is_file() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert entered.is_file(), (
            "Fixture native worker never started; "
            + process.stderr.read().decode(errors="replace")[:600]
            if process.poll() is not None else "Fixture worker startup timed out"
        )
        assert (root / ".guarded-request-killed-request.claim").is_dir()
        assert (root / ".guarded-native-worker.lock").is_dir()
    finally:
        process.kill()
        process.wait(timeout=10)
        process.stderr.close()

    # New coordinator has no Future. Persisted claim cannot imply completion.
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig

    app = Mock()
    restarted = GuardedRunJobs(app, enabled=True, execution_root=root)
    try:
        assert restarted.status("killed-request") == {
            "request_id": "killed-request", "status": "RECOVERY_UNVERIFIED",
        }
        with pytest.raises(KeyError):
            restarted.progress("killed-request")
        with pytest.raises(KeyError):
            restarted.cancel("killed-request")
        with pytest.raises(RuntimeError, match="already owned"):
            restarted.submit("new-request", object(), ResearchRunConfig())
        assert (root / ".guarded-native-worker.lock").is_dir()
        assert not (root / ".guarded-request-new-request.claim").exists()
        app.run.assert_not_called()
    finally:
        restarted.close()
