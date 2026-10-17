"""Failure lifecycle remains safe over the real guarded HTTP and job coordinator."""
from unittest.mock import Mock

from fastapi.testclient import TestClient

from crypto_strategy_lab.browser_guarded_integration import BrowserGuardedIntegration
from crypto_strategy_lab.browser_http import create_browser_app

TOKEN = "f" * 48
HEADERS = {"Authorization": "Bearer " + TOKEN}


def test_failed_job_is_sanitized_and_does_not_block_next_submission(tmp_path, monkeypatch):
    import crypto_strategy_lab.data_lake_config as schema

    config = schema.ResearchRunConfig()
    monkeypatch.setattr(schema, "normalize_data_lake_config", lambda _: config)
    service = Mock()
    service.progress_callback = None
    service.run.side_effect = [RuntimeError("private file C:/secret/run"), "ok"]
    integration = BrowserGuardedIntegration(service, tmp_path, enabled=True, execution_root=tmp_path)
    app = create_browser_app(token=TOKEN, guarded_integration=integration, guarded_enabled=True)
    request = {
        "exchange": "binance", "market": "futures_um", "symbol": "BTCUSDT",
        "period_start": "2025-01-01T00:00:00Z",
        "period_end": "2025-01-02T00:00:00Z",
        "strategy_timeframe": "4h", "intrabar_timeframe": "1m",
    }
    try:
        with TestClient(app, base_url="http://localhost") as client:
            first = client.post("/api/v1/guarded/jobs", headers=HEADERS,
                json={"request_id": "failed_job", "request": request, "config": {}})
            assert first.status_code == 202
            future = integration._jobs.result("failed_job")
            try:
                future.result(timeout=10)
            except RuntimeError:
                pass
            status = client.get("/api/v1/guarded/jobs/failed_job", headers=HEADERS)
            assert status.status_code == 200
            assert status.json() == {"request_id": "failed_job", "status": "FAILED"}
            assert "secret" not in status.text
            second = client.post("/api/v1/guarded/jobs", headers=HEADERS,
                json={"request_id": "new_job", "request": request, "config": {}})
            assert second.status_code == 202
            assert integration._jobs.result("new_job").result(timeout=10) == "ok"
            assert client.get("/api/v1/guarded/jobs/new_job", headers=HEADERS).json() == {
                "request_id": "new_job", "status": "COMPLETED"
            }
        assert service.run.call_count == 2
        assert service.progress_callback is None
    finally:
        integration.close()
