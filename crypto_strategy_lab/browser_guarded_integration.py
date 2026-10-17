"""Opt-in internal browser capability boundary; never mounted by the HTTP launcher.

Authorization is solely server-controlled. Read-only production composition must
not instantiate an enabled boundary before final independent certification.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from crypto_strategy_lab.browser_guarded_config import GuardedConfigStore
from crypto_strategy_lab.browser_guarded_jobs import GuardedRunJobs


class BrowserGuardedIntegration:
    """Minimal façade over the authoritative native persistence/run owners."""

    def __init__(self, application_service: Any, config_root: Path, *, enabled: bool = False):
        self._enabled = enabled is True
        self._config = GuardedConfigStore(config_root, enabled=self._enabled)
        self._jobs = GuardedRunJobs(application_service, enabled=self._enabled)

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise PermissionError("Browser mutation capabilities are disabled")

    def save_config(self, config_id: str, payload: dict) -> Path:
        self._require_enabled()
        return self._config.save(config_id, payload)

    def submit(self, request_id: str, request: Any, config: Any):
        self._require_enabled()
        return self._jobs.submit(request_id, request, config)

    def status(self, request_id: str) -> dict[str, str]:
        self._require_enabled()
        return self._jobs.status(request_id)

    def progress(self, request_id: str) -> dict[str, str]:
        self._require_enabled()
        return self._jobs.progress(request_id)

    def cancel(self, request_id: str) -> dict[str, str]:
        self._require_enabled()
        return self._jobs.cancel(request_id)

    def close(self) -> None:
        self._jobs.close()
