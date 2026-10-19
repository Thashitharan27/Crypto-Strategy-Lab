"""B4 review composition is a real read-only app, not a release switch."""
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from crypto_strategy_lab.browser_release_composition import compose_b4_review_only


def _roots(tmp_path):
    paths = {name: tmp_path / name for name in (
        "raw", "cache", "original-output", "original-config",
        "static", "future-config", "future-runs",
    )}
    for path in paths.values():
        path.mkdir()
    (paths["static"] / "index.html").write_text("read only", encoding="utf-8")
    env = {
        "CRYPTO_STRATEGY_LAB_RAW_ROOT": str(paths["raw"]),
        "CRYPTO_STRATEGY_LAB_CACHE_DIR": str(paths["cache"]),
        "CRYPTO_STRATEGY_LAB_OUTPUT_DIR": str(paths["original-output"]),
        "CRYPTO_STRATEGY_LAB_CONFIG_DIR": str(paths["original-config"]),
        "CRYPTO_STRATEGY_LAB_BROWSER_RELEASE_APPROVED": "true",
        "CRYPTO_STRATEGY_LAB_BROWSER_GUARDED_ENABLED": "1",
    }
    return paths, env


@pytest.mark.parametrize("attempt", [True, None, 1, "approved"])
def test_release_attempt_denied_before_any_http_or_native_composition(tmp_path, attempt):
    paths, env = _roots(tmp_path)
    with (
        patch("crypto_strategy_lab.browser_release_composition.preflight_browser_guarded_release") as preflight,
        patch("crypto_strategy_lab.browser_release_composition.build_browser_readonly_runtime") as launcher,
    ):
        with pytest.raises(PermissionError, match="does not authorize"):
            compose_b4_review_only(
                configuration=paths["future-config"],
                execution=paths["future-runs"], environ=env,
                release_requested=attempt,
            )
    preflight.assert_not_called()
    launcher.assert_not_called()


def test_review_composition_reuses_canonical_readonly_launcher_and_retains_roots(tmp_path):
    paths, env = _roots(tmp_path)
    app = Mock()
    with (
        patch("crypto_strategy_lab.browser_launcher.build_browser_readonly_service", return_value=Mock()),
        patch("crypto_strategy_lab.browser_launcher.create_browser_app", return_value=app) as create_app,
    ):
        review = compose_b4_review_only(
            configuration=paths["future-config"],
            execution=paths["future-runs"],
            environ=env, static_root=paths["static"],
            token="b" * 48, port=8919,
        )
    assert review.guarded_enabled is False
    assert review.user_release_approved is False
    assert review.runtime.app is app
    assert review.runtime.host == "127.0.0.1"
    assert review.runtime.port == 8919
    assert review.candidate_roots.configuration == paths["future-config"]
    assert review.candidate_roots.execution == paths["future-runs"]
    assert "guarded_enabled" not in create_app.call_args.kwargs
    assert "guarded_integration" not in create_app.call_args.kwargs
    assert not any(paths["future-runs"].iterdir())
    assert not any(paths["future-config"].iterdir())


