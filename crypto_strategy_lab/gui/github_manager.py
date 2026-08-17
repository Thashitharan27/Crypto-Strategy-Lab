"""Safe Git operations and the GitHub integration widget.

Git commands are passed as argument lists (never through a shell).  The manager is
deliberately usable without Qt so its safety rules can be tested in temporary
repositories.
"""
from __future__ import annotations

import fnmatch
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFileSystemModel,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QPlainTextEdit, QTreeView,
    QVBoxLayout, QWidget,
)


CONFLICT_CODES = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}
SENSITIVE_PATTERNS = (".env", ".env.*", "*.pem", "*.key", "credentials.json", "secrets.json",
                      "*cloudflared*credential*", "*tunnel*credential*")
CREATE_NO_WINDOW = 0x08000000


@dataclass(frozen=True)
class GitChange:
    code: str
    path: str

    @property
    def label(self) -> str:
        if self.code in CONFLICT_CODES or "U" in self.code:
            return "Conflict"
        if self.code == "??": return "Untracked"
        key = next((c for c in self.code if c not in " ?"), "?")
        return {"M": "Modified", "A": "Added", "D": "Deleted", "R": "Renamed"}.get(key, self.code)


@dataclass(frozen=True)
class GitStatus:
    branch: str
    remote_url: str
    changes: tuple[GitChange, ...]
    ahead: int = 0
    behind: int = 0

    @property
    def conflicts(self): return any(c.label == "Conflict" for c in self.changes)
    @property
    def state(self):
        if self.conflicts: return "Merge conflict"
        if self.ahead and self.behind: return "Local and remote have diverged"
        if self.behind: return "Remote updates available"
        if self.ahead: return "Local commits not pushed"
        if self.changes: return "Local changes"
        return "Up to date"

    @property
    def can_pull(self): return not self.changes and not (self.ahead and self.behind) and not self.conflicts
    @property
    def can_push(self): return not self.conflicts and not (self.ahead and self.behind)


class GitError(RuntimeError): pass


def project_root() -> Path:
    """Determine the checkout from this module's location, not a machine path."""
    return Path(__file__).resolve().parents[2]


def parse_porcelain(output: str) -> tuple[GitChange, ...]:
    changes = []
    for line in output.splitlines():
        if len(line) >= 3:
            path = line[3:]
            if " -> " in path: path = path.split(" -> ", 1)[1]
            changes.append(GitChange(line[:2], path.strip('"')))
    return tuple(changes)


def parse_ahead_behind(output: str) -> tuple[int, int]:
    left, right = output.strip().split()
    return int(left), int(right)


def is_sensitive(path: str) -> bool:
    name = Path(path).name.lower()
    return any(fnmatch.fnmatch(name, pattern) for pattern in SENSITIVE_PATTERNS)


class GitManager:
    def __init__(self, root: Path | None = None, git: str = "git"):
        self.root = Path(root or project_root()).resolve(); self.git = git

    def _run(self, *args: str, check=True) -> subprocess.CompletedProcess[str]:
        try:
            creationflags = CREATE_NO_WINDOW if os.name == "nt" else 0
            result = subprocess.run([self.git, *args], cwd=self.root, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
                                    creationflags=creationflags)
        except FileNotFoundError as exc:
            raise GitError("Git is not installed or not available in PATH.") from exc
        if check and result.returncode:
            raise GitError((result.stderr or result.stdout or "Git command failed.").strip())
        return result

    def validate(self):
        if not (self.root / ".git").exists(): raise GitError("The application folder is not a Git repository.")
        try: self._run("--version")
        except GitError as exc:
            if "not installed" in str(exc): raise
            raise GitError("Git is not installed or not available in PATH.") from exc
        return True

    def branch(self): return self._run("branch", "--show-current").stdout.strip()
    def remote_url(self): return self._run("remote", "get-url", "origin").stdout.strip()
    def changes(self): return parse_porcelain(self._run("status", "--porcelain").stdout)
    def ignored(self, path: str): return self._run("check-ignore", "-q", "--", path, check=False).returncode == 0
    def upstream(self):
        result = self._run("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}", check=False)
        return result.stdout.strip() if result.returncode == 0 else f"origin/{self.branch()}"
    def status(self, fetch=False):
        self.validate()
        if fetch: self._run("fetch", "origin")
        branch, remote, changes = self.branch(), self.remote_url(), self.changes()
        counts = self._run("rev-list", "--left-right", "--count", f"HEAD...{self.upstream()}", check=False)
        ahead, behind = parse_ahead_behind(counts.stdout) if counts.returncode == 0 else (0, 0)
        return GitStatus(branch, remote, changes, ahead, behind)

    def pull(self):
        status = self.status()
        if status.conflicts: raise GitError("Merge conflicts detected.\nResolve them before continuing.")
        if status.changes: raise GitError("Cannot pull while local changes are present.\n\nReview, commit, or discard the local changes first.")
        if status.ahead and status.behind: raise GitError("Local and remote branches have diverged. Resolve this manually before pulling.")
        return self._run("pull", "--ff-only").stdout.strip()

    def validate_commit(self, paths, message):
        if not message.strip(): raise GitError("A non-empty commit message is required.")
        if not paths: raise GitError("Select at least one file to commit.")
        for path in paths:
            if is_sensitive(path): raise GitError("This file appears to contain local credentials or secrets and cannot be committed from the GUI.")
            if self.ignored(path): raise GitError(f"Ignored files cannot be committed from the GUI: {path}")

    def commit(self, paths, message):
        self.validate_commit(paths, message)
        self._run("add", "--", *paths)
        result = self._run("commit", "-m", message.strip(), "--", *paths)
        return self._run("rev-parse", "--short", "HEAD").stdout.strip(), result.stdout.strip()

    def push(self, branch): return self._run("push", "origin", branch).stdout.strip()
    def diff(self, change: GitChange):
        path = self.root / change.path
        if change.code == "??":
            if not path.is_file() or path.stat().st_size > 256_000 or b"\0" in path.read_bytes()[:8192]:
                return "Binary or large untracked file; preview unavailable."
            return path.read_text(errors="replace")
        work = self._run("diff", "--", change.path, check=False).stdout
        staged = self._run("diff", "--cached", "--", change.path, check=False).stdout
        return "WORKING TREE\n" + (work or "(none)") + "\n\nSTAGED\n" + (staged or "(none)")


