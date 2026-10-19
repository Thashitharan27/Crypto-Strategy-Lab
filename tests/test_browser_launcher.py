from pathlib import Path
import sys
from unittest.mock import ANY, Mock, patch

import pytest

from crypto_strategy_lab.browser_launcher import (
    BrowserReadOnlyRuntime,
    build_browser_readonly_runtime,
    run_browser_readonly,
)


def _static_dist(root: Path) -> Path:
    root.mkdir()
    (root / "index.html").write_text("<!doctype html><title>CSL</title>", encoding="utf-8")
    return root


def test_launcher_composes_existing_read_service_and_http_app(tmp_path):
    static_root = _static_dist(tmp_path / "dist")
    output_root = tmp_path / "output"
    config_root = tmp_path / "configs"
    output_root.mkdir()
    config_root.mkdir()
    token = "t" * 48
    service = Mock()
    app = Mock()

    with (
        patch(
            "crypto_strategy_lab.browser_launcher.build_browser_readonly_service",
            return_value=service,
        ) as build_service,
        patch(
            "crypto_strategy_lab.browser_launcher.create_browser_app",
            return_value=app,
        ) as create_app,
    ):
        runtime = build_browser_readonly_runtime(
            environ={
                "CRYPTO_STRATEGY_LAB_RAW_ROOT": str(tmp_path / "raw"),
                "CRYPTO_STRATEGY_LAB_CACHE_DIR": str(tmp_path / "cache"),
            },
            token=token,
            port=9123,
            static_root=static_root,
            output_root=output_root,
            config_root=config_root,
        )

    build_service.assert_called_once_with(
        raw_root=tmp_path / "raw",
        cache_root=tmp_path / "cache",
    )
    create_app.assert_called_once_with(
        token=token,
        read_service=service,
        completed_run_root=output_root,
        config_root=config_root,
        static_root=static_root,
        visualizer_coordinator=ANY,
    )
    assert runtime.app is app
    assert runtime.host == "127.0.0.1"
    assert runtime.port == 9123
    assert runtime.url == "http://127.0.0.1:9123/"
    assert runtime.token == token


def test_launcher_reuses_existing_output_and_config_environment_contract(tmp_path):
    static_root = _static_dist(tmp_path / "dist")
    output_root = tmp_path / "shared-output"
    config_root = tmp_path / "shared-configs"
    output_root.mkdir()
    config_root.mkdir()

    with (
        patch(
            "crypto_strategy_lab.browser_launcher.build_browser_readonly_service",
            return_value=Mock(),
        ),
        patch(
            "crypto_strategy_lab.browser_launcher.create_browser_app",
            return_value=Mock(),
        ),
    ):
        runtime = build_browser_readonly_runtime(
            environ={
                "CRYPTO_STRATEGY_LAB_RAW_ROOT": str(tmp_path / "raw"),
                "CRYPTO_STRATEGY_LAB_CACHE_DIR": str(tmp_path / "cache"),
                "CRYPTO_STRATEGY_LAB_OUTPUT_DIR": str(output_root),
                "CRYPTO_STRATEGY_LAB_CONFIG_DIR": str(config_root),
            },
            token="e" * 48,
            static_root=static_root,
        )

    assert runtime.output_root == output_root.resolve()
    assert runtime.config_root == config_root.resolve()


@pytest.mark.parametrize("port", [0, 65536, True, 1.5])
def test_launcher_rejects_invalid_ports(port, tmp_path):
    with pytest.raises(ValueError):
        build_browser_readonly_runtime(
            port=port,
            token="p" * 48,
            static_root=tmp_path,
        )



def test_run_browser_binds_uvicorn_to_loopback_only(capsys):
    app = Mock()
    runtime = BrowserReadOnlyRuntime(
        app=app,
        token="s" * 48,
        host="127.0.0.1",
        port=8767,
        static_root=Path("/static"),
        output_root=Path("/output"),
        config_root=Path("/config"),
    )
    uvicorn = Mock()

    with (
        patch(
            "crypto_strategy_lab.browser_launcher.build_browser_readonly_runtime",
            return_value=runtime,
        ),
        patch.dict(sys.modules, {"uvicorn": uvicorn}),
    ):
        run_browser_readonly(port=8767)

    uvicorn.run.assert_called_once_with(
        app,
        host="127.0.0.1",
        port=8767,
        log_level="info",
    )
    output = capsys.readouterr().out
    assert "http://127.0.0.1:8767/" in output
    assert runtime.token in output
    assert runtime.token not in runtime.url


