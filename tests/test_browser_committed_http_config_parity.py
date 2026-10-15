"""HTTP parity regression using the committed BTCUSDT 4h native v3 fixture."""
from pathlib import Path

import pytest

from crypto_strategy_lab.browser_config import read_research_config
from crypto_strategy_lab.browser_http import create_browser_app


def test_committed_native_config_via_authorized_browser_http(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    source = Path(__file__).resolve().parents[1] / "config" / "data_lake" / "BTCUSDT_4H_SMOKE.json"
    root = tmp_path / "configs"
    root.mkdir()
    target = root / "btc_4h.json"
    target.write_bytes(source.read_bytes())
    before = target.read_bytes()
    expected = read_research_config(source)

    class Reader:
        def research_config(self, selected):
            assert selected == target.resolve()
            return read_research_config(selected)

    token = "b" * 48
    with TestClient(create_browser_app(token=token, read_service=Reader(), config_root=root), base_url="http://localhost") as client:
        assert client.get("/api/v1/configs/btc_4h").status_code == 401
        reply = client.get("/api/v1/configs/btc_4h", headers={"Authorization": "Bearer " + token})
        assert reply.status_code == 200
        assert reply.json()["config"] == expected
        assert reply.json()["config"]["data"]["strategy_timeframe_minutes"] == 240
    assert target.read_bytes() == before
    assert source.read_bytes() == before
