"""Safe, backtest-only control plane for Crypto Strategy Lab.

The control service intentionally does not expose arbitrary shell execution, source
editing, credentials, exchange connectivity, or live-trading actions.  A control
job can only materialize a strict v3 ResearchRunConfig and launch the repository's
authoritative ``tools/data_lake_run.py`` adapter with a fixed argument list.

Keeping execution in a child process gives the MCP control plane reliable status
and cancellation semantics without duplicating the ResearchRunner/engine stack.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
from typing import Any, Callable
from uuid import uuid4

from crypto_strategy_lab.data import DataRequest
from crypto_strategy_lab.data.timing import normalize_binance_interval
from crypto_strategy_lab.data_lake_config import (
    PROFILE_KEYS,
    ResearchRunConfig,
    normalize_data_lake_config,
)
from crypto_strategy_lab.paths import CACHE_DIR, CONFIG_DIR, MARKET_DATA_ROOT, OUTPUT_DIR, PROJECT_ROOT


DRAFT = "DRAFT"
RUNNING = "RUNNING"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"
TERMINAL_STATES = {COMPLETED, FAILED, CANCELLED}
_TIMEFRAME = re.compile(r"^(?P<count>[1-9]\d*)(?P<unit>[mhd])$", re.IGNORECASE)
_SYMBOL = re.compile(r"^[A-Z0-9]{3,30}$")


def _utc_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            raise ValueError("date/time cannot be empty")
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            text += "T00:00:00+00:00"
        elif text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"Invalid ISO date/time: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: str | datetime) -> str:
    return _utc_datetime(value).isoformat()


def _timeframe_minutes(value: str | int) -> int:
    if isinstance(value, bool):
        raise ValueError("timeframe must be a positive integer minutes value or e.g. 15m/1h/1d")
    if isinstance(value, int):
        if value <= 0:
            raise ValueError("timeframe minutes must be positive")
        return value
    match = _TIMEFRAME.fullmatch(str(value).strip())
    if not match:
        raise ValueError("timeframe must look like 15m, 1h, 4h, or 1d")
    count = int(match.group("count"))
    unit = match.group("unit").lower()
    multiplier = {"m": 1, "h": 60, "d": 1440}[unit]
    return count * multiplier


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(patch, dict):
        raise ValueError("settings patch must be an object")
    merged = deepcopy(base)
    for key, value in patch.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _tail(path: Path, lines: int) -> str:
    if not path.exists():
        return ""
    # Control logs are bounded to the last 1 MiB before splitting into lines.
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - 1_048_576))
        text = handle.read().decode("utf-8", errors="replace")
    return "\n".join(text.splitlines()[-lines:])


@dataclass
class ControlJob:
    run_id: str
    request: dict[str, str]
    config: dict[str, Any]
    state_dir: Path
    status: str = DRAFT
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    validated_at: str | None = None
    validation_token: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    pid: int | None = None
    returncode: int | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    cancel_requested: bool = False
    process: Any = field(default=None, repr=False, compare=False)

    @property
    def config_path(self) -> Path:
        return self.state_dir / "config.json"

    @property
    def result_path(self) -> Path:
        return self.state_dir / "result.json"

    @property
    def stdout_path(self) -> Path:
        return self.state_dir / "stdout.log"

    @property
    def stderr_path(self) -> Path:
        return self.state_dir / "stderr.log"


class BacktestControlService:
    """Validated control plane around the authoritative Data Lake CLI adapter."""

    def __init__(
        self,
        *,
        project_root: Path = PROJECT_ROOT,
        raw_root: Path = MARKET_DATA_ROOT,
        cache_root: Path = CACHE_DIR,
        output_root: Path = OUTPUT_DIR,
        config_root: Path = CONFIG_DIR / "data_lake",
        state_root: Path | None = None,
        runner_script: Path | None = None,
        process_factory: Callable[..., Any] = subprocess.Popen,
        max_concurrent_runs: int = 1,
    ):
        self.project_root = Path(project_root).expanduser().resolve()
        self.raw_root = Path(raw_root).expanduser().resolve()
        self.cache_root = Path(cache_root).expanduser().resolve()
        self.output_root = Path(output_root).expanduser().resolve()
        self.config_root = Path(config_root).expanduser().resolve()
        self.state_root = (
            Path(state_root).expanduser().resolve()
            if state_root is not None
            else self.cache_root / "control_jobs"
        )
        self.runner_script = (
            Path(runner_script).expanduser().resolve()
            if runner_script is not None
            else self.project_root / "tools" / "data_lake_run.py"
        )
        self.process_factory = process_factory
        self.max_concurrent_runs = int(max_concurrent_runs)
        if self.max_concurrent_runs <= 0:
            raise ValueError("max_concurrent_runs must be positive")
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.state_root.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, ControlJob] = {}
        self._lock = threading.RLock()

    def info(self) -> dict[str, Any]:
        return {
            "scope": "BACKTEST_ONLY",
            "safety": {
                "arbitrary_shell": False,
                "source_code_editing": False,
                "credential_access": False,
                "exchange_orders": False,
                "live_trading": False,
                "fixed_runner": str(self.runner_script),
                "bind_recommendation": "127.0.0.1 only",
            },
            "roots": {
                "raw_data": str(self.raw_root),
                "cache": str(self.cache_root),
                "output": str(self.output_root),
                "configs": str(self.config_root),
                "control_state": str(self.state_root),
            },
            "profiles": list(PROFILE_KEYS),
            "max_concurrent_runs": self.max_concurrent_runs,
            "workflow": [
                "create_run",
                "set_run_settings / set_filter_groups (optional)",
                "validate_run",
                "start_run with the returned validation_token",
                "get_run_status",
            ],
            "default_config": ResearchRunConfig().to_dict(),
        }

    def list_configs(self) -> list[str]:
        if not self.config_root.is_dir():
            return []
        return sorted(
            path.relative_to(self.config_root).as_posix()
            for path in self.config_root.rglob("*.json")
            if path.is_file() and not path.is_symlink()
        )

    def _config_path(self, name: str) -> Path:
        raw = Path(str(name))
        if raw.is_absolute() or not raw.parts or any(part == ".." for part in raw.parts):
            raise ValueError("Config name must be a relative path beneath the Data Lake config directory")
        if raw.suffix.lower() != ".json":
            raise ValueError("Config name must end in .json")
        unresolved = self.config_root
        for part in raw.parts:
            unresolved = unresolved / part
            if unresolved.is_symlink():
                raise ValueError("Symlinked config paths are not allowed")
        candidate = unresolved.resolve()
        if candidate != self.config_root and self.config_root not in candidate.parents:
            raise ValueError("Config path escapes the allowed config directory")
        if not candidate.is_file():
            raise ValueError(f"Config does not exist: {name}")
        return candidate

    @staticmethod
    def _normalize_config(values: dict[str, Any]) -> dict[str, Any]:
        parsed = normalize_data_lake_config(deepcopy(values))
        if not isinstance(parsed, ResearchRunConfig):
            raise ValueError("Control API accepts only native v3 ResearchRunConfig objects")
        parsed.validate()
        return parsed.to_dict()

    def load_config(self, name: str) -> dict[str, Any]:
        path = self._config_path(name)
        values = json.loads(path.read_text(encoding="utf-8-sig"))
        config = self._normalize_config(values)
        return {"name": path.relative_to(self.config_root).as_posix(), "config": config}

    def _request_for(self, request: dict[str, str], config: dict[str, Any]) -> DataRequest:
        parsed = self._normalize_config(config)
        data = parsed["data"]
        return DataRequest(
            symbol=request["symbol"],
            start=_utc_datetime(request["start"]),
            end=_utc_datetime(request["end"]),
            strategy_interval=f"{int(data['strategy_timeframe_minutes'])}m",
            intrabar_interval=(
                f"{int(data['intrabar_timeframe_minutes'])}m"
                if data["use_intrabar_data"]
                else None
            ),
        )

    def _validate_payload(self, request: dict[str, str], config: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_config(config)
        data_request = self._request_for(request, normalized)
        parsed = normalize_data_lake_config(normalized)
        assert isinstance(parsed, ResearchRunConfig)
        parsed.validate()
        expected_strategy = normalize_binance_interval(
            f"{int(parsed.data.strategy_timeframe_minutes)}m"
        )
        expected_intrabar = (
            normalize_binance_interval(f"{int(parsed.data.intrabar_timeframe_minutes)}m")
            if parsed.data.use_intrabar_data
            else None
        )
        if data_request.strategy_interval != expected_strategy:
            raise ValueError("DataRequest strategy interval disagrees with DataConfig")
        if data_request.intrabar_interval != expected_intrabar:
            raise ValueError("DataRequest intrabar interval disagrees with DataConfig")
        if data_request.end <= data_request.start:
            raise ValueError("Run end must be later than run start")
        return normalized

    def _forced_output_config(self, config: dict[str, Any]) -> dict[str, Any]:
        values = deepcopy(config)
        values.setdefault("reporting", {})["output_dir"] = str(self.output_root)
        return self._normalize_config(values)

    def _new_run_id(self) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return f"control_{stamp}_{uuid4().hex[:8]}"

    def create_run(
        self,
        *,
        symbol: str,
        start: str,
        end: str,
        config_name: str | None = None,
        config: dict[str, Any] | None = None,
        strategy_timeframe: str | int | None = None,
        intrabar_timeframe: str | int | None = None,
        use_intrabar_data: bool | None = None,
        run_name: str | None = None,
    ) -> dict[str, Any]:
        if config_name and config is not None:
            raise ValueError("Provide either config_name or config, not both")
        if config_name:
            values = self.load_config(config_name)["config"]
        elif config is not None:
            values = self._normalize_config(config)
        else:
            values = ResearchRunConfig().to_dict()

        values = deepcopy(values)
        if strategy_timeframe is not None:
            values["data"]["strategy_timeframe_minutes"] = _timeframe_minutes(strategy_timeframe)
        if intrabar_timeframe is not None:
            values["data"]["intrabar_timeframe_minutes"] = _timeframe_minutes(intrabar_timeframe)
        if use_intrabar_data is not None:
            values["data"]["use_intrabar_data"] = bool(use_intrabar_data)
        if run_name is not None:
            values["reporting"]["run_name"] = str(run_name).strip()

        normalized_symbol = str(symbol).upper().replace("/", "").replace("-", "").strip()
        if not _SYMBOL.fullmatch(normalized_symbol):
            raise ValueError("symbol must contain only 3-30 uppercase letters/digits")
        request = {
            "symbol": normalized_symbol,
            "start": _iso(start),
            "end": _iso(end),
        }
        values = self._forced_output_config(values)
        values = self._validate_payload(request, values)

        run_id = self._new_run_id()
        state_dir = self.state_root / run_id
        state_dir.mkdir(parents=False, exist_ok=False)
        job = ControlJob(run_id=run_id, request=request, config=values, state_dir=state_dir)
        with self._lock:
            self._jobs[run_id] = job
            self._persist(job)
        return self._public(job, include_config=True)

    def _job(self, run_id: str) -> ControlJob:
        try:
            return self._jobs[str(run_id)]
        except KeyError as exc:
            raise ValueError(f"Unknown control run: {run_id}") from exc

    def _ensure_draft(self, job: ControlJob) -> None:
        if job.status != DRAFT:
            raise ValueError(f"Run {job.run_id} is {job.status}; only DRAFT runs can be changed")

    def set_run_settings(self, run_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(patch, dict):
            raise ValueError("patch must be an object")
        if "config_version" in patch:
            raise ValueError("config_version cannot be changed through the control API")
        if isinstance(patch.get("reporting"), dict) and "output_dir" in patch["reporting"]:
            raise ValueError("reporting.output_dir is controlled by the backtest control service")
        with self._lock:
            job = self._job(run_id)
            self._ensure_draft(job)
            candidate = _deep_merge(job.config, patch)
            candidate = self._forced_output_config(candidate)
            job.config = self._validate_payload(job.request, candidate)
            job.validation_token = None
            job.validated_at = None
            self._persist(job)
            return self._public(job, include_config=True)

    def set_filter_groups(
        self,
        run_id: str,
        profile: str,
        rules: list[dict[str, Any]],
        *,
        enabled: bool | None = None,
        flip_direction: bool | None = None,
        flip_rule_match_mode: str | None = None,
        reject_rule_match_mode: str | None = None,
    ) -> dict[str, Any]:
        profile_key = str(profile).strip().lower()
        if profile_key not in PROFILE_KEYS:
            raise ValueError("profile must be one of: " + ", ".join(PROFILE_KEYS))
        if not isinstance(rules, list) or any(not isinstance(rule, dict) for rule in rules):
            raise ValueError("rules must be a list of rule objects")
        with self._lock:
            job = self._job(run_id)
            self._ensure_draft(job)
            candidate = deepcopy(job.config)
            profile_values = candidate["strategy"]["profiles"][profile_key]
            profile_values["entry_rules"] = deepcopy(rules)
            if enabled is not None:
                profile_values["enabled"] = bool(enabled)
            if flip_direction is not None:
                profile_values["flip_direction"] = bool(flip_direction)
            if flip_rule_match_mode is not None:
                profile_values["flip_rule_match_mode"] = str(flip_rule_match_mode).upper()
            if reject_rule_match_mode is not None:
                profile_values["reject_rule_match_mode"] = str(reject_rule_match_mode).upper()
            candidate = self._forced_output_config(candidate)
            job.config = self._validate_payload(job.request, candidate)
            job.validation_token = None
            job.validated_at = None
            self._persist(job)
            return self._public(job, include_config=True)

    def _fingerprint(self, job: ControlJob) -> str:
        payload = json.dumps(
            {"request": job.request, "config": job.config},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def validate_run(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._job(run_id)
            self._ensure_draft(job)
            job.config = self._validate_payload(job.request, self._forced_output_config(job.config))
            checks = {
                "raw_data_root_exists": self.raw_root.is_dir(),
                "runner_script_exists": self.runner_script.is_file(),
                "cache_root_writable": self.cache_root.is_dir(),
                "output_root_writable": self.output_root.is_dir(),
            }
            ready = all(checks.values())
            job.validation_token = f"v1:{self._fingerprint(job)}" if ready else None
            job.validated_at = datetime.now(timezone.utc).isoformat() if ready else None
            self._persist(job)
            preview = self._preview(job)
            return {
                "run_id": job.run_id,
                "ready": ready,
                "checks": checks,
                "validation_token": job.validation_token,
                "preview": preview,
            }

    def _command(self, job: ControlJob) -> list[str]:
        return [
            sys.executable,
            str(self.runner_script),
            "--config",
            str(job.config_path),
            "--raw-root",
            str(self.raw_root),
            "--cache-root",
            str(self.cache_root),
            "--symbol",
            job.request["symbol"],
            "--start",
            job.request["start"],
            "--end",
            job.request["end"],
            "--output-dir",
            str(self.output_root),
            "--result-json",
            str(job.result_path),
        ]

    def start_run(self, run_id: str, validation_token: str) -> dict[str, Any]:
        with self._lock:
            job = self._job(run_id)
            self._ensure_draft(job)
            expected = f"v1:{self._fingerprint(job)}"
            if not job.validation_token or validation_token != job.validation_token or validation_token != expected:
                raise ValueError("Run changed or was not validated; call validate_run again before start_run")
            if not self.raw_root.is_dir():
                raise ValueError(f"Raw market-data root does not exist: {self.raw_root}")
            if not self.runner_script.is_file():
                raise ValueError(f"Fixed backtest runner does not exist: {self.runner_script}")
            for other in self._jobs.values():
                self._refresh(other)
            running = sum(item.status == RUNNING for item in self._jobs.values())
            if running >= self.max_concurrent_runs:
                raise ValueError(
                    f"Maximum concurrent backtests reached ({self.max_concurrent_runs})"
                )

            job.config_path.write_text(json.dumps(job.config, indent=2), encoding="utf-8")
            stdout = job.stdout_path.open("w", encoding="utf-8")
            stderr = job.stderr_path.open("w", encoding="utf-8")
            try:
                process = self.process_factory(
                    self._command(job),
                    cwd=str(self.project_root),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    text=True,
                    shell=False,
                )
            finally:
                stdout.close()
                stderr.close()
            job.process = process
            job.pid = getattr(process, "pid", None)
            job.status = RUNNING
            job.started_at = datetime.now(timezone.utc).isoformat()
            job.validation_token = None
            self._persist(job)
            return self._public(job)

    def _refresh(self, job: ControlJob) -> None:
        if job.status != RUNNING or job.process is None:
            return
        returncode = job.process.poll()
        if returncode is None:
            return
        job.returncode = int(returncode)
        job.finished_at = datetime.now(timezone.utc).isoformat()
        if job.cancel_requested:
            job.status = CANCELLED
        elif returncode == 0 and job.result_path.is_file():
            try:
                job.result = json.loads(job.result_path.read_text(encoding="utf-8"))
                job.status = COMPLETED
            except (OSError, json.JSONDecodeError) as exc:
                job.status = FAILED
                job.error = f"Backtest exited successfully but result JSON was unreadable: {exc}"
        else:
            job.status = FAILED
            detail = _tail(job.stderr_path, 60).strip() or _tail(job.stdout_path, 60).strip()
            job.error = detail or f"Backtest process exited with code {returncode}"
        self._persist(job)

    def get_run_status(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._job(run_id)
            self._refresh(job)
            return self._public(job)

    def list_control_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        if not 1 <= int(limit) <= 500:
            raise ValueError("limit must be between 1 and 500")
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)
            for job in jobs:
                self._refresh(job)
            return [self._public(job) for job in jobs[: int(limit)]]

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._job(run_id)
            self._refresh(job)
            if job.status == DRAFT:
                job.status = CANCELLED
                job.finished_at = datetime.now(timezone.utc).isoformat()
                self._persist(job)
                return self._public(job)
            if job.status in TERMINAL_STATES:
                return self._public(job)
            if job.status != RUNNING or job.process is None:
                raise ValueError(f"Run {job.run_id} cannot be cancelled from state {job.status}")

            job.cancel_requested = True
            process = job.process
            process.terminate()
            try:
                returncode = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                returncode = process.wait(timeout=5)
            job.returncode = int(returncode)
            job.status = CANCELLED
            job.finished_at = datetime.now(timezone.utc).isoformat()
            self._persist(job)
            return self._public(job)

    def read_control_log(self, run_id: str, stream: str = "stderr", lines: int = 100) -> dict[str, Any]:
        if not 1 <= int(lines) <= 500:
            raise ValueError("lines must be between 1 and 500")
        with self._lock:
            job = self._job(run_id)
            self._refresh(job)
            normalized = str(stream).lower()
            if normalized not in {"stdout", "stderr"}:
                raise ValueError("stream must be stdout or stderr")
            path = job.stdout_path if normalized == "stdout" else job.stderr_path
            return {
                "run_id": job.run_id,
                "stream": normalized,
                "status": job.status,
                "text": _tail(path, int(lines)),
            }

    def _preview(self, job: ControlJob) -> dict[str, Any]:
        config = job.config
        enabled = {
            key: {
                "enabled": bool(value["enabled"]),
                "flip_direction": bool(value["flip_direction"]),
                "entry_rule_count": len(value.get("entry_rules", [])),
                "flip_rule_match_mode": value.get("flip_rule_match_mode"),
                "reject_rule_match_mode": value.get("reject_rule_match_mode"),
            }
            for key, value in config["strategy"]["profiles"].items()
        }
        return {
            "request": deepcopy(job.request),
            "data": deepcopy(config["data"]),
            "features": deepcopy(config["features"]),
            "strategy": {
                key: deepcopy(value)
                for key, value in config["strategy"].items()
                if key != "profiles"
            },
            "profiles": enabled,
            "execution": {
                key: deepcopy(value)
                for key, value in config["execution"].items()
                if key != "profiles"
            },
            "reporting": deepcopy(config["reporting"]),
        }

    def _persist(self, job: ControlJob) -> None:
        job.state_dir.mkdir(parents=True, exist_ok=True)
        job.config_path.write_text(json.dumps(job.config, indent=2), encoding="utf-8")
        payload = self._public(job)
        temp = job.state_dir / ".job.json.tmp"
        temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temp, job.state_dir / "job.json")

    def _public(self, job: ControlJob, *, include_config: bool = False) -> dict[str, Any]:
        payload = {
            "run_id": job.run_id,
            "status": job.status,
            "request": deepcopy(job.request),
            "created_at": job.created_at,
            "validated_at": job.validated_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "pid": job.pid,
            "returncode": job.returncode,
            "result": deepcopy(job.result),
            "error": job.error,
            "cancel_requested": job.cancel_requested,
            "preview": self._preview(job),
        }
        if include_config:
            payload["config"] = deepcopy(job.config)
        return payload