def test_launcher_real_app_serves_static_and_authorized_read_only_api(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    static_root = _static_dist(tmp_path / "dist")
    output_root = tmp_path / "output"
    config_root = tmp_path / "configs"
    output_root.mkdir()
    config_root.mkdir()
    service = Mock()
    service.symbols.return_value = ["BTCUSDT"]
    token = "a" * 48

    with patch(
        "crypto_strategy_lab.browser_launcher.build_browser_readonly_service",
        return_value=service,
    ):
        runtime = build_browser_readonly_runtime(
            environ={},
            token=token,
            static_root=static_root,
            output_root=output_root,
            config_root=config_root,
        )

    with TestClient(runtime.app, base_url="http://127.0.0.1:8767") as client:
        shell = client.get("/")
        assert shell.status_code == 200
        assert "CSL" in shell.text
        assert client.get("/api/v1/health").status_code == 401
        auth = {"Authorization": "Bearer " + token}
        assert client.get("/api/v1/health", headers=auth).json() == {
            "status": "ok", "mode": "read-only"
        }
        assert client.get("/api/v1/catalog/symbols", headers=auth).json() == {
            "symbols": ["BTCUSDT"]
        }
        assert client.post("/api/v1/catalog/symbols", headers=auth).status_code == 405
        assert client.get(
            "/api/v1/health",
            headers={**auth, "Host": "outside.example"},
        ).status_code == 403

    service.symbols.assert_called_once_with("futures_um")


def test_default_completed_run_root_matches_canonical_desktop_reporting(tmp_path):
    from crypto_strategy_lab.paths import OUTPUT_DIR
    with (
        patch("crypto_strategy_lab.browser_launcher.build_browser_readonly_service", return_value=Mock()),
        patch("crypto_strategy_lab.browser_launcher.create_browser_app", return_value=Mock()) as factory,
    ):
        runtime = build_browser_readonly_runtime(environ={}, token="d" * 48, static_root=tmp_path)
    assert runtime.output_root == (OUTPUT_DIR / "data_lake_v2").resolve()
    assert factory.call_args.kwargs["completed_run_root"] == OUTPUT_DIR / "data_lake_v2"


def test_launcher_portfolio_endpoint_uses_configured_root_and_auth(tmp_path):
    """The composed browser launcher must preserve Portfolio's fixed read boundary."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    static_root = _static_dist(tmp_path / "dist")
    output_root = tmp_path / "completed"
    config_root = tmp_path / "configs"
    output_root.mkdir()
    config_root.mkdir()
    service = Mock()
    service.portfolio_candidates.return_value = [{
        "run_id": "BTCUSDT_4h_frozen",
        "symbol": "BTCUSDT",
        "candidate_rows": 3,
        "sampling_mode": "EVERY_VIABLE_ENTRY",
    }]
    token = "p" * 48
    with patch(
        "crypto_strategy_lab.browser_launcher.build_browser_readonly_service",
        return_value=service,
    ):
        runtime = build_browser_readonly_runtime(
            environ={}, token=token, static_root=static_root,
            output_root=output_root, config_root=config_root,
        )

    with TestClient(runtime.app, base_url="http://127.0.0.1:8767") as client:
        assert client.get("/api/v1/portfolio/candidates").status_code == 401
        authorized = client.get(
            "/api/v1/portfolio/candidates",
            headers={"Authorization": "Bearer " + token},
        )
        assert authorized.status_code == 200
        assert authorized.json() == {"candidates": service.portfolio_candidates.return_value}
        assert client.post(
            "/api/v1/portfolio/candidates",
            headers={"Authorization": "Bearer " + token},
        ).status_code == 405
    service.portfolio_candidates.assert_called_once_with(output_root.resolve())


@pytest.mark.parametrize("release_request", [True, 1, "true", None])
def test_b4_explicit_production_guarded_request_denied_before_composition(tmp_path, release_request):
    """A release proposal is not a server-side release authorization."""
    with (
        patch("crypto_strategy_lab.browser_launcher.build_browser_readonly_service") as service,
        patch("crypto_strategy_lab.browser_launcher.create_browser_app") as factory,
    ):
        with pytest.raises(PermissionError, match="separate release approval"):
            build_browser_readonly_runtime(
                environ={},
                token="g" * 48,
                static_root=tmp_path,
                guarded_release_requested=release_request,
            )
    service.assert_not_called()
    factory.assert_not_called()


def test_b4_environment_cannot_activate_guarded_production_routes(tmp_path):
    """Feature-like environment toggles have no authority in production."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    static_root = _static_dist(tmp_path / "dist")
    output = tmp_path / "output"
    configs = tmp_path / "configs"
    output.mkdir()
    configs.mkdir()
    token = "b" * 48
    environ = {
        "CSL_BROWSER_GUARDED_ENABLED": "true",
        "CRYPTO_STRATEGY_LAB_BROWSER_GUARDED_ENABLED": "1",
        "CRYPTO_STRATEGY_LAB_BROWSER_RELEASE_APPROVED": "true",
    }
    with patch("crypto_strategy_lab.browser_launcher.build_browser_readonly_service", return_value=Mock()):
        runtime = build_browser_readonly_runtime(
            environ=environ, token=token, static_root=static_root,
            output_root=output, config_root=configs,
        )
    auth = {"Authorization": "Bearer " + token}
    with TestClient(runtime.app, base_url="http://127.0.0.1:8767") as client:
        assert client.get("/api/v1/health", headers=auth).json()["mode"] == "read-only"
        for method, path in (
            ("POST", "/api/v1/guarded/jobs"),
            ("PUT", "/api/v1/guarded/configs/safe"),
            ("GET", "/api/v1/guarded/jobs/safe"),
        ):
            assert client.request(method, path, headers=auth).status_code == 404


@pytest.mark.parametrize("use_alias", [False, True])
def test_production_launcher_rejects_certification_bundle_before_service(tmp_path, use_alias):
    """Only the separately opted-in certification server may serve this UI."""
    dedicated = tmp_path / "dist-certification"
    dedicated.mkdir()
    (dedicated / "index.html").write_text("certification only", encoding="utf-8")
    selected = dedicated
    if use_alias:
        selected = tmp_path / "production-alias"
        try:
            selected.symlink_to(dedicated, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("Filesystem directory links unavailable")
    with (
        patch("crypto_strategy_lab.browser_launcher.build_browser_readonly_service") as service,
        patch("crypto_strategy_lab.browser_launcher.create_browser_app") as factory,
    ):
        with pytest.raises(ValueError, match="Certification-only browser assets"):
            build_browser_readonly_runtime(
                environ={}, token="s" * 48, static_root=selected,
            )
    service.assert_not_called()
    factory.assert_not_called()
    assert (dedicated / "index.html").read_text(encoding="utf-8") == "certification only"


def test_b4_review_composition_cannot_serve_certification_ui(tmp_path):
    from crypto_strategy_lab.browser_release_composition import compose_b4_review_only
    asset = tmp_path / "dist-certification"
    config = tmp_path / "new-config"
    runs = tmp_path / "new-runs"
    for root in (asset, config, runs):
        root.mkdir()
    (asset / "index.html").write_text("certification only", encoding="utf-8")
    with (
        patch("crypto_strategy_lab.browser_launcher.build_browser_readonly_service") as service,
        patch("crypto_strategy_lab.browser_launcher.create_browser_app") as factory,
    ):
        with pytest.raises(ValueError, match="Certification-only browser assets"):
            compose_b4_review_only(
                configuration=config, execution=runs, static_root=asset,
                environ={
                    "CRYPTO_STRATEGY_LAB_RAW_ROOT": str(tmp_path / "raw"),
                    "CRYPTO_STRATEGY_LAB_CACHE_DIR": str(tmp_path / "cache"),
                }, token="r" * 48,
            )
    service.assert_not_called()
    factory.assert_not_called()
    assert not list(config.iterdir())
    assert not list(runs.iterdir())


def test_b4_authenticated_release_capabilities_remain_hard_off_in_production(tmp_path):
    """The production API advertises no execution/editing despite env claims."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    static_root = _static_dist(tmp_path / "dist")
    output = tmp_path / "output"
    configs = tmp_path / "configs"
    output.mkdir()
    configs.mkdir()
    with patch("crypto_strategy_lab.browser_launcher.build_browser_readonly_service", return_value=Mock()):
        runtime = build_browser_readonly_runtime(
            environ={
                "CRYPTO_STRATEGY_LAB_BROWSER_RELEASE_APPROVED": "true",
                "CRYPTO_STRATEGY_LAB_BROWSER_GUARDED_ENABLED": "true",
            },
            token="a" * 48, static_root=static_root,
            output_root=output, config_root=configs,
        )
    with TestClient(runtime.app, base_url="http://127.0.0.1:8767") as client:
        endpoint = "/api/v1/release/capabilities"
        assert client.get(endpoint).status_code == 401
        assert client.get(endpoint, headers={"Authorization": "Bearer wrong"}).status_code == 401
        auth = {"Authorization": "Bearer " + "a" * 48}
        assert client.get(endpoint, headers=auth).json() == {
            "execution": False, "configuration_editing": False,
        }
        assert client.get(endpoint, headers={**auth, "Host": "remote.example"}).status_code == 403
        for method, path in (
            ("POST", "/api/v1/guarded/jobs"),
            ("PUT", "/api/v1/guarded/configs/safe"),
        ):
            assert client.request(method, path, headers=auth).status_code == 404
