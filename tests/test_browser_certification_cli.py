"""The operator CLI must never implicitly enable production guarded routes."""
from pathlib import Path
from types import SimpleNamespace
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
    factory.assert_called_once()
    args = factory.call_args.kwargs
    assert args["raw_root"] == command.resolve_data_lake_runtime_paths().raw_root
    assert not args["cache_root"].exists(), "Temporary cache must be removed after the run"
    assert args["cache_root"] != command.resolve_data_lake_runtime_paths().cache_root
    runner.assert_called_once_with(
        native_application=native, static_root=root, port=8919,
        acknowledge_test_only=True,
    )


def test_operator_cli_propagates_explicit_evidence_destination(monkeypatch, tmp_path):
    root = tmp_path / "dist-certification"
    native = Mock()
    service = Mock()
    service.application_service = native
    factory = Mock(return_value=service)
    runner = Mock()
    monkeypatch.setattr(command, "build_browser_readonly_service", factory)
    monkeypatch.setattr(command, "serve_isolated_browser_certification", runner)
    evidence = tmp_path / "csl-browser-evidence-operator"
    command.main([
        "--acknowledge-test-only", "--static-root", str(root),
        "--port", "8919", "--evidence-root", str(evidence),
    ])
    runner.assert_called_once_with(
        native_application=native, static_root=root,
        port=8919, acknowledge_test_only=True, evidence_root=evidence,
    )


def test_certification_cache_is_fresh_and_cleans_up_after_server_failure(monkeypatch, tmp_path):
    dist = tmp_path / "dist-certification"
    native = Mock()
    observed = []
    source = tmp_path / "canonical-raw"
    source.mkdir()
    cache = tmp_path / "canonical-cache"
    cache.mkdir()
    (cache / "keep.txt").write_text("unchanged")
    monkeypatch.setattr(
        command, "resolve_data_lake_runtime_paths",
        lambda: SimpleNamespace(raw_root=source, cache_root=cache),
    )

    def build_service(*, raw_root, cache_root):
        assert raw_root == source
        assert cache_root.is_dir()
        assert cache_root != cache
        assert not list(cache_root.iterdir())
        observed.append(cache_root)
        (cache_root / "simulation-cache.bin").write_bytes(b"fixture")
        return SimpleNamespace(application_service=native)

    def failing_runner(**kwargs):
        assert kwargs["native_application"] is native
        assert (observed[-1] / "simulation-cache.bin").is_file()
        raise RuntimeError("injected certification server stop")

    monkeypatch.setattr(command, "build_browser_readonly_service", build_service)
    monkeypatch.setattr(command, "serve_isolated_browser_certification", failing_runner)
    with pytest.raises(RuntimeError, match="injected"):
        command.main(["--acknowledge-test-only", "--static-root", str(dist),
                      "--port", "8919"])
    assert len(observed) == 1
    assert not observed[0].exists()
    assert (cache / "keep.txt").read_text() == "unchanged"


def test_operator_cli_passes_explicit_original_config_as_read_only_seed(monkeypatch, tmp_path):
    native = Mock()
    facade = Mock()
    facade.application_service = native
    service = Mock(return_value=facade)
    runner = Mock()
    monkeypatch.setattr(command, "build_browser_readonly_service", service)
    monkeypatch.setattr(command, "serve_isolated_browser_certification", runner)
    dist = tmp_path / "dist-certification"
    source = tmp_path / "original-v3.json"
    command.main([
        "--acknowledge-test-only", "--static-root", str(dist),
        "--port", "8919", "--frozen-config", str(source),
    ])
    runner.assert_called_once_with(
        native_application=native, static_root=dist, port=8919,
        acknowledge_test_only=True, frozen_config_path=source,
    )


