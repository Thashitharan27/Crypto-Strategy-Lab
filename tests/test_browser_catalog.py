from unittest.mock import Mock

from crypto_strategy_lab.browser_catalog import catalog_coverage, catalog_symbols


def test_catalog_symbols_delegates_existing_catalog_reader():
    catalog = Mock()
    catalog.symbols.return_value = ["BTCUSDT", "ETHUSDT"]
    assert catalog_symbols(catalog, "futures_um") == ["BTCUSDT", "ETHUSDT"]
    catalog.symbols.assert_called_once_with("futures_um")


def test_catalog_coverage_delegates_without_refresh():
    catalog = Mock()
    request = object()
    coverage = [{"symbol": "BTCUSDT", "state": "AVAILABLE"}]
    catalog.coverage.return_value = coverage
    assert catalog_coverage(catalog, request) is coverage
    catalog.coverage.assert_called_once_with(request)
    catalog.refresh_catalog.assert_not_called()
