"""Downstream-only publication of a canonical completed Data Lake run."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any

import duckdb
import pandas as pd

from .feature_research import (_trade_fingerprint, _write_parquet_atomic,
                               write_research_artifacts)
from .report_workbooks import build_backtest_workbook
from .run_manifest import (CATALOG_SNAPSHOT_CONTRACT, PREPARED_CACHE_CONTRACT,
    RUN_MANIFEST_CONTRACT, RUN_MANIFEST_VERSION, atomic_json,
    capture_code_provenance, config_hashes, config_snapshot, file_sha256,
    new_run_identity, runtime_provenance, selected_source_snapshot)
from .statistics import summarize


def _catalog_entry(path: Path, run_dir: Path, fmt: str, rows: int | None = None,
                   schema_version: int = 1, **extra: Any) -> dict[str, Any]:
    return {"path": path.relative_to(run_dir).as_posix(), "format": fmt,
            "schema_version": schema_version, "rows": rows,
            "bytes": path.stat().st_size, "sha256": file_sha256(path), **extra}


class CsvManifestReporter:
    """Publish all artifacts, validate them, then atomically publish the manifest."""

    def __init__(self, output_root: Path):
        self.output_root = Path(output_root)
        self.run_id: str | None = None
        self.run_started_at: str | None = None
        self.code_provenance: dict[str, Any] | None = None

    def begin(self, request, config) -> None:
        if self.run_id is not None:
            raise RuntimeError("reporter instances publish exactly one run")
        self.run_id, self.run_started_at = new_run_identity()
        self.code_provenance = capture_code_provenance()

    def report(self, result, context):
        started = time.perf_counter()
        if self.run_id is None:
            self.begin(result.request, context.config)
        self.output_root.mkdir(parents=True, exist_ok=True)
        run_dir = self.output_root / f"{result.request.symbol}_{result.request.strategy_interval}_{self.run_id}"
        run_dir.mkdir(parents=True, exist_ok=False)
        artifacts_dir = run_dir / "artifacts"; artifacts_dir.mkdir()
        provenance_dir = run_dir / "provenance"; provenance_dir.mkdir()

        # Task 16 writer now owns the one authoritative trade/context Parquets.
        research = write_research_artifacts(run_dir, result, context, authoritative_layout=True)
        trades_path = artifacts_dir / "trades.parquet"
        context_path = artifacts_dir / "feature_context.parquet"
        trade_csv = run_dir / "trade_list.csv"
        result.trades.to_csv(trade_csv, index=False)

        signals = getattr(result, "signals", None)
        if signals is None:
            signals = pd.DataFrame({
                "signal_id": pd.Series(dtype="string"),
                "strategy_index": pd.Series(dtype="int64"),
                "candle_open_time": pd.Series(dtype="datetime64[ns, UTC]"),
                "decision_available_at": pd.Series(dtype="datetime64[ns, UTC]"),
                "side": pd.Series(dtype="string"), "profile": pd.Series(dtype="string"),
                "decision": pd.Series(dtype="string"), "reason_code": pd.Series(dtype="string"),
                "proposed_entry": pd.Series(dtype="float64"),
                "proposed_stop": pd.Series(dtype="float64"),
                "proposed_target": pd.Series(dtype="float64"),
            })
            signal_status = "NOT_AVAILABLE"
        else:
            signals = pd.DataFrame(signals); signal_status = "COLLECTED"
        signals_path = artifacts_dir / "signals.parquet"; _write_parquet_atomic(signals, signals_path)

        telemetry = getattr(result, "telemetry", None)
        if telemetry is None:
            telemetry = pd.DataFrame({"event_time": pd.Series(dtype="datetime64[ns, UTC]"),
                                      "event_type": pd.Series(dtype="string"),
                                      "strategy_index": pd.Series(dtype="int64")})
            telemetry_status = "NOT_ENABLED"
        else:
            telemetry = pd.DataFrame(telemetry); telemetry_status = "COLLECTED"
        telemetry_path = artifacts_dir / "telemetry.parquet"; _write_parquet_atomic(telemetry, telemetry_path)

        source_rows, source_digest = selected_source_snapshot(context.selected_source_records)
        source_frame = pd.DataFrame(source_rows)
        if source_frame.empty:
            source_frame = pd.DataFrame({name: pd.Series(dtype="string") for name in (
                "exchange", "market", "dataset", "symbol", "interval", "frequency",
                "period_start", "period_end", "raw_archive_fingerprint", "canonical_partition_identity")})
            source_frame["size_bytes"] = pd.Series(dtype="int64"); source_frame["mtime_ns"] = pd.Series(dtype="int64")
        source_path = provenance_dir / "source_archives.parquet"; _write_parquet_atomic(source_frame, source_path)

        try:
            summary = summarize(result.trades, context.config.execution.initial_equity)
        except (KeyError, TypeError):
            pnl = pd.to_numeric(result.trades.get("pair_net_pnl", pd.Series(dtype=float)), errors="coerce")
            r = pd.to_numeric(result.trades.get("pair_net_r", pd.Series(dtype=float)), errors="coerce")
            summary = {"total_trades": len(result.trades), "wins": int((pnl > 0).sum()),
                       "losses": int((pnl < 0).sum()), "win_rate": float((pnl > 0).mean()) if len(pnl) else 0.0,
                       "total_net_r": float(r.sum()), "average_net_r": float(r.mean()) if len(r) else 0.0,
                       "net_pnl": float(pnl.sum())}
        summary_path = run_dir / "summary.json"; atomic_json(summary_path, summary)
        quality_path = run_dir / "data_quality.json"
        atomic_json(quality_path, result.data_quality.to_dict() if result.data_quality else {"status": "NOT_AVAILABLE"})
        workbook = build_backtest_workbook(summary, context.config.execution, run_dir,
                                            pd.DataFrame(), pd.DataFrame())

        with duckdb.connect() as con:
            parquet_count = con.execute("SELECT count(*) FROM read_parquet(?)", [str(trades_path)]).fetchone()[0]
            csv_count = con.execute("SELECT count(*) FROM read_csv_auto(?, header=true)", [str(trade_csv)]).fetchone()[0]
        if int(parquet_count) != len(result.trades) or int(csv_count) != len(result.trades):
            raise ValueError("trade CSV/Parquet/summary parity validation failed")

        request = result.request
        effective_intrabar = getattr(context.bundle, "intrabar_interval", request.intrabar_interval)
        hashes = config_hashes(context.config, effective_intrabar)
        artifacts = {
            "trades": _catalog_entry(trades_path, run_dir, "parquet", len(result.trades)),
            "feature_context": _catalog_entry(context_path, run_dir, "parquet", len(context.prepared)),
            "signals": _catalog_entry(signals_path, run_dir, "parquet", len(signals), collection_status=signal_status),
            "telemetry": _catalog_entry(telemetry_path, run_dir, "parquet", len(telemetry), collection_status=telemetry_status),
            "source_archives": _catalog_entry(source_path, run_dir, "parquet", len(source_frame)),
            "trade_csv": _catalog_entry(trade_csv, run_dir, "csv", len(result.trades)),
            "summary": _catalog_entry(summary_path, run_dir, "json", None),
            "workbook": _catalog_entry(workbook, run_dir, "xlsx", None),
            "data_quality": _catalog_entry(quality_path, run_dir, "json", None),
        }
        grouped: dict[tuple[str, Any], list[dict[str, Any]]] = {}
        for row in source_rows: grouped.setdefault((row["dataset"], row["interval"]), []).append(row)
        source_summaries = [{"dataset": key[0], "interval": key[1], "partition_count": len(rows),
                             "source_signature": __import__("hashlib").sha256(
                                 json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                             "identity_version": 1} for key, rows in sorted(grouped.items(), key=str)]
        manifest = {
            "run_manifest_contract": RUN_MANIFEST_CONTRACT, "run_manifest_version": RUN_MANIFEST_VERSION,
            "run_id": self.run_id, "run_started_at": self.run_started_at,
            "run_completed_at": datetime.now(timezone.utc).isoformat(), "run_status": "COMPLETED",
            **(self.code_provenance or {}), "runtime": runtime_provenance(),
            "request": {"symbol": request.symbol, "market": getattr(getattr(request, "market", None), "value", getattr(request, "market", None)),
                        "start": request.start.isoformat(), "end": request.end.isoformat(),
                        "requested_strategy_interval": request.strategy_interval,
                        "requested_intrabar_interval": request.intrabar_interval,
                        "effective_intrabar_interval": effective_intrabar},
            "config": config_snapshot(context.config), "hashes": hashes,
            "catalog": {"catalog_contract_version": CATALOG_SNAPSHOT_CONTRACT,
                        "catalog_snapshot_digest": source_digest, "selected_archive_count": len(source_rows),
                        "source_archives_artifact": "provenance/source_archives.parquet",
                        "source_archives_sha256": artifacts["source_archives"]["sha256"], "datasets": source_summaries},
            "features": result.feature_cache_metadata,
            "prepared": {"prepared_cache_key": result.prepared_cache_key,
                         "prepared_cache_contract": PREPARED_CACHE_CONTRACT, "prepared_cache_version": 1,
                         "prepared_rows": result.prepared_rows},
            "execution_result": {"strategy_rows": result.strategy_rows, "intrabar_rows": result.intrabar_rows,
                                 "completed_trade_rows": len(result.trades),
                                 "trade_fingerprint": research["trade_fingerprint"],
                                 "trade_fingerprint_contract": research["trade_fingerprint_contract"],
                                 "stage_timings": {**result.stage_timings,
                                                   "reporting": time.perf_counter() - started}},
            "artifacts": artifacts, "research": research,
        }
        # Completion marker is deliberately the final write and atomic rename.
        atomic_json(run_dir / "run_manifest.json", manifest)
        object.__setattr__(result, "output_dir", run_dir)
