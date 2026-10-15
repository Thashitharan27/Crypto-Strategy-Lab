from unittest.mock import Mock

import pytest

from crypto_strategy_lab.browser_http import create_browser_app


def test_capabilities_endpoint_requires_auth_and_reuses_read_service():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    service = Mock()
    service.capabilities.return_value = {
        "mode": "read-only",
        "strategy": {"indicators": {"ADX": {"type": "numeric"}}},
        "features": [{"name": "core_directional"}],
    }
    token = "c" * 48
    app = create_browser_app(token=token, read_service=service)

    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/api/v1/capabilities").status_code == 401
        response = client.get(
            "/api/v1/capabilities",
            headers={"Authorization": "Bearer " + token},
        )

    assert response.status_code == 200
    assert response.json()["mode"] == "read-only"
    service.capabilities.assert_called_once_with()
