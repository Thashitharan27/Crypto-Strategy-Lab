from unittest.mock import Mock
import json
import pytest
from crypto_strategy_lab.browser_http import create_browser_app

def test_config_checks_auth_missing_ids_and_uses_canonical_reader(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    root = tmp_path / "configs"
    root.mkdir()
    (root / "valid.json").write_text('{"config_version": 3}', encoding="utf-8")
    service = Mock()
    service.research_config.return_value = {"version": 3}
    token = "d" * 48
    with TestClient(create_browser_app(token=token, read_service=service, config_root=root), base_url="http://localhost") as client:
        assert client.get("/api/v1/configs/valid").status_code == 401
        auth = {"Authorization": "Bearer " + token}
        assert client.get("/api/v1/configs/missing", headers=auth).status_code == 404
        assert client.get("/api/v1/configs/valid", headers=auth).json() == {"config": {"version": 3}}
    service.research_config.assert_called_once_with((root / "valid.json").resolve())
    assert json.loads((root / "valid.json").read_text()) == {"config_version": 3}
