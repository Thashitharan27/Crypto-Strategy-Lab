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


def test_browser_composition_reuses_gui_application_service(tmp_path):
    raw = tmp_path / "raw"
    cache = tmp_path / "cache"
    with patch("crypto_strategy_lab.browser_readonly_service.GuiApplicationService") as app_cls:
        catalog = Mock()
        app_cls.return_value.catalog = catalog
        from crypto_strategy_lab.browser_readonly_service import build_browser_readonly_service

        service = build_browser_readonly_service(raw_root=raw, cache_root=cache)

    app_cls.assert_called_once_with(raw, cache)
    assert service._catalog is catalog
    catalog.refresh_catalog.assert_not_called()


def test_portfolio_candidates_project_existing_discovery_without_leaking_local_paths(tmp_path):
    """The browser receives only approved metadata, never internal artifact paths."""
    source = [{
        "run_id": "BTCUSDT_4h_verified",
        "symbol": "BTCUSDT",
        "strategy_timeframe": "4h",
        "candidate_rows": 79,
        "completed_at": "2026-10-15T00:00:00Z",
        "sampling_mode": "EVERY_VIABLE_ENTRY",
        "run_dir": str(tmp_path / "private-run"),
        "samples_path": str(tmp_path / "private-run" / "samples.parquet"),
        "manifest_sha256": "internal",
    }]
    expected = [{
        "run_id": "BTCUSDT_4h_verified",
        "symbol": "BTCUSDT",
        "strategy_timeframe": "4h",
        "candidate_rows": 79,
        "completed_at": "2026-10-15T00:00:00Z",
        "sampling_mode": "EVERY_VIABLE_ENTRY",
    }]
    from crypto_strategy_lab import portfolio_replay
    with patch.object(portfolio_replay, "discover_resilience_runs", return_value=source) as discover:
        result = BrowserReadOnlyService(catalog=None).portfolio_candidates(tmp_path)
    discover.assert_called_once_with(tmp_path)
    assert result == expected
    assert result is not source
    assert source[0]["samples_path"].endswith("samples.parquet")


def test_portfolio_candidates_preserve_empty_discovery_without_side_effects(tmp_path):
    from crypto_strategy_lab import portfolio_replay
    with patch.object(portfolio_replay, "discover_resilience_runs", return_value=[]) as discover:
        result = BrowserReadOnlyService(catalog=None).portfolio_candidates(tmp_path)
    assert result == []
    discover.assert_called_once_with(tmp_path)
