"""Compare frozen local catalog selection with a saved run's source provenance.

Operator-only, read-only verification. This compares catalog metadata identity,
not actual ZIP bytes or candle/trade parity. Use the existing freeze utility
for content hashing and canonical engine tooling for replay.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

import pandas as pd
import duckdb


def _interval(value):
    return "none" if pd.isna(value) else str(value)


def _identity(interval, frequency, period_start, period_end, fingerprint):
    if not all((interval, frequency, period_start, period_end, fingerprint)):
        raise ValueError("missing source identity field")
    return (str(interval), str(frequency), pd.Timestamp(period_start).isoformat(),
            pd.Timestamp(period_end).isoformat(), str(fingerprint))


def verify_source_provenance(freeze: dict, source_rows: pd.DataFrame) -> dict[str, int]:
    if freeze.get("commit_sha") != "1ad8a2161877260d9f1d790f583a82e065f8730e":
        raise ValueError("frozen manifest commit does not match original 79-trade baseline")
    if freeze.get("strategy_timeframe_minutes") != 240 or freeze.get("intrabar_timeframe_minutes") != 1:
        raise ValueError("frozen baseline timeframes do not match 4h/1m")
    selection = freeze["selection"]
    if selection["symbol"] != "BTCUSDT" or selection["strategy_interval"] != "4h" or selection["intrabar_interval"] != "1m":
        raise ValueError("unexpected baseline selection")
    if (pd.Timestamp(selection["start"]) != pd.Timestamp("2020-06-01T00:00:00Z")
        or pd.Timestamp(selection["end"]) != pd.Timestamp("2026-09-01T00:00:00Z")):
        raise ValueError("frozen manifest trading window does not match original baseline")
    warmup_value = selection.get("strategy_source_start", selection["start"])
    try:
        warmup_start = pd.Timestamp(warmup_value)
    except (TypeError, ValueError) as error:
        raise ValueError("frozen manifest has invalid strategy warmup start") from error
    if pd.isna(warmup_start):
        raise ValueError("frozen manifest has invalid strategy warmup start")
    if warmup_start.tzinfo is None:
        raise ValueError("frozen manifest has timezone-naive strategy warmup start")
    if warmup_start > pd.Timestamp("2020-01-01T00:00:00Z"):
        raise ValueError("frozen manifest omits original strategy warmup sources")
    metadata = selection["catalog_records"]
    full_scope = selection.get("source_scope") == "all_saved_datasets"
    if len(metadata) != len(freeze["files"]):
        raise ValueError("catalog metadata and hashed file counts disagree")
    actual = Counter()
    for label, record in metadata.items():
        if label not in freeze["files"]:
            raise ValueError(f"unhashed catalog record: {label}")
        interval = record.get("interval") if full_scope else ("4h" if label.startswith("BTCUSDT_4h_") else "1m" if label.startswith("BTCUSDT_1m_") else None)
        key = _identity(_interval(interval), record["frequency"], record["period_start"], record["period_end"], record["catalog_fingerprint"])
        actual[((record.get("dataset", "klines"),) + key) if full_scope else key] += 1

    required = {"exchange", "market", "dataset", "symbol", "interval", "frequency",
                "size_bytes", "mtime_ns",
                "period_start", "period_end", "raw_archive_fingerprint"}
    if not required.issubset(source_rows.columns):
        raise ValueError(f"saved provenance missing fields: {sorted(required - set(source_rows.columns))}")
    subset = source_rows.loc[
        (source_rows["exchange"] == "binance")
        & (source_rows["market"] == "futures_um")
        & ((source_rows["dataset"].isin(["klines", "mark_price_klines", "index_price_klines", "premium_index_klines", "funding_rate", "metrics"])) if full_scope else (source_rows["dataset"] == "klines"))
        & (source_rows["symbol"] == "BTCUSDT")
        & ((source_rows["interval"].isin(["4h", "1m"])) if not full_scope else True)
    ]
    expected = Counter(((row.dataset,) if full_scope else ()) + _identity(_interval(row.interval), row.frequency, row.period_start,
                                 row.period_end, row.raw_archive_fingerprint)
                       for row in subset.itertuples(index=False))
    if actual != expected:
        missing = sum((expected - actual).values())
        unexpected = sum((actual - expected).values())
        raise ValueError(f"saved-run source provenance mismatch: {missing} missing, {unexpected} unexpected")
    # Compare exact file stat records in addition to the existing identity multiset.
    expected_stats = Counter(((str(row.dataset),) if full_scope else ()) + (str(row.interval or "none"), str(row.raw_archive_fingerprint), int(row.size_bytes), int(row.mtime_ns))
                             for row in subset.itertuples(index=False))
    actual_stats = Counter()
    for label, record in metadata.items():
        interval = (_interval(record.get("interval"))) if full_scope else ("4h" if label.startswith("BTCUSDT_4h_") else "1m")
        if "size_bytes" not in record or "mtime_ns" not in record:
            raise ValueError(f"frozen catalog stat metadata missing: {label}")
        if not isinstance(record["size_bytes"], int) or not isinstance(record["mtime_ns"], int):
            raise ValueError(f"invalid frozen catalog stat metadata: {label}")
        if record["size_bytes"] != freeze["files"][label]["bytes"]:
            raise ValueError(f"frozen catalog size disagrees with hashed bytes: {label}")
        actual_stats[((record.get("dataset", "klines"),) if full_scope else ()) + (interval, str(record["catalog_fingerprint"]), record["size_bytes"], record["mtime_ns"])] += 1
    if actual_stats != expected_stats:
        raise ValueError("saved-run source stat metadata mismatch")
    counts = {interval: sum(n for key, n in actual.items() if key[1 if full_scope else 0] == interval)
              for interval in ("4h", "1m")}
    if full_scope:
        counts["4h"] = sum(n for key, n in actual.items() if key[0] == "klines" and key[1] == "4h")
        counts["1m"] = sum(n for key, n in actual.items() if key[0] == "klines" and key[1] == "1m")
    if counts["4h"] != selection["strategy_record_count"] or counts["1m"] != selection["intrabar_record_count"]:
        raise ValueError("frozen source count mismatch")
    if full_scope:
        if len(subset) != 2956 or len(metadata) != 2956:
            raise ValueError("full saved-run source inventory count mismatch")
        counts["4h"] = sum(n for key, n in actual.items() if key[0] == "klines" and key[1] == "4h")
        counts["1m"] = sum(n for key, n in actual.items() if key[0] == "klines" and key[1] == "1m")
        counts["all_saved_sources"] = 2956
    return counts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-json", type=Path, required=True)
    parser.add_argument("--saved-provenance-parquet", type=Path, required=True)
    args = parser.parse_args(argv)
    freeze = json.loads(args.freeze_json.read_text(encoding="utf-8"))
    with duckdb.connect(":memory:") as connection:
        provenance = connection.execute(
            "SELECT * FROM read_parquet(?)", [str(args.saved_provenance_parquet)]
        ).df()
    counts = verify_source_provenance(freeze, provenance)
    print(f"Saved-run source metadata matches frozen catalog: 4h={counts['4h']}, 1m={counts['1m']}")
    if counts.get("all_saved_sources") == 2956:
        print("Full saved-run source metadata matches all 2,956 catalog records; actual archive content hashes are captured in the frozen manifest.")
    else:
        print("PARTIAL SOURCE SCOPE ONLY: validates BTCUSDT 4h/1m klines, not the full 2,956-archive saved-run inventory.")
    print("The saved-run feature manifest also references mark/index price, funding, metrics, and context candles.")
    print("Archive content, all required feature inputs and 79-trade execution parity remain unverified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
