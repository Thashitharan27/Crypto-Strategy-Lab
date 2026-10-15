import hashlib
import pytest

from crypto_strategy_lab.parity_fixture_manifest import file_fingerprint, frozen_fixture_manifest, verify_frozen_fixture_files

SHA = "a" * 40


def test_hashes_exact_bytes_and_portable_names(tmp_path):
    path = tmp_path / "trade_list.csv"
    content = b"id,pnl\\r\\n1,2\\r\\n"
    path.write_bytes(content)
    manifest = frozen_fixture_manifest(
        commit_sha=SHA, files={"trade_csv": path},
        strategy_timeframe_minutes=240, intrabar_timeframe_minutes=1,
    )
    assert manifest["files"]["trade_csv"] == {
        "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
    assert str(tmp_path) not in str(manifest)
    assert manifest["contract_version"] == 1


def test_changed_file_changes_fingerprint(tmp_path):
    p = tmp_path / "file"
    p.write_bytes(b"before")
    first = file_fingerprint(p)
    p.write_bytes(b"after")
    assert file_fingerprint(p) != first


@pytest.mark.parametrize("kwargs", [
    {"commit_sha": "invalid"},
    {"strategy_timeframe_minutes": 0},
    {"intrabar_timeframe_minutes": 241},
    {"files": {}},
])
def test_invalid_fixture_is_rejected(tmp_path, kwargs):
    p = tmp_path / "source"
    p.write_bytes(b"data")
    params = dict(commit_sha=SHA, files={"market_data": p},
                  strategy_timeframe_minutes=240, intrabar_timeframe_minutes=1)
    params.update(kwargs)
    with pytest.raises(ValueError):
        frozen_fixture_manifest(**params)


def test_missing_files_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="not a file"):
        file_fingerprint(tmp_path / "absent")


def test_frozen_files_verify_and_reject_mutated_bytes(tmp_path):
    p = tmp_path / "market_data.csv"
    p.write_bytes(b"2020-06-01,1")
    frozen = {"candles": file_fingerprint(p)}
    verify_frozen_fixture_files(frozen, {"candles": p})
    p.write_bytes(b"2020-06-01,2")
    with pytest.raises(ValueError, match="mismatch"):
        verify_frozen_fixture_files(frozen, {"candles": p})


def test_frozen_files_reject_missing_extra_and_invalid_digest(tmp_path):
    p = tmp_path / "market_data.csv"
    p.write_bytes(b"candles")
    frozen = {"candles": file_fingerprint(p)}
    with pytest.raises(ValueError, match="labels"):
        verify_frozen_fixture_files(frozen, {})
    with pytest.raises(ValueError, match="labels"):
        verify_frozen_fixture_files(frozen, {"candles": p, "unexpected": p})
    with pytest.raises(ValueError, match="invalid"):
        verify_frozen_fixture_files({"candles": {"sha256": "bad", "bytes": 7}}, {"candles": p})
    with pytest.raises(ValueError, match="invalid"):
        verify_frozen_fixture_files({"candles": {"sha256": frozen["candles"]["sha256"], "bytes": True}}, {"candles": p})


def test_stat_fingerprint_cannot_certify_identical_file_bytes(tmp_path):
    """Two same-size, same-mtime files can have different contents."""
    from crypto_strategy_lab.data.cache import stat_fingerprint
    p = tmp_path / "candles.zip"
    p.write_bytes(b"AAAA")
    before_stat = p.stat()
    before_metadata = stat_fingerprint(p)
    before_content = file_fingerprint(p)
    p.write_bytes(b"BBBB")
    import os
    os.utime(p, ns=(before_stat.st_atime_ns, before_stat.st_mtime_ns))
    assert stat_fingerprint(p) == before_metadata
    assert file_fingerprint(p)["sha256"] != before_content["sha256"]
