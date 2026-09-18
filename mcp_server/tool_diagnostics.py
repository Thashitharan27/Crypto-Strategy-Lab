"""Lightweight diagnostics for unified Crypto Strategy Lab MCP tool calls.

The goal is to distinguish four cases without touching causal state:

* the MCP tool was never invoked;
* it started and is still in flight;
* it finished locally but the transport lost/expired the response;
* it failed inside the MCP process.

Only bounded operational metadata is recorded. Tool arguments such as SQL, notes,
reasoning, configs, credentials, or rule payloads are never logged.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from functools import wraps
import inspect
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable
import uuid


DIAGNOSTICS_CONTRACT = "crypto_strategy_lab_mcp_diagnostics_v1"
DEFAULT_RECENT_LIMIT = 100
MAX_HEALTH_RECENT_CALLS = 50

_SAFE_ARGUMENT_FIELDS = (
    "experiment_id",
    "operation_id",
    "expected_sequence",
    "expected_state_hash",
    "candidate_id",
    "teacher_pair_id",
    "run_id",
    "run",
    "state_id",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short(value: Any, length: int = 12) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:length]


def _resolve_git_dir(project_root: Path) -> Path | None:
    dot_git = Path(project_root) / ".git"
    if dot_git.is_dir():
        return dot_git
    if dot_git.is_file():
        try:
            line = dot_git.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if line.lower().startswith("gitdir:"):
            candidate = Path(line.split(":", 1)[1].strip())
            if not candidate.is_absolute():
                candidate = (dot_git.parent / candidate).resolve()
            return candidate
    return None


def _git_head(project_root: Path) -> str | None:
    """Read the current commit without spawning git or a shell."""
    git_dir = _resolve_git_dir(project_root)
    if git_dir is None:
        return None
    head_path = git_dir / "HEAD"
    try:
        head = head_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not head:
        return None
    if not head.startswith("ref:"):
        return head

    ref = head.split(":", 1)[1].strip()
    ref_path = git_dir / ref
    try:
        if ref_path.is_file():
            return ref_path.read_text(encoding="utf-8").strip() or None
    except OSError:
        pass

    packed = git_dir / "packed-refs"
    try:
        for raw in packed.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("^"):
                continue
            sha, _, name = line.partition(" ")
            if name == ref:
                return sha or None
    except OSError:
        return None
    return None


def _result_metadata(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    return {
        "result_sequence": result.get("sequence"),
        "result_state_hash": result.get("state_hash"),
        "result_status": result.get("status"),
        "result_ok": result.get("ok"),
        "result_error_type": result.get("error_type"),
    }


class ToolDiagnostics:
    """Thread-safe bounded request lifecycle recorder."""

    def __init__(
        self,
        *,
        project_root: Path,
        logger: logging.Logger,
        recent_limit: int = DEFAULT_RECENT_LIMIT,
    ) -> None:
        self.project_root = Path(project_root)
        self.logger = logger
        self.started_at_utc = _utc_now()
        self._started_monotonic = time.monotonic()
        self._lock = threading.Lock()
        self._recent: deque[dict[str, Any]] = deque(maxlen=max(1, int(recent_limit)))
        self._in_flight: dict[str, dict[str, Any]] = {}

    def _arguments(
        self,
        func: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            bound = inspect.signature(func).bind_partial(*args, **kwargs)
            values = bound.arguments
        except (TypeError, ValueError):
            values = dict(kwargs)
        result: dict[str, Any] = {}
        for name in _SAFE_ARGUMENT_FIELDS:
            if name in values and values[name] not in (None, ""):
                result[name] = values[name]
        return result

    def _log_start(self, record: dict[str, Any]) -> None:
        self.logger.info(
            "MCP_CALL start call_id=%s tool=%s experiment_id=%s operation_id=%s "
            "expected_sequence=%s expected_hash=%s",
            record["call_id"],
            record["tool"],
            record.get("experiment_id"),
            record.get("operation_id"),
            record.get("expected_sequence"),
            _short(record.get("expected_state_hash")),
        )

    def _log_end(self, record: dict[str, Any]) -> None:
        self.logger.info(
            "MCP_CALL end call_id=%s tool=%s elapsed_ms=%.3f success=%s "
            "experiment_id=%s operation_id=%s before_sequence=%s before_hash=%s "
            "after_sequence=%s after_hash=%s status=%s error_type=%s",
            record["call_id"],
            record["tool"],
            float(record["elapsed_ms"]),
            bool(record["success"]),
            record.get("experiment_id"),
            record.get("operation_id"),
            record.get("expected_sequence"),
            _short(record.get("expected_state_hash")),
            record.get("result_sequence"),
            _short(record.get("result_state_hash")),
            record.get("result_status"),
            record.get("error_type"),
        )

    def instrument(self, server: Any):
        """Return a drop-in replacement for server.tool registration."""

        def instrumented_tool(*tool_args: Any, **tool_kwargs: Any):
            def register(func: Callable[..., Any]):
                signature = inspect.signature(func)

                @wraps(func)
                def wrapped(*args: Any, **kwargs: Any):
                    call_id = uuid.uuid4().hex[:16]
                    started_utc = _utc_now()
                    started_perf = time.perf_counter()
                    metadata = self._arguments(func, args, kwargs)
                    start_record = {
                        "call_id": call_id,
                        "tool": func.__name__,
                        "started_at_utc": started_utc,
                        **metadata,
                    }
                    with self._lock:
                        self._in_flight[call_id] = {
                            **deepcopy(start_record),
                            "_started_perf": started_perf,
                        }
                    self._log_start(start_record)

                    result: Any = None
                    success = False
                    error_type: str | None = None
                    error_text: str | None = None
                    try:
                        result = func(*args, **kwargs)
                        success = not (
                            isinstance(result, dict)
                            and result.get("ok") is False
                        )
                        if not success and isinstance(result, dict):
                            error_type = str(
                                result.get("error_type") or "ReturnedError"
                            )
                            error_text = (
                                str(result.get("error") or "")[:500] or None
                            )
                        return result
                    except Exception as exc:
                        error_type = type(exc).__name__
                        error_text = str(exc)[:500] or None
                        raise
                    finally:
                        elapsed_ms = (
                            time.perf_counter() - started_perf
                        ) * 1000.0
                        result_meta = _result_metadata(result)
                        completed = {
                            **start_record,
                            **result_meta,
                            "completed_at_utc": _utc_now(),
                            "elapsed_ms": round(elapsed_ms, 3),
                            "success": bool(success),
                            "error_type": error_type,
                            "error": error_text,
                        }
                        with self._lock:
                            self._in_flight.pop(call_id, None)
                            self._recent.append(deepcopy(completed))
                        self._log_end(completed)

                # Make schema introspection explicit even if an MCP/inspection
                # implementation does not follow functools.__wrapped__.
                wrapped.__signature__ = signature  # type: ignore[attr-defined]
                return server.tool(*tool_args, **tool_kwargs)(wrapped)

            return register

        return instrumented_tool

    def health(
        self,
        *,
        tool_count: int,
        recent_calls: int = 10,
    ) -> dict[str, Any]:
        if isinstance(recent_calls, bool) or not isinstance(recent_calls, int):
            raise ValueError("recent_calls must be an integer")
        if recent_calls < 0 or recent_calls > MAX_HEALTH_RECENT_CALLS:
            raise ValueError(
                f"recent_calls must be between 0 and {MAX_HEALTH_RECENT_CALLS}"
            )

        now = time.monotonic()
        with self._lock:
            in_flight = [
                deepcopy(record)
                for record in self._in_flight.values()
                if record.get("tool") != "mcp_health_status"
            ]
            recent = list(self._recent)
        if recent_calls:
            recent = recent[-recent_calls:]
        else:
            recent = []

        for record in in_flight:
            started_perf = record.pop("_started_perf", None)
            record["still_running"] = True
            if isinstance(started_perf, (int, float)):
                record["elapsed_ms_so_far"] = round(
                    (time.perf_counter() - float(started_perf)) * 1000.0,
                    3,
                )

        commit = _git_head(self.project_root)
        return {
            "contract": DIAGNOSTICS_CONTRACT,
            "ok": True,
            "service": "Crypto Strategy Lab",
            "pid": os.getpid(),
            "started_at_utc": self.started_at_utc,
            "uptime_seconds": round(now - self._started_monotonic, 3),
            "git_commit": commit,
            "git_commit_short": _short(commit),
            "tool_count": int(tool_count),
            "diagnostics": {
                "in_flight_count": len(in_flight),
                "in_flight": in_flight,
                "recent_call_count": len(recent),
                "recent_calls": recent,
                "recent_buffer_limit": int(self._recent.maxlen or 0),
            },
            "interpretation": {
                "no_call_record": (
                    "The MCP tool was not invoked in this server process."
                ),
                "in_flight": (
                    "The MCP tool started locally and has not returned yet."
                ),
                "completed": (
                    "The MCP tool returned locally. If ChatGPT timed out anyway, "
                    "the response was lost/expired after local completion."
                ),
            },
        }
