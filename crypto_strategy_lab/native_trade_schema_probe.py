"""Read-only schema probe for completed native trade_list.csv reports.

This probe records presence of existing engine columns. It intentionally does
not coerce, synthesize, or normalize trade outcomes.
"""
from __future__ import annotations

import csv
from pathlib import Path

NATIVE_REQUIRED_COLUMNS = frozenset({
    "trade_id", "pair_id", "result_type", "side",
    "signal_candle_time", "signal_available_at",
    "entry_time", "actual_entry_timestamp", "entry_price",
    "exit_time", "pair_net_pnl", "pair_total_fees", "pair_net_r",
})
NATIVE_LEG_FIELDS = (
    "entry_price", "quantity", "original_sl", "tp", "exit_time",
    "exit_price", "final_exit_reason", "total_fees", "net_pnl", "net_r",
)


def inspect_native_trade_columns(path: str | Path) -> dict[str, object]:
    """Return exact header and detected leg coverage, or reject a wrong schema."""
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])
    if len(header) != len(set(header)):
        raise ValueError("duplicate native trade report column")
    missing = sorted(NATIVE_REQUIRED_COLUMNS - set(header))
    leg_columns = {
        side: [f"{side}_{field}" for field in NATIVE_LEG_FIELDS
               if f"{side}_{field}" in header]
        for side in ("long", "short")
    }
    return {
        "column_count": len(header),
        "columns": header,
        "missing_required": missing,
        "leg_columns": leg_columns,
        "full_leg_coverage": {side: len(fields) == len(NATIVE_LEG_FIELDS)
                              for side, fields in leg_columns.items()},
    }
