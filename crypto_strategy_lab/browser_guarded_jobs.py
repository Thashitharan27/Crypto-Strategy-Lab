"""Internal experimental job boundary; not wired to the browser or launcher.

Exactly one worker may touch a given native GuiApplicationService instance.
No cancellation is claimed: native cancellation must be separately certified.
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from threading import RLock
from typing import Any
from pathlib import Path
import re
from crypto_strategy_lab.browser_guarded_output import bind_guarded_output_root


class GuardedRunJobs:
    def __init__(self, application_service: Any, *, enabled: bool = False, execution_root: Path | None = None):
        self._application = application_service
        self._execution_root = execution_root
        self._enabled = enabled
        self._lock = RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="csl-guarded-run")
        self._submitted: dict[str, Future] = {}
        self._active: str | None = None
        self._closed = False
        self._progress: dict[str, dict[str, str]] = {}

    def submit(self, request_id: str, request: Any, config: Any) -> Future:
        if self._enabled is not True:
            raise PermissionError("Browser research execution is disabled")
        if not isinstance(request_id, str) or not request_id.isascii() or not (
            1 <= len(request_id) <= 100
        ) or not all(char.isalnum() or char in "_-" for char in request_id):
            raise ValueError("Invalid request identifier")
        with self._lock:
            if self._closed:
                raise RuntimeError("Job coordinator is closed")
            if request_id in self._submitted:
                raise ValueError("Duplicate request identifier")
            if self._active is not None:
                raise RuntimeError("A native research job is already active")
            # Important: avoid submitting a queue of jobs against a shared
            # native store.progress_callback observer.
            self._active = request_id
            try:
                future = self._executor.submit(self._run_observed, request_id, request, config)
            except BaseException:
                self._active = None
                raise
            # A completed Future may invoke callbacks immediately in this thread.
            # RLock avoids deadlocking the submitter in that fast completion case.
            self._submitted[request_id] = future
            future.add_done_callback(lambda _: self._finished(request_id))
            return future

    def _run_observed(self, request_id: str, request: Any, config: Any) -> Any:
        # The native service calls progress_callback from the worker thread.
        # Bound diagnostic fields; never expose arbitrary event details or paths.
        previous = getattr(self._application, "progress_callback", None)
        def observe(event: Any) -> None:
            if isinstance(event, dict) and event.get("kind") == "stage":
                phase = event.get("phase")
                # No free-form native diagnostics, paths or secrets in HTTP progress.
                # A stage identifier may contain only bounded ASCII token characters.
                if isinstance(phase, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", phase, flags=re.ASCII):
                    with self._lock:
                        self._progress[request_id] = {"phase": phase}
            if callable(previous):
                previous(event)
        self._application.progress_callback = observe
        try:
            if self._execution_root is not None:
                config = bind_guarded_output_root(config, self._execution_root)
            return self._application.run(request, config)
        finally:
            self._application.progress_callback = previous

    def progress(self, request_id: str) -> dict[str, str]:
        """Return safe, bounded latest phase for a known job, or empty dict."""
        self.result(request_id)
        with self._lock:
            return dict(self._progress.get(request_id, {}))

    def _finished(self, request_id: str) -> None:
        with self._lock:
            if self._active == request_id:
                self._active = None

    def result(self, request_id: str) -> Future:
        with self._lock:
            if request_id not in self._submitted:
                raise KeyError("Unknown research request")
            return self._submitted[request_id]

    def status(self, request_id: str) -> dict[str, str]:
        """Return bounded lifecycle state without exposing native results/errors."""
        future = self.result(request_id)
        if not future.done():
            state = "RUNNING" if future.running() else "QUEUED"
        elif future.cancelled():
            state = "CANCELLED"
        elif future.exception() is not None:
            state = "FAILED"
        else:
            state = "COMPLETED"
        return {"request_id": request_id, "status": state}

    def cancel(self, request_id: str) -> dict[str, str]:
        """Fail safely: never claim a running native simulation was cancelled.

        A pending Future can be cancelled before it starts. Once running,
        native engine cancellation has not been certified and is unsupported.
        """
        future = self.result(request_id)
        if not future.done() and not future.cancel():
            return {"request_id": request_id, "status": "CANCELLATION_UNAVAILABLE"}
        return self.status(request_id)

    def close(self) -> None:
        with self._lock:
            self._closed = True
        # Wait for a native run to finish; never pretend to forcibly cancel it.
        self._executor.shutdown(wait=True, cancel_futures=False)
