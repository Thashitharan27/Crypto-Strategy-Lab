"""B4 read-only release smoke: real HTTP composition, no activation.

Run from a clean checkout:
    python -m crypto_strategy_lab.browser_release_smoke

This runs only against temporary fixture directories; it never touches the
canonical Data Lake or original saved configurations and never starts a server.
It is engineering release-readiness evidence, NOT permission to activate.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch


def verify_clean_checkout(repo: Path) -> str:
    """Require a tracked, clean Git checkout for a release-ready smoke."""
    root = Path(repo).resolve(strict=True)
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root), *args], check=True,
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
    # Git for Windows reports forward-slash paths even when pathlib uses
    # backslashes. Compare canonical paths, not platform-specific text.
    if Path(git("rev-parse", "--show-toplevel")).resolve(strict=True) != root:
        raise ValueError("Smoke requires the repository checkout root")
    commit = git("rev-parse", "HEAD")
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit.lower()):
        raise ValueError("Invalid checkout commit")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise ValueError("Release smoke requires a clean worktree")
    return commit


def run_readonly_release_smoke() -> dict[str, object]:
    """Exercise actual FastAPI routes, auth and protected-root separation."""
    from fastapi.testclient import TestClient
    from crypto_strategy_lab.browser_release_composition import compose_b4_review_only

    with TemporaryDirectory(prefix="csl-b4-review-smoke-") as scratch:
        base = Path(scratch).resolve()
        names = ("raw", "cache", "saved-runs", "saved-configs", "static",
                 "future-config", "future-runs")
        dirs = {name: base / name for name in names}
        for directory in dirs.values():
            directory.mkdir()
        (dirs["static"] / "index.html").write_text(
            "<!doctype html><title>CSL read-only smoke</title>", encoding="utf-8",
        )
        protected = dirs["saved-runs"] / "original.bin"
        protected.write_bytes(b"must-stay-original")
        environ = {
            "CRYPTO_STRATEGY_LAB_RAW_ROOT": str(dirs["raw"]),
            "CRYPTO_STRATEGY_LAB_CACHE_DIR": str(dirs["cache"]),
            "CRYPTO_STRATEGY_LAB_OUTPUT_DIR": str(dirs["saved-runs"]),
            "CRYPTO_STRATEGY_LAB_CONFIG_DIR": str(dirs["saved-configs"]),
            "CRYPTO_STRATEGY_LAB_BROWSER_RELEASE_APPROVED": "true",
            "CRYPTO_STRATEGY_LAB_BROWSER_GUARDED_ENABLED": "true",
        }
        token = "b4-smoke-" + "s" * 48
        with patch(
            "crypto_strategy_lab.browser_launcher.build_browser_readonly_service",
            return_value=Mock(),
        ):
            review = compose_b4_review_only(
                configuration=dirs["future-config"], execution=dirs["future-runs"],
                environ=environ, static_root=dirs["static"], token=token,
            )
        if review.guarded_enabled or review.user_release_approved:
            raise AssertionError("Release preparation accidentally enabled guarded operations")
        auth = {"Authorization": "Bearer " + token}
        forbidden = {"Authorization": "Bearer invalid"}
        checked = 0
        with TestClient(review.runtime.app, base_url="http://127.0.0.1:8767") as client:
            for headers, expected in (({}, 401), (forbidden, 401), (auth, 200)):
                response = client.get("/api/v1/health", headers=headers)
                assert response.status_code == expected
                checked += 1
            assert client.get("/api/v1/health", headers=auth).json() == {
                "status": "ok", "mode": "read-only",
            }
            checked += 1
            assert client.get(
                "/api/v1/health", headers={**auth, "Host": "remote.example"},
            ).status_code == 403
            checked += 1
            assert client.get("/api/v1/release/capabilities").status_code == 401
            checked += 1
            assert client.get("/api/v1/release/capabilities", headers=auth).json() == {
                "execution": False, "configuration_editing": False,
            }
            checked += 1
            # Cross-origin requests cannot borrow a local bearer session.
            # A non-local web origin is forbidden everywhere. A different
            # loopback port is permitted on read-only GETs by existing policy,
            # but must be forbidden at the guarded mutation boundary.
            assert client.get(
                "/api/v1/health",
                headers={**auth, "Origin": "http://malicious.example:8767"},
            ).status_code == 403
            checked += 1
            assert client.get(
                "/api/v1/health",
                headers={**auth, "Origin": "http://127.0.0.1:9999"},
            ).status_code == 200
            checked += 1
            assert client.get(
                "/api/v1/guarded/jobs/smoke",
                headers={**auth, "Origin": "http://127.0.0.1:9999"},
            ).status_code == 403
            checked += 1
            for method, path in (
                ("POST", "/api/v1/guarded/jobs"),
                ("PUT", "/api/v1/guarded/configs/smoke"),
                ("GET", "/api/v1/guarded/jobs/smoke"),
                ("GET", "/api/v1/guarded/jobs/smoke/progress"),
                ("POST", "/api/v1/guarded/jobs/smoke/cancel"),
            ):
                assert client.request(method, path, headers=auth).status_code == 404
                checked += 1
        # Read-only rollback evidence smoke: an interrupted mutation and surviving
        # native ownership must remain release-held with no evidence modified.
        from crypto_strategy_lab.browser_release_audit import B4AuditJournal
        from crypto_strategy_lab.browser_release_rollback_review import inspect_b4_rollback_readiness
        audit_dir = base / "audit"
        audit_dir.mkdir()
        claim = dirs["future-runs"] / ".guarded-request-interrupted.claim"
        worker = dirs["future-runs"] / ".guarded-native-worker.lock"
        claim.mkdir()
        worker.mkdir()
        retained = claim / "retained.bin"
        retained.write_bytes(b"retain native ownership")
        with B4AuditJournal(audit_dir, "rollback-smoke") as journal:
            journal({"operation": "JOB_SUBMIT", "outcome": "ATTEMPT"})
            journal({"operation": "STATUS", "outcome": "SUCCESS"})
        before_audit = journal.path.read_bytes()
        evidence = inspect_b4_rollback_readiness(
            audit_root=audit_dir, session_id="rollback-smoke",
            execution_root=dirs["future-runs"], request_id="interrupted",
        )
        assert evidence["status"] == "RELEASE_HELD"
        assert evidence["safe_to_replay"] is False
        assert evidence["safe_to_clear_locks"] is False
        assert evidence["production_activation_authorized"] is False
        assert {"MUTATION_ATTEMPT_REQUIRES_REVIEW",
                "REQUEST_CLAIM_REQUIRES_REVIEW",
                "WORKER_LOCK_REQUIRES_REVIEW"} <= set(evidence["issues"])
        assert journal.path.read_bytes() == before_audit
        assert retained.read_bytes() == b"retain native ownership"
        assert claim.is_dir() and worker.is_dir()
        assert protected.read_bytes() == b"must-stay-original"
        assert not list(dirs["future-config"].iterdir())
        assert sorted(p.name for p in dirs["future-runs"].iterdir()) == [
            ".guarded-native-worker.lock", ".guarded-request-interrupted.claim",
        ]
        return {"status": "PASS_READ_ONLY", "http_checks": checked,
                "guarded_routes_available": False, "originals_unchanged": True,
                "rollback_evidence": "RELEASE_HELD"}


def main() -> None:
    import json
    repo = Path(__file__).resolve().parents[1]
    commit = verify_clean_checkout(repo)
    outcome = run_readonly_release_smoke()
    print(json.dumps({"commit": commit, **outcome}, sort_keys=True))


if __name__ == "__main__":
    main()
