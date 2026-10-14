"""Reusable confirmation-to-entry pipeline for strategy signal adapters.

This composes shared evidence and scheduling only. The execution simulator
retains sole responsibility for order eligibility, fills, and intrabar ordering.
"""
from __future__ import annotations

from dataclasses import dataclass

from .candle_confirmation import CandleConfirmationPlan, evaluate_candle_confirmation
from .entry_plan import EntryIntent, EntryPlan, ScheduledEntry, schedule_entry


@dataclass(frozen=True)
class EntryDecision:
    confirmed: bool
    reason: str
    scheduled_entry: ScheduledEntry | None = None


def confirm_and_schedule(
    candles,
    *,
    signal_index: int,
    direction: str,
    candle_plan: CandleConfirmationPlan,
    entry_plan: EntryPlan,
    limit_price: float | None = None,
    reason_prefix: str = "SHARED",
) -> EntryDecision:
    """Check only available candles, then build an immutable execution request.

    This API never fills a trade or searches forward for a confirming candle.
    A caller must invoke it at the decision boundary for a closed signal bar.
    """
    confirmed, reason = evaluate_candle_confirmation(
        candles, signal_index, direction, candle_plan,
        reason_prefix=reason_prefix,
    )
    if not confirmed:
        return EntryDecision(False, reason)
    intent = EntryIntent(
        direction=direction,
        signal_index=signal_index,
        limit_price=limit_price,
    )
    return EntryDecision(True, reason, schedule_entry(intent, entry_plan))
