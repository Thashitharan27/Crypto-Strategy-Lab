"""Offline Batch API support for causal OpenAI direction decisions.

This module deliberately separates three phases:

1. prepare deterministic request + manifest JSONL files (no API spend),
2. submit prepared request files to OpenAI Batch API,
3. collect completed output and append validated decisions to the normal cache.

The simulator itself remains cache-only and deterministic during historical replay.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable, Iterator

import numpy as np

from crypto_strategy_lab.ai_decision import (
    AI_DECISION_JSON_SCHEMA,
    AI_PROMPT_VERSION,
    AI_SYSTEM_PROMPT,
    AIDecisionCache,
    canonical_snapshot,
    decision_cache_key,
    validate_ai_decision,
)

BATCH_ENDPOINT = "/v1/responses"
BATCH_COMPLETION_WINDOW = "24h"
BATCH_MAX_REQUESTS = 50_000
BATCH_MAX_INPUT_BYTES = 200 * 1024 * 1024
# Keep headroom for newline/serialization differences and API-side accounting.
BATCH_SAFE_INPUT_BYTES = 190 * 1024 * 1024


@dataclass(frozen=True)
class PreparedAIBatchFile:
    request_file: Path
    manifest_file: Path
    request_count: int
    request_bytes: int

    def payload(self) -> dict[str, Any]:
        value = asdict(self)
        value["request_file"] = str(self.request_file)
        value["manifest_file"] = str(self.manifest_file)
        return value


@dataclass(frozen=True)
class PreparedAIBatches:
    files: tuple[PreparedAIBatchFile, ...]
    candidate_count: int
    prepared_count: int
    skipped_cached: int
    model: str
    reasoning_effort: str
    prompt_version: str
    cache_path: Path

    def payload(self) -> dict[str, Any]:
        return {
            "files": [item.payload() for item in self.files],
            "candidate_count": self.candidate_count,
            "prepared_count": self.prepared_count,
            "skipped_cached": self.skipped_cached,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "prompt_version": self.prompt_version,
            "cache_path": str(self.cache_path),
        }


def response_request_body(
    snapshot: dict[str, Any], *, model: str, reasoning_effort: str
) -> dict[str, Any]:
    """Return the exact Responses API body used by offline decision batches."""
    return {
        "model": str(model),
        "reasoning": {"effort": str(reasoning_effort)},
        "instructions": AI_SYSTEM_PROMPT,
        "input": canonical_snapshot(snapshot),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "crypto_direction_decision",
                "schema": AI_DECISION_JSON_SCHEMA,
                "strict": True,
            }
        },
    }


def batch_request_row(
    snapshot: dict[str, Any],
    *,
    model: str,
    reasoning_effort: str,
    prompt_version: str = AI_PROMPT_VERSION,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build one Batch API request plus the local validation manifest row."""
    cache_key, digest = decision_cache_key(
        snapshot,
        model=model,
        reasoning_effort=reasoning_effort,
        prompt_version=prompt_version,
    )
    custom_id = f"ai-{cache_key}"
    request = {
        "custom_id": custom_id,
        "method": "POST",
        "url": BATCH_ENDPOINT,
        "body": response_request_body(
            snapshot, model=model, reasoning_effort=reasoning_effort
        ),
    }
    manifest = {
        "custom_id": custom_id,
        "cache_key": cache_key,
        "snapshot_hash": digest,
        "model": str(model),
        "reasoning_effort": str(reasoning_effort),
        "prompt_version": str(prompt_version),
        "decision_timestamp": snapshot.get("decision_timestamp"),
        "symbol": snapshot.get("symbol"),
        "strategy_timeframe_minutes": snapshot.get("strategy_timeframe_minutes"),
    }
    return request, manifest


