from unittest.mock import Mock, patch

import pytest

from crypto_strategy_lab.browser_visualizer_adapter import load_browser_visualizer


def test_browser_visualizer_reuses_verified_completed_run_and_model(tmp_path):
    run_id = "BTCUSDT_4h_verified"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    service = Mock()
    manifest = {"run_id": run_id, "run_status": "COMPLETED"}
    service.completed_runs.read.return_value = (manifest, {"net_pnl": 0})
    model = Mock()

    with patch(
        "crypto_strategy_lab.browser_visualizer_adapter.CompletedRunVisualizer.load",
        return_value=model,
    ) as load:
        result = load_browser_visualizer(service, tmp_path, run_id)

    assert result is model
    service.completed_runs.read.assert_called_once_with(run_dir.resolve())
    load.assert_called_once_with(service, run_dir.resolve(), manifest)


@pytest.mark.parametrize("bad", [
    "../other", "/tmp/other", "folder/child", "folder\\child", "", "a" * 101,
    "space in name", "🚀",
])
def test_browser_visualizer_rejects_invalid_run_ids(tmp_path, bad):
    service = Mock()
    with pytest.raises(ValueError, match="Invalid completed run ID"):
        load_browser_visualizer(service, tmp_path, bad)
    service.completed_runs.read.assert_not_called()


def test_browser_visualizer_rejects_missing_run(tmp_path):
    service = Mock()
    with pytest.raises(ValueError, match="Completed run not found"):
        load_browser_visualizer(service, tmp_path, "missing")
    service.completed_runs.read.assert_not_called()


def test_browser_visualizer_rejects_symlinked_run(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "runs"
    root.mkdir()
    try:
        (root / "BTCUSDT_4h").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported on this platform")
    service = Mock()
    with pytest.raises(ValueError, match="Symlinked"):
        load_browser_visualizer(service, root, "BTCUSDT_4h")
    service.completed_runs.read.assert_not_called()


def test_browser_visualizer_rejects_invalid_manifest_without_loading_model(tmp_path):
    (tmp_path / "BTCUSDT_4h").mkdir()
    service = Mock()
    service.completed_runs.read.side_effect = ValueError("Unverified artifact")
    with patch(
        "crypto_strategy_lab.browser_visualizer_adapter.CompletedRunVisualizer.load"
    ) as load:
        with pytest.raises(ValueError, match="Unverified artifact"):
            load_browser_visualizer(service, tmp_path, "BTCUSDT_4h")
    load.assert_not_called()
