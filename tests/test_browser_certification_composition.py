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
        # Verify actual HTTP auth, not route list introspection.
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


def test_certification_optional_evidence_preserves_only_isolated_inputs_and_outputs(tmp_path):
    from crypto_strategy_lab.browser_certification import isolated_browser_certification
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig

    static_root = _certification_dist(tmp_path)
    evidence = tmp_path / "csl-browser-evidence-case1"
    original = tmp_path / "original-saved-config.json"
    original.write_bytes(b"original untouched")
    native = Mock()

    with isolated_browser_certification(
        native_application=native, static_root=static_root,
        acknowledge_test_only=True, evidence_root=evidence,
    ) as (app, token):
        headers = {"Authorization": "Bearer " + token}
        with TestClient(app, base_url="http://localhost") as client:
            result = client.put("/api/v1/guarded/configs/fixture",
                                json=ResearchRunConfig().to_dict(),
                                headers=headers)
            assert result.status_code == 200, result.text
        assert evidence.is_dir()
        assert not (evidence / "configs").exists()
        assert not (evidence / "runs").exists()
    assert (evidence / "configs" / "fixture.json").is_file()
    assert (evidence / "runs").is_dir()
    assert original.read_bytes() == b"original untouched"
    native.run.assert_not_called()


def test_certification_evidence_fails_closed_on_existing_or_unsafe_paths(tmp_path):
    static_root = _certification_dist(tmp_path)
    native = Mock()
    existing = tmp_path / "csl-browser-evidence-existing"
    existing.mkdir()
    protected = existing / "original.json"
    protected.write_bytes(b"never overwrite")
    cases = (
        existing,
        tmp_path / "not-a-certification-directory",
        Path("csl-browser-evidence-relative"),
    )
    for case in cases:
        with pytest.raises(ValueError, match="Evidence destination"):
            with isolated_browser_certification(
                native_application=native, static_root=static_root,
                acknowledge_test_only=True, evidence_root=case,
            ):
                pytest.fail("Unsafe evidence path was accepted")
    assert protected.read_bytes() == b"never overwrite"
    assert not (existing / "configs").exists()
    native.run.assert_not_called()


def test_invalid_frozen_config_does_not_reserve_evidence_root(tmp_path):
    """Reject a bad original before creating the operator's evidence folder."""
    from crypto_strategy_lab.gui.v2_controller import GuiApplicationService
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig

    dist = _certification_dist(tmp_path)
    native = Mock()
    evidence = tmp_path / "csl-browser-evidence-rejected"
    frozen = tmp_path / "invalid.name.json"
    GuiApplicationService.save_config(frozen, ResearchRunConfig())

    with pytest.raises(ValueError, match="Unsafe frozen"):
        with isolated_browser_certification(
            native_application=native, static_root=dist,
            acknowledge_test_only=True, evidence_root=evidence,
            frozen_config_path=frozen,
        ):
            pytest.fail("Invalid frozen input must not open certification")
    assert not evidence.exists()
    assert frozen.is_file()
    native.run.assert_not_called()


def test_certification_app_composition_failure_leaves_no_evidence_destination(tmp_path, monkeypatch):
    """The operator should not lose an evidence name if FastAPI setup fails."""
    import crypto_strategy_lab.browser_certification as certification

    dist = _certification_dist(tmp_path)
    evidence = tmp_path / "csl-browser-evidence-app-rejected"
    native = Mock()
    closes = []
    original_close = certification.BrowserGuardedIntegration.close

    def tracked_close(self):
        closes.append(True)
        return original_close(self)

    monkeypatch.setattr(certification.BrowserGuardedIntegration, "close", tracked_close)

    def fail_composition(**_kwargs):
        raise RuntimeError("injected test-only app composition failure")

    monkeypatch.setattr(certification, "create_browser_app", fail_composition)
    with pytest.raises(RuntimeError, match="app composition failure"):
        with isolated_browser_certification(
            native_application=native, static_root=dist,
            acknowledge_test_only=True, evidence_root=evidence,
        ):
            pytest.fail("Rejected app must never start a certification session")
    assert not evidence.exists()
    assert closes == [True]
    native.run.assert_not_called()


