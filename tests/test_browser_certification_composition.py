"""Isolated certification composition must never reuse original writable roots."""
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from crypto_strategy_lab.browser_certification import isolated_browser_certification
from crypto_strategy_lab.browser_http import create_browser_app

TOKEN = "c" * 48


def _certification_dist(tmp_path: Path) -> Path:
    path = tmp_path / "dist-certification"
    path.mkdir()
    (path / "index.html").write_text("<h1>Certification only</h1>", encoding="utf-8")
    return path


def test_certification_requires_opt_in_separate_bundle_and_native_owner(tmp_path):
    dist = _certification_dist(tmp_path)
    native = Mock()
    with pytest.raises(PermissionError, match="opt-in"):
        with isolated_browser_certification(native_application=native, static_root=dist):
            pytest.fail("Disabled certification never constructs an app")
    with pytest.raises(ValueError, match="separate certification"):
        with isolated_browser_certification(native_application=native,
                                            static_root=tmp_path, acknowledge_test_only=True):
            pytest.fail("Production dist rejected")
    with pytest.raises(ValueError, match="native application"):
        with isolated_browser_certification(native_application=None,
                                            static_root=dist, acknowledge_test_only=True):
            pytest.fail("Native owner required")
    native.run.assert_not_called()


def test_certification_uses_ephemeral_roots_and_authenticated_native_http(tmp_path, monkeypatch):
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig
    from types import SimpleNamespace

    dist = _certification_dist(tmp_path)
    original_config_root = tmp_path / "original-configs"
    original_run_root = tmp_path / "original-runs"
    original_config_root.mkdir()
    original_run_root.mkdir()
    (original_config_root / "do-not-touch.json").write_bytes(b"unaltered")
    (original_run_root / "do-not-touch.bin").write_bytes(b"unaltered")
    original_config = (original_config_root / "do-not-touch.json").read_bytes()
    original_run = (original_run_root / "do-not-touch.bin").read_bytes()

    native = Mock()
    seen_output = []
    def run(request, config):
        seen_output.append(Path(config.reporting.output_dir))
        assert seen_output[-1].name == "runs"
        return SimpleNamespace(output_dir=None)
    native.run.side_effect = run

    with isolated_browser_certification(
        native_application=native, static_root=dist, acknowledge_test_only=True,
    ) as (app, token):
        assert token != TOKEN and len(token) >= 32
        guarded = next(route for route in app.routes
                       if getattr(route, "path", "") == "/api/v1/guarded/jobs")
        assert guarded is not None
        with TestClient(app, base_url="http://localhost") as client:
            assert client.get("/").status_code == 200
            assert client.post("/api/v1/guarded/jobs", json={}).status_code == 401
            headers = {"Authorization": "Bearer " + token}
            assert client.put("/api/v1/guarded/configs/test", json=ResearchRunConfig().to_dict(),
                              headers=headers).status_code == 200
            assert client.get("/api/v1/configs/test", headers=headers).status_code == 200
            payload = {
                "request_id": "cert-only",
                "request": {
                    "exchange": "binance", "market": "futures_um",
                    "symbol": "BTCUSDT",
                    "period_start": "2025-01-01T00:00:00Z",
                    "period_end": "2025-01-02T00:00:00Z",
                    "strategy_timeframe": "4h", "intrabar_timeframe": "1m",
                },
                "config": ResearchRunConfig().to_dict(),
            }
            response = client.post("/api/v1/guarded/jobs", json=payload, headers=headers)
            assert response.status_code == 202, response.text
            # Native work uses existing single guarded coordinator; a status
            # alone does not prove persisted artifact integrity.
        assert seen_output
        output = seen_output[0]
        assert output.parent.name.startswith("csl-browser-cert-")
        scratch = output.parent
    assert not scratch.exists()
    assert (original_config_root / "do-not-touch.json").read_bytes() == original_config
    assert (original_run_root / "do-not-touch.bin").read_bytes() == original_run
    native.run.assert_called_once()


def test_production_read_only_composition_still_has_no_guarded_routes():
    app = create_browser_app(token=TOKEN)
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/v1/guarded/jobs" not in paths
    assert not any(path and path.startswith("/api/v1/guarded/configs/")
                   for path in paths)


def test_certification_listener_is_explicitly_local_and_closes_ephemeral_roots(tmp_path, monkeypatch, capsys):
    from crypto_strategy_lab.browser_certification import (
        serve_isolated_browser_certification,
    )
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig
    from types import SimpleNamespace
    import uvicorn

    dist = _certification_dist(tmp_path)
    native = Mock()
    recorded = []

    def fake_run(app, **options):
        recorded.append(options)
        assert options["host"] == "127.0.0.1"
        assert options["port"] == 8917
        with TestClient(app, base_url="http://127.0.0.1:8917") as client:
            assert client.get("/").status_code == 200
            assert client.post("/api/v1/guarded/jobs", json={}).status_code == 401
            assert client.put("/api/v1/guarded/configs/valid", json={}).status_code == 401
        # Only the certification root is served; the native app is not executed.
        native.run.assert_not_called()

    monkeypatch.setattr(uvicorn, "run", fake_run)
    with pytest.raises(PermissionError):
        serve_isolated_browser_certification(
            native_application=native, static_root=dist, port=8917,
        )
    for invalid_port in (0, 65536, True, "8917"):
        with pytest.raises(ValueError):
            serve_isolated_browser_certification(
                native_application=native, static_root=dist,
                port=invalid_port, acknowledge_test_only=True,
            )
    serve_isolated_browser_certification(
        native_application=native, static_root=dist,
        port=8917, acknowledge_test_only=True,
    )
    assert len(recorded) == 1
    printed = capsys.readouterr().out
    assert "http://127.0.0.1:8917/" in printed
    assert "TEST ONLY" in printed
