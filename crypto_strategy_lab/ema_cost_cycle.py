"""Optional EMA-cross cost-cover / break-even / re-entry execution state machine."""
from __future__ import annotations

import numpy as np
import pandas as pd
from types import SimpleNamespace

from .config import IntrabarMissingPolicy
from .trade import ExitReason, ExitSource, Side


class EmaCostCycleMixin:
    def _ema_initial_phantom_enabled(self):
        return self._ema_cost_cycle_enabled() and bool(getattr(self.config, "ema_cross_initial_phantom_enabled", False))

    def run(self):
        result = super().run()
        records = getattr(self, "ema_initial_phantom_setups", [])
        for record in records:
            if record["status"] == "PENDING":
                record["status"] = "END_OF_DATA"
        if records:
            result.attrs["ema_initial_phantom_setups"] = records
        return result

    def _arm_ema_initial_phantom(self, i, decision):
        indicator = int(decision["indicator_index"])
        if self.active_pairs:
            return
        passed, reason = self._entry_filter_result(indicator, i)
        plan = self._ema_100_cross_stop_plan(indicator, i)
        if not passed or not plan.get("passed"):
            self._record_skipped_signal(indicator, reason if not passed else plan.get("reason", "INVALID_PHANTOM_STOP"))
            return
        direction = self._selected_direction(indicator)
        sign = 1 if direction == "LONG" else -1
        entry = float(self._expected_entry_price(indicator, i, direction))
        distance = float(plan["distance"])
        if not np.isfinite(distance) or distance <= 0:
            return
        previous = getattr(self, "_ema_cycle_pending", None)
        if previous and previous.get("initial_phantom"):
            previous["initial_phantom"].update(status="CANCELLED_EMA_ALIGNMENT", cancelled_at=pd.Timestamp(self.times[i]).isoformat())
        records = getattr(self, "ema_initial_phantom_setups", [])
        self.ema_initial_phantom_setups = records
        record = {"setup_id": len(records)+1, "side": direction,
                  "initial_time": pd.Timestamp(self.times[i]).isoformat(),
                  "initial_entry": entry, "initial_stop": entry-sign*distance,
                  "initial_ema_gap": self._ema_cycle_gap(i-1),
                  "distance": distance, "status": "PENDING", "checkpoints": []}
        records.append(record)
        self._ema_cycle_pending = {
            "direction": direction, "trigger": entry+sign*distance, "stop": entry,
            "available": pd.Timestamp(self.times[i]), "cycle": 0, "parent": None,
            "root": None, "reference_gap": self._ema_cycle_gap(i-1),
            "distance": distance, "checkpoint": 1,
            "owner": SimpleNamespace(ema_cycle_phantom_records=record["checkpoints"]),
            "initial_phantom": record,
        }

    def _ema_cost_cycle_enabled(self):
        return bool(
            getattr(self.config, "ema_cross_cost_cycle_enabled", False)
            and getattr(self, "signal_strategy_mode", "") == "EMA_9_20_PULLBACK"
            and self._ema_920_cross_plan()
        )

    def _init_ema_cost_cycle(self, pair, schedule=None):
        """This option owns protection and partial exits for the whole runner."""
        pending = getattr(self, "_ema_cycle_opening", None)
        for pos in pair.positions():
            pos.ema_cost_cycle_enabled = True
            pos.ema_cycle_intrabar_entry = str((schedule or {}).get("fill_price_source", "")) in {"EMA_CROSS_CONFIRMATION", "EMA_COST_CYCLE_REENTRY"}
            pos.ema_cycle_number = pending["cycle"] if pending else 0
            pos.ema_cycle_parent_id = pending["parent"] if pending else None
            pos.ema_cycle_root_id = (pending["root"] or pair.pair_id) if pending else pair.pair_id
            initial = pending.get("initial_phantom") if pending else None
            pos.ema_cycle_initial_phantom_id = initial["setup_id"] if initial else None
            pos.ema_cycle_initial_phantom_records = list(initial["checkpoints"]) if initial else []
            if initial:
                initial.update(status="ENTERED", entry_time=pd.Timestamp(pos.entry_time).isoformat(),
                               entry_price=float(pos.entry_price), stop=float(pos.original_sl),
                               entry_ema_gap=self._ema_cycle_gap(pos.entry_index-1),
                               reference_ema_gap=pending["reference_gap"],
                               entry_checkpoint=pending["checkpoint"], pair_id=pair.pair_id)
            pos.ema_cycle_entry_ema_gap = self._ema_cycle_gap(pos.entry_index - 1)
            pos.ema_cycle_reference_ema_gap = pending["reference_gap"] if pending else np.nan
            pos.ema_cycle_reentry_checkpoint = pending.get("checkpoint", 1) if pending else 0
            pos.ema_cycle_phantom_records = []
            pos.ema_cycle_widening_enabled = bool(getattr(self.config, "ema_cross_reentry_widening_enabled", False))
            pos.ema_cycle_trigger = pos.entry_price + (1 if pos.side == Side.LONG else -1) * abs(pos.entry_price - pos.original_sl)
            pos.partial_tp_enabled = True
            pos.partial_sl_enabled = False
            pos.original_quantity = pos.remaining_quantity = pos.quantity
            pos.tp1_price = pos.ema_cycle_trigger
            pos.tp2_price = np.inf if pos.side == Side.LONG else -np.inf
            pos.tp1_quantity = pos.tp2_quantity = 0.0
            pos.tp = np.nan
            pos.be_enabled = True
            pos.be_offset_r = 0.0
            pos.profile_break_even_activation_r = 1.0
            pos.trailing_enabled = pos.r_step_trailing_enabled = False
            pos.atr_checkpoint_extension_enabled = False

    def _ema_cycle_aligned(self, i, direction):
        if i < 0:
            return False
        fast, slow = float(self.ema_20_values[i]), float(self.ema_100_values[i])
        return np.isfinite(fast) and np.isfinite(slow) and (fast > slow if direction == "LONG" else fast < slow)

    def _ema_cycle_gap(self, i):
        """EMA distance in price units, using completed strategy candles only."""
        if i < 0:
            return np.nan
        fast, slow = float(self.ema_20_values[i]), float(self.ema_100_values[i])
        return abs(fast - slow) if np.isfinite(fast) and np.isfinite(slow) else np.nan

    def _ema_cycle_phantom_checkpoints(self, pending, i, timestamp, high, low):
        """Advance rejected levels without placing orders or changing capital."""
        initial = pending.get("initial_phantom")
        if not initial and not getattr(self.config, "ema_cross_reentry_widening_enabled", False):
            return
        gap = self._ema_cycle_gap(i - 1)
        reference = pending["reference_gap"]
        if not initial and np.isfinite(gap) and np.isfinite(reference) and gap > reference:
            return
        sign = 1 if pending["direction"] == "LONG" else -1
        while (high >= pending["trigger"] if sign > 0 else low <= pending["trigger"]):
            reference = pending["reference_gap"]
            if (not initial or pending["checkpoint"] >= 2) and np.isfinite(gap) and np.isfinite(reference) and gap > reference:
                break
            pending["owner"].ema_cycle_phantom_records.append({
                "time": pd.Timestamp(timestamp).isoformat(),
                "checkpoint": pending["checkpoint"], "side": pending["direction"],
                "entry": pending["trigger"], "stop": pending["stop"],
                "ema_gap": gap if np.isfinite(gap) else None,
                "reference_ema_gap": reference if np.isfinite(reference) else None,
                "status": "PHANTOM_FIRST_1R" if initial and pending["checkpoint"] == 1 else "PHANTOM_EMA_NOT_WIDER",
            })
            if initial:
                pending["reference_gap"] = gap
            pending["stop"] = pending["trigger"]
            pending["trigger"] += sign * pending["distance"]
            if not np.isfinite(pending["trigger"]) or pending["trigger"] == pending["stop"]:
                raise ValueError("EMA phantom checkpoint distance cannot advance the price")
            pending["checkpoint"] += 1

    def _ema_cycle_rows(self, i):
        """Use execution bars; honor the ordinary missing-data policy."""
        start = pd.Timestamp(self.times[i])
        end = start + self.entry_delta
        data = getattr(self, "intrabar_data", None)
        if self.config.use_intrabar_data and data is not None:
            fast = getattr(data, "fast_window", None)
            if callable(fast):
                window = fast(start, end)
                rows = [] if window is None else list(window.rows())
            else:
                times = pd.to_datetime(data.timestamp)
                sub = data.loc[(times >= start) & (times < end)]
                rows = [(j, pd.Timestamp(r.timestamp), float(r.open), float(r.high), float(r.low)) for j, r in sub.iterrows()]
            step = pd.Timedelta(minutes=self.config.intrabar_timeframe_minutes)
            complete = bool(rows) and pd.Timestamp(rows[0][1]) == start and pd.Timestamp(rows[-1][1]) == end - step
            complete = complete and all(pd.Timestamp(b[1]) - pd.Timestamp(a[1]) == step for a, b in zip(rows, rows[1:]))
            if complete:
                return rows, ExitSource.INTRABAR, step
            if self.config.intrabar_missing_policy == IntrabarMissingPolicy.ERROR:
                raise ValueError("Missing intrabar candles during EMA cost-cover cycle")
            if self.config.intrabar_missing_policy != IntrabarMissingPolicy.WARN_AND_USE_15M:
                return rows, ExitSource.INTRABAR, step
        return [(i, start, float(self.open[i]), float(self.high[i]), float(self.low[i]))], ExitSource.FALLBACK_15M, self.entry_delta

    def _update_positions_to_strategy_index(self, i):
        if not self._ema_cost_cycle_enabled():
            return super()._update_positions_to_strategy_index(i)
        return self._scan_ema_cost_cycle(i)

    def _scan_ema_cost_cycle(self, i):
        # A confirmation fill may have already scanned this interval.
        if getattr(self, "_ema_cycle_scanned_index", None) == i:
            return
        self._ema_cycle_scanned_index = i
        pending = getattr(self, "_ema_cycle_pending", None)
        if pending and not self._ema_cycle_aligned(i - 1, pending["direction"]):
            if pending.get("initial_phantom"):
                pending["initial_phantom"].update(status="CANCELLED_EMA_ALIGNMENT", cancelled_at=pd.Timestamp(self.times[i]).isoformat())
            self._ema_cycle_pending = None
        for pair in list(self.active_pairs):
            self._close_on_ema_20_100_cross(pair.positions(), i)
        self._collect_closed_pairs()
        if not self.active_pairs and not getattr(self, "_ema_cycle_pending", None):
            return
        rows, source, step = self._ema_cycle_rows(i)
        for j, timestamp, opening, high, low in rows:
            timestamp = pd.Timestamp(timestamp)
            pending = getattr(self, "_ema_cycle_pending", None)
            newly_triggered = False
            if pending and not self.active_pairs and timestamp >= pending["available"]:
                long = pending["direction"] == "LONG"
                self._ema_cycle_phantom_checkpoints(pending, i, timestamp, high, low)
                reached = high >= pending["trigger"] if long else low <= pending["trigger"]
                if reached and self._in_trading_window(i) and self.current_equity > 0:
                    raw = max(opening, pending["trigger"]) if long else min(opening, pending["trigger"])
                    self._ema_cycle_opening = dict(pending, raw=raw)
                    try:
                        passed, reason = self._entry_filter_result(i - 1, i)
                        if passed:
                            self._open_pair(i, True, reason, {
                                "indicator_index": i - 1, "fill_price": raw,
                                "fill_price_source": "EMA_COST_CYCLE_REENTRY",
                                "actual_entry_timestamp": timestamp,
                            })
                    finally:
                        self._ema_cycle_opening = None
                    if self.active_pairs:
                        self._ema_cycle_pending = None
                        newly_triggered = raw != opening
            for pair in list(self.active_pairs):
                for pos in pair.positions():
                    if not pos.is_open or timestamp < pd.Timestamp(pos.entry_time):
                        continue
                    # Filled inside an OHLC bar: protect pessimistically, but do
                    # not credit a second favourable target from its old high.
                    if source == ExitSource.FALLBACK_15M and self.config.use_intrabar_data:
                        pos.missing_intrabar_data = True
                        pos.fallback_reason = "ema_cost_cycle_intrabar_unavailable"
                    in_fill_bar = pos.ema_cycle_intrabar_entry and timestamp == pd.Timestamp(pos.entry_time)
                    self._ema_cycle_bar(pair, pos, i, timestamp, opening, high, low, source, step, newly_triggered or in_fill_bar)
            self._collect_closed_pairs()

    def _ema_cycle_bar(self, pair, pos, i, timestamp, opening, high, low, source, step, newly_triggered=False):
        long = pos.side == Side.LONG
        slip = 1 - self.config.slippage if long else 1 + self.config.slippage
        stopped = low <= pos.sl if long else high >= pos.sl
        if stopped:
            raw = pos.sl if newly_triggered else (min(opening, pos.sl) if long else max(opening, pos.sl))
            reason = ExitReason.BE if pos.be_triggered else ExitReason.SL
            self._close_position(pos, i, raw * slip, reason, source, timestamp)
            if pos.be_triggered and self._ema_cycle_aligned(i - 1, pos.side.value):
                self._ema_cycle_pending = {
                    "direction": pos.side.value, "trigger": pos.ema_cycle_trigger,
                    "stop": pos.entry_price, "available": timestamp + step,
                    "cycle": pos.ema_cycle_number + 1, "parent": pair.pair_id,
                    "root": pos.ema_cycle_root_id,
                    "reference_gap": pos.ema_cycle_entry_ema_gap,
                    "distance": abs(pos.ema_cycle_trigger - pos.entry_price),
                    "checkpoint": 1, "owner": pos,
                }
            return
        reached = high >= pos.ema_cycle_trigger if long else low <= pos.ema_cycle_trigger
        if pos.tp1_hit or not reached or newly_triggered:
            return
        sign = 1 if long else -1
        fee = self.config.maker_fee if self.config.use_maker_exit else self.config.taker_fee
        partial_price = (max(opening, pos.ema_cycle_trigger) if long else min(opening, pos.ema_cycle_trigger)) * slip
        be_price = pos.entry_price * slip
        partial_net = sign * (partial_price - pos.entry_price) - partial_price * fee
        be_net = sign * (be_price - pos.entry_price) - be_price * fee
        denominator = partial_net - be_net
        quantity = (pos.entry_fee - pos.original_quantity * be_net) / denominator if denominator > 0 else np.inf
        if not np.isfinite(quantity) or quantity < 0 or quantity >= pos.remaining_quantity:
            pos.ema_cycle_cost_cover_rejected = True
            return
        if quantity > 0:
            self._partial_fill(pos, quantity, partial_price, "tp1", i, timestamp, source)
        else:
            pos.tp1_hit = True  # Zero-cost runs still move their stop at 1R.
        pos.sl = pos.be_stop_price = pos.entry_price
        pos.be_triggered = True
        pos.be_trigger_time = timestamp
        pos.be_triggered_by_side = pos.side
        pos.be_exit_reason = ExitReason.BE
        pos.be_mode = "COST_COVER_PARTIAL"
        pos.final_active_stop = pos.sl
        pos.ema_cycle_cost_cover_fraction = quantity / pos.original_quantity