def test_evidence_reservation_failure_closes_guarded_native_coordinator(tmp_path, monkeypatch):
    """An exclusive-create failure after app composition must release its worker."""
    import crypto_strategy_lab.browser_certification as certification

    dist = _certification_dist(tmp_path)
    evidence = tmp_path / "csl-browser-evidence-create-failure"
    native = Mock()
    closes = []
    original_close = certification.BrowserGuardedIntegration.close
    original_mkdir = certification.os.mkdir

    def track_close(self):
        closes.append(True)
        return original_close(self)

    def fail_evidence_only(path, *args, **kwargs):
        if Path(path) == evidence:
            raise OSError("injected exclusive-create failure")
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(certification.BrowserGuardedIntegration, "close", track_close)
    monkeypatch.setattr(certification.os, "mkdir", fail_evidence_only)
    with pytest.raises(OSError, match="exclusive-create failure"):
        with isolated_browser_certification(
            native_application=native, static_root=dist,
            acknowledge_test_only=True, evidence_root=evidence,
        ):
            pytest.fail("No session may start without the requested evidence root")
    assert closes == [True]
    assert not evidence.exists()
    native.run.assert_not_called()


def test_certification_evidence_never_follows_output_symlinks(tmp_path):
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig
    from types import SimpleNamespace

    dist = _certification_dist(tmp_path)
    secret = tmp_path / "original-private.txt"
    secret.write_text("do-not-copy", encoding="utf-8")
    evidence = tmp_path / "csl-browser-evidence-links"
    native = Mock()

    def run(request, config):
        root = Path(config.reporting.output_dir)
        try:
            (root / "unsafe-link").symlink_to(secret)
        except (OSError, NotImplementedError):
            pytest.skip("Local filesystem symlinks unavailable")
        return SimpleNamespace(output_dir=None)

    native.run.side_effect = run
    with pytest.raises(ValueError, match="Unsafe symlink"):
        with isolated_browser_certification(
            native_application=native, static_root=dist,
            acknowledge_test_only=True, evidence_root=evidence,
        ) as (app, token):
            with TestClient(app, base_url="http://localhost") as client:
                payload = {
                    "request_id": "with-link",
                    "request": {
                        "exchange": "binance", "market": "futures_um",
                        "symbol": "BTCUSDT",
                        "period_start": "2025-01-01T00:00:00Z",
                        "period_end": "2025-01-02T00:00:00Z",
                        "strategy_timeframe": "4h", "intrabar_timeframe": "1m",
                    },
                    "config": ResearchRunConfig().to_dict(),
                }
                response = client.post(
                    "/api/v1/guarded/jobs", json=payload,
                    headers={"Authorization": "Bearer " + token},
                )
                assert response.status_code == 202
    assert secret.read_text(encoding="utf-8") == "do-not-copy"
    assert not (evidence / "runs" / "unsafe-link").exists()


