from pathlib import Path
from types import SimpleNamespace

from crypto_strategy_lab.gui import app_restart
from crypto_strategy_lab.gui import github_sync_install
from crypto_strategy_lab.gui.github_sync_install import (
    GitUpdateResult,
    apply_github_sync_safety,
    is_dependency_file,
)


class _Field:
    def __init__(self):
        self.text = None
        self.enabled = True

    def setText(self, value):
        self.text = value

    def setEnabled(self, value):
        self.enabled = bool(value)


class _Manager:
    def __init__(self, changed_files=()):
        self.changed_files = tuple(changed_files)
        self.pull_calls = 0

    def pull(self):
        self.pull_calls += 1
        return "Fast-forward"

    def _run(self, *args, **_kwargs):
        if args == ("rev-parse", "HEAD"):
            head = "old" if self.pull_calls == 0 else "new"
            return SimpleNamespace(stdout=head + "\n")
        if args[:2] == ("diff", "--name-only"):
            return SimpleNamespace(stdout="\n".join(self.changed_files) + "\n")
        raise AssertionError(args)


class _Widget:
    def __init__(self, manager):
        self.manager = manager
        self.state = _Field()
        self.status_detail = _Field()
        self.pull_btn = _Field()
        self.refresh = _Field()
        self.review = _Field()
        self.commit_btn = _Field()
        self.logs = []
        self.refresh_calls = []
        self.errors = []

    def _log(self, value):
        self.logs.append(value)

    def refresh_status(self, fetch):
        self.refresh_calls.append(fetch)

    def _error(self, value):
        self.errors.append(value)


class _Window:
    def __init__(self, widget):
        self.widget = widget
        self._thread = None

    def findChild(self, _cls):
        return self.widget


def test_dependency_file_detection_covers_current_and_common_python_metadata():
    assert is_dependency_file("requirements.txt")
    assert is_dependency_file("requirements-dev.txt")
    assert is_dependency_file("requirements/base.txt")
    assert is_dependency_file("pyproject.toml")
    assert is_dependency_file("uv.lock")
    assert not is_dependency_file("app.py")
    assert not is_dependency_file("crypto_strategy_lab/gui/github_manager.py")


def test_normal_update_requests_clean_restart(monkeypatch):
    manager = _Manager(("app.py", "crypto_strategy_lab/gui/example.py"))
    widget = _Widget(manager)
    window = _Window(widget)
    app = SimpleNamespace(quit_calls=0)

    def quit_app():
        app.quit_calls += 1

    app.quit = quit_app
    monkeypatch.setattr(
        github_sync_install,
        "QApplication",
        SimpleNamespace(instance=lambda: app),
    )
    monkeypatch.setattr(
        github_sync_install,
        "QTimer",
        SimpleNamespace(singleShot=lambda _delay, callback: callback()),
    )

    apply_github_sync_safety(window)
    result = widget.manager.pull()
    assert isinstance(result, GitUpdateResult)
    assert result.updated
    assert not result.dependency_files

    widget._pulled(result)

    assert window._restart_after_exit is True
    assert app.quit_calls == 1
    assert widget.state.text == "● Update installed"
    assert "Restarting Crypto Strategy Lab" in widget.status_detail.text
    assert not widget.pull_btn.enabled
    assert not widget.refresh.enabled


def test_dependency_update_does_not_restart(monkeypatch):
    manager = _Manager(("requirements.txt", "app.py"))
    widget = _Widget(manager)
    window = _Window(widget)
    app = SimpleNamespace(quit_calls=0)
    messages = []

    def quit_app():
        app.quit_calls += 1

    app.quit = quit_app
    monkeypatch.setattr(
        github_sync_install,
        "QApplication",
        SimpleNamespace(instance=lambda: app),
    )
    monkeypatch.setattr(
        github_sync_install.QMessageBox,
        "information",
        lambda *_args: messages.append(_args[-1]),
    )

    apply_github_sync_safety(window)
    result = widget.manager.pull()
    assert result.dependency_files == ("requirements.txt",)

    widget._pulled(result)

    assert window._restart_after_exit is False
    assert app.quit_calls == 0
    assert widget.refresh_calls == [False]
    assert messages
    assert "pip install -r requirements.txt" in messages[0]


def test_replacement_process_uses_same_python_without_shell(monkeypatch, tmp_path):
    calls = []
    app_path = tmp_path / "app.py"
    app_path.write_text("print('ok')\n")

    monkeypatch.setattr(
        app_restart.subprocess,
        "Popen",
        lambda command, **kwargs: calls.append((command, kwargs)) or object(),
    )

    app_restart.launch_replacement("/opt/project/python", app_path)

    command, kwargs = calls[0]
    assert command == [str(Path("/opt/project/python").resolve()), str(app_path.resolve())]
    assert kwargs["cwd"] == str(tmp_path.resolve())
    assert kwargs["shell"] is False