def test_review_real_http_never_mounts_guarded_routes(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    paths, env = _roots(tmp_path)
    service = Mock()
    token = "b" * 48
    with patch("crypto_strategy_lab.browser_launcher.build_browser_readonly_service", return_value=service):
        review = compose_b4_review_only(
            configuration=paths["future-config"],
            execution=paths["future-runs"],
            environ=env, static_root=paths["static"],
            token=token,
        )
    auth = {"Authorization": "Bearer " + token}
    with TestClient(review.runtime.app, base_url="http://127.0.0.1:8767") as client:
        assert client.get("/api/v1/health").status_code == 401
        assert client.get("/api/v1/health", headers=auth).json() == {
            "status": "ok", "mode": "read-only",
        }
        for method, endpoint in (
            ("POST", "/api/v1/guarded/jobs"),
            ("PUT", "/api/v1/guarded/configs/test"),
            ("GET", "/api/v1/guarded/jobs/test"),
            ("POST", "/api/v1/guarded/jobs/test/cancel"),
        ):
            assert client.request(method, endpoint, headers=auth).status_code == 404
    assert list(paths["future-runs"].iterdir()) == []
    assert list(paths["future-config"].iterdir()) == []


def test_bad_future_roots_refused_before_server_instantiation(tmp_path):
    paths, env = _roots(tmp_path)
    with patch("crypto_strategy_lab.browser_release_composition.build_browser_readonly_runtime") as launcher:
        with pytest.raises(ValueError, match="protected"):
            compose_b4_review_only(
                configuration=paths["future-config"],
                execution=paths["raw"], environ=env,
                static_root=paths["static"],
            )
    launcher.assert_not_called()


def test_candidate_refuses_default_activation_before_touching_native_or_roots(tmp_path):
    from crypto_strategy_lab.browser_release_composition import compose_b4_guarded_candidate
    native = Mock()
    with patch("crypto_strategy_lab.browser_release_composition.preflight_browser_guarded_release") as roots:
        with pytest.raises(PermissionError, match="not approved"):
            compose_b4_guarded_candidate(
                native_application=native, configuration=tmp_path / "config",
                execution=tmp_path / "runs", audit_callback=lambda event: None,
            )
    roots.assert_not_called()
    native.run.assert_not_called()


def test_candidate_requires_auditor_and_native_service_before_root_access(tmp_path):
    from crypto_strategy_lab.browser_release_composition import compose_b4_guarded_candidate
    with patch("crypto_strategy_lab.browser_release_composition.preflight_browser_guarded_release") as roots:
        with pytest.raises(ValueError, match="audit"):
            compose_b4_guarded_candidate(
                native_application=Mock(), configuration=tmp_path, execution=tmp_path,
                approval_granted=True, audit_callback=None,
            )
        with pytest.raises(ValueError, match="native"):
            compose_b4_guarded_candidate(
                native_application=object(), configuration=tmp_path, execution=tmp_path,
                approval_granted=True, audit_callback=lambda event: None,
            )
    roots.assert_not_called()


def test_isolated_candidate_reuses_existing_router_and_never_executes_without_auth(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from crypto_strategy_lab.browser_release_composition import compose_b4_guarded_candidate

    paths, env = _roots(tmp_path)
    native = Mock()
    events = []
    token = "r" * 48
    candidate = compose_b4_guarded_candidate(
        native_application=native,
        configuration=paths["future-config"], execution=paths["future-runs"],
        static_root=paths["static"], environ=env,
        token=token, audit_callback=events.append, approval_granted=True,
    )
    assert candidate.host == "127.0.0.1"
    try:
        with TestClient(candidate.app, base_url="http://127.0.0.1:8767") as client:
            path = "/api/v1/guarded/jobs/saved"
            assert client.get(path).status_code == 401
            assert client.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401
            auth = {"Authorization": "Bearer " + token}
            assert client.get(path, headers={**auth, "Origin": "http://127.0.0.1:9876"}).status_code == 403
            assert client.get(path, headers={**auth, "Host": "evil.example"}).status_code == 403
            # Unknown ID must not be confused with native execution or replay.
            assert client.get(path, headers=auth).status_code == 404
            assert client.get("/api/v1/release/capabilities", headers=auth).json() == {
                "execution": False, "configuration_editing": False,
            }
        native.run.assert_not_called()
        assert events and all(set(item) == {"operation", "outcome"} for item in events)
        assert all(token not in repr(item) for item in events)
        assert not list(paths["future-config"].iterdir())
        assert not list(paths["future-runs"].iterdir())
    finally:
        candidate.close()


def test_candidate_factory_does_not_override_normal_readonly_launcher(tmp_path):
    from crypto_strategy_lab.browser_release_composition import compose_b4_guarded_candidate
    paths, env = _roots(tmp_path)
    with patch("crypto_strategy_lab.browser_release_composition.preflight_browser_guarded_release") as preflight:
        with pytest.raises(PermissionError):
            compose_b4_guarded_candidate(
                native_application=Mock(), configuration=paths["future-config"],
                execution=paths["future-runs"], audit_callback=lambda event: None,
                environ={**env, "CRYPTO_STRATEGY_LAB_BROWSER_RELEASE_APPROVED": "true"},
            )
    preflight.assert_not_called()


def test_guarded_candidate_audit_events_persist_without_sensitive_data(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from crypto_strategy_lab.browser_release_audit import B4AuditJournal
    from crypto_strategy_lab.browser_release_composition import compose_b4_guarded_candidate

    paths, env = _roots(tmp_path)
    audit_root = tmp_path / "audit"
    audit_root.mkdir()
    native = Mock()
    token = "journal-secret-" + "x" * 48
    with B4AuditJournal(audit_root, "session-1") as journal:
        candidate = compose_b4_guarded_candidate(
            native_application=native, configuration=paths["future-config"],
            execution=paths["future-runs"], static_root=paths["static"],
            environ=env, token=token, audit_callback=journal,
            approval_granted=True,
        )
        try:
            with TestClient(candidate.app, base_url="http://127.0.0.1:8767") as client:
                url = "/api/v1/guarded/jobs/not-found"
                assert client.get(url).status_code == 401
                assert client.get(url, headers={"Authorization": "Bearer " + token}).status_code == 404
        finally:
            candidate.close()
    assert journal.path.read_bytes() == (
        b'{"operation":"AUTH","outcome":"DENIED"}\n'
        b'{"operation":"STATUS","outcome":"NOT_FOUND"}\n'
    )
    assert token.encode() not in journal.path.read_bytes()
    native.run.assert_not_called()


def test_exhausted_journal_blocks_native_mutation_and_retains_evidence(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from crypto_strategy_lab import browser_release_audit as audit_module
    from crypto_strategy_lab.browser_release_composition import compose_b4_guarded_candidate
    from crypto_strategy_lab.browser_release_audit_verify import inspect_b4_audit

    paths, env = _roots(tmp_path)
    audit_root = tmp_path / "audit"
    audit_root.mkdir()
    native = Mock()
    token = "capacity-only-" + "s" * 48
    with audit_module.B4AuditJournal(audit_root, "capacity") as journal:
        journal({"operation": "STATUS", "outcome": "SUCCESS"})
        original = journal.path.read_bytes()
        monkeypatch.setattr(audit_module, "_MAX_RECORDS", 1)
        candidate = compose_b4_guarded_candidate(
            native_application=native, configuration=paths["future-config"],
            execution=paths["future-runs"], static_root=paths["static"],
            environ=env, token=token, audit_callback=journal, approval_granted=True,
        )
        try:
            with patch.object(candidate.integration, "cancel") as cancel:
                with TestClient(candidate.app, base_url="http://127.0.0.1:8767") as client:
                    for _ in range(2):
                        response = client.post("/api/v1/guarded/jobs/probe/cancel",
                                               headers={"Authorization": "Bearer " + token})
                        assert response.status_code == 503
                cancel.assert_not_called()
        finally:
            candidate.close()
        assert journal.path.read_bytes() == original
    assert inspect_b4_audit(audit_root, "capacity")["status"] == "AUDIT_VERIFIED"
    assert not list(paths["future-runs"].iterdir())
    assert not list(paths["future-config"].iterdir())
    native.run.assert_not_called()
