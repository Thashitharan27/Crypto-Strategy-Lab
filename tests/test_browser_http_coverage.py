from unittest.mock import Mock
import pytest
from crypto_strategy_lab.browser_http import create_browser_app


def test_coverage_requires_auth_and_reuses_catalog_boundary():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    token = "x" * 48
    service = Mock()
    service.coverage.return_value = [{"symbol": "BTCUSDT", "state": "AVAILABLE"}]
    app = create_browser_app(token=token, read_service=service)
    params = dict(symbol="BTCUSDT", market="futures_um", start="2020-06-01T00:00:00Z",
                  end="2020-07-01T00:00:00Z", strategy_timeframe="4h", intrabar_timeframe="1m")
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/api/v1/catalog/coverage", params=params).status_code == 401
        assert client.get("/api/v1/catalog/coverage", params={**params, "symbol": "../bad"},
                          headers={"Authorization": "Bearer " + token}).status_code == 422
        response = client.get("/api/v1/catalog/coverage", params=params, headers={"Authorization": "Bearer " + token})
        assert response.status_code == 200
        assert response.json()["coverage"][0]["state"] == "AVAILABLE"
    request = service.coverage.call_args.args[0]
    assert request.symbol == "BTCUSDT"
    assert request.strategy_timeframe == "4h"
    service.completed_run.assert_not_called()
