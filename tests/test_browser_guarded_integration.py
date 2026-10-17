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
    integration = BrowserGuardedIntegration(app, tmp_path, enabled=True)
    try:
        future = integration.submit("job-1", "request", "config")
        assert future.result(timeout=5) == "native-only"
        assert integration.status("job-1") == {
            "request_id": "job-1", "status": "COMPLETED"
        }
        assert integration.progress("job-1") == {}
        app.run.assert_called_once_with("request", "config")
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
