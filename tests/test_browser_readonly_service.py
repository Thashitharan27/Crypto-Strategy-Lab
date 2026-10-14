from unittest.mock import Mock, patch

from crypto_strategy_lab.browser_readonly_service import BrowserReadOnlyService


def test_readonly_service_reuses_existing_catalog_and_readers(tmp_path):
    catalog = Mock()
    catalog.symbols.return_value = ["BTCUSDT"]
    catalog.coverage.return_value = [{"state": "AVAILABLE"}]
    service = BrowserReadOnlyService(catalog)
    request = object()
    assert service.symbols() == ["BTCUSDT"]
    assert service.coverage(request) == [{"state": "AVAILABLE"}]
    catalog.symbols.assert_called_once_with("futures_um")
    catalog.coverage.assert_called_once_with(request)
    with patch("crypto_strategy_lab.browser_readonly_service.read_completed_run", return_value={"summary": {}}) as completed:
        assert service.completed_run(tmp_path) == {"summary": {}}
        completed.assert_called_once_with(tmp_path)
    with patch("crypto_strategy_lab.browser_readonly_service.read_research_config", return_value={"config_version": 3}) as config:
        assert service.research_config(tmp_path / "cfg.json") == {"config_version": 3}
        config.assert_called_once_with(tmp_path / "cfg.json")
    catalog.refresh_catalog.assert_not_called()
