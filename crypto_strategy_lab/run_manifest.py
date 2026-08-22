"""Canonical, immutable completed-run provenance contract."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
from typing import Any, Mapping
import uuid

RUN_MANIFEST_CONTRACT = "crypto_strategy_lab_run_v1"
RUN_MANIFEST_VERSION = 1
CATALOG_SNAPSHOT_CONTRACT = "selected_source_catalog_v1"
PREPARED_CACHE_CONTRACT = "prepared_backtest_frame_v1"


class RunArtifactError(ValueError):
    """A completed run or cataloged immutable artifact is invalid."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def new_run_identity() -> tuple[str, str]:
    return uuid.uuid4().hex, datetime.now(timezone.utc).isoformat()


def capture_code_provenance(repo: Path | None = None) -> dict[str, Any]:
    repo = Path(repo or Path(__file__).resolve().parents[1])
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                                capture_output=True, text=True).stdout.strip()
        status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"],
                                cwd=repo, check=True, capture_output=True, text=True).stdout
        dirty = bool(status.strip())
        result: dict[str, Any] = {
            "code_commit": commit, "code_dirty": dirty,
            "code_provenance_status": "DIRTY_WORKTREE" if dirty else "CLEAN_COMMIT",
            "reproducibility_status": "PARTIAL" if dirty else "REPRODUCIBLE",
        }
        if dirty:
            diff = subprocess.run(["git", "diff", "--binary", "HEAD"], cwd=repo,
                                  check=True, capture_output=True).stdout
            result["tracked_diff_sha256"] = hashlib.sha256(diff).hexdigest()
            result["untracked_source_paths"] = sorted(
                line[3:] for line in status.splitlines()
                if line.startswith("?? ") and Path(line[3:]).suffix in {".py", ".toml", ".yaml", ".yml"}
                and Path(line[3:]).name != ".env"
            )
        return result
    except (OSError, subprocess.SubprocessError):
        return {"code_commit": None, "code_dirty": None,
                "code_provenance_status": "GIT_UNAVAILABLE", "reproducibility_status": "PARTIAL"}


def runtime_provenance(repo: Path | None = None) -> dict[str, Any]:
    requirements = Path(repo or Path(__file__).resolve().parents[1]) / "requirements.txt"
    return {"python_version": sys.version, "platform": platform.platform(),
            "project_config_contract": "research_run_config_v3", "project_config_version": 3,
            "requirements_sha256": file_sha256(requirements) if requirements.is_file() else None}


def config_snapshot(config: Any) -> dict[str, Any]:
    value = config.to_dict() if hasattr(config, "to_dict") else asdict(config) if is_dataclass(config) else dict(config)
    return value


def config_hashes(config: Any, effective_intrabar_interval: str | None) -> dict[str, str]:
    snapshot = config_snapshot(config)
    return {
        "strategy_hash": canonical_sha256(snapshot["strategy"]),
        "execution_hash": canonical_sha256({"execution": snapshot["execution"],
                                             "effective_intrabar_interval": effective_intrabar_interval,
                                             "use_intrabar_data": snapshot["data"].get("use_intrabar_data")}),
        "feature_config_hash": canonical_sha256(snapshot["features"]),
        "data_config_hash": canonical_sha256(snapshot["data"]),
    }


def source_record(record: Any) -> dict[str, Any]:
    value = {"exchange": record.exchange, "market": getattr(record.market, "value", record.market),
             "dataset": getattr(record.dataset, "value", record.dataset), "symbol": record.symbol,
             "interval": record.interval, "frequency": record.frequency,
             "period_start": record.period_start.isoformat() if record.period_start else None,
             "period_end": record.period_end.isoformat() if record.period_end else None,
             "size_bytes": int(record.size_bytes), "mtime_ns": int(record.mtime_ns),
             "raw_archive_fingerprint": record.fingerprint}
    value["canonical_partition_identity"] = canonical_sha256(value)
    return value


def selected_source_snapshot(records: tuple[Any, ...] | list[Any]) -> tuple[list[dict[str, Any]], str]:
    unique = {canonical_json(source_record(item)): source_record(item) for item in records}
    rows = sorted(unique.values(), key=canonical_json)
    return rows, canonical_sha256(rows)


def load_completed_manifest(run_dir: Path) -> dict[str, Any]:
    path = Path(run_dir) / "run_manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunArtifactError("completed run manifest is missing or corrupt") from exc
    if (manifest.get("run_manifest_contract") != RUN_MANIFEST_CONTRACT or
            manifest.get("run_manifest_version") != RUN_MANIFEST_VERSION or
            manifest.get("run_status") != "COMPLETED"):
        raise RunArtifactError("incompatible or incomplete run manifest")
    return manifest


def artifact_path(run_dir: Path, manifest: Mapping[str, Any], name: str, *, verify: bool = True) -> Path:
    entry = manifest.get("artifacts", {}).get(name)
    if not isinstance(entry, Mapping) or not entry.get("path"):
        raise RunArtifactError(f"artifact is not cataloged: {name}")
    relative = Path(entry["path"])
    root = Path(run_dir).resolve(strict=True)
    if relative.is_absolute() or ".." in relative.parts:
        raise RunArtifactError("unsafe artifact catalog path")
    try: path = (root / relative).resolve(strict=True)
    except (OSError, RuntimeError) as exc: raise RunArtifactError(f"artifact is missing: {name}") from exc
    if root not in path.parents or path.is_symlink() or not path.is_file():
        raise RunArtifactError("artifact escapes completed run")
    if verify and file_sha256(path) != entry.get("sha256"):
        raise RunArtifactError(f"artifact integrity error: {name}")
    return path
