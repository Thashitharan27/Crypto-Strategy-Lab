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
