"""The operator CLI must never implicitly enable production guarded routes."""
from pathlib import Path
from unittest.mock import Mock

import pytest

import crypto_strategy_lab.browser_certification_cli as command


def test_cli_fails_before_constructing_native_service_without_explicit_opt_in(monkeypatch, tmp_path):
    native_factory = Mock(side_effect=AssertionError("Native service must not initialize"))
    monkeypatch.setattr(command, "build_browser_readonly_service", native_factory)
    root = tmp_path / "dist-certification"
    for argv in (
        ["--static-root", str(root), "--port", "8919"],
        ["--acknowledge-test-only", "--static-root", str(tmp_path), "--port", "8919"],
        ["--acknowledge-test-only", "--static-root", str(root), "--port", "0"],
        ["--acknowledge-test-only", "--static-root", str(root), "--port", "65536"],
    ):
        with pytest.raises(SystemExit) as error:
            command.main(argv)
        assert error.value.code == 2
    native_factory.assert_not_called()


def test_cli_delegates_only_explicit_isolated_composition(monkeypatch, tmp_path):
    root = tmp_path / "dist-certification"
    root.mkdir()
    (root / "index.html").write_text("Certification only", encoding="utf-8")
    native = Mock()
    read_service = Mock()
    read_service.application_service = native
    factory = Mock(return_value=read_service)
    runner = Mock()
    monkeypatch.setattr(command, "build_browser_readonly_service", factory)
    monkeypatch.setattr(command, "serve_isolated_browser_certification", runner)
    command.main(["--acknowledge-test-only", "--static-root", str(root),
                  "--port", "8919"])
    factory.assert_called_once_with()
    runner.assert_called_once_with(
        native_application=native, static_root=root, port=8919,
        acknowledge_test_only=True,
    )