def _base_candidate(engine, i: int) -> bool:
    """Return whether a candle can ever require an AI direction decision.

    Active-position state is intentionally excluded: it depends on earlier AI
    decisions and exits. Therefore WAIT_UNTIL_CLOSED preparation can over-generate
    requests. The later simulator simply consumes the subset it actually needs.
    """
    try:
        risk = float(engine.risk[i])
    except (AttributeError, IndexError, TypeError, ValueError):
        return False
    if not math.isfinite(risk) or risk <= 0:
        return False
    try:
        if not bool(engine._in_trading_window(i)):
            return False
    except Exception:
        return False
    try:
        if engine._regime_at(i) is None:
            return False
    except Exception:
        pass

    config = engine.config
    if bool(getattr(config, "enable_daily_entry_schedule", False)):
        try:
            return i > 0 and bool(engine._is_scheduled_candle(i))
        except Exception:
            return False

    entry_mode = str(getattr(getattr(config, "entry_mode", None), "value", getattr(config, "entry_mode", ""))).upper()
    if entry_mode == "EVERY_N_CANDLES":
        interval = max(1, int(getattr(config, "entry_interval", 1)))
        return i % interval == 0
    return True


def candidate_decision_indices(engine) -> Iterator[int]:
    for i in range(len(engine.times)):
        if _base_candidate(engine, i):
            yield i


class _BatchFileWriter:
    def __init__(
        self,
        output_dir: Path,
        *,
        prefix: str,
        max_requests: int,
        max_bytes: int,
    ) -> None:
        if not 1 <= max_requests <= BATCH_MAX_REQUESTS:
            raise ValueError(f"max_requests must be between 1 and {BATCH_MAX_REQUESTS}")
        if not 1 <= max_bytes <= BATCH_MAX_INPUT_BYTES:
            raise ValueError(f"max_bytes must be between 1 and {BATCH_MAX_INPUT_BYTES}")
        self.output_dir = output_dir
        self.prefix = prefix
        self.max_requests = max_requests
        self.max_bytes = max_bytes
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.files: list[PreparedAIBatchFile] = []
        self._request_handle = None
        self._manifest_handle = None
        self._request_path: Path | None = None
        self._manifest_path: Path | None = None
        self._count = 0
        self._bytes = 0
        self._part = 0

    def _open(self) -> None:
        self._part += 1
        suffix = f"{self._part:03d}"
        self._request_path = self.output_dir / f"{self.prefix}_{suffix}.jsonl"
        self._manifest_path = self.output_dir / f"{self.prefix}_{suffix}.manifest.jsonl"
        self._request_handle = self._request_path.open("w", encoding="utf-8", newline="\n")
        self._manifest_handle = self._manifest_path.open("w", encoding="utf-8", newline="\n")
        self._count = 0
        self._bytes = 0

    def _close(self) -> None:
        if self._request_handle is None:
            return
        self._request_handle.close()
        self._manifest_handle.close()
        assert self._request_path is not None and self._manifest_path is not None
        self.files.append(
            PreparedAIBatchFile(
                request_file=self._request_path,
                manifest_file=self._manifest_path,
                request_count=self._count,
                request_bytes=self._bytes,
            )
        )
        self._request_handle = None
        self._manifest_handle = None

    def add(self, request: dict[str, Any], manifest: dict[str, Any]) -> None:
        request_line = json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n"
        manifest_line = json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
        request_bytes = len(request_line.encode("utf-8"))
        if request_bytes > self.max_bytes:
            raise ValueError("one AI batch request exceeds the configured batch file byte limit")
        if self._request_handle is None:
            self._open()
        if self._count and (
            self._count >= self.max_requests or self._bytes + request_bytes > self.max_bytes
        ):
            self._close()
            self._open()
        self._request_handle.write(request_line)
        self._manifest_handle.write(manifest_line)
        self._count += 1
        self._bytes += request_bytes

    def finish(self) -> tuple[PreparedAIBatchFile, ...]:
        self._close()
        return tuple(self.files)


