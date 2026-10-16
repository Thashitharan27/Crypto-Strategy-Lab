from unittest.mock import Mock, patch

from crypto_strategy_lab.browser_readonly_service import BrowserReadOnlyService


def test_portfolio_candidates_reuses_verified_discovery_and_hides_paths(tmp_path):
    service = BrowserReadOnlyService(Mock())
    candidates = [{
        "run_id": "BTCUSDT_4h_test", "symbol": "BTCUSDT",
        "strategy_timeframe": "4h", "candidate_rows": 25,
        "completed_at": "2026-09-01", "sampling_mode": "EVERY_VIABLE_ENTRY",
        "run_dir": tmp_path / "private", "samples_path": tmp_path / "private.parquet",
        "execution_hash": "private_hash",
    }]
    with patch("crypto_strategy_lab.portfolio_replay.discover_resilience_runs", return_value=candidates) as discovered:
        rows = service.portfolio_candidates(tmp_path)
    discovered.assert_called_once_with(tmp_path)
    assert rows == [{
        "run_id": "BTCUSDT_4h_test", "symbol": "BTCUSDT",
        "run_folder_id": "private",
        "strategy_timeframe": "4h", "candidate_rows": 25,
        "completed_at": "2026-09-01", "sampling_mode": "EVERY_VIABLE_ENTRY",
    }]
    assert "run_dir" not in rows[0]
    service._catalog.refresh_catalog.assert_not_called()
