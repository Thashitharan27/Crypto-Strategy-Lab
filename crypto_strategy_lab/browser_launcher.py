"""Optional production composition for the local read-only browser workspace.

This is the only browser runtime entrypoint. It composes existing CSL read
services and the existing authenticated FastAPI adapter; it does not expose
research execution, configuration writes, trading, or live-bot operations.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import secrets
from typing import Any

from crypto_strategy_lab.browser_http import create_browser_app
from crypto_strategy_lab.browser_release_preflight import (
    GuardedReleaseRoots, prepare_guarded_release_roots,
)
from crypto_strategy_lab.browser_visualizer_coordinator import BrowserVisualizerCoordinator
from crypto_strategy_lab.browser_readonly_service import build_browser_readonly_service
from crypto_strategy_lab.paths import (
    CONFIG_DIR,
    OUTPUT_DIR,
    PROJECT_ROOT,
    resolve_data_lake_runtime_paths,
)


@dataclass(frozen=True)
class BrowserReadOnlyRuntime:
    """Composed local browser runtime and its per-launch credentials."""

    app: Any
    token: str
    host: str
    port: int
    static_root: Path
    output_root: Path
    config_root: Path

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"


def _path_from_env(
    environ: Mapping[str, str],
    name: str,
    default: Path,
) -> Path:
    value = str(environ.get(name, "")).strip()
    return Path(value).expanduser() if value else Path(default)


def preflight_browser_guarded_release(
    *,
    configuration: Path,
    execution: Path,
    environ: Mapping[str, str] | None = None,
    static_root: Path | None = None,
    output_root: Path | None = None,
    config_root: Path | None = None,
) -> GuardedReleaseRoots:
    """Validate future isolated roots without constructing a writable server.

    Both existing desktop/browser saved roots, canonical Data Lake raw/cache
    and the served browser assets remain protected. Validation never grants
    release authorization; only the separately reviewed activation path can.
    """
    source = os.environ if environ is None else environ
    lake = resolve_data_lake_runtime_paths(source)
    assets = Path(static_root) if static_root is not None else PROJECT_ROOT / "browser_ui" / "dist"
    original_output = Path(output_root) if output_root is not None else _path_from_env(
        source, "CRYPTO_STRATEGY_LAB_OUTPUT_DIR", OUTPUT_DIR / "data_lake_v2",
    )
    original_config = Path(config_root) if config_root is not None else _path_from_env(
        source, "CRYPTO_STRATEGY_LAB_CONFIG_DIR", CONFIG_DIR / "data_lake",
    )
    return prepare_guarded_release_roots(
        configuration=configuration,
        execution=execution,
        protected_roots=(
            lake.raw_root, lake.cache_root, assets,
            OUTPUT_DIR, CONFIG_DIR, original_output, original_config,
        ),
    )


def build_browser_readonly_runtime(
    *,
    environ: Mapping[str, str] | None = None,
    token: str | None = None,
    port: int = 8767,
    static_root: str | Path | None = None,
    output_root: str | Path | None = None,
    config_root: str | Path | None = None,
    guarded_release_requested: bool = False,
) -> BrowserReadOnlyRuntime:
    """Compose the existing read-only browser pieces without starting a server."""

    # B4 preparation is not release approval. There is deliberately no
    # production code path that attaches guarded routes, even if a caller or
    # operator sets a feature-like environment variable.
    if guarded_release_requested is not False:
        raise PermissionError("Production browser mutations await separate release approval")
    if isinstance(port, bool) or not isinstance(port, int) or not (1 <= port <= 65535):
        raise ValueError("Browser port must be an integer from 1 to 65535")

    source = os.environ if environ is None else environ
    data_paths = resolve_data_lake_runtime_paths(source)
    effective_static_root = (
        Path(static_root)
        if static_root is not None
        else PROJECT_ROOT / "browser_ui" / "dist"
    )
    # The certification-only React build exposes experimental guarded controls.
    # Never serve that UI through the ordinary production read-only launcher,
    # even when the caller explicitly overrides its static distribution.
    # The separate operator-only certification server owns that bundle.
    if (effective_static_root.name == "dist-certification" or
            effective_static_root.resolve(strict=False).name == "dist-certification"):
        raise ValueError("Certification-only browser assets cannot be served in production")
    effective_output_root = (
        Path(output_root)
        if output_root is not None
        else _path_from_env(
            source,
            "CRYPTO_STRATEGY_LAB_OUTPUT_DIR",
            OUTPUT_DIR / "data_lake_v2",
        )
    )
    effective_config_root = (
        Path(config_root)
        if config_root is not None
        else _path_from_env(
            source,
            "CRYPTO_STRATEGY_LAB_CONFIG_DIR",
            CONFIG_DIR / "data_lake",
        )
    )
    runtime_token = token if token is not None else secrets.token_urlsafe(48)
    if not isinstance(runtime_token, str) or len(runtime_token) < 32:
        raise ValueError("A fresh, high-entropy browser token is required")

    read_service = build_browser_readonly_service(
        raw_root=data_paths.raw_root,
        cache_root=data_paths.cache_root,
    )
    coordinator = BrowserVisualizerCoordinator(
        read_service.application_service, effective_output_root,
    )
    app = create_browser_app(
        token=runtime_token,
        read_service=read_service,
        completed_run_root=effective_output_root,
        config_root=effective_config_root,
        static_root=effective_static_root,
        visualizer_coordinator=coordinator,
    )
    return BrowserReadOnlyRuntime(
        app=app,
        token=runtime_token,
        host="127.0.0.1",
        port=port,
        static_root=effective_static_root.resolve(),
        output_root=effective_output_root.resolve(),
        config_root=effective_config_root.resolve(),
    )


def run_browser_readonly(*, port: int = 8767) -> None:
    """Start the optional local read-only browser server on loopback only."""

    runtime = build_browser_readonly_runtime(port=port)
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise RuntimeError(
            "Browser runtime requires the optional 'uvicorn' package."
        ) from exc

    # Never put the token in a URL. The current shell accepts it through the
    # password field after launch.
    print(f"Crypto Strategy Lab read-only browser: {runtime.url}")
    print(f"Local session token: {runtime.token}")
    print("No browser execution or configuration writes are enabled.")
    uvicorn.run(
        runtime.app,
        host=runtime.host,
        port=runtime.port,
        log_level="info",
    )


def main() -> None:
    run_browser_readonly()


if __name__ == "__main__":
    main()
