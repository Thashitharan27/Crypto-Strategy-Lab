"""Isolated HTTP-to-native guarded lifecycle regression; no real market data or disk writes."""
from threading import Event
from unittest.mock import Mock

from fastapi.testclient import TestClient

from crypto_strategy_lab.browser_http import create_browser_app
from crypto_strategy_lab.browser_guarded_integration import BrowserGuardedIntegration

TOKEN = "g" * 48


def test_guarded_http_submit_status_cancel_and_completion(tmp_path, monkeypatch):
    import crypto_strategy_lab.data_lake_config as schema

    config = schema.ResearchRunConfig()
    monkeypatch.setattr(schema, "normalize_data_lake_config", lambda _: config)
    entered, release = Event(), Event()
    app_service = Mock()

    def native_run(request, cfg):
        assert cfg.reporting.output_dir == str(tmp_path)
        entered.set()
        assert release.wait(10)
        return {"private": "native result"}

    app_service.run.side_effect = native_run
    integration = BrowserGuardedIntegration(app_service, tmp_path, enabled=True, execution_root=tmp_path)
    app = create_browser_app(
        token=TOKEN, guarded_integration=integration, guarded_enabled=True,
    )
    payload = {
        "request_id": "job_1",
        "request": {
            "exchange": "binance", "market": "futures_um",
            "symbol": "BTCUSDT", "period_start": "2025-01-01T00:00:00Z",
            "period_end": "2025-01-02T00:00:00Z",
            "strategy_timeframe": "4h", "intrabar_timeframe": "1m",
        },
        "config": {},
    }
    headers = {"Authorization": "Bearer " + TOKEN}
    try:
        with TestClient(app, base_url="http://localhost") as client:
            assert client.post("/api/v1/guarded/jobs", json=payload).status_code == 401
            submit = client.post("/api/v1/guarded/jobs", json=payload, headers=headers)
            assert submit.status_code == 202
            assert submit.json() == {"request_id": "job_1", "status": "ACCEPTED"}
            assert entered.wait(10)
            status = client.get("/api/v1/guarded/jobs/job_1", headers=headers)
            assert status.json() == {"request_id": "job_1", "status": "RUNNING"}
            denied = client.post("/api/v1/guarded/jobs/job_1/cancel", headers=headers)
            assert denied.json() == {"request_id": "job_1", "status": "CANCELLATION_UNAVAILABLE"}
            assert client.post("/api/v1/guarded/jobs", json=payload, headers=headers).status_code == 409
            release.set()
            integration._jobs.result("job_1").result(timeout=10)
            assert client.get("/api/v1/guarded/jobs/job_1", headers=headers).json() == {
                "request_id": "job_1", "status": "COMPLETED"
            }
            assert client.get("/api/v1/guarded/jobs/job_1/progress", headers=headers).json() == {}
        app_service.run.assert_called_once()
    finally:
        release.set()
        integration.close()


def test_production_app_is_read_only_even_with_real_guarded_integration(tmp_path):
    service = Mock()
    integration = BrowserGuardedIntegration(service, tmp_path, enabled=True, execution_root=tmp_path)
    try:
        app = create_browser_app(token=TOKEN, guarded_integration=integration)
        with TestClient(app, base_url="http://localhost") as client:
            headers = {"Authorization": "Bearer " + TOKEN}
            assert client.post("/api/v1/guarded/jobs", json={}, headers=headers).status_code == 404
            assert client.put("/api/v1/guarded/configs/any", json={}, headers=headers).status_code == 404
        service.run.assert_not_called()
    finally:
        integration.close()
