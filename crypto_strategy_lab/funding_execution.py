"""Funding-settlement cashflow accounting for the native futures simulator.

Funding context remains causal and strategy-facing in ``features.funding``. This
module consumes the exact settlement batches only after trades have closed, so
funding changes realized PnL/equity without becoming an entry signal or creating
look-ahead in strategy decisions.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from crypto_strategy_lab.rule_native_engine import (
    RuleAwareDataLakeProductionBacktestEngine,
)
from crypto_strategy_lab.trade import Side


_FUNDING_SETTLEMENTS_COLUMN = "funding_settlements_json"


def _utc_ns(value) -> np.datetime64:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert("UTC").tz_localize(None)
    return np.datetime64(timestamp.to_datetime64(), "ns")


class FundingAwareRuleBacktestEngine(RuleAwareDataLakeProductionBacktestEngine):
    """Rule-aware simulator whose net results include perpetual funding cashflows."""

    @classmethod
    def from_prepared(cls, *args, **kwargs):
        engine = super().from_prepared(*args, **kwargs)
        engine._funding_event_times = np.array([], dtype="datetime64[ns]")
        engine._funding_event_rates = np.array([], dtype=float)

        block = getattr(engine, "research_features", {}).get("funding_context")
        values = getattr(block, "values", None) if block is not None else None
        batches = None if values is None else values.get(_FUNDING_SETTLEMENTS_COLUMN)
        if batches is not None:
            event_times: list[np.datetime64] = []
            event_rates: list[float] = []
            for raw in batches:
                if raw is None:
                    continue
                try:
                    parsed = json.loads(str(raw))
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ValueError("Invalid prepared funding settlement payload") from exc
                for timestamp_ns, rate in parsed:
                    numeric_rate = float(rate)
                    if not np.isfinite(numeric_rate):
                        continue
                    event_times.append(np.datetime64(int(timestamp_ns), "ns"))
                    event_rates.append(numeric_rate)

            if event_times:
                times = np.asarray(event_times, dtype="datetime64[ns]")
                rates = np.asarray(event_rates, dtype=float)
                order = np.argsort(times, kind="stable")
                times, rates = times[order], rates[order]
                # Settlement batches are non-overlapping by construction, but keep
                # the runtime defensive against malformed duplicate cache rows.
                keep = np.ones(len(times), dtype=bool)
                if len(times) > 1:
                    keep[:-1] = times[:-1] != times[1:]
                engine._funding_event_times = times[keep]
                engine._funding_event_rates = rates[keep]

        # Exact settlement payloads are an internal execution transport. The
        # normal entry-time funding research fields remain published, but the JSON
        # batch itself should not widen every completed-trade row/report.
        engine.research_output_columns = tuple(
            column
            for column in getattr(engine, "research_output_columns", ())
            if column != _FUNDING_SETTLEMENTS_COLUMN
        )
        return engine

    def _funding_reference_price(self, event_time: np.datetime64, pos) -> tuple[float, str]:
        """Use the closest causal execution price available at settlement time.

        Binance funding uses mark-price notional. Historical funding archives do
        not contain the mark price, so the backtester uses the exact intrabar open
        when available and otherwise the containing strategy-candle open. This is
        deliberately reported as a proxy rather than presented as exact mark price.
        """
        intrabar = getattr(self, "intrabar_data", None)
        if intrabar is not None and hasattr(intrabar, "timestamp") and len(intrabar.timestamp):
            index = int(np.searchsorted(intrabar.timestamp, event_time, side="right") - 1)
            if index >= 0:
                price = float(intrabar.open[index])
                if np.isfinite(price) and price > 0:
                    return price, "INTRABAR_OPEN_PROXY"

        strategy_times = np.asarray(getattr(self, "times", ()), dtype="datetime64[ns]")
        if len(strategy_times):
            index = int(np.searchsorted(strategy_times, event_time, side="right") - 1)
            if index >= 0:
                price = float(self.open[index])
                if np.isfinite(price) and price > 0:
                    return price, "STRATEGY_OPEN_PROXY"

        return float(pos.entry_price), "ENTRY_PRICE_FALLBACK"

    @staticmethod
    def _quantity_reductions(pos) -> list[tuple[np.datetime64, float]]:
        reductions: list[tuple[np.datetime64, float]] = []
        for time_name, quantity_name in (
            ("sl1_exit_time", "sl1_quantity"),
            ("tp1_exit_time", "tp1_quantity"),
            ("tp2_exit_time", "tp2_quantity"),
        ):
            exit_time = getattr(pos, time_name, None)
            quantity = float(getattr(pos, quantity_name, 0.0) or 0.0)
            if exit_time is not None and quantity > 0:
                reductions.append((_utc_ns(exit_time), quantity))
        reductions.sort(key=lambda item: item[0])
        return reductions

    def _apply_funding_cashflow(self, pos) -> None:
        if getattr(pos, "funding_applied", False) or pos.is_open:
            return

        pos.funding_applied = True
        pos.funding_event_count = 0
        pos.funding_paid = 0.0
        pos.funding_received = 0.0
        pos.funding_net_pnl = 0.0
        pos.funding_price_source = "NONE"

        times = getattr(self, "_funding_event_times", np.array([], dtype="datetime64[ns]"))
        rates = getattr(self, "_funding_event_rates", np.array([], dtype=float))
        if not len(times) or pos.exit_time is None:
            return

        entry_time = _utc_ns(pos.entry_time)
        exit_time = _utc_ns(pos.exit_time)
        # Boundary-exclusive semantics avoid charging an event that occurs at the
        # exact instant the trade enters or exits. Ordinary settlements strictly
        # inside the holding interval are unambiguous.
        left = int(np.searchsorted(times, entry_time, side="right"))
        right = int(np.searchsorted(times, exit_time, side="left"))
        if left >= right:
            return

        original_quantity = float(getattr(pos, "original_quantity", 0.0) or 0.0)
        if original_quantity <= 0:
            original_quantity = float(pos.quantity)
        reductions = self._quantity_reductions(pos)
        side_multiplier = -1.0 if pos.side == Side.LONG else 1.0
        sources: set[str] = set()

        paid = received = 0.0
        for event_time, rate in zip(times[left:right], rates[left:right]):
            reduced = sum(quantity for reduction_time, quantity in reductions if reduction_time < event_time)
            quantity = max(0.0, original_quantity - reduced)
            if quantity <= 0:
                continue
            price, source = self._funding_reference_price(event_time, pos)
            sources.add(source)
            cashflow = side_multiplier * quantity * price * float(rate)
            if cashflow >= 0:
                received += cashflow
            else:
                paid += -cashflow
            pos.funding_event_count += 1

        funding_net = received - paid
        pos.funding_paid = paid
        pos.funding_received = received
        pos.funding_net_pnl = funding_net
        pos.funding_price_source = "+".join(sorted(sources)) if sources else "NONE"
        pos.net_pnl += funding_net
        pos.net_r = pos.net_pnl / pos.risk_amount if pos.risk_amount else 0.0

    def _collect_closed_pairs(self, force=False):
        # Apply funding before the parent updates shared capital from net_pnl.
        for pair in self.active_pairs:
            if force or not pair.is_open:
                for pos in pair.positions():
                    if not pos.is_open:
                        self._apply_funding_cashflow(pos)
        return super()._collect_closed_pairs(force=force)

    def _pos_cols(self, prefix, pos):
        cols = super()._pos_cols(prefix, pos)
        cols.update(
            {
                f"{prefix}_funding_event_count": int(getattr(pos, "funding_event_count", 0) or 0),
                f"{prefix}_funding_paid": float(getattr(pos, "funding_paid", 0.0) or 0.0),
                f"{prefix}_funding_received": float(getattr(pos, "funding_received", 0.0) or 0.0),
                f"{prefix}_funding_net_pnl": float(getattr(pos, "funding_net_pnl", 0.0) or 0.0),
                f"{prefix}_funding_price_source": getattr(pos, "funding_price_source", "NONE"),
            }
        )
        return cols

    def _build_result_row(self, p, row_kind, positions):
        row = super()._build_result_row(p, row_kind, positions)
        paid = sum(float(getattr(pos, "funding_paid", 0.0) or 0.0) for pos in positions)
        received = sum(float(getattr(pos, "funding_received", 0.0) or 0.0) for pos in positions)
        event_count = sum(int(getattr(pos, "funding_event_count", 0) or 0) for pos in positions)
        row.update(
            pair_funding_event_count=event_count,
            pair_funding_paid=paid,
            pair_funding_received=received,
            pair_funding_net_pnl=received - paid,
        )
        return row
