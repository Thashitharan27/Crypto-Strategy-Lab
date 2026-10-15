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


def _identity(interval, frequency, period_start, period_end, fingerprint):
    if not all((interval, frequency, period_start, period_end, fingerprint)):
        raise ValueError("missing source identity field")
    return (str(interval), str(frequency), pd.Timestamp(period_start).isoformat(),
            pd.Timestamp(period_end).isoformat(), str(fingerprint))


def verify_source_provenance(freeze: dict, source_rows: pd.DataFrame) -> dict[str, int]:
    selection = freeze["selection"]
    if selection["symbol"] != "BTCUSDT" or selection["strategy_interval"] != "4h" or selection["intrabar_interval"] != "1m":
        raise ValueError("unexpected baseline selection")
    metadata = selection["catalog_records"]
    if len(metadata) != len(freeze["files"]):
        raise ValueError("catalog metadata and hashed file counts disagree")
    actual = Counter()
    for label, record in metadata.items():
        if label not in freeze["files"]:
            raise ValueError(f"unhashed catalog record: {label}")
        interval = "4h" if label.startswith("BTCUSDT_4h_") else "1m" if label.startswith("BTCUSDT_1m_") else None
        actual[_identity(interval, record["frequency"], record["period_start"], record["period_end"], record["catalog_fingerprint"])] += 1

    required = {"exchange", "market", "dataset", "symbol", "interval", "frequency",
                "period_start", "period_end", "raw_archive_fingerprint"}
    if not required.issubset(source_rows.columns):
        raise ValueError(f"saved provenance missing fields: {sorted(required - set(source_rows.columns))}")
    subset = source_rows.loc[
        (source_rows["exchange"] == "binance")
        & (source_rows["market"] == "futures_um")
        & (source_rows["dataset"] == "klines")
        & (source_rows["symbol"] == "BTCUSDT")
        & (source_rows["interval"].isin(["4h", "1m"]))
    ]
    expected = Counter(_identity(row.interval, row.frequency, row.period_start,
                                 row.period_end, row.raw_archive_fingerprint)
                       for row in subset.itertuples(index=False))
    if actual != expected:
        missing = sum((expected - actual).values())
        unexpected = sum((actual - expected).values())
        raise ValueError(f"saved-run source provenance mismatch: {missing} missing, {unexpected} unexpected")
    counts = {interval: sum(n for key, n in actual.items() if key[0] == interval)
              for interval in ("4h", "1m")}
    if counts["4h"] != selection["strategy_record_count"] or counts["1m"] != selection["intrabar_record_count"]:
        raise ValueError("frozen source count mismatch")
    return counts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-json", type=Path, required=True)
    parser.add_argument("--saved-provenance-parquet", type=Path, required=True)
    args = parser.parse_args(argv)
    freeze = json.loads(args.freeze_json.read_text(encoding="utf-8"))
    provenance = pd.read_parquet(args.saved_provenance_parquet)
    counts = verify_source_provenance(freeze, provenance)
    print(f"Saved-run source metadata matches frozen catalog: 4h={counts['4h']}, 1m={counts['1m']}")
    print("This is metadata matching only; byte integrity and trade parity remain separate gates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
