from unittest.mock import Mock

import pytest

from crypto_strategy_lab.browser_http import create_browser_app


def test_portfolio_candidates_requires_auth_and_fixed_root(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    root = tmp_path / "completed"
    root.mkdir()
    service = Mock()
    service.portfolio_candidates.return_value = [{"run_id": "BTCUSDT_4h", "symbol": "BTCUSDT"}]
    token = "a" * 48
    with TestClient(create_browser_app(token=token, read_service=service, completed_run_root=root),
                    base_url="http://localhost") as client:
        assert client.get("/api/v1/portfolio/candidates").status_code == 401
        response = client.get("/api/v1/portfolio/candidates", headers={"Authorization": "Bearer " + token})
        assert response.status_code == 200
        assert response.json() == {"candidates": [{"run_id": "BTCUSDT_4h", "symbol": "BTCUSDT"}]}
    service.portfolio_candidates.assert_called_once_with(root.resolve())


def test_portfolio_candidates_is_bounded_and_no_root_gives_empty(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    service = Mock()
    service.portfolio_candidates.return_value = [{"run_id": str(i)} for i in range(120)]
    token = "a" * 48
    missing = tmp_path / "missing"
    with TestClient(create_browser_app(token=token, read_service=service, completed_run_root=missing),
                    base_url="http://localhost") as client:
        assert client.get("/api/v1/portfolio/candidates", headers={"Authorization": "Bearer " + token}).json() == {"candidates": []}
    service.portfolio_candidates.assert_not_called()
    root = tmp_path / "runs"
    root.mkdir()
    with TestClient(create_browser_app(token=token, read_service=service, completed_run_root=root),
                    base_url="http://localhost") as client:
        response = client.get("/api/v1/portfolio/candidates", headers={"Authorization": "Bearer " + token})
        assert response.status_code == 200
        assert len(response.json()["candidates"]) == 100


def test_portfolio_http_projects_only_allowlisted_discovery_fields(tmp_path):
    """HTTP boundary must not leak disk paths or internal research hashes."""
    from unittest.mock import patch

    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from crypto_strategy_lab.browser_readonly_service import BrowserReadOnlyService

    output = tmp_path / "completed"
    output.mkdir()
    private = str(tmp_path / "private-portfolio.parquet")
    discovered = [{
        "run_id": "BTCUSDT_4h_verified",
        "symbol": "BTCUSDT",
        "strategy_timeframe": "4h",
        "candidate_rows": 12,
        "completed_at": "2026-09-01",
        "sampling_mode": "EVERY_VIABLE_ENTRY",
        "run_dir": private,
        "samples_path": private,
        "execution_hash": "sensitive-internal-fingerprint",
    }]
    service = BrowserReadOnlyService(Mock())
    token = "b" * 48
    with patch("crypto_strategy_lab.portfolio_replay.discover_resilience_runs", return_value=discovered) as discovery:
        with TestClient(create_browser_app(token=token, read_service=service, completed_run_root=output),
                        base_url="http://localhost") as client:
            response = client.get("/api/v1/portfolio/candidates", headers={"Authorization": "Bearer " + token})
    discovery.assert_called_once_with(output.resolve())
    assert response.status_code == 200
    assert response.json() == {"candidates": [{
        "run_id": "BTCUSDT_4h_verified",
        "symbol": "BTCUSDT",
        "strategy_timeframe": "4h",
        "candidate_rows": 12,
        "completed_at": "2026-09-01",
        "sampling_mode": "EVERY_VIABLE_ENTRY",
    }]}
    assert private not in response.text
    assert "sensitive-internal-fingerprint" not in response.text
