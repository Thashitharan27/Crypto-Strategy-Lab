import shutil
import subprocess

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
from crypto_strategy_lab.gui.github_manager import GitError, GitManager, GitStatus, is_sensitive, parse_ahead_behind


def git(path, *args, check=True):
    return subprocess.run(["git", *args], cwd=path, text=True, capture_output=True, check=check)


@pytest.fixture
def repo(tmp_path):
    if not shutil.which("git"): pytest.skip("git unavailable")
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.email", "tests@example.invalid")
    git(tmp_path, "config", "user.name", "Test User")
    (tmp_path/"tracked.txt").write_text("one\n")
    git(tmp_path, "add", "tracked.txt"); git(tmp_path, "commit", "-m", "initial")
    return tmp_path


def test_repository_branch_clean_modified_and_untracked(repo):
    manager=GitManager(repo)
    assert manager.validate() and manager.branch()=="main"
    # status needs an origin, while local change parsing does not.
    assert manager.changes()==()
    (repo/"tracked.txt").write_text("two\n"); (repo/"new.txt").write_text("new\n")
    changes={c.path:c.label for c in manager.changes()}
    assert changes=={"tracked.txt":"Modified", "new.txt":"Untracked"}


def test_missing_repository_and_git_unavailable(tmp_path, repo):
    with pytest.raises(GitError, match="not a Git repository"): GitManager(tmp_path).validate()
    with pytest.raises(GitError, match="not installed"): GitManager(repo, "definitely-no-such-git").validate()


def test_ahead_behind_and_status_safety_states():
    assert parse_ahead_behind("2\t3\n")== (2,3)
    clean=GitStatus("main","origin",(),0,1); assert clean.can_pull
    dirty=GitStatus("main","origin",(),1,1); assert dirty.state=="Local and remote have diverged" and not dirty.can_pull
    conflict=GitStatus("main","origin",(__import__("crypto_strategy_lab.gui.github_manager",fromlist=["GitChange"]).GitChange("UU","x"),))
    assert conflict.conflicts and not conflict.can_pull and not conflict.can_push


def test_pull_eligibility_clean_and_dirty(repo):
    manager=GitManager(repo)
    manager.remote_url=lambda:"unused"; manager.upstream=lambda:"HEAD"
    assert manager.status().can_pull
    (repo/"tracked.txt").write_text("dirty\n")
    with pytest.raises(GitError, match="Cannot pull"): manager.pull()


def test_commit_requires_message_and_stages_only_selection(repo):
    manager=GitManager(repo); (repo/"a.txt").write_text("a"); (repo/"b.txt").write_text("b")
    with pytest.raises(GitError, match="non-empty"): manager.commit(["a.txt"], " ")
    commit,_=manager.commit(["a.txt"], "selected only")
    assert commit and git(repo,"show","--name-only","--format=", "HEAD").stdout.strip()=="a.txt"
    assert "?? b.txt" in git(repo,"status","--porcelain").stdout


def test_ignored_and_sensitive_files_cannot_be_staged(repo):
    manager=GitManager(repo); (repo/".gitignore").write_text("ignored.txt\n"); (repo/"ignored.txt").write_text("x")
    assert manager.ignored("ignored.txt")
    with pytest.raises(GitError, match="Ignored"): manager.validate_commit(["ignored.txt"],"message")
    for path in (".env", ".env.local", "private.pem", "private.key", "credentials.json", "secrets.json"):
        assert is_sensitive(path)
        with pytest.raises(GitError, match="credentials or secrets"): manager.validate_commit([path],"message")


def test_commands_never_construct_force_push(repo, monkeypatch):
    manager=GitManager(repo); seen=[]
    monkeypatch.setattr(manager,"_run",lambda *args,**kwargs: seen.append(args) or type("R",(),{"stdout":""})())
    manager.push("main")
    assert seen==[("push","origin","main")]
    assert all("--force" not in command for command in seen)
