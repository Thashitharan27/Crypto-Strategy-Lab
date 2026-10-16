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


def test_batch_parity_keeps_valid_sources_unchanged_when_other_fixture_fails(tmp_path, capsys):
    """A failed configuration must not be disguised by an earlier PASS."""
    valid = tmp_path / "valid.json"
    invalid = tmp_path / "invalid.json"
    valid.write_text(json.dumps(ResearchRunConfig().to_dict(), allow_nan=False), encoding="utf-8")
    invalid.write_text("{broken", encoding="utf-8")
    before_valid, before_invalid = valid.read_bytes(), invalid.read_bytes()

    assert main([str(valid), str(invalid)]) == 1
    results = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(results) == 2
    assert results[0]["pass"] is True
    assert results[0]["exact_match"] is True
    assert results[1]["pass"] is False
    assert results[1]["error_type"]
    assert "native_sha256" not in results[1]
    assert valid.read_bytes() == before_valid
    assert invalid.read_bytes() == before_invalid


def test_saved_config_http_parity_uses_authenticated_route_and_preserves_bytes(tmp_path, capsys):
    import pytest
    pytest.importorskip("fastapi")
    from crypto_strategy_lab.browser_saved_config_parity import check_http

    path = tmp_path / "frozen_v3.json"
    path.write_text(json.dumps(ResearchRunConfig().to_dict()), encoding="utf-8")
    original = path.read_bytes()
    report = check_http(path)
    assert report["pass"] is True
    assert report["auth_rejected"] is True
    assert report["exact_match"] is True
    assert report["native_sha256"] == report["browser_reader_sha256"] == report["browser_http_sha256"]
    assert path.read_bytes() == original
    assert main(["--http", str(path)]) == 0
    assert "Bearer" not in capsys.readouterr().out
    assert path.read_bytes() == original


def test_saved_config_http_parity_fails_closed_for_invalid_ids(tmp_path):
    import pytest
    pytest.importorskip("fastapi")
    from crypto_strategy_lab.browser_saved_config_parity import check_http

    path = tmp_path / "not allowed.json"
    path.write_text(json.dumps(ResearchRunConfig().to_dict()), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="allowed browser ID"):
        check_http(path)
    assert main(["--http", str(path)]) == 1
    assert path.read_bytes() == before


def test_saved_config_http_rejects_json_scalar_type_drift_even_when_python_equal(tmp_path, monkeypatch):
    import pytest
    pytest.importorskip("fastapi")
    from crypto_strategy_lab.browser_saved_config_parity import check_http
    from crypto_strategy_lab import browser_http

    path = tmp_path / "native_v3.json"
    path.write_text(json.dumps(ResearchRunConfig().to_dict(), allow_nan=False), encoding="utf-8")
    before = path.read_bytes()
    original = browser_http.create_browser_app

    def mutating_app(*, read_service, **kwargs):
        canonical = read_service.research_config

        def typed_drift(selected):
            result = canonical(selected)
            # JSON True and 1 are different types even though Python calls them equal.
            result["features"]["fib_candle_confirmation_enabled"] = 1
            return result

        read_service.research_config = typed_drift
        return original(read_service=read_service, **kwargs)

    monkeypatch.setattr(browser_http, "create_browser_app", mutating_app)
    report = check_http(path)
    assert report["auth_rejected"] is True
    assert report["native_sha256"] != report["browser_http_sha256"]
    assert report["exact_match"] is False
    assert report["pass"] is False
    assert path.read_bytes() == before


def test_saved_config_http_rejects_browser_reader_drift_even_if_http_matches_native(tmp_path, monkeypatch):
    """Three-way certification must not silently skip the browser reader."""
    import pytest
    pytest.importorskip("fastapi")
    from crypto_strategy_lab import browser_saved_config_parity as parity

    path = tmp_path / "original_v3.json"
    path.write_text(json.dumps(ResearchRunConfig().to_dict(), allow_nan=False), encoding="utf-8")
    before = path.read_bytes()
    original_reader = parity.read_research_config

    def drifted_reader(selected):
        result = original_reader(selected)
        result["features"]["fib_candle_confirmation_enabled"] = 1
        return result

    monkeypatch.setattr(parity, "read_research_config", drifted_reader)
    report = parity.check_http(path)
    assert report["auth_rejected"] is True
    assert report["native_sha256"] == report["browser_http_sha256"]
    assert report["browser_reader_sha256"] != report["native_sha256"]
    assert report["exact_match"] is False
    assert report["pass"] is False
    assert path.read_bytes() == before
