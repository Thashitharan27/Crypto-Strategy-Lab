from unittest.mock import patch

import pytest

from crypto_strategy_lab.browser_guarded_recovery_verify import verify_recovered_run
from crypto_strategy_lab.run_manifest import RunArtifactError


def test_absent_run_never_verifies(tmp_path):
    assert verify_recovered_run(tmp_path, "missing")["status"] == "RECOVERY_UNVERIFIED"


def test_symlinked_run_never_verifies(tmp_path):
    (tmp_path / "elsewhere").mkdir()
    try:
        (tmp_path / "linked").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Filesystem symlinks unavailable")
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


@pytest.mark.parametrize("malformed", [None, [], "untrusted"])
def test_malformed_native_manifest_fails_closed(tmp_path, malformed):
    (tmp_path / "run1").mkdir()
    with patch("crypto_strategy_lab.browser_guarded_recovery_verify.load_completed_manifest", return_value=malformed):
        assert verify_recovered_run(tmp_path, "run1")["status"] == "RECOVERY_UNVERIFIED"


def test_recovery_rejects_symlinked_parent_without_traversing_run(tmp_path):
    from crypto_strategy_lab.browser_guarded_recovery_verify import verify_recovered_run
    import pytest

    original = tmp_path / "original"
    original.mkdir()
    (original / "jobs").mkdir()
    link = tmp_path / "linked"
    try:
        link.symlink_to(original, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable")
    assert verify_recovered_run(link / "jobs", "job") == {
        "run_id": "job", "status": "RECOVERY_UNVERIFIED"
    }


def test_recovery_rejects_relative_root_without_accessing_outputs():
    from pathlib import Path
    from crypto_strategy_lab.browser_guarded_recovery_verify import verify_recovered_run

    assert verify_recovered_run(Path("relative"), "job") == {
        "run_id": "job", "status": "RECOVERY_UNVERIFIED"
    }


def test_recovery_root_resolution_io_error_fails_closed(tmp_path):
    with patch("pathlib.Path.resolve", side_effect=OSError("private inaccessible root")):
        assert verify_recovered_run(tmp_path, "run1") == {
            "run_id": "run1", "status": "RECOVERY_UNVERIFIED"
        }


def test_recovery_candidate_inspection_io_error_fails_closed(tmp_path):
    (tmp_path / "run1").mkdir()
    original_is_dir = type(tmp_path).is_dir

    def inaccessible_candidate(path):
        if path == tmp_path / "run1":
            raise PermissionError("private candidate path")
        return original_is_dir(path)

    with patch("pathlib.Path.is_dir", autospec=True, side_effect=inaccessible_candidate):
        assert verify_recovered_run(tmp_path, "run1") == {
            "run_id": "run1", "status": "RECOVERY_UNVERIFIED"
        }


def test_native_completed_manifest_reader_and_recovery_verify_real_artifact_hashes(tmp_path):
    """No mocked loader: native completed reader and recovery share canonical hashes."""
    import hashlib
    import json

    from crypto_strategy_lab.feature_research import (
        FEATURE_RESEARCH_ARTIFACT_CONTRACT,
        FEATURE_RESEARCH_ARTIFACT_VERSION,
    )
    from crypto_strategy_lab.gui.v2_controller import CompletedRunReader
    from crypto_strategy_lab.run_manifest import (
        RUN_MANIFEST_CONTRACT,
        RUN_MANIFEST_VERSION,
        RunArtifactError,
    )

    run = tmp_path / "frozen-run"
    run.mkdir()
    artifacts = run / "artifacts"
    artifacts.mkdir()
    summary_path = artifacts / "summary.json"
    trade_path = artifacts / "trades.csv"
    summary = {"total_trades": 1, "ending_equity": 1009.79}
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    trade_path.write_text(
        "side,entry_time,exit_time,pair_net_pnl,equity_after_trade\\n"
        "LONG,2024-01-01T00:15:00Z,2024-01-01T00:30:00Z,9.79,1009.79\\n",
        encoding="utf-8",
    )
    def catalog(path):
        return {
            "path": path.relative_to(run).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        }

    manifest = {
        "run_manifest_contract": RUN_MANIFEST_CONTRACT,
        "run_manifest_version": RUN_MANIFEST_VERSION,
        "run_status": "COMPLETED",
        "research": {
            "artifact_contract": FEATURE_RESEARCH_ARTIFACT_CONTRACT,
            "artifact_version": FEATURE_RESEARCH_ARTIFACT_VERSION,
        },
        "artifacts": {
            "summary": catalog(summary_path),
            "trades": catalog(trade_path),
        },
    }
    (run / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    native_manifest, native_summary = CompletedRunReader().read(run)
    assert native_manifest == manifest
    assert native_summary == summary
    assert verify_recovered_run(tmp_path, "frozen-run") == {
        "run_id": "frozen-run", "status": "ARTIFACTS_VERIFIED",
    }

    # A valid manifest and summary alone cannot establish verified completion.
    original = trade_path.read_bytes()
    trade_path.write_bytes(original.replace(b"9.79", b"8.79"))
    assert verify_recovered_run(tmp_path, "frozen-run") == {
        "run_id": "frozen-run", "status": "RECOVERY_UNVERIFIED",
    }
    with pytest.raises(RunArtifactError, match="integrity"):
        CompletedRunReader.artifact_path(run, manifest, "trades")
    assert CompletedRunReader().read(run)[1] == summary
    assert (run / "run_manifest.json").read_text(encoding="utf-8") == json.dumps(manifest)
