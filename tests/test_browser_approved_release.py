"""Approved-session composition is unlaunched; every test owns fresh fixtures."""
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest


def _fixture(tmp_path):
    from crypto_strategy_lab.browser_approved_release import ReleaseDeployment, prior_state_digest
    roots = {name: tmp_path / name for name in (
        'raw', 'original-cache', 'cache', 'original-config', 'original-output',
        'code', 'configuration', 'execution', 'audit', 'approval',
    )}
    for p in roots.values():
        p.mkdir()
    static = roots['code'] / 'dist'
    static.mkdir()
    index = static / 'index.html'
    index.write_text('ordinary build')
    deployment = ReleaseDeployment(
        commit='a' * 40, runtime_identity='fixture-account', port=8767,
        raw=roots['raw'], original_cache=roots['original-cache'], cache=roots['cache'],
        original_config=roots['original-config'], original_output=roots['original-output'],
        code=roots['code'], static=static, configuration=roots['configuration'],
        execution=roots['execution'], audit=roots['audit'], approval_root=roots['approval'],
        artifacts={'dist/index.html': hashlib.sha256(index.read_bytes()).hexdigest()},
    )
    receipt = {
        'schema': 1, 'decision': 'APPROVE_GUARDED_SESSION', 'session_id': 'fixture-1',
        'deployment_sha256': deployment.fingerprint(),
        'prior_state_sha256': prior_state_digest(deployment),
        'issued_at': '2026-10-19T00:00:00+00:00', 'expires_at': '2026-10-20T00:00:00+00:00',
        'release_owner': 'fixture-owner', 'review_reference': 'fixture-review',
        'accepted_limits': ['manual-uncertain-work-review', 'no-automatic-replay',
                            'bounded-audit-no-safe-rotation', 'finite-historical-evidence'],
    }
    path = roots['approval'] / 'approved.json'
    path.write_text(json.dumps(receipt))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return deployment, path, digest, receipt


def _compose(deployment, path, digest, **kwargs):
    import datetime
    from crypto_strategy_lab.browser_approved_release import compose_approved_release
    native = Mock(raw_root=deployment.raw, cache_root=deployment.cache)
    return compose_approved_release(
        deployment=deployment, approval_path=path, approved_record_sha256=digest,
        current_identity=lambda: 'fixture-account',
        clock=kwargs.pop('clock', lambda: datetime.datetime(2026, 10, 19, 12, tzinfo=datetime.timezone.utc)),
        native_factory=kwargs.pop('native_factory', lambda raw, cache: native), **kwargs,
    )


@pytest.mark.parametrize('pin', [None, '', True, 'true', '0' * 64])
def test_missing_or_wrong_trusted_pin_has_no_effects(tmp_path, pin):
    d, p, digest, _ = _fixture(tmp_path)
    native = Mock()
    with pytest.raises(PermissionError):
        _compose(d, p, pin, native_factory=native)
    native.assert_not_called()
    assert not list(d.execution.iterdir()) and not list(d.audit.iterdir())


@pytest.mark.parametrize('change', ['expiry', 'identity', 'code', 'prior-state', 'worker-lock'])
def test_stale_or_changed_deployment_refused_before_native_construction(tmp_path, change):
    d, p, digest, receipt = _fixture(tmp_path)
    if change == 'expiry':
        receipt['expires_at'] = '2026-10-19T01:00:00+00:00'
        p.write_text(json.dumps(receipt)); digest = hashlib.sha256(p.read_bytes()).hexdigest()
    elif change == 'identity':
        object.__setattr__(d, 'runtime_identity', 'another-account')
    elif change == 'code':
        (d.static / 'index.html').write_text('changed')
    elif change == 'prior-state':
        (d.audit / 'retained.jsonl').write_text('retained uncertain record')
    else:
        (d.execution / '.guarded-native-worker.lock').mkdir()
    native = Mock()
    with pytest.raises((PermissionError, ValueError)):
        _compose(d, p, digest, native_factory=native)
    native.assert_not_called()
    assert not list(d.execution.glob('.b4-release-*'))


def test_live_gate_matches_routes_and_revocation_denies_native_writes(tmp_path):
    from fastapi.testclient import TestClient
    d, p, digest, _ = _fixture(tmp_path)
    runtime = _compose(d, p, digest)
    auth = {'Authorization': 'Bearer ' + runtime.token}
    try:
        with TestClient(runtime.app, base_url='http://127.0.0.1:8767') as client:
            assert client.get('/api/v1/release/capabilities').status_code == 401
            assert client.get('/api/v1/health', headers=auth).json()['mode'] == 'guarded'
            assert client.get('/api/v1/release/capabilities', headers=auth).json() == {
                'execution': True, 'configuration_editing': True,
            }
            assert client.get('/api/v1/guarded/jobs/unknown', headers=auth).status_code == 404
            p.write_text('revoked')
            assert client.get('/api/v1/release/capabilities', headers=auth).json() == {
                'execution': False, 'configuration_editing': False,
            }
            assert client.put('/api/v1/guarded/configs/blocked', headers=auth, json={}).status_code == 503
            assert not list(d.configuration.iterdir())
    finally:
        runtime.close()
    assert list(d.execution.glob('.b4-release-*.claim'))
    assert list(d.audit.glob('*.jsonl'))


