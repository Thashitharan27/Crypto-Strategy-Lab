"""Browser-submitted native output paths cannot override the trusted server root."""
from dataclasses import replace
from unittest.mock import Mock

from fastapi.testclient import TestClient

from crypto_strategy_lab.browser_http import create_browser_app
from crypto_strategy_lab.browser_guarded_integration import BrowserGuardedIntegration
from crypto_strategy_lab.data_lake_config import ResearchRunConfig

TOKEN = "k" * 48
HEADERS = {"Authorization": "Bearer " + TOKEN}
REQUEST = {
    "exchange": "binance", "market": "futures_um", "symbol": "BTCUSDT",
    "period_start": "2025-01-01T00:00:00Z",
    "period_end": "2025-01-02T00:00:00Z",
    "strategy_timeframe": "4h", "intrabar_timeframe": "1m",
}


def test_http_untrusted_native_output_destination_is_overridden_before_run(tmp_path, monkeypatch):
    import crypto_strategy_lab.data_lake_config as schema

    approved = tmp_path / "approved"
    approved.mkdir()
    forged = tmp_path / "forged"
    config = ResearchRunConfig()
    config = replace(config, reporting=replace(config.reporting, output_dir=str(forged)))
    monkeypatch.setattr(schema, "normalize_data_lake_config", lambda _: config)

    service = Mock()
    service.run.return_value = "native completed"
    integration = BrowserGuardedIntegration(
        service, tmp_path, enabled=True, execution_root=approved,
    )
    app = create_browser_app(token=TOKEN, guarded_integration=integration, guarded_enabled=True)
    try:
        with TestClient(app, base_url="http://localhost") as client:
            response = client.post("/api/v1/guarded/jobs", headers=HEADERS, json={
                "request_id": "confined", "request": REQUEST, "config": {"reporting": {"output_dir": str(forged)}},
            })
            assert response.status_code == 202
            assert integration._jobs.result("confined").result(timeout=10) == "native completed"
        assert service.run.call_args.args[1].reporting.output_dir == str(approved)
        assert config.reporting.output_dir == str(forged)
        assert not forged.exists()
    finally:
        integration.close()


def test_http_missing_approved_root_never_starts_native_execution(tmp_path, monkeypatch):
    import crypto_strategy_lab.data_lake_config as schema

    monkeypatch.setattr(schema, "normalize_data_lake_config", lambda _: ResearchRunConfig())
    service = Mock()
    integration = BrowserGuardedIntegration(
        service, tmp_path, enabled=True, execution_root=tmp_path / "missing",
    )
    app = create_browser_app(token=TOKEN, guarded_integration=integration, guarded_enabled=True)
    try:
        with TestClient(app, base_url="http://localhost") as client:
            response = client.post("/api/v1/guarded/jobs", headers=HEADERS, json={
                "request_id": "rejected", "request": REQUEST, "config": {},
            })
            assert response.status_code == 409
            assert response.json() == {"detail": "Job submission rejected"}
        service.run.assert_not_called()
        assert not (tmp_path / "missing").exists()
    finally:
        integration.close()
