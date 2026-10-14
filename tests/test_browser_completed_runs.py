from unittest.mock import patch

from crypto_strategy_lab.browser_completed_runs import read_completed_run


def test_browser_boundary_uses_existing_verified_completed_run_reader(tmp_path):
    manifest = {"run_id": "existing-id"}
    summary = {"ending_equity": 1010}
    with patch("crypto_strategy_lab.browser_completed_runs.CompletedRunReader") as reader:
        reader.return_value.read.return_value = (manifest, summary)
        result = read_completed_run(tmp_path)
        reader.return_value.read.assert_called_once_with(tmp_path)
    assert result == {"manifest": manifest, "summary": summary}


def test_browser_boundary_propagates_manifest_validation_errors(tmp_path):
    import pytest
    with pytest.raises(Exception):
        read_completed_run(tmp_path / "does-not-exist")
