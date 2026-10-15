from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from crypto_strategy_lab.browser_launcher import build_browser_readonly_runtime


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
