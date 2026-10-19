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
