"""Keep unrelated GUI tests offline; GitHub widget tests wire their own jobs."""
import pytest


@pytest.fixture(autouse=True)
def offline_github_widget_jobs(monkeypatch):
    # Window construction starts a remote status fetch on the global Qt pool.
    # Unmocked jobs can outlive windows and deadlock Qt/GC during test teardown.
    # Dedicated GitHub tests explicitly replace _async with their controlled
    # executor, overriding this default without bypassing manager unit tests.
    try:
        from crypto_strategy_lab.gui.github_manager import GitHubIntegrationWidget
    except ImportError:
        return
    monkeypatch.setattr(GitHubIntegrationWidget, "_async", lambda *args, **kwargs: None)
