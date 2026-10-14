import pytest
from crypto_strategy_lab.browser_http import create_browser_app

def test_same_origin_static_shell_respects_host_guard(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    (tmp_path / "index.html").write_text("<!doctype html><title>Read-only CSL</title>")
    app = create_browser_app(token="a" * 48, static_root=tmp_path)
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/").status_code == 200
        assert client.get("/").headers["cache-control"] == "no-store"
        assert client.get("/", headers={"Host": "remote.invalid"}).status_code == 403
        assert client.post("/").status_code == 405
        assert client.get("/api/v1/health").status_code == 401

def test_static_host_rejects_missing_distribution(tmp_path):
    pytest.importorskip("fastapi")
    with pytest.raises(ValueError):
        create_browser_app(token="a" * 48, static_root=tmp_path)