def prepare_engine_batches(
    engine,
    output_dir: str | Path,
    *,
    indices: Iterable[int] | None = None,
    include_cached: bool = False,
    prefix: str = "ai_direction_batch",
    max_requests: int = BATCH_MAX_REQUESTS,
    max_bytes: int = BATCH_SAFE_INPUT_BYTES,
) -> PreparedAIBatches:
    """Prepare one or more JSONL Batch files without making any API call."""
    if getattr(engine, "signal_strategy_mode", "") != "OPENAI_DECISION":
        raise ValueError("engine must use OPENAI_DECISION before preparing AI batches")

    model, reasoning, prompt_version, _runtime_mode, cache_path = engine._ai_runtime_identity()
    cache = AIDecisionCache(cache_path)
    writer = _BatchFileWriter(
        Path(output_dir), prefix=prefix, max_requests=max_requests, max_bytes=max_bytes
    )
    candidate_count = prepared_count = skipped_cached = 0
    source = indices if indices is not None else candidate_decision_indices(engine)
    for raw_index in source:
        i = int(raw_index)
        candidate_count += 1
        snapshot = engine._ai_market_snapshot(i)
        request, manifest = batch_request_row(
            snapshot,
            model=model,
            reasoning_effort=reasoning,
            prompt_version=prompt_version,
        )
        if not include_cached:
            existing = cache.get(
                manifest["cache_key"],
                model=model,
                reasoning_effort=reasoning,
                prompt_version=prompt_version,
                expected_snapshot_hash=manifest["snapshot_hash"],
            )
            if existing is not None:
                skipped_cached += 1
                continue
        manifest["strategy_index"] = i
        writer.add(request, manifest)
        prepared_count += 1

    return PreparedAIBatches(
        files=writer.finish(),
        candidate_count=candidate_count,
        prepared_count=prepared_count,
        skipped_cached=skipped_cached,
        model=model,
        reasoning_effort=reasoning,
        prompt_version=prompt_version,
        cache_path=Path(cache_path),
    )


def _require_api_key() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for Batch API operations")


def _openai_client():
    _require_api_key()
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("The OpenAI Python SDK is required for Batch API operations") from exc
    return OpenAI()


def _count_request_lines(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def submit_batch_file(request_file: str | Path, *, metadata: dict[str, str] | None = None) -> dict[str, Any]:
    """Upload one prepared file and submit it to `/v1/responses`."""
    path = Path(request_file)
    size = path.stat().st_size
    if size > BATCH_MAX_INPUT_BYTES:
        raise ValueError("Batch input file exceeds OpenAI's 200 MB per-file limit")
    count = _count_request_lines(path)
    if count > BATCH_MAX_REQUESTS:
        raise ValueError("Batch input file exceeds OpenAI's 50,000 request limit")
    client = _openai_client()
    with path.open("rb") as handle:
        uploaded = client.files.create(file=handle, purpose="batch")
    batch = client.batches.create(
        input_file_id=uploaded.id,
        endpoint=BATCH_ENDPOINT,
        completion_window=BATCH_COMPLETION_WINDOW,
        metadata=metadata or {"purpose": "crypto_strategy_ai_direction_cache"},
    )
    return {
        "batch_id": batch.id,
        "input_file_id": uploaded.id,
        "status": getattr(batch, "status", None),
        "request_count": count,
        "request_bytes": size,
    }


def batch_status(batch_id: str) -> dict[str, Any]:
    batch = _openai_client().batches.retrieve(str(batch_id))
    counts = getattr(batch, "request_counts", None)
    if hasattr(counts, "model_dump"):
        counts = counts.model_dump()
    return {
        "batch_id": batch.id,
        "status": getattr(batch, "status", None),
        "input_file_id": getattr(batch, "input_file_id", None),
        "output_file_id": getattr(batch, "output_file_id", None),
        "error_file_id": getattr(batch, "error_file_id", None),
        "request_counts": counts,
    }


def _content_text(content) -> str:
    value = getattr(content, "text", None)
    if callable(value):
        value = value()
    if isinstance(value, str):
        return value
    reader = getattr(content, "read", None)
    if callable(reader):
        value = reader()
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)
    if isinstance(content, bytes):
        return content.decode("utf-8")
    return str(content)


