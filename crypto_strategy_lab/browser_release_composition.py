"""B4 reviewed composition contract; production mutation activation is absent.

This factory deliberately reuses the sole read-only production launcher and
the already validated dedicated-root preflight. It does not construct a
BrowserGuardedIntegration or mount any guarded endpoint. The actual guarded
native owner continues to be exercised only by the isolated certification app
until a separate approved release change is implemented.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from crypto_strategy_lab.browser_launcher import (
    BrowserReadOnlyRuntime, build_browser_readonly_runtime,
    preflight_browser_guarded_release,
)
from crypto_strategy_lab.browser_release_preflight import GuardedReleaseRoots


@dataclass(frozen=True)
class B4ReviewOnlyComposition:
    """Actual read-only app plus validated future roots; not authorization."""

    runtime: BrowserReadOnlyRuntime
    candidate_roots: GuardedReleaseRoots
    guarded_enabled: bool = False
    user_release_approved: bool = False


def compose_b4_review_only(
    *,
    configuration: Path,
    execution: Path,
    environ: Mapping[str, str] | None = None,
    static_root: Path | None = None,
    output_root: Path | None = None,
    config_root: Path | None = None,
    token: str | None = None,
    port: int = 8767,
    release_requested: bool = False,
) -> B4ReviewOnlyComposition:
    """Exercise the future deployment layout without enabling writes or runs.

    The public production read-only launcher and its route selection are
    authoritative. This composition has no approval secret, flag, environment
    shortcut or mutable alternate route. Every activation attempt is denied
    before the read service or HTTP app is constructed.
    """
    if release_requested is not False:
        raise PermissionError("B4 release preparation does not authorize activation")
    roots = preflight_browser_guarded_release(
        configuration=configuration,
        execution=execution,
        environ=environ,
        static_root=static_root,
        output_root=output_root,
        config_root=config_root,
    )
    runtime = build_browser_readonly_runtime(
        environ=environ,
        token=token,
        port=port,
        static_root=static_root,
        output_root=output_root,
        config_root=config_root,
        guarded_release_requested=False,
    )
    return B4ReviewOnlyComposition(runtime=runtime, candidate_roots=roots)


@dataclass(frozen=True)
class B4GuardedCandidate:
    """Guarded FastAPI candidate for independent tests; not a running server."""

    app: object
    token: str
    roots: GuardedReleaseRoots
    integration: object
    host: str = "127.0.0.1"

    def close(self) -> None:
        self.integration.close()


def compose_b4_guarded_candidate(
    *,
    native_application: object,
    configuration: Path,
    execution: Path,
    audit_callback,
    approval_granted: bool = False,
    environ: Mapping[str, str] | None = None,
    static_root: Path | None = None,
    output_root: Path | None = None,
    config_root: Path | None = None,
    token: str | None = None,
) -> B4GuardedCandidate:
    """Prepare a guarded candidate only for an explicitly reviewed invocation.

    The ordinary production launcher never imports or calls this factory.
    A boolean argument is deliberately NOT sourced from the environment or
    the browser. No production launch option/CLI is added by this change.
    No process is started; the caller owns the native integration lifetime.
    """
    if approval_granted is not True:
        raise PermissionError("B4 guarded production candidate is not approved")
    if not callable(audit_callback):
        raise ValueError("A dedicated bounded audit callback is required")
    if native_application is None or not callable(getattr(native_application, "run", None)):
        raise ValueError("Authoritative native application service required")
    import secrets
    from crypto_strategy_lab.browser_guarded_integration import BrowserGuardedIntegration
    from crypto_strategy_lab.browser_readonly_service import BrowserReadOnlyService
    from crypto_strategy_lab.browser_http import create_browser_app

    roots = preflight_browser_guarded_release(
        configuration=configuration, execution=execution, environ=environ,
        static_root=static_root, output_root=output_root, config_root=config_root,
    )
    if token is None:
        token = secrets.token_urlsafe(48)
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("Strong per-session bearer token required")
    integration = BrowserGuardedIntegration(
        native_application, roots.configuration, enabled=True,
        execution_root=roots.execution,
    )
    read_service = BrowserReadOnlyService(
        getattr(native_application, "catalog", None),
        application_service=native_application,
    )
    try:
        app = create_browser_app(
            token=token, read_service=read_service,
            completed_run_root=roots.execution, config_root=roots.configuration,
            static_root=static_root, guarded_integration=integration,
            guarded_enabled=True, guarded_audit_callback=audit_callback,
        )
    except BaseException:
        integration.close()
        raise
    return B4GuardedCandidate(
        app=app, token=token, roots=roots, integration=integration,
    )