def test_audit_failure_closes_admission_and_cannot_reuse_approval(tmp_path):
    from fastapi.testclient import TestClient
    d, p, digest, _ = _fixture(tmp_path)
    runtime = _compose(d, p, digest)
    runtime.journal.close()
    with TestClient(runtime.app, base_url='http://127.0.0.1:8767') as client:
        auth = {'Authorization': 'Bearer ' + runtime.token}
        assert client.post('/api/v1/guarded/jobs', headers=auth, json={}).status_code == 503
    runtime.close()
    with pytest.raises(PermissionError):
        _compose(d, p, digest)


def test_original_configuration_read_and_new_save_use_separate_native_roots(tmp_path):
    from fastapi.testclient import TestClient
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig
    d, p, digest, _ = _fixture(tmp_path)
    original = d.original_config / 'saved.json'
    payload = ResearchRunConfig().to_dict()
    original.write_text(json.dumps(payload))
    before = original.read_bytes()
    runtime = _compose(d, p, digest)
    try:
        with TestClient(runtime.app, base_url='http://127.0.0.1:8767') as client:
            auth = {'Authorization': 'Bearer ' + runtime.token}
            assert client.get('/api/v1/configs/saved', headers=auth).status_code == 200
            assert client.put('/api/v1/guarded/configs/saved', headers=auth, json=payload).status_code == 200
            assert (d.configuration / 'saved.json').is_file()
            assert original.read_bytes() == before
            assert client.get('/api/v1/configs/saved', headers=auth).status_code == 200
    finally:
        runtime.close()


def test_revocation_during_body_stream_cannot_cross_native_admission(tmp_path):
    from fastapi.testclient import TestClient
    d, p, digest, _ = _fixture(tmp_path)
    runtime = _compose(d, p, digest)
    def body():
        yield b'{'
        p.write_text('revoked while reading request')
        yield b'}'
    try:
        with TestClient(runtime.app, base_url='http://127.0.0.1:8767') as client:
            response = client.put('/api/v1/guarded/configs/blocked', content=body(),
                headers={'Authorization': 'Bearer ' + runtime.token})
            assert response.status_code == 503
            assert not list(d.configuration.iterdir())
            assert 'ATTEMPT' not in runtime.journal.path.read_text()
    finally:
        runtime.close()


def test_concurrent_bootstraps_cannot_consume_one_approval_twice(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    d, p, digest, _ = _fixture(tmp_path)
    native = Mock(raw_root=d.raw, cache_root=d.cache)
    factory = Mock(return_value=native)
    def attempt():
        try:
            return _compose(d, p, digest, native_factory=factory)
        except PermissionError:
            return None
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: attempt(), range(2)))
    successful = [r for r in results if r is not None]
    assert len(successful) == 1
    successful[0].close()
    factory.assert_called_once()


def test_existing_empty_claim_changes_prior_state_digest(tmp_path):
    from crypto_strategy_lab.browser_approved_release import prior_state_digest
    d, _, _, _ = _fixture(tmp_path)
    before = prior_state_digest(d)
    (d.execution / '.guarded-request-retained.claim').mkdir()
    assert prior_state_digest(d) != before


def test_native_constructor_failure_retains_consumed_receipt_and_journal(tmp_path):
    d, p, digest, _ = _fixture(tmp_path)
    native = Mock(side_effect=OSError('fixture native initialization failure'))
    with pytest.raises(OSError):
        _compose(d, p, digest, native_factory=native)
    assert list(d.execution.glob('.b4-release-*.claim'))
    assert list(d.audit.glob('*.jsonl'))
    with pytest.raises(PermissionError):
        _compose(d, p, digest)


def test_preapproved_wrong_port_and_foreign_origin_do_not_touch_guarded_owner(tmp_path):
    from fastapi.testclient import TestClient
    d, p, digest, _ = _fixture(tmp_path)
    runtime = _compose(d, p, digest)
    try:
        with TestClient(runtime.app, base_url='http://127.0.0.1:8767') as client:
            auth = {'Authorization': 'Bearer ' + runtime.token}
            assert client.get('/api/v1/health', headers={**auth, 'Host': '127.0.0.1:8768'}).status_code == 403
            assert client.put('/api/v1/guarded/configs/no', json={},
                headers={**auth, 'Origin': 'http://127.0.0.1:8768'}).status_code == 403
            assert not list(d.configuration.iterdir())
    finally:
        runtime.close()


