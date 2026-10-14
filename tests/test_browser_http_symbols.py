from unittest.mock import Mock

import pytest

from crypto_strategy_lab.browser_http import create_browser_app


def test_symbols_endpoint_reuses_injected_read_service():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    service = Mock()
    service.symbols.return_value = ["BTCUSDT", "ETHUSDT"]
    token = "b" * 48
    app = create_browser_app(token=token, read_service=service)
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/api/v1/catalog/symbols").status_code == 401
        assert client.get("/api/v1/catalog/symbols", headers={"Authorization": "Bearer " + token}, params={"market": "unknown"}).status_code == 422
        response = client.get("/api/v1/catalog/symbols", headers={"Authorization": "Bearer " + token}, params={"market": "futures_um"})
        assert response.status_code == 200
        assert response.json() == {"symbols": ["BTCUSDT", "ETHUSDT"]}
        assert client.get("/api/v1/catalog/symbols", headers={"Authorization": "Bearer " + token, "Host": "evil.invalid"}).status_code == 403
    service.symbols.assert_called_once_with("futures_um")
    service.completed_run.assert_not_called()
    service.research_config.assert_not_called()
