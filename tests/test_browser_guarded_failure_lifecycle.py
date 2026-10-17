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


def test_missing_required_1m_native_run_fails_closed_and_next_request_runs(tmp_path, monkeypatch):
    """Native-owner failure, not a simulated browser-side data-quality rule."""
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig
    from crypto_strategy_lab.gui.v2_controller import GuiApplicationService

    import crypto_strategy_lab.data_lake_config as schema

    config = ResearchRunConfig()
    assert config.data.intrabar_missing_policy == "ERROR"
    monkeypatch.setattr(schema, "normalize_data_lake_config", lambda _: config)

    class Runner:
        calls = 0

        def run(self, request, effective_config, **kwargs):
            type(self).calls += 1
            assert request.intrabar_interval == "1m"
            assert effective_config.data.intrabar_missing_policy == "ERROR"
            if type(self).calls == 1:
                raise ValueError("missing required 1m candles at /private/raw/2025")
            return "native completed"

    runner = Runner()
    native = GuiApplicationService(
        tmp_path / "raw", tmp_path / "cache", runner_factory=lambda _: runner,
    )
    integration = BrowserGuardedIntegration(
        native, tmp_path, enabled=True, execution_root=tmp_path,
    )
    app = create_browser_app(
        token=TOKEN, guarded_integration=integration, guarded_enabled=True,
    )
    request = {
        "exchange": "binance", "market": "futures_um", "symbol": "BTCUSDT",
        "period_start": "2025-01-01T00:00:00Z",
        "period_end": "2025-01-02T00:00:00Z",
        "strategy_timeframe": "4h", "intrabar_timeframe": "1m",
    }
    try:
        with TestClient(app, base_url="http://localhost") as client:
            first = client.post("/api/v1/guarded/jobs", headers=HEADERS,
                json={"request_id": "missing-1m", "request": request, "config": {}})
            assert first.status_code == 202
            future = integration._jobs.result("missing-1m")
            from pytest import raises
            with raises(ValueError, match="missing required 1m"):
                future.result(timeout=10)
            response = client.get("/api/v1/guarded/jobs/missing-1m", headers=HEADERS)
            assert response.json() == {"request_id": "missing-1m", "status": "FAILED"}
            assert "/private/" not in response.text
            assert not (tmp_path / ".guarded-native-worker.lock").exists()
            assert (tmp_path / ".guarded-request-missing-1m.claim").is_dir()
            with_retry = client.post("/api/v1/guarded/jobs", headers=HEADERS,
                json={"request_id": "missing-1m", "request": request, "config": {}})
            assert with_retry.status_code == 409
            next_run = client.post("/api/v1/guarded/jobs", headers=HEADERS,
                json={"request_id": "valid-after-gap", "request": request, "config": {}})
            assert next_run.status_code == 202
            assert integration._jobs.result("valid-after-gap").result(timeout=10) == "native completed"
            assert client.get("/api/v1/guarded/jobs/valid-after-gap",
                headers=HEADERS).json()["status"] == "COMPLETED"
        assert Runner.calls == 2
        assert native.store.progress_callback is None
    finally:
        integration.close()
