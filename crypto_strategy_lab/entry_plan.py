"""Strategy-agnostic entry scheduling contract.

Separate signal generation from the moment an executable entry can be placed.
This module is intentionally pure: the simulator remains responsible for
exchange/order fills and intrabar price ordering.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite


class EntryTiming(str, Enum):
    SIGNAL_CLOSE = "SIGNAL_CLOSE"
    NEXT_OPEN = "NEXT_OPEN"
    LIMIT_LEVEL = "LIMIT_LEVEL"


@dataclass(frozen=True)
class EntryPlan:
    timing: EntryTiming = EntryTiming.NEXT_OPEN
    limit_timeout_bars: int | None = None

    def __post_init__(self):
        if self.timing == EntryTiming.LIMIT_LEVEL:
            if self.limit_timeout_bars is not None and self.limit_timeout_bars < 1:
                raise ValueError("limit_timeout_bars must be positive")
        elif self.limit_timeout_bars is not None:
            raise ValueError("limit_timeout_bars only applies to LIMIT_LEVEL entries")


@dataclass(frozen=True)
class EntryIntent:
    """Confirmed signal facts; no future fill price or execution assumptions."""

    direction: str
    signal_index: int
    limit_price: float | None = None

    def __post_init__(self):
        if self.direction not in {"LONG", "SHORT"}:
            raise ValueError("entry direction must be LONG or SHORT")
        if self.signal_index < 0:
            raise ValueError("signal_index must be nonnegative")
        if self.limit_price is not None and (
            not isfinite(self.limit_price) or self.limit_price <= 0
        ):
            raise ValueError("limit_price must be finite and positive")


@dataclass(frozen=True)
class ScheduledEntry:
    direction: str
    earliest_index: int
    timing: EntryTiming
    limit_price: float | None = None
    expires_after_index: int | None = None


def schedule_entry(intent: EntryIntent, plan: EntryPlan) -> ScheduledEntry:
    """Map a confirmed signal to an eligible execution interval.

    SIGNAL_CLOSE is eligible at the confirmed bar close, NOT at its open.
    The execution engine must enforce event ordering and fill restrictions.
    NEXT_OPEN and LIMIT_LEVEL are never eligible on the signal candle.
    """
    if plan.timing == EntryTiming.LIMIT_LEVEL and intent.limit_price is None:
        raise ValueError("LIMIT_LEVEL requires an explicit limit_price")
    if plan.timing != EntryTiming.LIMIT_LEVEL and intent.limit_price is not None:
        raise ValueError("limit_price is valid only for LIMIT_LEVEL")
    earliest = intent.signal_index + int(plan.timing != EntryTiming.SIGNAL_CLOSE)
    return ScheduledEntry(
        direction=intent.direction,
        earliest_index=earliest,
        timing=plan.timing,
        limit_price=intent.limit_price,
        expires_after_index=(
            earliest + plan.limit_timeout_bars - 1
            if plan.timing == EntryTiming.LIMIT_LEVEL
            and plan.limit_timeout_bars is not None
            else None
        ),
    )


def is_scheduled_entry_eligible(entry: ScheduledEntry, execution_index: int) -> bool:
    """Whether an order may be considered for filling on this candle.

    Eligibility does not imply a fill: the simulator must still validate price
    interaction, order side, and intrabar ordering.
    """
    if execution_index < 0:
        return False
    if execution_index < entry.earliest_index:
        return False
    if entry.expires_after_index is not None and execution_index > entry.expires_after_index:
        return False
    # Signal-close/next-open orders are single-event intents; limit orders
    # can remain working over their configured eligible interval.
    if entry.timing != EntryTiming.LIMIT_LEVEL:
        return execution_index == entry.earliest_index
    return True


def limit_order_touched(
    entry: ScheduledEntry,
    execution_index: int,
    candle_low: float,
    candle_high: float,
) -> bool:
    """Check price-range contact only after a limit order is eligible.

    This is a candidate touch, not a simulated fill. Gap pricing, bid/ask,
    queue priority and intrabar stop/target ordering belong to the simulator.
    """
    if entry.timing != EntryTiming.LIMIT_LEVEL or entry.limit_price is None:
        return False
    if not is_scheduled_entry_eligible(entry, execution_index):
        return False
    if not (isfinite(candle_low) and isfinite(candle_high)):
        return False
    if candle_low <= 0 or candle_high < candle_low:
        return False
    return candle_low <= entry.limit_price <= candle_high
