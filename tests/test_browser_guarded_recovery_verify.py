from unittest.mock import patch

import pytest

from crypto_strategy_lab.browser_guarded_recovery_verify import verify_recovered_run
from crypto_strategy_lab.run_manifest import RunArtifactError


def test_absent_and_symlinked_run_never_verify(tmp_path):
    assert verify_recovered_run(tmp_path, "missing")["status"] == "RECOVERY_UNVERIFIED"
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "linked").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    assert verify_recovered_run(tmp_path, "linked")["status"] == "RECOVERY_UNVERIFIED"


def test_validates_every_cataloged_artifact_using_native_owner(tmp_path):
    (tmp_path / "run1").mkdir()
    manifest = {"artifacts": {"summary": {}, "trades": {}}}
    with patch("crypto_strategy_lab.browser_guarded_recovery_verify.load_completed_manifest", return_value=manifest), patch("crypto_strategy_lab.browser_guarded_recovery_verify.artifact_path") as verify:
        assert verify_recovered_run(tmp_path, "run1") == {"run_id": "run1", "status": "ARTIFACTS_VERIFIED"}
        assert verify.call_count == 2
        assert all(c.kwargs["verify"] is True for c in verify.call_args_list)


def test_failed_native_integrity_check_never_claims_verification(tmp_path):
    (tmp_path / "run1").mkdir()
    with patch("crypto_strategy_lab.browser_guarded_recovery_verify.load_completed_manifest", side_effect=RunArtifactError("corrupt manifest")):
        assert verify_recovered_run(tmp_path, "run1")["status"] == "RECOVERY_UNVERIFIED"


@pytest.mark.parametrize("bad", ["../escape", "bad.path", "", "é"])
def test_recovery_verifier_rejects_invalid_identifiers(tmp_path, bad):
    with pytest.raises(ValueError):
        verify_recovered_run(tmp_path, bad)
