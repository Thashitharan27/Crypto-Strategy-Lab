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

    api_routes = {}
    for route in app.routes:
        if route.path == "/api/v1" or route.path.startswith("/api/v1/"):
            # Mounted sub-apps can hide arbitrary methods behind a path, so
            # fail closed rather than treating a Mount as a harmless GET.
            assert route.__class__.__name__ != "Mount"
            assert route.methods is not None, "Uninspectable API route"
            api_routes.setdefault(route.path, set()).update(route.methods)

    assert api_routes == {
        "/api/v1/health": {"GET"},
        "/api/v1/capabilities": {"GET"},
        "/api/v1/catalog/symbols": {"GET"},
        "/api/v1/catalog/coverage": {"GET"},
        "/api/v1/portfolio/candidates": {"GET"},
        "/api/v1/runs/{run_id}": {"GET"},
        "/api/v1/configs/{config_id}": {"GET"},
    }
    assert all(methods <= {"GET", "HEAD"} for methods in api_routes.values())
    assert not any(
        token in path.lower()
        for path in api_routes
        for token in ("execute", "run/create", "start", "write", "save", "delete", "trade")
    )


def test_browser_api_inventory_guard_rejects_root_and_mounted_routes(tmp_path):
    pytest.importorskip("fastapi")
    from unittest.mock import Mock
    from fastapi import FastAPI
    from starlette.routing import Mount

    app = create_browser_app(
        token="r" * 48, read_service=Mock(),
        completed_run_root=tmp_path, config_root=tmp_path,
    )
    expected = {
        "/api/v1/health", "/api/v1/capabilities", "/api/v1/catalog/symbols",
        "/api/v1/catalog/coverage", "/api/v1/portfolio/candidates", "/api/v1/runs/{run_id}",
        "/api/v1/configs/{config_id}",
    }
    def assert_safe_routes():
        api_routes = {}
        for route in app.routes:
            if route.path == "/api/v1" or route.path.startswith("/api/v1/"):
                assert not isinstance(route, Mount), "Mounted API routes are not certified"
                assert route.methods is not None, "Uninspectable API route"
                api_routes.setdefault(route.path, set()).update(route.methods)
        assert set(api_routes) == expected
        assert all(methods == {"GET"} for methods in api_routes.values())

    assert_safe_routes()
    @app.post("/api/v1")
    def unsafe_root():
        return {}
    with pytest.raises(AssertionError):
        assert_safe_routes()
    app.router.routes.pop()

    mounted = FastAPI()
    @mounted.post("/write")
    def unsafe_write():
        return {}
    app.mount("/api/v1", mounted)
    with pytest.raises(AssertionError, match="Mounted API routes"):
        assert_safe_routes()


def test_completed_run_infinite_profit_factor_json_safe(tmp_path):
    pytest.importorskip("fastapi")
    from unittest.mock import Mock
    from fastapi.testclient import TestClient

    token = "z" * 48
    run_dir = tmp_path / "run_sample"
    run_dir.mkdir()
    service = Mock()
    service.completed_run.return_value = {
        "manifest": {"run_id": "run_sample", "run_status": "COMPLETED"},
        "summary": {"total_trades": 3, "win_rate": 1.0, "net_pnl": 10.0, "profit_factor": float("inf")},
    }
    app = create_browser_app(token=token, read_service=service, completed_run_root=tmp_path)
    with TestClient(app, base_url="http://localhost") as client:
        response = client.get("/api/v1/runs/run_sample", headers={"Authorization": "Bearer " + token})
        assert response.status_code == 200
        assert response.json()["summary"]["profit_factor"] == "Infinity"
        assert response.json()["summary"]["total_trades"] == 3
    assert service.completed_run.return_value["summary"]["profit_factor"] == float("inf")


def test_completed_run_undefined_summary_metrics_json_safe(tmp_path):
    pytest.importorskip("fastapi")
    from unittest.mock import Mock
    from fastapi.testclient import TestClient
    import math

    token = "n" * 48
    run_dir = tmp_path / "run_nan"
    run_dir.mkdir()
    summary = {
        "total_trades": 2,
        "average_adx_of_losing_trades": float("nan"),
        "average_combined_effective_leverage": float("nan"),
        "profit_factor": float("inf"),
        "outcomes": {"TP": {"average_net_r": float("-inf"), "count": 2}},
        "win_rate": 1.0,
    }
    service = Mock()
    service.completed_run.return_value = {"summary": summary}
    app = create_browser_app(token=token, read_service=service, completed_run_root=tmp_path)
    with TestClient(app, base_url="http://localhost") as client:
        response = client.get("/api/v1/runs/run_nan", headers={"Authorization": "Bearer " + token})
        assert response.status_code == 200
        encoded = response.json()["summary"]
        assert encoded["average_adx_of_losing_trades"] is None
        assert encoded["average_combined_effective_leverage"] is None
        assert encoded["profit_factor"] == "Infinity"
        assert encoded["outcomes"]["TP"]["average_net_r"] == "-Infinity"
        assert encoded["outcomes"]["TP"]["count"] == 2
        assert encoded["win_rate"] == 1.0
    assert math.isnan(summary["average_adx_of_losing_trades"])
    assert math.isinf(summary["profit_factor"])


def test_browser_api_rejects_malformed_local_host_ports():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    token = "h" * 48
    app = create_browser_app(token=token)
    with TestClient(app, base_url="http://localhost") as client:
        headers = {"Authorization": "Bearer " + token}
        for host in ("localhost:invalid", "127.0.0.1:99999", "localhost:-1", "localhost:"):
            response = client.get("/api/v1/health", headers={**headers, "Host": host})
            assert response.status_code == 403, host
        assert client.get("/api/v1/health", headers={**headers, "Host": "localhost:8767"}).status_code == 200
