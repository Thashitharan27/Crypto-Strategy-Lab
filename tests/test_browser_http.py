import pytest

from crypto_strategy_lab.browser_http import create_browser_app


def test_browser_api_requires_long_token():
    with pytest.raises(ValueError):
        create_browser_app(token="short")


def test_browser_api_authenticated_health_and_host_restriction():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    token = "a" * 48
    app = create_browser_app(token=token)
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/api/v1/health").status_code == 401
        result = client.get("/api/v1/health", headers={"Authorization": "Bearer " + token})
        assert result.status_code == 200
        assert result.json() == {"status": "ok", "mode": "read-only"}
        assert client.get("/api/v1/health", headers={"Authorization": "Bearer " + token, "Host": "attacker.invalid"}).status_code == 403
        assert client.get("/api/v1/health", headers={"Authorization": "Bearer " + token, "Origin": "https://attacker.invalid"}).status_code == 403
        assert client.get("/api/v1/health", headers={"Authorization": "Bearer " + token, "Origin": "http://localhost:8080.evil.com"}).status_code == 403
        assert client.get("/api/v1/health", headers={"Authorization": "Bearer " + token, "Origin": "http://localhost:3000"}).status_code == 200


def test_browser_api_route_inventory_is_read_only(tmp_path):
    pytest.importorskip("fastapi")
    from unittest.mock import Mock

    token = "r" * 48
    app = create_browser_app(
        token=token,
        read_service=Mock(),
        completed_run_root=tmp_path,
        config_root=tmp_path,
    )

    api_routes = {
        route.path: set(route.methods or ())
        for route in app.routes
        if route.path.startswith("/api/v1/")
    }

    assert api_routes == {
        "/api/v1/health": {"GET"},
        "/api/v1/capabilities": {"GET"},
        "/api/v1/catalog/symbols": {"GET"},
        "/api/v1/catalog/coverage": {"GET"},
        "/api/v1/runs/{run_id}": {"GET"},
        "/api/v1/configs/{config_id}": {"GET"},
    }
    assert all(methods <= {"GET", "HEAD"} for methods in api_routes.values())
    assert not any(
        token in path.lower()
        for path in api_routes
        for token in ("execute", "run/create", "start", "write", "save", "delete", "trade")
    )
