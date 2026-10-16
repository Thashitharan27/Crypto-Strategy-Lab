"""Read-only HTTP config route must preserve the exact native serialized snapshot."""
import json

import pytest

from crypto_strategy_lab.browser_config import read_research_config
from crypto_strategy_lab.browser_http import create_browser_app
from crypto_strategy_lab.data_lake_config import ResearchRunConfig


def test_authenticated_http_config_matches_native_reader_byte_safe(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    root = tmp_path / "configs"
    root.mkdir()
    path = root / "native_fixture.json"
    config = ResearchRunConfig()
    path.write_text(json.dumps(config.to_dict(), allow_nan=False), encoding="utf-8")
    before = path.read_bytes()
    expected = read_research_config(path)
    assert expected == config.to_dict()

    class Reader:
        def research_config(self, selected):
            assert selected == path.resolve()
            return read_research_config(selected)

    token = "f" * 48
    with TestClient(create_browser_app(token=token, read_service=Reader(), config_root=root), base_url="http://localhost") as client:
        endpoint = "/api/v1/configs/native_fixture"
        assert client.get(endpoint).status_code == 401
        response = client.get(endpoint, headers={"Authorization": "Bearer " + token})
        assert response.status_code == 200
        assert response.json()["config"] == expected
    assert path.read_bytes() == before


def test_http_preserves_fibonacci_flags_and_all_six_profiles(tmp_path):
    """Exercise historical feature fields and all regime profiles with no browser defaults."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from crypto_strategy_lab.data_lake_config import PROFILE_KEYS

    root = tmp_path / "configs"
    root.mkdir()
    path = root / "fib_snapshot.json"
    snapshot = ResearchRunConfig().to_dict()
    snapshot["features"]["fib_candle_confirmation_enabled"] = True
    snapshot["features"]["fib_first_zone_hold_entry"] = True
    snapshot["features"]["fib_candle_engulfing"] = False
    for index, profile in enumerate(PROFILE_KEYS):
        snapshot["strategy"]["profiles"][profile]["flip_direction"] = bool(index % 2)
        snapshot["execution"]["profiles"][profile]["reward_risk_ratio"] = float(index + 1)
    path.write_text(json.dumps(snapshot, allow_nan=False), encoding="utf-8")
    before = path.read_bytes()
    expected = read_research_config(path)

    class Reader:
        def research_config(self, selected):
            assert selected == path.resolve()
            return read_research_config(selected)

    token = "a" * 48
    with TestClient(create_browser_app(token=token, read_service=Reader(), config_root=root), base_url="http://localhost") as client:
        response = client.get("/api/v1/configs/fib_snapshot", headers={"Authorization": "Bearer " + token})
        assert response.status_code == 200
        actual = response.json()["config"]
        assert actual == expected
        for section in ("data", "features", "strategy", "execution"):
            assert actual[section] == expected[section]
        assert set(actual["strategy"]["profiles"]) == set(PROFILE_KEYS)
        assert set(actual["execution"]["profiles"]) == set(PROFILE_KEYS)
        for index, profile in enumerate(PROFILE_KEYS):
            assert actual["strategy"]["profiles"][profile]["flip_direction"] is bool(index % 2)
            assert actual["execution"]["profiles"][profile]["reward_risk_ratio"] == float(index + 1)
        assert actual["features"]["fib_candle_confirmation_enabled"] is True
        assert actual["features"]["fib_first_zone_hold_entry"] is True
        assert actual["features"]["fib_candle_engulfing"] is False
        serialized = json.dumps(actual, sort_keys=True, separators=(",", ":"), allow_nan=False)
        assert json.loads(serialized) == expected
    assert path.read_bytes() == before
