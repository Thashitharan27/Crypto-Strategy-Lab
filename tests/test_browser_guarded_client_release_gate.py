"""Release guard: experimental browser mutations remain unreachable in the shipped app.

These source-level invariants supplement, not replace, HTTP authorization tests.
"""
from pathlib import Path

from crypto_strategy_lab.browser_guarded_integration import BrowserGuardedIntegration


ROOT = Path(__file__).resolve().parents[1]


def test_production_react_app_does_not_mount_guarded_controls():
    source = (ROOT / "browser_ui" / "src" / "main.tsx").read_text(encoding="utf-8")
    assert "GuardedRunControls" not in source
    assert "saveGuardedConfig" not in source
    assert "submitGuardedRun" not in source
    assert "/api/v1/guarded/" not in source


def test_experimental_component_requires_explicit_client_opt_in():
    source = (ROOT / "browser_ui" / "src" / "GuardedRunControls.tsx").read_text(
        encoding="utf-8"
    )
    assert "enabled = false" in source
    assert 'if (enabled !== true) return null' in source
    assert 'if (enabled !== true) throw new Error("Guarded operations are disabled")' in source
    assert 'credentials: "omit"' in source
    assert 'redirect: "error"' in source


def test_server_integration_still_denies_mutations_by_default(tmp_path):
    class ForbiddenNativeService:
        def run(self, *_args, **_kwargs):
            raise AssertionError("Never execute from a disabled browser")

    integration = BrowserGuardedIntegration(
        ForbiddenNativeService(), tmp_path, execution_root=tmp_path,
    )
    try:
        try:
            integration.submit("unapproved", object(), object())
        except PermissionError:
            pass
        else:
            raise AssertionError("Server must refuse disabled execution")
        assert not (tmp_path / ".guarded-request-unapproved.claim").exists()
    finally:
        integration.close()


def test_guarded_client_session_epoch_and_executable_browser_build_gate():
    component = (ROOT / "browser_ui" / "src" / "GuardedRunControls.tsx").read_text(encoding="utf-8")
    package = (ROOT / "browser_ui" / "package.json").read_text(encoding="utf-8")
    assert "configSelection.current.version + 1" in component
    assert "configSelection.current.version === selection.version" in component
    assert "setConfigJson(\"{}\")" in component
    assert "session.current.version + 1" in component
    assert "session.current.version === submittedSession.version" in component
    assert "if (isCurrent()) setState" in component
    assert "jobSelection.current.version === selectedJob.version" in component
    assert "setPhase(result.phase" in component
    assert "requireGuardedSession(enabled, token)" in component
    assert "npm run test:guarded && tsc -b && vite build" in package
