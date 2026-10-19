"""Read-only B4 crash evidence must never imply replay or native completion."""
from pathlib import Path
from unittest.mock import patch

import pytest

from crypto_strategy_lab.browser_release_reconciliation import inspect_b4_recovery


def test_missing_claims_are_not_completed_or_replayed(tmp_path):
    with patch("crypto_strategy_lab.browser_release_reconciliation.verify_recovered_run") as verify:
        report = inspect_b4_recovery(tmp_path, "request-1")
    assert report == {
        "request_id": "request-1",
        "request_status": "RECOVERY_UNVERIFIED",
        "claim_present": False,
        "worker_lock_present": False,
        "saved_run_folder_id": None,
        "saved_artifacts_status": "NOT_CHECKED",
        "request_to_run_mapping": "UNVERIFIED",
    }
    verify.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_stale_worker_and_request_claim_remain_intact(tmp_path):
    lock = tmp_path / ".guarded-native-worker.lock"
    claim = tmp_path / ".guarded-request-safe.claim"
    lock.mkdir()
    claim.mkdir()
    marker = claim / "keep.bin"
    marker.write_bytes(b"operator evidence")
    report = inspect_b4_recovery(tmp_path, "safe")
    assert report["claim_present"] is True
    assert report["worker_lock_present"] is True
    assert report["request_status"] == "RECOVERY_UNVERIFIED"
    assert marker.read_bytes() == b"operator evidence"
    assert lock.is_dir() and claim.is_dir()


def test_verified_native_artifact_does_not_resolve_request_identity(tmp_path):
    (tmp_path / ".guarded-request-request1.claim").mkdir()
    (tmp_path / "native-folder").mkdir()
    with patch("crypto_strategy_lab.browser_release_reconciliation.verify_recovered_run",
               return_value={"run_id": "native-folder", "status": "ARTIFACTS_VERIFIED"}) as verify:
        report = inspect_b4_recovery(tmp_path, "request1", run_folder_id="native-folder")
    verify.assert_called_once_with(tmp_path, "native-folder")
    assert report["saved_artifacts_status"] == "ARTIFACTS_VERIFIED"
    assert report["request_to_run_mapping"] == "UNVERIFIED"
    assert report["request_status"] == "RECOVERY_UNVERIFIED"


def test_corrupt_or_absent_native_outputs_never_claim_success(tmp_path):
    for filename in ("missing", "bad"):
        report = inspect_b4_recovery(tmp_path, "request1", run_folder_id=filename)
        assert report["saved_artifacts_status"] == "RECOVERY_UNVERIFIED"
        assert report["request_status"] == "RECOVERY_UNVERIFIED"


@pytest.mark.parametrize("bad", ["", "../escape", "dot.bad", "é", "x" * 101])
def test_invalid_identifiers_rejected_before_filesystem_access(tmp_path, bad):
    with patch("crypto_strategy_lab.browser_release_reconciliation._safe_root") as root:
        with pytest.raises(ValueError):
            inspect_b4_recovery(tmp_path, bad)
        with pytest.raises(ValueError):
            inspect_b4_recovery(tmp_path, "safe", run_folder_id=bad)
    root.assert_not_called()


def test_unsafe_root_or_symlink_claim_fails_closed(tmp_path):
    external = tmp_path / "external"
    external.mkdir()
    root = tmp_path / "isolated"
    root.mkdir()
    link = tmp_path / "alias"
    try:
        link.symlink_to(root, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Filesystem links unavailable")
    report = inspect_b4_recovery(link, "safe")
    assert report["claim_present"] is None
    assert report["worker_lock_present"] is None
    target = root / ".guarded-request-safe.claim"
    target.symlink_to(external, target_is_directory=True)
    report = inspect_b4_recovery(root, "safe")
    assert report["claim_present"] is None
    assert not list(external.iterdir())


def test_claim_access_failure_returns_unknown_not_false(tmp_path):
    with patch("crypto_strategy_lab.browser_release_reconciliation._claimed_directory",
               side_effect=OSError("private inaccessible")):
        # Native OS errors must be bounded and never erase the evidence.
        with pytest.raises(OSError):
            inspect_b4_recovery(tmp_path, "safe")