def test_certification_seeds_original_native_config_unchanged_and_reads_through_http(tmp_path, monkeypatch):
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig
    from crypto_strategy_lab.gui.v2_controller import GuiApplicationService

    dist = _certification_dist(tmp_path)
    original_folder = tmp_path / "originals"
    original_folder.mkdir()
    source = original_folder / "native-reference.json"
    config = ResearchRunConfig()
    GuiApplicationService.save_config(source, config)
    original_bytes = source.read_bytes()
    actual_load = GuiApplicationService.load_config
    validated_paths = []

    def tracked_native_load(path):
        validated_paths.append(Path(path))
        assert Path(path) != source
        assert Path(path).read_bytes() == original_bytes
        return actual_load(path)

    monkeypatch.setattr(GuiApplicationService, "load_config", tracked_native_load)
    native = Mock()
    with isolated_browser_certification(
        native_application=native, static_root=dist,
        acknowledge_test_only=True, frozen_config_path=source,
    ) as (app, token):
        with TestClient(app, base_url="http://localhost") as client:
            path = "/api/v1/configs/native-reference"
            assert client.get(path).status_code == 401
            response = client.get(path, headers={"Authorization": "Bearer " + token})
            assert response.status_code == 200
            from crypto_strategy_lab.browser_config import read_research_config
            from fastapi.encoders import jsonable_encoder
            assert response.json()["config"] == jsonable_encoder(read_research_config(source))
        # The original remains untouched before and after the HTTP read.
        assert source.read_bytes() == original_bytes
    assert source.read_bytes() == original_bytes
    assert len(validated_paths) == 1
    native.run.assert_not_called()


def test_certification_frozen_config_rejects_invalid_and_linked_sources(tmp_path):
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig
    from crypto_strategy_lab.gui.v2_controller import GuiApplicationService

    dist = _certification_dist(tmp_path)
    native = Mock()
    invalid = tmp_path / "bad.name.json"
    GuiApplicationService.save_config(invalid, ResearchRunConfig())
    for candidate in (invalid, tmp_path / "absent.json", Path("relative.json")):
        with pytest.raises(ValueError):
            with isolated_browser_certification(
                native_application=native, static_root=dist,
                frozen_config_path=candidate, acknowledge_test_only=True,
            ):
                pytest.fail("Unsafe source admitted")
    source = tmp_path / "original.json"
    GuiApplicationService.save_config(source, ResearchRunConfig())
    link = tmp_path / "linked.json"
    try:
        link.symlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable")
    with pytest.raises(ValueError, match="Unsafe frozen"):
        with isolated_browser_certification(
            native_application=native, static_root=dist,
            frozen_config_path=link, acknowledge_test_only=True,
        ):
            pytest.fail("Symlinked source admitted")
    assert source.exists()
    native.run.assert_not_called()


def test_persistent_crash_certification_preserves_claims_across_independent_sessions(tmp_path):
    """A real coordinator is reused across sessions without replay or stale-lock cleanup."""
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig

    dist = _certification_dist(tmp_path)
    output = tmp_path / "csl-browser-crash-test"
    output.mkdir()
    marker = output / ".csl-browser-crash-test-only"
    marker.write_bytes(b"CSL_BROWSER_CRASH_CERT_V1")
    native = Mock()
    native.run.return_value = None
    headers = None
    first_token = None
    with isolated_browser_certification(
        native_application=native, static_root=dist,
        acknowledge_test_only=True, persistent_execution_root=output,
    ) as (app, token):
        first_token = token
        headers = {"Authorization": "Bearer " + token}
        with TestClient(app, base_url="http://localhost") as client:
            payload = {
                "request_id": "persisted-request",
                "request": {
                    "exchange": "binance", "market": "futures_um", "symbol": "BTCUSDT",
                    "period_start": "2025-01-01T00:00:00Z",
                    "period_end": "2025-01-02T00:00:00Z",
                    "strategy_timeframe": "4h", "intrabar_timeframe": "1m",
                },
                "config": ResearchRunConfig().to_dict(),
            }
            response = client.post("/api/v1/guarded/jobs", json=payload, headers=headers)
            assert response.status_code == 202, response.text
        assert (output / ".guarded-request-persisted-request.claim").is_dir()
    assert (output / ".guarded-request-persisted-request.claim").is_dir()
    assert marker.read_bytes() == b"CSL_BROWSER_CRASH_CERT_V1"
    assert native.run.call_count == 1

    with isolated_browser_certification(
        native_application=native, static_root=dist,
        acknowledge_test_only=True, persistent_execution_root=output,
    ) as (app, token):
        assert token != first_token
        with TestClient(app, base_url="http://localhost") as client:
            assert client.get("/api/v1/guarded/jobs/persisted-request",
                              headers=headers).status_code == 401
            auth = {"Authorization": "Bearer " + token}
            result = client.get("/api/v1/guarded/jobs/persisted-request", headers=auth)
            assert result.json() == {"request_id": "persisted-request",
                                     "status": "RECOVERY_UNVERIFIED"}
            rejected = client.post("/api/v1/guarded/jobs", json=payload, headers=auth)
            assert rejected.status_code == 409
        assert native.run.call_count == 1
    assert (output / ".guarded-request-persisted-request.claim").is_dir()
    assert marker.is_file()


