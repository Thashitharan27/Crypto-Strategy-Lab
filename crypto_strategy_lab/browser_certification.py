"""Isolated, opt-in certification composition; never a production launcher.

Only for independently exercising the certification-only React bundle against
existing guarded FastAPI/native owners. Fresh temporary config/output roots are
created for each session and deleted after close. Native market data sources
remain those of the injected authoritative application service.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import os
import secrets
import shutil
from tempfile import TemporaryDirectory

from crypto_strategy_lab.browser_guarded_integration import BrowserGuardedIntegration
from crypto_strategy_lab.browser_http import create_browser_app
from crypto_strategy_lab.browser_readonly_service import BrowserReadOnlyService


@contextmanager
def isolated_browser_certification(
    *, native_application, static_root: Path, acknowledge_test_only: bool = False,
    evidence_root: Path | None = None,
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

    # Optional evidence is strictly opt-in, exclusive-create, and can never
    # overwrite existing original files or a previous certification.
    evidence = None
    if evidence_root is not None:
        evidence = Path(evidence_root)
        if (not evidence.is_absolute()
                or not evidence.name.startswith("csl-browser-evidence-")
                or evidence.exists() or evidence.is_symlink()
                or not evidence.parent.is_dir()
                or any(part.is_symlink() for part in (evidence.parent, *evidence.parent.parents))
                or evidence.parent.resolve(strict=True) != evidence.parent):
            raise ValueError("Evidence destination must be a new canonical csl-browser-evidence-* directory")
        os.mkdir(evidence, mode=0o700)

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
            try:
                integration.close()
            finally:
                # Preserve only this session's ephemeral evidence after native
                # workers finish, even when the server exits with an error.
                # Do not infer certification success from copying files.
                if evidence is not None:
                    shutil.copytree(config_root, evidence / "configs")
                    shutil.copytree(output_root, evidence / "runs")


def serve_isolated_browser_certification(
    *, native_application, static_root: Path, port: int,
    acknowledge_test_only: bool = False,
    evidence_root: Path | None = None,
) -> None:
    """Serve test-only UI/API on loopback, never on public interfaces.

    This intentionally requires a caller-owned native application and
    the separately built certification assets. It has no CLI/production
    integration, auto-enable flag, or access to user-provided write roots.
    """
    if acknowledge_test_only is not True:
        raise PermissionError("Explicit isolated certification opt-in required")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Certification port must be in 1..65535")
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("Optional certification runtime requires uvicorn") from exc

    with isolated_browser_certification(
        native_application=native_application,
        static_root=static_root,
        acknowledge_test_only=True,
        evidence_root=evidence_root,
    ) as (app, token):
        # Token remains in the local operator terminal and never in a URL.
        print(f"CSL isolated browser certification: http://127.0.0.1:{port}/")
        print(f"Isolated certification token: {token}")
        print("TEST ONLY: no normal browser writes or execution enabled.")
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
