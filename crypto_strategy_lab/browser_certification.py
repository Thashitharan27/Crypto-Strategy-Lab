"""Isolated, opt-in certification composition; never a production launcher.

Only for independently exercising the certification-only React bundle against
existing guarded FastAPI/native owners. Normal sessions use fresh temporary
config/output roots. Explicit crash testing can retain an operator-owned
isolated execution root across restarts. Native market data sources
remain those of the injected authoritative application service.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import os
import secrets
import shutil
import re
import stat
from tempfile import TemporaryDirectory

_CRASH_ROOT_MARKER = ".csl-browser-crash-test-only"
_CRASH_ROOT_MARKER_CONTENT = b"CSL_BROWSER_CRASH_CERT_V1"


def _unsafe_reparse_path(path: Path) -> bool:
    """Reject symlinks, NTFS junctions and other Windows reparse points."""
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _validated_crash_execution_root(path: Path) -> Path:
    """Operator-prepared, marker-protected root; never create or clean it."""
    path = Path(path)
    if (not path.is_absolute() or not path.name.startswith("csl-browser-crash-")
            or not path.is_dir() or any(_unsafe_reparse_path(part) for part in (path, *path.parents))
            or path.resolve(strict=True) != path):
        raise ValueError("Unsafe persistent certification execution root")
    marker = path / _CRASH_ROOT_MARKER
    if (not marker.is_file() or _unsafe_reparse_path(marker)
            or marker.read_bytes() != _CRASH_ROOT_MARKER_CONTENT
            or any(_unsafe_reparse_path(item) for item in path.rglob("*"))):
        raise ValueError("Persistent certification root requires a test-only marker and no links")
    return path

from crypto_strategy_lab.browser_guarded_integration import BrowserGuardedIntegration
from crypto_strategy_lab.browser_http import create_browser_app
from crypto_strategy_lab.browser_readonly_service import BrowserReadOnlyService


@contextmanager
def isolated_browser_certification(
    *, native_application, static_root: Path, acknowledge_test_only: bool = False,
    evidence_root: Path | None = None,
    frozen_config_path: Path | None = None,
    persistent_execution_root: Path | None = None,
):
    """Yield (FastAPI app, bearer token) with no original-file mutation roots.

    The caller must explicitly supply the existing native application. There
    is intentionally no default path, environment-based opt-in or automatic
    persistent-root creation. Crash mode requires a separately prepared marker.
    """
    if acknowledge_test_only is not True:
        raise PermissionError("Explicit isolated certification opt-in required")
    root = Path(static_root)
    if (not root.is_absolute() or root.name != "dist-certification"
            or not root.is_dir() or not (root / "index.html").is_file()
            or any(_unsafe_reparse_path(part) for part in (root, *root.parents))
            or any(_unsafe_reparse_path(part) for part in root.rglob("*"))
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
                or any(_unsafe_reparse_path(part) for part in (evidence.parent, *evidence.parent.parents))
                or evidence.parent.resolve(strict=True) != evidence.parent):
            raise ValueError("Evidence destination must be a new canonical csl-browser-evidence-* directory")

    if persistent_execution_root is not None and evidence is not None:
        raise ValueError("Persistent crash root and evidence-copy mode are mutually exclusive")
    crash_root = (_validated_crash_execution_root(persistent_execution_root)
                  if persistent_execution_root is not None else None)

    with TemporaryDirectory(prefix="csl-browser-cert-") as scratch:
        temp_root = Path(scratch).resolve()
        config_root = temp_root / "configs"
        output_root = crash_root if crash_root is not None else temp_root / "runs"
        config_root.mkdir()
        if crash_root is None:
            output_root.mkdir()
        if frozen_config_path is not None:
            # Import an explicitly selected original *read-only*, without
            # modifying its bytes or sending the original path to the client.
            from crypto_strategy_lab.gui.v2_controller import GuiApplicationService

            source = Path(frozen_config_path)
            config_id = source.stem
            if (not source.is_absolute() or source.suffix != ".json"
                    or re.fullmatch(r"[A-Za-z0-9_-]{1,100}", config_id, flags=re.ASCII) is None
                    or not source.is_file()
                    or any(_unsafe_reparse_path(part) for part in (source, *source.parents))
                    or source.resolve(strict=True) != source):
                raise ValueError("Unsafe frozen native configuration source")
            original = source.read_bytes()
            if len(original) > 4 * 1024 * 1024:
                raise ValueError("Frozen configuration exceeds guarded JSON limit")
            # Validate the exact bytes that will be served, rather than
            # reopening a mutable original after the read (TOCTOU).
            seeded = config_root / source.name
            seeded.write_bytes(original)
            native_config = GuiApplicationService.load_config(seeded)
            native_config.validate()
            # The source is never opened for writing. Browser GET uses the
            # original safe saved ID from the isolated copy.
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
        try:
            app = create_browser_app(
                token=token, read_service=service,
                completed_run_root=output_root, config_root=config_root,
                static_root=root, guarded_integration=integration,
                guarded_enabled=True,
            )
        except BaseException:
            # No ASGI lifespan exists to close this coordinator if
            # application composition itself fails.
            integration.close()
            raise
        # Reserve an evidence directory only after *all* native input and
        # application-composition checks succeeded. A failed factory setup
        # must not leave an empty operator evidence destination behind.
        try:
            if evidence is not None:
                os.mkdir(evidence, mode=0o700)
        except BaseException:
            # The native coordinator is already constructed. A failed
            # exclusive evidence reservation must not leak its worker pool.
            integration.close()
            raise
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
                    # Never follow an output symlink into original data.
                    for source in (config_root, output_root):
                        if any(_unsafe_reparse_path(path) for path in source.rglob("*")):
                            raise ValueError("Unsafe symlink or reparse point in certification evidence")
                    shutil.copytree(config_root, evidence / "configs")
                    shutil.copytree(output_root, evidence / "runs")


def serve_isolated_browser_certification(
    *, native_application, static_root: Path, port: int,
    acknowledge_test_only: bool = False,
    evidence_root: Path | None = None,
    frozen_config_path: Path | None = None,
    persistent_execution_root: Path | None = None,
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
        frozen_config_path=frozen_config_path,
        persistent_execution_root=persistent_execution_root,
    ) as (app, token):
        # Token remains in the local operator terminal and never in a URL.
        print(f"CSL isolated browser certification: http://127.0.0.1:{port}/")
        print(f"Isolated certification token: {token}")
        print("TEST ONLY: no normal browser writes or execution enabled.")
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