def test_persistent_crash_certification_preserves_stale_worker_lock(tmp_path):
    """A stale root stays owned; restarting must never clear it or launch native work."""
    dist = _certification_dist(tmp_path)
    output = tmp_path / "csl-browser-crash-stale"
    output.mkdir()
    marker = output / ".csl-browser-crash-test-only"
    marker.write_bytes(b"CSL_BROWSER_CRASH_CERT_V1")
    (output / ".guarded-request-killed.claim").mkdir()
    (output / ".guarded-native-worker.lock").mkdir()
    native = Mock()
    with isolated_browser_certification(
        native_application=native, static_root=dist,
        acknowledge_test_only=True, persistent_execution_root=output,
    ) as (app, token):
        with TestClient(app, base_url="http://localhost") as client:
            headers = {"Authorization": "Bearer " + token}
            assert client.get("/api/v1/guarded/jobs/killed", headers=headers).json() == {
                "request_id": "killed", "status": "RECOVERY_UNVERIFIED",
            }
    assert (output / ".guarded-native-worker.lock").is_dir()
    native.run.assert_not_called()


def test_persistent_crash_certification_rejects_unsafe_roots_before_start(tmp_path):
    dist = _certification_dist(tmp_path)
    native = Mock()
    good = tmp_path / "csl-browser-crash-safe"
    good.mkdir()
    marker = good / ".csl-browser-crash-test-only"
    marker.write_bytes(b"CSL_BROWSER_CRASH_CERT_V1")
    original = tmp_path / "original-files"
    original.mkdir()
    (original / "keep.json").write_bytes(b"original")
    for path in (original, tmp_path / "csl-browser-crash-missing",
                 Path("csl-browser-crash-relative")):
        with pytest.raises(ValueError, match="Unsafe persistent"):
            with isolated_browser_certification(
                native_application=native, static_root=dist,
                acknowledge_test_only=True, persistent_execution_root=path,
            ):
                pytest.fail("Unsafe persistence root accepted")
    marker.unlink()
    with pytest.raises(ValueError, match="test-only marker"):
        with isolated_browser_certification(
            native_application=native, static_root=dist,
            acknowledge_test_only=True, persistent_execution_root=good,
        ):
            pytest.fail("Unmarked root accepted")
    marker.write_bytes(b"CSL_BROWSER_CRASH_CERT_V1")
    with pytest.raises(ValueError, match="mutually exclusive"):
        with isolated_browser_certification(
            native_application=native, static_root=dist,
            acknowledge_test_only=True, persistent_execution_root=good,
            evidence_root=tmp_path / "csl-browser-evidence-do-not-create",
        ):
            pytest.fail("Incompatible evidence-copy and crash-root modes accepted")
    assert (original / "keep.json").read_bytes() == b"original"
    native.run.assert_not_called()


