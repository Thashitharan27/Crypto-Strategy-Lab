"""Read-only trade-level parity checks for future desktop/browser regression fixtures.

Inputs are *frozen* trade row mappings from independent executions. No market
data is fetched and this module does not run or modify a trading strategy.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isclose, isfinite
from typing import Any

# A versioned comparison contract. An adapter from each actual report schema
# must explicitly map into these fields; silently missing fields are failures.
TRADE_FIELDS = (
    "trade_id", "side", "signal_time", "entry_time", "exit_time",
    "entry_price", "exit_price", "quantity", "stop_price", "target_price",
    "exit_reason", "fees", "slippage", "realized_r", "pnl",
)
NUMERIC_FIELDS = frozenset((
    "entry_price", "exit_price", "quantity", "stop_price", "target_price",
    "fees", "slippage", "realized_r", "pnl",
))


@dataclass(frozen=True)
class ParityDifference:
    trade_index: int
    field: str
    expected: Any
    actual: Any


def compare_trades(
    expected: Sequence[Mapping[str, Any]],
    actual: Sequence[Mapping[str, Any]],
    *,
    abs_tol: float = 1e-10,
    rel_tol: float = 1e-10,
) -> list[ParityDifference]:
    """Compare ordered trades without masking changes to fills or chronology.

    Numerical tolerance is for representation differences only, not an
    authorization to accept altered prices. Consumers may choose zero tolerance.
    """
    if not isfinite(abs_tol) or not isfinite(rel_tol) or abs_tol < 0 or rel_tol < 0:
        raise ValueError("tolerances must be finite nonnegative numbers")
    differences: list[ParityDifference] = []
    if len(expected) != len(actual):
        differences.append(ParityDifference(-1, "trade_count", len(expected), len(actual)))
    # A duplicated trade identity makes a purportedly exact historical replay
    # ambiguous even when both reports contain the same duplicated rows.
    for label, rows in (("expected", expected), ("actual", actual)):
        seen: set[str] = set()
        for index, row in enumerate(rows):
            identity = row.get("trade_id")
            if not isinstance(identity, str) or not identity.strip():
                differences.append(ParityDifference(index, f"{label}_trade_id_valid", identity, "nonempty string"))
            elif identity in seen:
                differences.append(ParityDifference(index, f"{label}_trade_id_duplicate", identity, "unique trade ID"))
            else:
                seen.add(identity)
    for index, (old, new) in enumerate(zip(expected, actual)):
        for key in TRADE_FIELDS:
            if key not in old or key not in new:
                differences.append(ParityDifference(
                    index, key, old.get(key, "<MISSING>"), new.get(key, "<MISSING>")
                ))
                continue
            left, right = old[key], new[key]
            if key in NUMERIC_FIELDS:
                # bool is an int subclass, but never a valid trade amount.
                if (isinstance(left, bool) or isinstance(right, bool)
                    or not isinstance(left, (int, float))
                    or not isinstance(right, (int, float))
                    or not isfinite(left) or not isfinite(right)
                    or not isclose(left, right, rel_tol=rel_tol, abs_tol=abs_tol)):
                    differences.append(ParityDifference(index, key, left, right))
            elif left != right or type(left) is not type(right):
                differences.append(ParityDifference(index, key, left, right))
    return differences
