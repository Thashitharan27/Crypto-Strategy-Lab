from unittest.mock import Mock

import pytest

from crypto_strategy_lab.browser_http import create_browser_app


def _client():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    owner = Mock()
    owner.open_completed_run.return_value = "http://127.0.0.1:42111/session/unique/"
    app = create_browser_app(token="t" * 48, visualizer_coordinator=owner)
    return TestClient(app, base_url="http://127.0.0.1:8767"), owner


def test_visualizer_session_requires_explicit_authenticated_same_origin_post():
    client, owner = _client()
    endpoint = "/api/v1/visualizer/sessions/BTCUSDT_4h_123"
    assert client.get(endpoint).status_code == 405
    assert client.post(endpoint, headers={"Origin": "http://127.0.0.1:8767"}).status_code == 401
    bearer = {"Authorization": "Bearer " + "t" * 48}
    assert client.post(endpoint, headers=bearer).status_code == 403
    for origin in ("http://127.0.0.1:9999", "http://localhost:8767", "https://evil.example"):
        assert client.post(endpoint, headers={**bearer, "Origin": origin}).status_code == 403
    assert client.post(endpoint, headers={**bearer, "Origin": "http://127.0.0.1:8767",
                                          "Sec-Fetch-Site": "cross-site"}).status_code == 403
    owner.open_completed_run.assert_not_called()
    response = client.post(endpoint, headers={**bearer, "Origin": "http://127.0.0.1:8767",
                                               "Sec-Fetch-Site": "same-origin"})
    assert response.status_code == 201
    assert response.json() == {"url": owner.open_completed_run.return_value}
    owner.open_completed_run.assert_called_once_with("BTCUSDT_4h_123")


def test_visualizer_invalid_or_unverified_run_never_exposes_session():
    client, owner = _client()
    owner.open_completed_run.side_effect = ValueError("no verified manifest")
    result = client.post("/api/v1/visualizer/sessions/BAD", headers={
        "Authorization": "Bearer " + "t" * 48, "Origin": "http://127.0.0.1:8767"
    })
    assert result.status_code == 404
    assert "no verified manifest" not in result.text


def test_visualizer_lifecycle_stops_on_app_shutdown():
    client, owner = _client()
    with client:
        pass
    owner.stop.assert_called_once_with()


def test_visualizer_post_only_when_coordinator_explicitly_wired():
    from fastapi.testclient import TestClient
    app = create_browser_app(token="t" * 48)
    with TestClient(app, base_url="http://127.0.0.1:8767") as client:
        assert client.post("/api/v1/visualizer/sessions/BTCUSDT_4h").status_code == 404


def test_visualizer_route_is_the_only_explicit_non_get_api_operation(tmp_path):
    from unittest.mock import Mock
    app = create_browser_app(
        token="t" * 48, read_service=Mock(), visualizer_coordinator=Mock(),
        completed_run_root=tmp_path, config_root=tmp_path,
    )

    def assert_exact_inventory():
        operations = {}
        for route in app.routes:
            if route.path == "/api/v1" or route.path.startswith("/api/v1/"):
                assert route.__class__.__name__ != "Mount"
                assert route.methods is not None
                operations.setdefault(route.path, set()).update(route.methods)
        assert operations == {
            "/api/v1/health": {"GET"},
            "/api/v1/release/capabilities": {"GET"},
            "/api/v1/capabilities": {"GET"},
            "/api/v1/catalog/symbols": {"GET"},
            "/api/v1/catalog/coverage": {"GET"},
            "/api/v1/portfolio/candidates": {"GET"},
            "/api/v1/runs/{run_id}": {"GET"},
            "/api/v1/configs/{config_id}": {"GET"},
            "/api/v1/visualizer/sessions/{run_id}": {"POST"},
        }

    assert_exact_inventory()
    # An added coordinator-only GET must not silently pass the safety gate.
    @app.get("/api/v1/coordinator-unreviewed")
    def unexpected_route():
        return {}
    with pytest.raises(AssertionError):
        assert_exact_inventory()


def test_visualizer_rejects_noncanonical_run_ids_before_coordinator():
    client, owner = _client()
    headers = {"Authorization": "Bearer " + "t" * 48,
               "Origin": "http://127.0.0.1:8767"}
    with client:
        for run_id in (".", "..", "bad.name", "invalid%20name", "a" * 101):
            response = client.post(f"/api/v1/visualizer/sessions/{run_id}", headers=headers)
            assert response.status_code in {404, 422}
    owner.open_completed_run.assert_not_called()
