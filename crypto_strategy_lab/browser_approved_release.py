"""Explicit, unlaunched release composition for a trusted operator bootstrap.

No CLI, environment switch or HTTP parameter can supply the trusted approval
digest. The reviewed, account-read-only bootstrap must pin it out of band, after
the release owner's decision. A digest computed from an untrusted receipt is NOT
authorization. This module neither issues approvals nor starts a listener.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
from types import MappingProxyType
from collections.abc import Callable, Mapping

from crypto_strategy_lab.browser_release_preflight import (
    _nonlink_canonical_directory, _overlaps, prepare_guarded_release_roots,
)

_SHA = re.compile(r'[0-9a-f]{64}\Z')
_SESSION = re.compile(r'[A-Za-z0-9_-]{1,64}\Z')
_LIMITS = frozenset({'manual-uncertain-work-review', 'no-automatic-replay',
                     'bounded-audit-no-safe-rotation', 'finite-historical-evidence'})


def operating_identity() -> str:
    """Read the effective OS identity; never trust environment/user arguments."""
    if os.name != 'nt':
        return 'uid:' + str(os.geteuid())
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    api = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    api.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    api.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                       wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    api.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    token = wintypes.HANDLE()
    if not api.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
        raise OSError('Cannot inspect runtime token')
    text = wintypes.LPWSTR()
    try:
        needed = wintypes.DWORD()
        api.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
        if not 0 < needed.value < 65536:
            raise OSError('Unexpected runtime token size')
        buffer = ctypes.create_string_buffer(needed.value)
        if not api.GetTokenInformation(token, 1, buffer, needed, ctypes.byref(needed)):
            raise OSError('Cannot read runtime token')
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        if not api.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            raise OSError('Cannot read runtime SID')
        return text.value
    finally:
        if text:
            kernel.LocalFree(ctypes.cast(text, ctypes.c_void_p))
        kernel.CloseHandle(token)


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def _read(path: Path, limit: int) -> bytes:
    _nonlink_canonical_directory(path.parent)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or getattr(before, 'st_file_attributes', 0) & 0x400:
        raise PermissionError('Release evidence must be a regular non-reparse file')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_ino, opened.st_dev) != (before.st_ino, before.st_dev) or opened.st_size > limit:
            raise PermissionError('Release evidence changed or exceeds bounds')
        # The cap is a rejection boundary, not an allocation request. Keep one
        # extra byte to observe growth without allocating 1 GiB per tiny file.
        content = stream.read(opened.st_size + 1)
        after = path.lstat()
        keys = lambda s: (s.st_ino, s.st_dev, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if len(content) > limit or keys(opened) != keys(after):
            raise PermissionError('Release evidence changed while reading')
    return content


def _files(root: Path, *, directories=False):
    pending = [root]
    count = 0
    while pending:
        current = pending.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                count += 1
                if count > 100_000:
                    raise PermissionError('Release inventory exceeds bounds')
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise PermissionError('Release inventory contains a link/reparse object')
                path = Path(entry.path)
                if stat.S_ISDIR(info.st_mode):
                    pending.append(path)
                    if directories:
                        yield path
                elif stat.S_ISREG(info.st_mode):
                    yield path
                else:
                    raise PermissionError('Unexpected release inventory object')


@dataclass(frozen=True)
class ReleaseDeployment:
    commit: str
    runtime_identity: str
    port: int
    raw: Path
    original_cache: Path
    cache: Path
    original_config: Path
    original_output: Path
    code: Path
    static: Path
    configuration: Path
    execution: Path
    audit: Path
    approval_root: Path
    artifacts: Mapping[str, str] = field(repr=False)

    def __post_init__(self):
        object.__setattr__(self, 'artifacts', MappingProxyType(dict(self.artifacts)))

    def fingerprint(self) -> str:
        return _digest({k: dict(v) if k == 'artifacts' else str(v) if isinstance(v, Path) else v
                        for k, v in vars(self).items()})

    def validate(self):
        if (not isinstance(self.commit, str) or not re.fullmatch(r'[0-9a-f]{40}', self.commit)
                or not isinstance(self.runtime_identity, str) or not 1 <= len(self.runtime_identity) <= 200):
            raise PermissionError('Missing reviewed code/identity binding')
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise PermissionError('Invalid release port')
        for value in vars(self).values():
            if isinstance(value, Path):
                _nonlink_canonical_directory(value)
        protected = (self.raw, self.original_cache, self.original_config,
                     self.original_output, self.code, self.approval_root)
        if any(_overlaps(self.approval_root, p) for p in protected[:-1]):
            raise PermissionError('Approval root must be separate from code and originals')
        prepare_guarded_release_roots(configuration=self.configuration, execution=self.execution,
                                      protected_roots=protected + (self.cache, self.audit))
        for other in protected + (self.cache, self.configuration, self.execution):
            if _overlaps(self.audit, other):
                raise PermissionError('Audit root overlaps another release resource')
        for other in protected + (self.configuration, self.execution, self.audit):
            if _overlaps(self.cache, other):
                raise PermissionError('Runtime cache overlaps another release resource')
        if not self.static.is_relative_to(self.code) or self.static.name == 'dist-certification':
            raise PermissionError('Ordinary assets must belong to reviewed code')
        if not (self.static / 'index.html').is_file():
            raise PermissionError('Ordinary browser index is unavailable')
        actual = {p.relative_to(self.code).as_posix() for p in _files(self.code)}
        if not self.artifacts or actual != set(self.artifacts):
            raise PermissionError('Reviewed code inventory differs')
        for relative, expected in self.artifacts.items():
            p = Path(relative)
            if p.is_absolute() or '..' in p.parts or p.as_posix() != relative or not _SHA.fullmatch(expected):
                raise PermissionError('Unsafe release artifact binding')
            if hashlib.sha256(_read(self.code / p, 1024 ** 3)).hexdigest() != expected:
                raise PermissionError('Reviewed release artifact changed')


def prior_state_digest(deployment: ReleaseDeployment) -> str:
    """Seal prior evidence, never reconcile/replay/delete it. Bounded to 1 GiB."""
    result = {}
    total = 0
    for role in ('configuration', 'execution', 'audit'):
        root = _nonlink_canonical_directory(getattr(deployment, role))
        # Any worker ownership object, including a malformed one, is a hold.
        if role == 'execution':
            try:
                (root / '.guarded-native-worker.lock').lstat()
            except FileNotFoundError:
                pass
            else:
                raise PermissionError('Native worker ownership requires review')
        for p in _files(root, directories=True):
            key = role + '/' + p.relative_to(root).as_posix()
            if p.is_dir():
                result[key] = 'DIRECTORY'
                continue
            content = _read(p, 1024 ** 3)
            total += len(content)
            if total > 1024 ** 3:
                raise PermissionError('Prior release evidence exceeds bounds')
            result[key] = hashlib.sha256(content).hexdigest()
    return _digest(result)


class ApprovedRelease:
    def __init__(self, *, deployment, app, token, integration, journal, close_gate, visualizer):
        self.deployment, self.app, self.token = deployment, app, token
        self.integration, self.journal = integration, journal
        self.host, self.port = '127.0.0.1', deployment.port
        self._close_gate = close_gate
        self.visualizer = visualizer
        self._closed = False

    def close(self):
        if not self._closed:
            self._closed = True
            self._close_gate()
            try:
                self.integration.close()  # Wait, never pretend to cancel native work.
            finally:
                try:
                    self.journal.close()
                finally:
                    self.visualizer.stop()


def compose_approved_release(*, deployment: ReleaseDeployment, approval_path: Path,
                             approved_record_sha256: str | None = None,
                             current_identity: Callable[[], str] = operating_identity,
                             clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                             native_factory=None) -> ApprovedRelease:
    """Trusted-bootstrap API only; no environment/CLI/HTTP approval source.

    Missing, changed, expired or spent approvals cannot construct native owners.
    The bootstrap must verify actual identity/ACLs and pin the reviewed receipt
    hash outside runtime-controlled inputs; this API is not an OS sandbox.
    """
    if not isinstance(approved_record_sha256, str) or not _SHA.fullmatch(approved_record_sha256):
        raise PermissionError('Trusted operator approval pin required')
    deployment.validate()
    path = Path(approval_path)
    if path.parent != deployment.approval_root:
        raise PermissionError('Approval must belong to the trusted approval root')
    data = _read(path, 65536)
    if hashlib.sha256(data).hexdigest() != approved_record_sha256:
        raise PermissionError('Approval does not match trusted operator pin')
    try:
        receipt = json.loads(data)
        session = receipt['session_id']
        prior_digest = receipt['prior_state_sha256']
        issued, expires = (datetime.fromisoformat(receipt[k]) for k in ('issued_at', 'expires_at'))
        if (type(receipt['schema']) is not int or receipt['schema'] != 1
                or receipt['decision'] != 'APPROVE_GUARDED_SESSION'
                or not _SESSION.fullmatch(session)
                or not _SHA.fullmatch(prior_digest)
                or not receipt['release_owner'] or not receipt['review_reference']
                or not isinstance(receipt['accepted_limits'], list) or len(receipt['accepted_limits']) != len(_LIMITS)
                or set(receipt['accepted_limits']) != _LIMITS
                or receipt['deployment_sha256'] != deployment.fingerprint()
                or current_identity() != deployment.runtime_identity
                or issued.utcoffset() is None or expires.utcoffset() is None
                or not 0 < (expires - issued).total_seconds() <= 86400
                or not issued <= clock() < expires):
            raise ValueError('Approval binding invalid')
    except (ValueError, KeyError, TypeError) as exc:
        raise PermissionError('Release approval invalid or expired') from exc
    if prior_digest != prior_state_digest(deployment):
        raise PermissionError('Prior release state differs from owner review')
    # Atomic single-use admission. Retain even if later construction fails.
    claim = deployment.execution / ('.b4-release-' + session + '.claim')
    try:
        claim.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise PermissionError('Release approval already consumed') from exc
    # Persist a receipt marker before constructing any native/audit owner. Keep
    # both objects on failure. POSIX also flushes the parent directory, matching
    # native request claims; Windows hardware power-loss durability is unproven.
    with (claim / 'approval.sha256').open('xb') as marker:
        marker.write((approved_record_sha256 + '\n').encode('ascii'))
        marker.flush()
        os.fsync(marker.fileno())
    if os.name == 'posix':
        fd = os.open(claim, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        fd = os.open(deployment.execution, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    from crypto_strategy_lab.browser_release_audit import B4AuditJournal
    from crypto_strategy_lab.browser_guarded_integration import BrowserGuardedIntegration
    from crypto_strategy_lab.browser_readonly_service import BrowserReadOnlyService
    from crypto_strategy_lab.browser_http import create_browser_app
    journal = None
    integration = None
    closed = False

    def stop_gate():
        nonlocal closed
        closed = True

    def gate():
        nonlocal closed
        if closed:
            return False
        try:
            if (not issued <= clock() < expires or current_identity() != deployment.runtime_identity
                    or hashlib.sha256(_read(path, 65536)).hexdigest() != approved_record_sha256
                    or not journal.available()):
                closed = True
        except Exception:
            closed = True
        return not closed

    try:
        journal = B4AuditJournal(deployment.audit, session)
        journal({'operation': 'STATUS', 'outcome': 'SUCCESS'})
        if native_factory is None:
            from crypto_strategy_lab.gui.v2_controller import GuiApplicationService
            native_factory = GuiApplicationService
        native = native_factory(deployment.raw, deployment.cache)
        if Path(native.raw_root) != deployment.raw or Path(native.cache_root) != deployment.cache:
            raise PermissionError('Native service roots differ from approved deployment')
        integration = BrowserGuardedIntegration(native, deployment.configuration, enabled=True,
                                                execution_root=deployment.execution)
        if not gate():
            raise PermissionError('Release approval unavailable after native initialization')
        token = secrets.token_urlsafe(48)
        from crypto_strategy_lab.browser_visualizer_coordinator import BrowserVisualizerCoordinator
        visualizer = BrowserVisualizerCoordinator(native, deployment.execution,
            original_completed_run_root=deployment.original_output)
        result = ApprovedRelease(deployment=deployment, app=None, token=token,
                                 integration=integration, journal=journal, close_gate=stop_gate,
                                 visualizer=visualizer)
        result.app = create_browser_app(
            token=token, read_service=BrowserReadOnlyService(native.catalog, application_service=native),
            completed_run_root=deployment.execution, config_root=deployment.configuration,
            static_root=deployment.static, guarded_integration=integration, guarded_enabled=True,
            guarded_audit_callback=journal, guarded_require_audit_admission=True,
            guarded_release_gate=gate, guarded_release_close=result.close,
            guarded_release_origin=f'http://127.0.0.1:{deployment.port}',
            original_config_root=deployment.original_config,
            original_completed_run_root=deployment.original_output,
            visualizer_coordinator=visualizer,
        )
        return result
    except BaseException:
        stop_gate()
        try:
            if integration is not None:
                integration.close()
        finally:
            if journal is not None:
                journal.close()
        raise
