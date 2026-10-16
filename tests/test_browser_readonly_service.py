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


def test_portfolio_discovery_skips_linked_directories_outside_root(tmp_path, monkeypatch):
    """Follow the shared discovery path but never inspect linked external runs."""
    import pytest
    from crypto_strategy_lab import portfolio_replay

    root = tmp_path / "output"
    root.mkdir()
    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "run_manifest.json").write_text("{}", encoding="utf-8")
    ordinary = root / "ordinary_run"
    ordinary.mkdir()
    (ordinary / "run_manifest.json").write_text("{}", encoding="utf-8")
    try:
        (root / "linked_private").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Directory symlinks unavailable: {type(exc).__name__}")

    inspected = []

    def inspect(path):
        inspected.append(path)
        return {"run_id": path.name, "symbol": "BTCUSDT", "completed_at": "2026-10-16"}

    monkeypatch.setattr(portfolio_replay, "inspect_resilience_run", inspect)
    result = portfolio_replay.discover_resilience_runs(root)
    assert [row["run_id"] for row in result] == ["ordinary_run"]
    assert inspected == [ordinary]

    # Simulate Windows junction semantics: the link may not report is_symlink.
    # The resolved-parent containment check must still exclude its target.
    from pathlib import Path
    real_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path, "is_symlink",
        lambda path: False if path.name == "linked_private" else real_is_symlink(path),
    )
    inspected.clear()
    rows = portfolio_replay.discover_resilience_runs(root)
    assert [row["run_id"] for row in rows] == ["ordinary_run"]
    assert inspected == [ordinary]


def test_portfolio_discovery_skips_unresolvable_entry_and_keeps_valid_runs(tmp_path, monkeypatch):
    """A single denied directory resolution must not turn the whole GET into 503."""
    from pathlib import Path
    from crypto_strategy_lab import portfolio_replay

    root = tmp_path / "output"
    root.mkdir()
    bad = root / "unreadable"
    good = root / "ordinary_run"
    for item in (bad, good):
        item.mkdir()
        (item / "run_manifest.json").write_text("{}", encoding="utf-8")

    original_resolve = Path.resolve

    def blocked_resolve(path, *args, **kwargs):
        if path == bad:
            raise OSError("simulated access denied")
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", blocked_resolve)
    inspected = []

    def inspect(path):
        inspected.append(path)
        return {"run_id": path.name, "symbol": "BTCUSDT", "completed_at": "2026-10-16"}

    monkeypatch.setattr(portfolio_replay, "inspect_resilience_run", inspect)
    rows = portfolio_replay.discover_resilience_runs(root)
    assert [row["run_id"] for row in rows] == ["ordinary_run"]
    assert inspected == [good]
