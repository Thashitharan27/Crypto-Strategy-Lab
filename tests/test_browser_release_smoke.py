"""B4 smoke must refuse dirty trees and test the real read-only HTTP app."""
import subprocess
from unittest.mock import patch

import pytest

from crypto_strategy_lab.browser_release_smoke import verify_clean_checkout


def test_clean_checkout_verifier_accepts_exact_clean_commit(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    head = "a" * 40
    def fake_run(args, **kwargs):
        if "--show-toplevel" in args:
            return subprocess.CompletedProcess(args, 0, str(repo) + "\n", "")
        if "rev-parse" in args:
            return subprocess.CompletedProcess(args, 0, head + "\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")
    with patch("crypto_strategy_lab.browser_release_smoke.subprocess.run", side_effect=fake_run):
        assert verify_clean_checkout(repo) == head


def test_clean_checkout_verifier_rejects_dirty_worktree(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    def fake_run(args, **kwargs):
        if "--show-toplevel" in args:
            output = str(repo)
        elif "rev-parse" in args:
            output = "a" * 40
        else:
            output = "?? untracked.py"
        return subprocess.CompletedProcess(args, 0, output + "\n", "")
    with patch("crypto_strategy_lab.browser_release_smoke.subprocess.run", side_effect=fake_run):
        with pytest.raises(ValueError, match="clean worktree"):
            verify_clean_checkout(repo)


def test_clean_checkout_verifier_refuses_non_root(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    with patch("crypto_strategy_lab.browser_release_smoke.subprocess.run",
               return_value=subprocess.CompletedProcess([], 0, str(tmp_path), "")):
        with pytest.raises(ValueError, match="checkout root"):
            verify_clean_checkout(repo)


def test_release_smoke_actual_http_security_and_original_preservation():
    pytest.importorskip("fastapi")
    from crypto_strategy_lab.browser_release_smoke import run_readonly_release_smoke
    result = run_readonly_release_smoke()
    assert result == {
        "status": "PASS_READ_ONLY", "http_checks": 10,
        "guarded_routes_available": False, "originals_unchanged": True,
    }
