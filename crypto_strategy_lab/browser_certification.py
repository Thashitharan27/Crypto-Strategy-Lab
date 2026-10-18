"""Isolated, opt-in certification composition; never a production launcher.

Only for independently exercising the certification-only React bundle against
existing guarded FastAPI/native owners. Fresh temporary config/output roots are
created for each session and deleted after close. Native market data sources
remain those of the injected authoritative application service.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory

from crypto_strategy_lab.browser_guarded_integration import BrowserGuardedIntegration
from crypto_strategy_lab.browser_http import create_browser_app
from crypto_strategy_lab.browser_readonly_service import BrowserReadOnlyService


@contextmanager
def isolated_browser_certification(
    *, native_application, static_root: Path, acknowledge_test_only: bool = False,
):
    """Yield (FastAPI app, bearer token) with no original-file mutation roots.

    The caller must explicitly supply the existing native application. There
    is intentionally no default path, environment-based opt-in, port listener,
    CLI entrypoint or persistent request/output root.
    """
    if acknowledge_test_only is not True:
        raise PermissionError("Explicit isolated certification opt-in required")
    root = Path(static_root)
    if (not root.is_absolute() or root.name != "dist-certification"
            or not root.is_dir() or not (root / "index.html").is_file()
            or any(part.is_symlink() for part in (root, *root.parents))
            or root.resolve(strict=True) != root):
        raise ValueError("Only a canonical separate certification build is allowed")
    if native_application is None or not callable(getattr(native_application, "run", None)):
        raise ValueError("Existing native application service required")

    with TemporaryDirectory(prefix="csl-browser-cert-") as scratch:
        temp_root = Path(scratch).resolve()
        config_root, output_root = temp_root / "configs", temp_root / "runs"
        config_root.mkdir()
        output_root.mkdir()
        integration = BrowserGuardedIntegration(
            native_application, config_root, enabled=True,
            execution_root=output_root,
        )
        token = secrets.token_urlsafe(48)
        # Reuse native completed-run and config readers. Only the explicitly
        # isolated roots are resolvable through the HTTP routes.
        service = BrowserReadOnlyService(
            getattr(native_application, "catalog", None),
            application_service=native_application,
        )
        app = create_browser_app(
            token=token, read_service=service,
            completed_run_root=output_root, config_root=config_root,
            static_root=root, guarded_integration=integration,
            guarded_enabled=True,
        )
        try:
            yield app, token
        finally:
            integration.close()
