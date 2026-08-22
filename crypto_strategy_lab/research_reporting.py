"""Artifact-only reporters for composed research runs."""
from __future__ import annotations
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path


class CsvManifestReporter:
    def __init__(self, output_root: Path): self.output_root = Path(output_root)

    def report(self, result, context):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_dir = self.output_root / f"{result.request.symbol}_{result.request.strategy_interval}_{stamp}"
        run_dir.mkdir(parents=True, exist_ok=False)
        result.trades.to_csv(run_dir / "trade_list.csv", index=False)
        manifest = {
            "config_contract": "research_run_config_v3",
            "request": {"symbol": result.request.symbol, "start": result.request.start.isoformat(),
                        "end": result.request.end.isoformat(),
                        "strategy_interval": result.request.strategy_interval,
                        "intrabar_interval": result.request.intrabar_interval},
            "prepared_cache": {"hit": result.prepared_cache_hit, "key": result.prepared_cache_key},
            "features": result.feature_cache_metadata, "canonical_cache": result.canonical_cache_metadata,
            "strategy_rows": result.strategy_rows, "intrabar_rows": result.intrabar_rows,
            "prepared_rows": result.prepared_rows, "trade_rows": len(result.trades),
        }
        (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        object.__setattr__(result, "output_dir", run_dir)

