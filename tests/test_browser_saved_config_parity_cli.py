"""Regression tests for the read-only existing-file parity CLI."""
import json

from crypto_strategy_lab.browser_saved_config_parity import check, main
from crypto_strategy_lab.data_lake_config import ResearchRunConfig


def test_real_file_parity_preserves_exact_bytes(tmp_path):
    path = tmp_path / "actual_saved.json"
    config = ResearchRunConfig()
    path.write_text(json.dumps(config.to_dict()), encoding="utf-8")
    before = path.read_bytes()
    result = check(path)
    assert result["pass"] is True
    assert result["exact_match"] is True
    assert result["source_unchanged"] is True
    assert result["native_sha256"] == result["browser_reader_sha256"]
    assert path.read_bytes() == before
    assert main([str(path)]) == 0


def test_real_file_parity_rejects_invalid_input(tmp_path, capsys):
    path = tmp_path / "invalid.json"
    path.write_text("{invalid", encoding="utf-8")
    before = path.read_bytes()
    assert main([str(path)]) == 1
    output = capsys.readouterr().out
    assert '"pass": false' in output
    assert path.read_bytes() == before
