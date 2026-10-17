"""Worker-time output validation guards against post-submission root replacement."""
from unittest.mock import Mock

import pytest

from crypto_strategy_lab.browser_guarded_jobs import GuardedRunJobs
from crypto_strategy_lab.data_lake_config import ResearchRunConfig


def test_worker_rejects_output_root_changed_to_symlink_before_native_run(tmp_path):
    root = tmp_path / "approved"
    root.mkdir()
    other = tmp_path / "outside"
    other.mkdir()
    service = Mock()
    jobs = GuardedRunJobs(service, enabled=True, execution_root=root)
    root.rmdir()
    try:
        root.symlink_to(other, target_is_directory=True)
    except (OSError, NotImplementedError):
        jobs.close()
        pytest.skip("Symlinks unavailable")
    try:
        with pytest.raises(ValueError, match="symlink"):
            jobs._run_observed("job", "native request", ResearchRunConfig())
        service.run.assert_not_called()
    finally:
        jobs.close()


def test_worker_uses_native_configuration_with_approved_root(tmp_path):
    service = Mock()
    service.run.return_value = "native"
    jobs = GuardedRunJobs(service, enabled=True, execution_root=tmp_path)
    try:
        future = jobs.submit("job", "native request", ResearchRunConfig())
        assert future.result(timeout=10) == "native"
        cfg = service.run.call_args.args[1]
        assert cfg.reporting.output_dir == str(tmp_path)
    finally:
        jobs.close()
