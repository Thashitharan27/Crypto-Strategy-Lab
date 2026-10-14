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