class _Signals(QObject):
    done = Signal(object); failed = Signal(str)

class _Task(QRunnable):
    def __init__(self, fn): super().__init__(); self.fn=fn; self.signals=_Signals()
    def run(self):
        try: self.signals.done.emit(self.fn())
        except Exception as exc: self.signals.failed.emit(str(exc))


class GitHubIntegrationWidget(QWidget):
    """Thin asynchronous UI over :class:`GitManager`."""
    def __init__(self, parent=None, active_work: Callable[[], bool] | None = None):
        super().__init__(parent); self.manager=GitManager(); self.active_work=active_work or (lambda: False)
        self.pool=QThreadPool.globalInstance(); self.current=None; self.activity=[]; self._build()
        self._async(lambda: self.manager.status(False), self._show_status, "Validating Git repository")

    def _build(self):
        layout=QVBoxLayout(self); title=QLabel("GitHub Integration"); title.setStyleSheet("font-size:18px;font-weight:600"); layout.addWidget(title)
        details=QFormLayout(); self.repo=QLabel(self.manager.root.name); self.branch_label=QLabel("—"); self.remote=QLabel("origin")
        details.addRow("Repository",self.repo); details.addRow("Current Branch",self.branch_label); details.addRow("Remote",self.remote); layout.addLayout(details)
        status_box=QGroupBox("Repository Status"); form=QFormLayout(status_box); self.state=QLabel("● Checking…"); self.local=QLabel("0"); self.behind=QLabel("0"); self.ahead=QLabel("0")
        form.addRow(self.state); form.addRow("Local changes",self.local); form.addRow("Commits behind",self.behind); form.addRow("Commits ahead",self.ahead); layout.addWidget(status_box)
        row=QHBoxLayout(); self.check=QPushButton("Check Status"); self.pull_btn=QPushButton("Pull Latest"); row.addWidget(self.check); row.addWidget(self.pull_btn); row.addStretch(); layout.addLayout(row)
        layout.addWidget(QLabel("Changes")); self.change_list=QListWidget(); layout.addWidget(self.change_list)
        row=QHBoxLayout(); self.refresh=QPushButton("Refresh Changes"); self.review=QPushButton("Review Changes"); self.commit_btn=QPushButton("Commit & Push…")
        for b in (self.refresh,self.review,self.commit_btn): row.addWidget(b)
        row.addStretch(); layout.addLayout(row)
        row=QHBoxLayout(); folder=QPushButton("Open Repository Folder"); web=QPushButton("Open GitHub Repository"); logs=QPushButton("Open Git Logs")
        for b in (folder,web,logs): row.addWidget(b)
        row.addStretch(); layout.addLayout(row)
        self.check.clicked.connect(lambda:self.refresh_status(True)); self.refresh.clicked.connect(lambda:self.refresh_status(False)); self.pull_btn.clicked.connect(self.pull)
        self.review.clicked.connect(self.review_changes); self.commit_btn.clicked.connect(self.commit_push); folder.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.manager.root))))
        web.clicked.connect(self.open_remote); logs.clicked.connect(self.open_logs)

    def _log(self,text): self.activity=(self.activity+[f"[GIT] {text}"])[-200:]
    def _async(self, fn, done, description):
        self._log(description); task=_Task(fn); task.signals.done.connect(done); task.signals.failed.connect(self._error); self.pool.start(task)
    def _error(self,message): self.state.setText("● Git error"); self._log("Error: "+message.splitlines()[0]); QMessageBox.warning(self,"GitHub Integration",message)
    def refresh_status(self,fetch=True): self._async(lambda:self.manager.status(fetch),self._show_status,"Checking repository status")
    def _show_status(self,status):
        self.current=status; self.branch_label.setText(status.branch or "—"); self.remote.setText(status.remote_url); self.repo.setText(self._repository_name(status.remote_url)); self.state.setText("● "+status.state)
        self.local.setText(str(len(status.changes))); self.behind.setText(str(status.behind)); self.ahead.setText(str(status.ahead)); self.change_list.clear()
        for change in status.changes: self.change_list.addItem(f"{change.code}  {change.path}  — {change.label}")
        busy=self.active_work(); self.pull_btn.setEnabled(status.can_pull and not busy); self.commit_btn.setEnabled(status.can_push and bool(status.changes) and not busy)
    @staticmethod
    def _repository_name(url):
        value=url.rstrip("/").removesuffix(".git"); return value.split(":",1)[-1] if "@" in value else "/".join(value.split("/")[-2:])
    def pull(self):
        if self.active_work(): return self._error("Pull is disabled while a backtest or portfolio run is active.")
        self._async(self.manager.pull,self._pulled,"Pulling latest changes with fast-forward only")
    def _pulled(self,_):
        self._log("Pull completed"); self.refresh_status(False)
        QMessageBox.information(self,"Update downloaded","Update downloaded successfully.\n\nRestart Crypto Strategy Lab to use the new version.\n\nPlease restart the application manually.")
    def review_changes(self):
        if not self.current or not self.current.changes: return
        dialog=QDialog(self); dialog.setWindowTitle("Review Changes"); dialog.resize(900,650); layout=QHBoxLayout(dialog); files=QListWidget(); preview=QPlainTextEdit(); preview.setReadOnly(True); layout.addWidget(files,1); layout.addWidget(preview,3)
        for c in self.current.changes: item=QListWidgetItem(f"{c.label}: {c.path}"); item.setData(256,c); files.addItem(item)
        def selected(item):
            preview.setPlainText("Loading preview…")
            change=item.data(256)
            self._async(lambda:self.manager.diff(change), preview.setPlainText, "Reviewing changes")
        files.itemClicked.connect(selected); dialog.exec()
    def commit_push(self):
        if self.active_work(): return self._error("Commit and push is disabled while a backtest or portfolio run is active.")
        if not self.current: return
        dialog=QDialog(self); dialog.setWindowTitle("Commit & Push"); layout=QVBoxLayout(dialog); layout.addWidget(QLabel(f"Branch: {self.current.branch}\n\nFiles to commit:")); checks=[]
        for change in self.current.changes:
            box=QCheckBox(f"{change.label}: {change.path}"); blocked=is_sensitive(change.path); box.setEnabled(not blocked); box.setToolTip("This file appears sensitive and cannot be selected." if blocked else "Ignored paths are also rejected before staging."); layout.addWidget(box); checks.append((box,change.path))
        message=QLineEdit(); message.setPlaceholderText("Required commit message"); layout.addWidget(QLabel("Commit message:")); layout.addWidget(message)
        buttons=QDialogButtonBox(QDialogButtonBox.Cancel|QDialogButtonBox.Ok); buttons.button(QDialogButtonBox.Ok).setText("Commit & Push"); layout.addWidget(buttons); buttons.rejected.connect(dialog.reject); buttons.accepted.connect(dialog.accept)
        if dialog.exec()!=QDialog.Accepted: return
        paths=[path for box,path in checks if box.isChecked()]
        branch=self.current.branch
        def operation():
            commit,_=self.manager.commit(paths,message.text()); self.manager.push(branch); return commit
        self._async(operation,self._pushed,"Committing selected files and pushing")
    def _pushed(self,commit): self._log(f"Commit {commit} created"); self._log("Push completed"); self.refresh_status(False); QMessageBox.information(self,"GitHub Integration",f"Commit {commit} was pushed successfully.")
    def open_remote(self):
        if not self.current: return
        url=self.current.remote_url
        if url.startswith("git@github.com:"): url="https://github.com/"+url.split(":",1)[1]
        if url.startswith("https://") or url.startswith("http://"): QDesktopServices.openUrl(QUrl(url.removesuffix(".git")))
        else: self._error("The origin remote is not a GitHub web URL.")
    def open_logs(self):
        dialog=QDialog(self); dialog.setWindowTitle("Git Activity"); dialog.resize(700,400); layout=QVBoxLayout(dialog); text=QPlainTextEdit("\n".join(self.activity)); text.setReadOnly(True); layout.addWidget(text); dialog.exec()
