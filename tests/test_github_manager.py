import shutil
import subprocess

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
from crypto_strategy_lab.gui.github_manager import (
    GitChange,
    GitError,
    GitHubIntegrationWidget,
    GitManager,
    GitStatus,
    is_sensitive,
    parse_ahead_behind,
)


def git(path, *args, check=True):
    return subprocess.run(
        ["git", *args], cwd=path, text=True, capture_output=True, check=check
    )


@pytest.fixture
def repo(tmp_path):
    if not shutil.which("git"):
        pytest.skip("git unavailable")
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.email", "tests@example.invalid")
    git(tmp_path, "config", "user.name", "Test User")
    (tmp_path / "tracked.txt").write_text("one\n")
    git(tmp_path, "add", "tracked.txt")
    git(tmp_path, "commit", "-m", "initial")
    return tmp_path


def test_repository_branch_clean_modified_and_untracked(repo):
    manager = GitManager(repo)
    assert manager.validate() and manager.branch() == "main"
    # status needs an origin, while local change parsing does not.
    assert manager.changes() == ()
    (repo / "tracked.txt").write_text("two\n")
    (repo / "new.txt").write_text("new\n")
    changes = {c.path: c.label for c in manager.changes()}
    assert changes == {"tracked.txt": "Modified", "new.txt": "Untracked"}


def test_missing_repository_and_git_unavailable(tmp_path, repo):
    with pytest.raises(GitError, match="not a Git repository"):
        GitManager(tmp_path / "not-a-repo").validate()
    with pytest.raises(GitError, match="not installed"):
        GitManager(repo, "definitely-no-such-git").validate()


def test_ahead_behind_and_status_safety_states():
    assert parse_ahead_behind("2\t3\n") == (2, 3)
    clean = GitStatus("main", "origin", (), 0, 1)
    assert clean.can_pull
    dirty = GitStatus("main", "origin", (), 1, 1)
    assert dirty.state == "Local and remote have diverged" and not dirty.can_pull
    conflict = GitStatus("main", "origin", (GitChange("UU", "x"),))
    assert conflict.conflicts and not conflict.can_pull and not conflict.can_push


def test_sync_summary_and_guidance_prioritize_local_change_blocker():
    status = GitStatus(
        "main",
        "origin",
        (GitChange(" M", "launcher.vbs"), GitChange("??", "local.json")),
        ahead=0,
        behind=3,
    )
    assert status.sync_summary == "main • 2 local changes • 3 GitHub updates available"
    assert "Update blocked" in status.guidance
    assert "2 local change(s)" in status.guidance
    assert "3 update(s) waiting" in status.guidance


def test_pull_eligibility_clean_and_dirty(repo):
    manager = GitManager(repo)
    manager.remote_url = lambda: "unused"
    manager.upstream = lambda: "HEAD"
    assert manager.status().can_pull
    (repo / "tracked.txt").write_text("dirty\n")
    with pytest.raises(GitError, match="Cannot update"):
        manager.pull()


def test_status_fetches_origin_when_requested(repo, monkeypatch):
    manager = GitManager(repo)
    manager.validate = lambda: True
    manager.branch = lambda: "main"
    manager.remote_url = lambda: "https://github.com/example/repo.git"
    manager.changes = lambda: ()
    manager.upstream = lambda: "origin/main"
    calls = []

    class Result:
        returncode = 0
        stdout = "0\t2\n"
        stderr = ""

    def fake_run(*args, **kwargs):
        calls.append(args)
        return Result()

    monkeypatch.setattr(manager, "_run", fake_run)
    status = manager.status(fetch=True)

    assert calls[0] == ("fetch", "origin")
    assert calls[1][:3] == ("rev-list", "--left-right", "--count")
    assert status.behind == 2


def test_commit_requires_message_and_stages_only_selection(repo):
    manager = GitManager(repo)
    (repo / "a.txt").write_text("a")
    (repo / "b.txt").write_text("b")
    with pytest.raises(GitError, match="non-empty"):
        manager.commit(["a.txt"], " ")
    commit, _ = manager.commit(["a.txt"], "selected only")
    assert commit and git(repo, "show", "--name-only", "--format=", "HEAD").stdout.strip() == "a.txt"
    assert "?? b.txt" in git(repo, "status", "--porcelain").stdout


