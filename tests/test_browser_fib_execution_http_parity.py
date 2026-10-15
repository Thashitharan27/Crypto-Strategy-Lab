"""Fibonacci and execution settings must survive authorized browser HTTP without mutation."""
from dataclasses import replace
import json

import pytest

from crypto_strategy_lab.browser_config import read_research_config
from crypto_strategy_lab.browser_http import create_browser_app
from crypto_strategy_lab.data_lake_config import ResearchRunConfig


def test_fibonacci_execution_profiles_authorized_http_parity(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    base = ResearchRunConfig()
    saved = replace(
        base,
        features=replace(base.features, fib_third_retest_entry=True,
                         fib_candle_confirmation_enabled=True, fib_candle_engulfing=False),
        execution=replace(base.execution, ema_320_flip_signals=True,
                          ema_cross_entry_confirmation_enabled=True),
    )
    saved.validate()
    root = tmp_path / "configs"
    root.mkdir()
    path = root / "fibonacci_execution.json"
    path.write_text(json.dumps(saved.to_dict(), allow_nan=False), encoding="utf-8")
    before = path.read_bytes()
    expected = read_research_config(path)

    class Reader:
        def research_config(self, selected):
            assert selected == path.resolve()
            return read_research_config(selected)

    token = "c" * 48
    with TestClient(create_browser_app(token=token, read_service=Reader(), config_root=root), base_url="http://localhost") as client:
        url = "/api/v1/configs/fibonacci_execution"
        assert client.get(url).status_code == 401
        reply = client.get(url, headers={"Authorization": "Bearer " + token})
        assert reply.status_code == 200
        actual = reply.json()["config"]
    assert actual == expected == saved.to_dict()
    assert actual["features"]["fib_third_retest_entry"] is True
    assert actual["execution"]["ema_cross_entry_confirmation_enabled"] is True
    assert actual["strategy"]["profiles"] == expected["strategy"]["profiles"]
    assert actual["execution"]["profiles"] == expected["execution"]["profiles"]
    assert path.read_bytes() == before
