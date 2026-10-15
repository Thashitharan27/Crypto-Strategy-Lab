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