def extract_response_output_text(body: dict[str, Any]) -> str:
    direct = body.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    parts: list[str] = []
    for item in body.get("output") or ():
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or ():
            if not isinstance(content, dict):
                continue
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                parts.append(content["text"])
    return "\n".join(parts).strip()


def _load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        custom_id = str(row.get("custom_id", ""))
        if not custom_id:
            raise ValueError(f"manifest row {number} has no custom_id")
        if custom_id in rows:
            raise ValueError(f"manifest contains duplicate custom_id {custom_id}")
        rows[custom_id] = row
    return rows


def collect_batch_to_cache(
    batch_id: str,
    manifest_file: str | Path,
    cache_path: str | Path,
    *,
    failure_file: str | Path | None = None,
) -> dict[str, Any]:
    """Import successful Batch results into the standard append-only AI cache."""
    client = _openai_client()
    batch = client.batches.retrieve(str(batch_id))
    output_file_id = getattr(batch, "output_file_id", None)
    if not output_file_id:
        raise RuntimeError(
            f"batch {batch_id} has no output_file_id yet (status={getattr(batch, 'status', None)})"
        )

    manifest = _load_manifest(Path(manifest_file))
    cache = AIDecisionCache(cache_path)
    output_text = _content_text(client.files.content(output_file_id))
    imported = 0
    failures: list[dict[str, Any]] = []
    seen: set[str] = set()

    for number, line in enumerate(output_text.splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        custom_id = str(row.get("custom_id", ""))
        meta = manifest.get(custom_id)
        if meta is None:
            failures.append({"line": number, "custom_id": custom_id, "error": "UNKNOWN_CUSTOM_ID"})
            continue
        seen.add(custom_id)
        response = row.get("response")
        if not isinstance(response, dict) or int(response.get("status_code", 0)) != 200:
            failures.append(
                {
                    "line": number,
                    "custom_id": custom_id,
                    "error": row.get("error") or response,
                }
            )
            continue
        body = response.get("body")
        if not isinstance(body, dict):
            failures.append({"line": number, "custom_id": custom_id, "error": "MISSING_RESPONSE_BODY"})
            continue
        structured_text = extract_response_output_text(body)
        if not structured_text:
            failures.append({"line": number, "custom_id": custom_id, "error": "MISSING_OUTPUT_TEXT"})
            continue
        try:
            raw = json.loads(structured_text)
            decision = validate_ai_decision(
                raw,
                model=str(meta["model"]),
                reasoning_effort=str(meta["reasoning_effort"]),
                prompt_version=str(meta["prompt_version"]),
                snapshot_hash=str(meta["snapshot_hash"]),
                response_id=str(body.get("id", "")),
                cache_hit=False,
            )
            cache.put(str(meta["cache_key"]), decision)
            imported += 1
        except Exception as exc:
            failures.append({"line": number, "custom_id": custom_id, "error": str(exc)})

    for custom_id in sorted(set(manifest) - seen):
        failures.append({"custom_id": custom_id, "error": "NO_OUTPUT_ROW"})

    error_file_id = getattr(batch, "error_file_id", None)
    batch_error_text = None
    if error_file_id:
        batch_error_text = _content_text(client.files.content(error_file_id))

    if failure_file is not None:
        path = Path(failure_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for row in failures:
                handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
            if batch_error_text:
                for line in batch_error_text.splitlines():
                    if line.strip():
                        handle.write(line.rstrip() + "\n")

    return {
        "batch_id": str(batch_id),
        "status": getattr(batch, "status", None),
        "manifest_count": len(manifest),
        "imported": imported,
        "failed": len(failures),
        "cache_path": str(cache_path),
        "failure_file": str(failure_file) if failure_file is not None else None,
        "batch_error_file_id": error_file_id,
    }