def test_ignored_and_sensitive_files_cannot_be_staged(repo):
    manager = GitManager(repo)
    (repo / ".gitignore").write_text("ignored.txt\n")
    (repo / "ignored.txt").write_text("x")
    assert manager.ignored("ignored.txt")
    with pytest.raises(GitError, match="Ignored"):
        manager.validate_commit(["ignored.txt"], "message")
    for path in (
        ".env",
        ".env.local",
        "private.pem",
        "private.key",
        "credentials.json",
        "secrets.json",
    ):
        assert is_sensitive(path)
        with pytest.raises(GitError, match="credentials or secrets"):
            manager.validate_commit([path], "message")


def test_restore_tracked_discards_modified_worktree_file(repo):
    manager = GitManager(repo)
    (repo / "tracked.txt").write_text("changed locally\n")
    change = next(item for item in manager.changes() if item.path == "tracked.txt")
    assert change.can_restore

    assert manager.restore_tracked(change) == "tracked.txt"

    assert (repo / "tracked.txt").read_text() == "one\n"
    assert manager.changes() == ()


def test_restore_tracked_refuses_untracked_or_conflict(repo):
    manager = GitManager(repo)
    (repo / "new.txt").write_text("new\n")
    untracked = next(item for item in manager.changes() if item.path == "new.txt")
    with pytest.raises(GitError, match="modified or deleted tracked"):
        manager.restore_tracked(untracked)


def test_remove_untracked_deletes_only_exact_file(repo):
    manager = GitManager(repo)
    target = repo / "local.json"
    target.write_text("{}\n")
    change = next(item for item in manager.changes() if item.path == "local.json")
    assert change.can_remove_untracked

    assert manager.remove_untracked(change) == "local.json"

    assert not target.exists()
    assert manager.changes() == ()


def test_remove_untracked_refuses_directory(repo):
    manager = GitManager(repo)
    folder = repo / "scratch"
    folder.mkdir()
    (folder / "a.txt").write_text("a")
    change = next(item for item in manager.changes() if item.path.startswith("scratch"))

    with pytest.raises(GitError, match="single untracked file"):
        manager.remove_untracked(change)

    assert (folder / "a.txt").exists()


def test_widget_initial_refresh_fetches_remote_and_uses_clean_labels(qapp, monkeypatch):
    status = GitStatus(
        "main",
        "https://github.com/example/repo.git",
        (GitChange(" M", "launcher.vbs"),),
        ahead=0,
        behind=2,
    )
    fetch_values = []

    def fake_status(self, fetch=False):
        fetch_values.append(fetch)
        return status

    monkeypatch.setattr(GitManager, "status", fake_status)
    monkeypatch.setattr(
        GitHubIntegrationWidget,
        "_async",
        lambda self, fn, done, description, **kwargs: done(fn()),
    )

    widget = GitHubIntegrationWidget()
    try:
        assert fetch_values == [True]
        assert widget.sync_summary.text() == "main • 1 local change • 2 GitHub updates available"
        assert widget.change_list.item(0).text().startswith("Modified")
        assert " M" not in widget.change_list.item(0).text()
        assert widget.pull_btn.text() == "Update from GitHub"
        assert not widget.pull_btn.isEnabled()
        assert "Update blocked" in widget.status_detail.text()
    finally:
        widget.close()


def test_widget_shows_up_to_date_instead_of_second_refresh_action(qapp, monkeypatch):
    status = GitStatus("main", "https://github.com/example/repo.git", ())
    monkeypatch.setattr(GitManager, "status", lambda self, fetch=False: status)
    monkeypatch.setattr(
        GitHubIntegrationWidget,
        "_async",
        lambda self, fn, done, description, **kwargs: done(fn()),
    )

    widget = GitHubIntegrationWidget()
    try:
        assert widget.refresh.text() == "Refresh"
        assert widget.pull_btn.text() == "Up to date"
        assert not widget.pull_btn.isEnabled()
        assert widget.more_panel.isHidden()
    finally:
        widget.close()


