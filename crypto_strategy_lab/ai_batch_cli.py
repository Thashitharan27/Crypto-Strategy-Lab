"""CLI for preparing, submitting, checking, and collecting AI decision batches."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from crypto_strategy_lab.ai_batch import (
    batch_status,
    collect_batch_to_cache,
    prepare_engine_batches,
    submit_batch_file,
)
from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.gui.config_logic import build_backtest_config, load_config_json
from crypto_strategy_lab.loader import load_backtest_data


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline OpenAI Batch API cache workflow for OPENAI_DECISION"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="Build request/manifest JSONL files without API spend")
    prepare.add_argument("--config", type=Path, required=True)
    prepare.add_argument("--output-dir", type=Path, default=Path("output/ai_batches"))
    prepare.add_argument("--include-cached", action="store_true")
    prepare.add_argument("--max-requests", type=int, default=50_000)

    submit = sub.add_parser("submit", help="Upload and submit one prepared JSONL file")
    submit.add_argument("--request-file", type=Path, required=True)

    status = sub.add_parser("status", help="Read one OpenAI batch status")
    status.add_argument("--batch-id", required=True)

    collect = sub.add_parser("collect", help="Import completed batch output into AI cache")
    collect.add_argument("--batch-id", required=True)
    collect.add_argument("--manifest-file", type=Path, required=True)
    collect.add_argument("--cache", type=Path, default=Path("output/ai_decision_cache.jsonl"))
    collect.add_argument("--failure-file", type=Path)

    return parser


def _prepare(args: argparse.Namespace) -> dict:
    values = load_config_json(args.config)
    config = build_backtest_config(values, require_paths=True)
    data, intrabar = load_backtest_data(config)
    engine = BacktestEngine(data, config, intrabar)
    result = prepare_engine_batches(
        engine,
        args.output_dir,
        include_cached=bool(args.include_cached),
        max_requests=int(args.max_requests),
    )
    payload = result.payload()
    payload["note"] = (
        "Preparation makes no OpenAI API call. WAIT_UNTIL_CLOSED can over-generate "
        "candidate candles because active-position state depends on earlier AI decisions."
    )
    return payload


def main() -> None:
    args = _parser().parse_args()
    if args.command == "prepare":
        payload = _prepare(args)
    elif args.command == "submit":
        payload = submit_batch_file(args.request_file)
    elif args.command == "status":
        payload = batch_status(args.batch_id)
    elif args.command == "collect":
        failure_file = args.failure_file
        if failure_file is None:
            failure_file = Path("output/ai_batches") / f"{args.batch_id}.failures.jsonl"
        payload = collect_batch_to_cache(
            args.batch_id,
            args.manifest_file,
            args.cache,
            failure_file=failure_file,
        )
    else:  # pragma: no cover - argparse enforces this.
        raise AssertionError(args.command)
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