@pytest.mark.parametrize("location", ["root", "ancestor", "descendant", "marker"])
def test_persistent_crash_root_rejects_windows_junction_like_reparse_entries(
    tmp_path, monkeypatch, location,
):
    """Model a Windows reparse attribute on each path without requiring NTFS."""
    import crypto_strategy_lab.browser_certification as certification

    dist = _certification_dist(tmp_path)
    parent = tmp_path / "isolated-parent"
    parent.mkdir()
    root = parent / "csl-browser-crash-reparse"
    root.mkdir()
    marker = root / ".csl-browser-crash-test-only"
    marker.write_bytes(b"CSL_BROWSER_CRASH_CERT_V1")
    descendant = root / "subdir"
    descendant.mkdir()
    flagged = {"root": root, "ancestor": parent,
               "descendant": descendant, "marker": marker}[location]
    real_check = certification._unsafe_reparse_path
    monkeypatch.setattr(
        certification, "_unsafe_reparse_path",
        lambda candidate: Path(candidate) == flagged or real_check(candidate),
    )
    native = Mock()
    with pytest.raises(ValueError, match="persistent|marker",):
        with isolated_browser_certification(
            native_application=native, static_root=dist,
            acknowledge_test_only=True, persistent_execution_root=root,
        ):
            pytest.fail("A Windows junction-like reparse path must be rejected")
    native.run.assert_not_called()


@pytest.mark.parametrize("location", ["static-parent", "static-asset", "frozen-file", "frozen-parent", "evidence-parent"])
def test_certification_rejects_windows_reparse_sources_and_destination_parents(
    tmp_path, monkeypatch, location,
):
    """Emulate NTFS reparse paths on POSIX to protect original Windows inputs."""
    import crypto_strategy_lab.browser_certification as certification
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig
    from crypto_strategy_lab.gui.v2_controller import GuiApplicationService

    dist_parent = tmp_path / "static-parent"
    dist_parent.mkdir()
    dist = dist_parent / "dist-certification"
    dist.mkdir()
    asset = dist / "index.html"
    asset.write_text("certification", encoding="utf-8")
    frozen_parent = tmp_path / "original-configs"
    frozen_parent.mkdir()
    frozen = frozen_parent / "original.json"
    GuiApplicationService.save_config(frozen, ResearchRunConfig())
    evidence_parent = tmp_path / "evidence-parent"
    evidence_parent.mkdir()
    evidence = evidence_parent / "csl-browser-evidence-uncreated"
    flagged = {
        "static-parent": dist_parent, "static-asset": asset,
        "frozen-file": frozen, "frozen-parent": frozen_parent,
        "evidence-parent": evidence_parent,
    }[location]
    original_bytes = frozen.read_bytes()
    real_check = certification._unsafe_reparse_path
    monkeypatch.setattr(
        certification, "_unsafe_reparse_path",
        lambda path: Path(path) == flagged or real_check(path),
    )
    native = Mock()
    with pytest.raises(ValueError, match="canonical|Unsafe"):
        with isolated_browser_certification(
            native_application=native, static_root=dist,
            acknowledge_test_only=True, frozen_config_path=frozen,
            evidence_root=evidence,
        ):
            pytest.fail("A reparse-backed source or destination was accepted")
    assert not evidence.exists()
    assert frozen.read_bytes() == original_bytes
    native.run.assert_not_called()


