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


def test_config_endpoint_rejects_reparse_like_alias_to_nested_file(tmp_path, monkeypatch):
    """A browser config ID cannot resolve into a nested or redirected file."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from pathlib import Path

    root = tmp_path / "configs"
    nested = root / "nested"
    nested.mkdir(parents=True)
    source = nested / "existing.json"
    source.write_text('{"config_version": 3}', encoding="utf-8")
    alias = root / "alias.json"
    try:
        alias.symlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("File symlinks unavailable on this platform")

    original_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path, "is_symlink",
        lambda path: False if path == alias else original_is_symlink(path),
    )
    service = Mock()
    token = "a" * 48
    with TestClient(
        create_browser_app(token=token, read_service=service, config_root=root),
        base_url="http://localhost",
    ) as client:
        response = client.get(
            "/api/v1/configs/alias",
            headers={"Authorization": "Bearer " + token},
        )
    assert response.status_code == 404
    service.research_config.assert_not_called()
    assert source.read_text(encoding="utf-8") == '{"config_version": 3}'