def test_operating_identity_reads_the_real_os_token():
    import os
    from crypto_strategy_lab.browser_approved_release import operating_identity
    actual = operating_identity()
    if os.name == 'nt':
        import csv
        import subprocess
        text = subprocess.check_output([str(Path(os.environ['SystemRoot']) / 'System32/whoami.exe'),
            '/user', '/fo', 'csv', '/nh'], text=True)
        assert actual == next(csv.reader(text.splitlines()))[1]
    else:
        assert actual == 'uid:' + str(os.geteuid())


def test_approval_for_another_account_is_denied_even_with_matching_deployment_hash(tmp_path):
    d, p, _, receipt = _fixture(tmp_path)
    object.__setattr__(d, 'runtime_identity', 'another-account')
    receipt['deployment_sha256'] = d.fingerprint()
    p.write_text(json.dumps(receipt))
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    with pytest.raises(PermissionError):
        _compose(d, p, digest)
    assert not list(d.audit.iterdir()) and not list(d.execution.iterdir())


def test_claim_flush_failure_retains_evidence_before_any_native_owner(tmp_path, monkeypatch):
    import os
    d, p, digest, _ = _fixture(tmp_path)
    native = Mock()
    monkeypatch.setattr(os, 'fsync', Mock(side_effect=OSError('fixture claim flush failed')))
    with pytest.raises(OSError, match='fixture claim flush failed'):
        _compose(d, p, digest, native_factory=native)
    native.assert_not_called()
    assert list(d.execution.glob('.b4-release-*.claim'))
    assert not list(d.audit.iterdir())


def test_session_claim_contains_flushed_receipt_marker_before_native_construction(tmp_path):
    d, p, digest, _ = _fixture(tmp_path)
    marker = d.execution / '.b4-release-fixture-1.claim' / 'approval.sha256'
    def native(raw, cache):
        assert marker.read_text() == digest + '\n'
        return Mock(raw_root=raw, cache_root=cache)
    runtime = _compose(d, p, digest, native_factory=native)
    runtime.close()


@pytest.mark.skipif(os.name != 'posix', reason='POSIX directory fsync; Windows power-loss durability unproven')
def test_parent_directory_flush_failure_blocks_native_construction(tmp_path, monkeypatch):
    import stat
    d, p, digest, _ = _fixture(tmp_path)
    native = Mock()
    original_fsync = os.fsync
    execution_inode = d.execution.stat().st_ino
    def fail_parent(fd):
        info = os.fstat(fd)
        if stat.S_ISDIR(info.st_mode) and info.st_ino == execution_inode:
            raise OSError('fixture parent directory flush failed')
        original_fsync(fd)
    monkeypatch.setattr(os, 'fsync', fail_parent)
    with pytest.raises(OSError, match='fixture parent directory flush failed'):
        _compose(d, p, digest, native_factory=native)
    native.assert_not_called()
    assert list(d.execution.glob('.b4-release-*.claim'))
    assert not list(d.audit.iterdir())


@pytest.mark.parametrize('kind', ['directory', 'file'])
def test_invalid_isolated_entry_shadows_original_portfolio_candidate(tmp_path, kind):
    from fastapi.testclient import TestClient
    from crypto_strategy_lab.browser_http import create_browser_app
    isolated, original = tmp_path / 'isolated', tmp_path / 'original'
    isolated.mkdir(); original.mkdir()
    entry = isolated / 'retained'
    entry.mkdir() if kind == 'directory' else entry.write_text('partial invalid run')
    read = Mock()
    read.portfolio_candidates.side_effect = lambda root: [] if Path(root) == isolated else [
        {'run_folder_id': 'retained'}, {'run_folder_id': 'unshadowed'}]
    token = 'p' * 48
    app = create_browser_app(token=token, read_service=read, completed_run_root=isolated,
        original_completed_run_root=original)
    with TestClient(app, base_url='http://localhost') as client:
        result = client.get('/api/v1/portfolio/candidates', headers={'Authorization': 'Bearer ' + token})
        assert result.status_code == 200
        assert result.json()['candidates'] == [{'run_folder_id': 'unshadowed'}]


def test_evidence_reads_allocate_only_observed_file_size_plus_sentinel(tmp_path, monkeypatch):
    from crypto_strategy_lab.browser_approved_release import _read
    path = tmp_path / 'small-evidence.json'
    payload = b'{"small":true}'
    path.write_bytes(payload)
    real_fdopen = os.fdopen
    class ObservedRead:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def fileno(self):
            return self.stream.fileno()
        def read(self, size):
            assert size == len(payload) + 1
            return self.stream.read(size)
    monkeypatch.setattr(os, 'fdopen', lambda fd, mode: ObservedRead(real_fdopen(fd, mode)))
    assert _read(path, 1024 ** 3) == payload