def test_cli_passes_only_explicit_persistent_crash_root(monkeypatch, tmp_path):
    native = Mock()
    facade = Mock()
    facade.application_service = native
    factory = Mock(return_value=facade)
    runner = Mock()
    monkeypatch.setattr(command, "build_browser_readonly_service", factory)
    monkeypatch.setattr(command, "serve_isolated_browser_certification", runner)
    dist = tmp_path / "dist-certification"
    root = tmp_path / "csl-browser-crash-prepared"
    command.main([
        "--acknowledge-test-only", "--static-root", str(dist),
        "--port", "8919", "--persistent-execution-root", str(root),
    ])
    runner.assert_called_once_with(
        native_application=native, static_root=dist, port=8919,
        acknowledge_test_only=True, persistent_execution_root=root,
    )


def test_cli_rejects_combining_persistent_root_and_evidence_before_native_setup(monkeypatch, tmp_path):
    factory = Mock(side_effect=AssertionError("Native must not be constructed"))
    monkeypatch.setattr(command, "build_browser_readonly_service", factory)
    with pytest.raises(SystemExit) as error:
        command.main([
            "--acknowledge-test-only",
            "--static-root", str(tmp_path / "dist-certification"),
            "--port", "8919",
            "--persistent-execution-root", str(tmp_path / "csl-browser-crash-prepared"),
            "--evidence-root", str(tmp_path / "csl-browser-evidence-existing"),
        ])
    assert error.value.code == 2
    factory.assert_not_called()


@pytest.mark.parametrize("overlap", ["raw_child", "cache_child", "raw_parent", "static_child", "frozen_parent"])
def test_cli_rejects_persistent_execution_root_overlapping_protected_sources(
    monkeypatch, tmp_path, overlap,
):
    """Never reach the native factory with an output rooted in original inputs."""
    raw = tmp_path / "original-raw"
    cache = tmp_path / "original-cache"
    static = tmp_path / "dist-certification"
    frozen = tmp_path / "original-configs" / "saved.json"
    for p in (raw, cache, static, frozen.parent):
        p.mkdir()
    mapping = {
        "raw_child": raw / "csl-browser-crash-inside",
        "cache_child": cache / "csl-browser-crash-inside",
        "raw_parent": tmp_path,
        "static_child": static / "csl-browser-crash-inside",
        "frozen_parent": frozen.parent / "csl-browser-crash-inside",
    }
    root = mapping[overlap]
    build = Mock(side_effect=AssertionError("Native app must not be constructed"))
    runner = Mock()
    monkeypatch.setattr(command, "build_browser_readonly_service", build)
    monkeypatch.setattr(command, "serve_isolated_browser_certification", runner)
    monkeypatch.setattr(command, "resolve_data_lake_runtime_paths",
                        lambda: SimpleNamespace(raw_root=raw, cache_root=cache))
    with pytest.raises(SystemExit) as exc:
        command.main([
            "--acknowledge-test-only", "--static-root", str(static), "--port", "8919",
            "--frozen-config", str(frozen),
            "--persistent-execution-root", str(root),
        ])
    assert exc.value.code == 2
    build.assert_not_called()
    runner.assert_not_called()


def test_cli_accepts_separate_persistent_root_without_touching_canonical_sources(
    monkeypatch, tmp_path,
):
    raw = tmp_path / "original-raw"
    cache = tmp_path / "original-cache"
    static = tmp_path / "dist-certification"
    original_configs = tmp_path / "original-configs"
    root = tmp_path / "isolated" / "csl-browser-crash-dedicated"
    for p in (raw, cache, static, original_configs, root.parent):
        p.mkdir()
    frozen = original_configs / "saved.json"
    frozen.write_bytes(b"original")
    fixture = SimpleNamespace(application_service=Mock())
    factory = Mock(return_value=fixture)
    runner = Mock()
    monkeypatch.setattr(command, "build_browser_readonly_service", factory)
    monkeypatch.setattr(command, "serve_isolated_browser_certification", runner)
    monkeypatch.setattr(command, "resolve_data_lake_runtime_paths",
                        lambda: SimpleNamespace(raw_root=raw, cache_root=cache))
    command.main([
        "--acknowledge-test-only", "--static-root", str(static), "--port", "8919",
        "--frozen-config", str(frozen), "--persistent-execution-root", str(root),
    ])
    factory.assert_called_once()
    runner.assert_called_once()
    assert runner.call_args.kwargs["persistent_execution_root"] == root
    assert frozen.read_bytes() == b"original"


