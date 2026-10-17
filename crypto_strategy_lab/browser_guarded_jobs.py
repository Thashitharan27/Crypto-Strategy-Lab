"""Internal experimental job boundary; not wired to the browser or launcher.

Exactly one worker may touch a given native GuiApplicationService instance.
No cancellation is claimed: native cancellation must be separately certified.
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from threading import RLock
from typing import Any


class GuardedRunJobs:
    def __init__(self, application_service: Any, *, enabled: bool = False):
        self._application = application_service
        self._enabled = enabled
        self._lock = RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="csl-guarded-run")
        self._submitted: dict[str, Future] = {}
        self._active: str | None = None
        self._closed = False

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
                future = self._executor.submit(self._application.run, request, config)
            except BaseException:
                self._active = None
                raise
            # A completed Future may invoke callbacks immediately in this thread.
            # RLock avoids deadlocking the submitter in that fast completion case.
            self._submitted[request_id] = future
            future.add_done_callback(lambda _: self._finished(request_id))
            return future

    def _finished(self, request_id: str) -> None:
        with self._lock:
            if self._active == request_id:
                self._active = None

    def result(self, request_id: str) -> Future:
        with self._lock:
            if request_id not in self._submitted:
                raise KeyError("Unknown research request")
            return self._submitted[request_id]

    def close(self) -> None:
        with self._lock:
            self._closed = True
        # Wait for a native run to finish; never pretend to forcibly cancel it.
        self._executor.shutdown(wait=True, cancel_futures=False)