def test_commands_never_construct_force_push(repo, monkeypatch):
    manager = GitManager(repo)
    seen = []
    monkeypatch.setattr(
        manager,
        "_run",
        lambda *args, **kwargs: seen.append(args) or type("R", (), {"stdout": ""})(),
    )
    manager.push("main")
    assert seen == [("push", "origin", "main")]
    assert all("--force" not in command for command in seen)


def test_background_refresh_failure_is_inline_and_does_not_open_modal(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    warnings = []
    fetches = []

    def unavailable(self, fetch=False):
        fetches.append(fetch)
        raise GitError("Background fetch unavailable")

    monkeypatch.setattr(GitManager, "status", unavailable)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    widget = GitHubIntegrationWidget()
    qtbot.addWidget(widget)
    # Drive the real QThreadPool -> queued Qt signal path, not a synchronous
    # replacement of _async. This was the event-loop hang seen in raw CI.
    qtbot.waitUntil(lambda: widget.state.text() == "● Git error", timeout=3000)
    assert fetches == [True]
    assert widget.status_detail.text() == "Background fetch unavailable"
    assert widget.activity[-1] == "[GIT] Error: Background fetch unavailable"
    assert warnings == []


def test_explicit_operation_failure_keeps_error_dialog(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    warnings = []
    monkeypatch.setattr(GitManager, "status", lambda self, fetch=False: GitStatus("main", "origin", ()))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    widget = GitHubIntegrationWidget()
    qtbot.addWidget(widget)

    def unavailable():
        raise GitError("Explicit update failed")

    widget._async(unavailable, lambda result: None, "Updating from GitHub")
    qtbot.waitUntil(lambda: bool(warnings), timeout=3000)
    assert warnings[0][1:] == ("GitHub Sync", "Explicit update failed")


def test_git_subprocess_timeout_is_bounded_and_reported(monkeypatch, tmp_path):
    from crypto_strategy_lab.gui import github_manager
    from types import SimpleNamespace
    calls = []

    def stalled(command, **kwargs):
        calls.append((command, kwargs))
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(github_manager.subprocess, "run", stalled)
    monkeypatch.setattr(github_manager, "os", SimpleNamespace(name="posix"))
    with pytest.raises(GitError, match="timed out after 120 seconds") as failure:
        GitManager(tmp_path)._run("fetch", "--prune", "origin")
    assert isinstance(failure.value.__cause__, subprocess.TimeoutExpired)
    assert calls[0][1]["timeout"] == github_manager.GIT_COMMAND_TIMEOUT_SECONDS
    assert calls[0][1]["shell"] is False


@pytest.mark.parametrize("failed", [False, True])
def test_git_task_completion_after_qt_signal_deletion_is_safe(qapp, failed):
    from crypto_strategy_lab.gui.github_manager import _Task
    from shiboken6 import delete

    seen = []
    def work():
        seen.append(True)
        if failed:
            raise GitError("native timeout")
        return "completed"
    task = _Task(work)
    delete(task.signals)
    task.run()
    assert seen == [True]


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Real Windows process-tree contract')
def test_windows_git_timeout_kills_child_holding_output_pipes(tmp_path, monkeypatch):
    import sys
    import time
    import ctypes
    from crypto_strategy_lab.gui import github_manager

    marker = tmp_path / 'owned-child.pid'
    child = (
        "import subprocess,sys,time;from pathlib import Path;"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
        f"Path({str(marker)!r}).write_text(str(p.pid));time.sleep(60)"
    )
    monkeypatch.setattr(github_manager, 'GIT_COMMAND_TIMEOUT_SECONDS', 3)
    started = time.monotonic()
    with pytest.raises(GitError, match='timed out after 3 seconds'):
        GitManager(tmp_path, git=sys.executable)._run('-c', child)
    assert time.monotonic() - started < 15
    assert marker.is_file(), 'Owned child must start before timeout'
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x00100000, False, int(marker.read_text()))
    if handle:
        try:
            assert kernel.WaitForSingleObject(handle, 0) == 0
        finally:
            kernel.CloseHandle(handle)
