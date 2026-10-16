from unittest.mock import Mock
import pytest
from crypto_strategy_lab.browser_http import create_browser_app

def test_completed_run_checks_auth_missing_ids_and_reuses_reader(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    root = tmp_path / "runs"
    root.mkdir()
    (root / "run_abc").mkdir()
    service = Mock()
    service.completed_run.return_value = {"summary": {"trades": 2}, "manifest": {"run_id": "abc"}}
    token = "c" * 48
    app = create_browser_app(token=token, read_service=service, completed_run_root=root)
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/api/v1/runs/run_abc").status_code == 401
        headers = {"Authorization": "Bearer " + token}
        assert client.get("/api/v1/runs/unknown", headers=headers).status_code == 404
        result = client.get("/api/v1/runs/run_abc", headers=headers)
        assert result.status_code == 200
        assert result.json()["summary"]["trades"] == 2
    service.completed_run.assert_called_once_with((root / "run_abc").resolve())
    service.research_config.assert_not_called()


def test_portfolio_discovery_requires_auth_and_bounds_existing_readonly_results(tmp_path):
    from fastapi.testclient import TestClient

    service = Mock()
    rows = [{"run_id": f"existing_{i}", "candidate_rows": i} for i in range(125)]
    service.portfolio_candidates.return_value = rows
    token = "p" * 48
    with TestClient(
        create_browser_app(token=token, read_service=service, completed_run_root=tmp_path),
        base_url="http://localhost",
    ) as client:
        assert client.get("/api/v1/portfolio/candidates").status_code == 401
        service.portfolio_candidates.assert_not_called()
        response = client.get(
            "/api/v1/portfolio/candidates", headers={"Authorization": "Bearer " + token},
        )
        assert response.status_code == 200
        assert response.json() == {"candidates": rows[:100]}
    service.portfolio_candidates.assert_called_once_with(tmp_path.resolve())


def test_portfolio_missing_root_returns_empty_without_discovery(tmp_path):
    from fastapi.testclient import TestClient

    service = Mock()
    root = tmp_path / "not_present"
    token = "p" * 48
    with TestClient(
        create_browser_app(token=token, read_service=service, completed_run_root=root),
        base_url="http://localhost",
    ) as client:
        response = client.get(
            "/api/v1/portfolio/candidates", headers={"Authorization": "Bearer " + token},
        )
    assert response.status_code == 200
    assert response.json() == {"candidates": []}
    service.portfolio_candidates.assert_not_called()


def test_portfolio_discovery_errors_fail_closed_without_paths(tmp_path):
    from fastapi.testclient import TestClient

    service = Mock()
    service.portfolio_candidates.side_effect = OSError("private original source path")
    token = "p" * 48
    with TestClient(
        create_browser_app(token=token, read_service=service, completed_run_root=tmp_path),
        base_url="http://localhost",
    ) as client:
        response = client.get(
            "/api/v1/portfolio/candidates", headers={"Authorization": "Bearer " + token},
        )
    assert response.status_code == 503
    assert response.json() == {"detail": "Portfolio discovery unavailable"}
    assert "private original source path" not in response.text
