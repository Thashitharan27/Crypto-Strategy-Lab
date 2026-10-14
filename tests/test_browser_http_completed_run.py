from unittest.mock import Mock
import pytest
from crypto_strategy_lab.browser_http import create_browser_app

def test_completed_run_rejects_traversal_and_reuses_reader(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    root = tmp_path / "runs"
    root.mkdir()
    (root / "run_abc").mkdir()
    (root / "escape").symlink_to(tmp_path, target_is_directory=True)
    service = Mock()
    service.completed_run.return_value = {"summary": {"trades": 2}, "manifest": {"run_id": "abc"}}
    token = "c" * 48
    app = create_browser_app(token=token, read_service=service, completed_run_root=root)
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/api/v1/runs/run_abc").status_code == 401
        headers = {"Authorization": "Bearer " + token}
        assert client.get("/api/v1/runs/escape", headers=headers).status_code == 404
        assert client.get("/api/v1/runs/unknown", headers=headers).status_code == 404
        result = client.get("/api/v1/runs/run_abc", headers=headers)
        assert result.status_code == 200
        assert result.json()["summary"]["trades"] == 2
    service.completed_run.assert_called_once_with((root / "run_abc").resolve())
    service.research_config.assert_not_called()
