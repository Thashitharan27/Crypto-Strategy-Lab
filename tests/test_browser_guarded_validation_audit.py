from unittest.mock import Mock

from fastapi.testclient import TestClient

from crypto_strategy_lab.browser_http import create_browser_app


def test_invalid_guarded_job_payloads_emit_only_bounded_audit_events():
    events = []
    integration = Mock()
    app = create_browser_app(
        token="j" * 48, guarded_integration=integration,
        guarded_enabled=True, guarded_audit_callback=events.append,
    )
    headers = {"Authorization": "Bearer " + "j" * 48}
    with TestClient(app, base_url="http://localhost") as client:
        invalid = [
            {"request_id": "../secret", "request": {}, "config": {}},
            {"request_id": "valid", "request": "private", "config": {}},
            {"request_id": "valid", "request": {"symbol": "SECRET"}, "config": {}},
            {"request_id": "valid", "request": {
                "exchange": "binance", "market": "spot", "symbol": "BTCUSDT",
                "period_start": "secret invalid", "period_end": "2025-01-01T00:00:00Z",
                "strategy_timeframe": "4h", "intrabar_timeframe": "1m",
            }, "config": {}},
        ]
        for payload in invalid:
            response = client.post("/api/v1/guarded/jobs", json=payload, headers=headers)
            assert response.status_code == 422
    assert events == [{"operation": "JOB_SUBMIT", "outcome": "INVALID_INPUT"}] * 4
    assert "SECRET" not in str(events)
    integration.submit.assert_not_called()