@pytest.mark.parametrize("overlap", [
    "raw_child", "cache_child", "raw_parent", "static_child", "frozen_parent",
])
def test_cli_rejects_evidence_overlapping_protected_sources_before_native_setup(
    monkeypatch, tmp_path, overlap,
):
    """Evidence copying must never target canonical data, cache or originals."""
    raw = tmp_path / "original-raw"
    cache = tmp_path / "original-cache"
    static = tmp_path / "dist-certification"
    frozen = tmp_path / "original-configs" / "saved.json"
    for part in (raw, cache, static, frozen.parent):
        part.mkdir()
    frozen.write_bytes(b"original")
    (raw / "keep.bin").write_bytes(b"raw")
    (cache / "keep.bin").write_bytes(b"cache")
    candidates = {
        "raw_child": raw / "csl-browser-evidence-in-raw",
        "cache_child": cache / "csl-browser-evidence-in-cache",
        "raw_parent": tmp_path,
        "static_child": static / "csl-browser-evidence-in-static",
        "frozen_parent": frozen.parent / "csl-browser-evidence-in-configs",
    }
    evidence = candidates[overlap]
    build = Mock(side_effect=AssertionError("Native must not be constructed"))
    runner = Mock()
    monkeypatch.setattr(command, "build_browser_readonly_service", build)
    monkeypatch.setattr(command, "serve_isolated_browser_certification", runner)
    monkeypatch.setattr(command, "resolve_data_lake_runtime_paths",
                        lambda: SimpleNamespace(raw_root=raw, cache_root=cache))
    with pytest.raises(SystemExit) as exc:
        command.main([
            "--acknowledge-test-only", "--static-root", str(static),
            "--port", "8919", "--frozen-config", str(frozen),
            "--evidence-root", str(evidence),
        ])
    assert exc.value.code == 2
    build.assert_not_called()
    runner.assert_not_called()
    assert frozen.read_bytes() == b"original"
    assert (raw / "keep.bin").read_bytes() == b"raw"
    assert (cache / "keep.bin").read_bytes() == b"cache"
    if overlap != "raw_parent":
        assert not evidence.exists()


def test_cli_accepts_separate_evidence_root_without_touching_canonical_sources(
    monkeypatch, tmp_path,
):
    raw = tmp_path / "original-raw"
    cache = tmp_path / "original-cache"
    static = tmp_path / "dist-certification"
    original_configs = tmp_path / "original-configs"
    evidence = tmp_path / "isolated" / "csl-browser-evidence-dedicated"
    for part in (raw, cache, static, original_configs, evidence.parent):
        part.mkdir()
    frozen = original_configs / "saved.json"
    frozen.write_bytes(b"original")
    factory = Mock(return_value=SimpleNamespace(application_service=Mock()))
    runner = Mock()
    monkeypatch.setattr(command, "build_browser_readonly_service", factory)
    monkeypatch.setattr(command, "serve_isolated_browser_certification", runner)
    monkeypatch.setattr(command, "resolve_data_lake_runtime_paths",
                        lambda: SimpleNamespace(raw_root=raw, cache_root=cache))
    command.main([
        "--acknowledge-test-only", "--static-root", str(static),
        "--port", "8919", "--frozen-config", str(frozen),
        "--evidence-root", str(evidence),
    ])
    factory.assert_called_once()
    runner.assert_called_once()
    assert runner.call_args.kwargs["evidence_root"] == evidence
    assert frozen.read_bytes() == b"original"