def test_certification_evidence_copy_rejects_output_reparse_entries(tmp_path, monkeypatch):
    """Do not copy or traverse junction-like native output descendants."""
    import crypto_strategy_lab.browser_certification as certification

    dist = _certification_dist(tmp_path)
    evidence = tmp_path / "csl-browser-evidence-reparse"
    native = Mock()
    real_check = certification._unsafe_reparse_path
    flagged = set()
    monkeypatch.setattr(
        certification, "_unsafe_reparse_path",
        lambda path: Path(path) in flagged or real_check(path),
    )
    with pytest.raises(ValueError, match="reparse"):
        with isolated_browser_certification(
            native_application=native, static_root=dist,
            acknowledge_test_only=True, evidence_root=evidence,
        ) as (app, token):
            output = None
            # Run through one authenticated client lifespan. Exiting TestClient
            # closes the guarded coordinator, so never reopen it for submission.
            # The native original roots remain inaccessible. Mark only an
            # isolated native output directory through its private integration.
            from crypto_strategy_lab.data_lake_config import ResearchRunConfig
            from types import SimpleNamespace

            def native_run(request, config):
                nonlocal output
                output = Path(config.reporting.output_dir)
                file = output / "junction-like-output"
                file.mkdir()
                flagged.add(file)
                return SimpleNamespace(output_dir=None)

            native.run.side_effect = native_run
            payload = {
                "request_id": "reparse-output",
                "request": {
                    "exchange": "binance", "market": "futures_um", "symbol": "BTCUSDT",
                    "period_start": "2025-01-01T00:00:00Z",
                    "period_end": "2025-01-02T00:00:00Z",
                    "strategy_timeframe": "4h", "intrabar_timeframe": "1m",
                },
                "config": ResearchRunConfig().to_dict(),
            }
            with TestClient(app, base_url="http://localhost") as client:
                res = client.post("/api/v1/guarded/jobs", json=payload,
                                  headers={"Authorization": "Bearer " + token})
                assert res.status_code == 202
    assert evidence.is_dir()
    assert not (evidence / "runs").exists()


@pytest.mark.parametrize("overlap", ["inside-static", "inside-frozen", "ancestor-of-static"])
def test_direct_certification_factory_rejects_persistent_root_overlapping_inputs(
    tmp_path, overlap,
):
    """The underlying test-only composition cannot bypass CLI path isolation."""
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig
    from crypto_strategy_lab.gui.v2_controller import GuiApplicationService

    static_parent = tmp_path / "csl-browser-crash-parent"
    static_parent.mkdir()
    dist = static_parent / "dist-certification"
    dist.mkdir()
    (dist / "index.html").write_text("test-only", encoding="utf-8")
    frozen_parent = tmp_path / "original-configs"
    frozen_parent.mkdir()
    frozen = frozen_parent / "frozen.json"
    GuiApplicationService.save_config(frozen, ResearchRunConfig())
    output = {
        "inside-static": dist / "csl-browser-crash-overlap",
        "inside-frozen": frozen_parent / "csl-browser-crash-overlap",
        "ancestor-of-static": static_parent,
    }[overlap]
    output.mkdir(exist_ok=True)
    (output / ".csl-browser-crash-test-only").write_bytes(b"CSL_BROWSER_CRASH_CERT_V1")
    original = frozen.read_bytes()
    native = Mock()
    with pytest.raises(ValueError, match="overlaps protected inputs"):
        with isolated_browser_certification(
            native_application=native, static_root=dist,
            acknowledge_test_only=True,
            persistent_execution_root=output, frozen_config_path=frozen,
        ):
            pytest.fail("Overlapping test-only root accepted")
    assert frozen.read_bytes() == original
    native.run.assert_not_called()

@pytest.mark.parametrize("location", ["inside-static", "inside-original-configs"])
def test_evidence_destination_cannot_overlap_certification_or_original_inputs(tmp_path, location):
    """Reject evidence destinations inside source trees before reservation."""
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig
    from crypto_strategy_lab.gui.v2_controller import GuiApplicationService

    dist = _certification_dist(tmp_path)
    original_parent = tmp_path / "original-configs"
    original_parent.mkdir()
    frozen = original_parent / "pinned.json"
    GuiApplicationService.save_config(frozen, ResearchRunConfig())
    original_bytes = frozen.read_bytes()
    evidence = (dist / "csl-browser-evidence-static" if location == "inside-static"
                else original_parent / "csl-browser-evidence-original")
    native = Mock()
    with pytest.raises(ValueError, match="overlaps protected inputs"):
        with isolated_browser_certification(
            native_application=native, static_root=dist,
            acknowledge_test_only=True, frozen_config_path=frozen,
            evidence_root=evidence,
        ):
            pytest.fail("Overlapping evidence root was accepted")
    assert frozen.read_bytes() == original_bytes
    assert not evidence.exists()
    native.run.assert_not_called()
