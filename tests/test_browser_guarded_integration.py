"""The optional integration boundary must deny every operation by default."""
from unittest.mock import Mock

import pytest

from crypto_strategy_lab.browser_guarded_integration import BrowserGuardedIntegration


def test_default_deny_all_methods_even_when_storage_does_not_exist(tmp_path):
    app = Mock()
    integration = BrowserGuardedIntegration(app, tmp_path / "absent")
    try:
        operations = (
            lambda: integration.save_config("valid", {}),
            lambda: integration.submit("job-1", None, None),
            lambda: integration.status("job-1"),
            lambda: integration.progress("job-1"),
            lambda: integration.cancel("job-1"),
        )
        for operation in operations:
            with pytest.raises(PermissionError, match="disabled"):
                operation()
        app.run.assert_not_called()
        assert not (tmp_path / "absent").exists()
    finally:
        integration.close()


def test_explicit_server_opt_in_delegates_to_native_job_owner(tmp_path):
    app = Mock()
    app.run.return_value = "native-only"
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig
    config = ResearchRunConfig()
    integration = BrowserGuardedIntegration(app, tmp_path, enabled=True, execution_root=tmp_path)
    try:
        future = integration.submit("job-1", "request", config)
        assert future.result(timeout=5) == "native-only"
        assert integration.status("job-1") == {
            "request_id": "job-1", "status": "COMPLETED"
        }
        assert integration.progress("job-1") == {}
        assert app.run.call_args.args[0] == "request"
        assert app.run.call_args.args[1].reporting.output_dir == str(tmp_path)
    finally:
        integration.close()


def test_enabled_config_path_rejects_traversal_before_native_validation(tmp_path):
    integration = BrowserGuardedIntegration(Mock(), tmp_path, enabled=True)
    try:
        with pytest.raises(ValueError, match="Invalid configuration ID"):
            integration.save_config("../item", {"not": "a native config"})
        assert not (tmp_path / "item.json").exists()
    finally:
        integration.close()


def test_enabled_submission_without_server_root_fails_before_native_run(tmp_path):
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig
    app = Mock()
    integration = BrowserGuardedIntegration(app, tmp_path, enabled=True)
    try:
        with pytest.raises(PermissionError, match="root is not configured"):
            integration.submit("job", "request", ResearchRunConfig())
        app.run.assert_not_called()
    finally:
        integration.close()
