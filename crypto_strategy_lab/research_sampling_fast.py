"""Research-only batching for independent fixed-exit observations.

The portfolio simulator remains the semantic authority. This mixin accelerates
only the strategy-research population when an active Position has no stateful
exit management.

V2 resolves a stateless fixed SL/TP research position across its full remaining
execution horizon once, rather than revisiting that same independent position on
every later strategy candle. The first executable TP/SL/timeout event is still
passed through the mature exit helpers, preserving tie policy, slippage, fees and
funding-aware result construction. End-of-data closes use the same mature close
helper and exact canonical end timestamp.

If the full-horizon path cannot prove identical execution semantics (telemetry is
enabled, alignment is unsafe, a gap exists before the candidate event, coverage
is incomplete, or a position is stateful), it falls back to the existing V1
per-strategy-interval batching or the mature Data Lake scanner.
"""
from __future__ import annotations

from collections import defaultdict
import time

import numpy as np
import pandas as pd

from crypto_strategy_lab.trade import ExitReason, ExitSource, Side


class ResearchSamplingFastExitMixin:
    """Semantics-preserving acceleration used only by research sampling."""

    research_enable_direct_simple_exits = True
    research_enable_batched_simple_exits = True
    research_simple_exit_batch_size = 2048

    def run(self):
        """Time only the research engine so reporting overhead stays measurable."""
        started = time.perf_counter()
        try:
            return super().run()
        finally:
            self.research_engine_run_seconds = time.perf_counter() - started

    def _record_skipped_signal(self, i, reason):
        """Retain rejection counts/reasons without building unused rich snapshots.

        Strategy-resilience artifacts publish only viable entries. The normal
        engine's full skipped-signal rows are therefore redundant in this second,
        research-only simulation. ``results_frame`` still receives the exact
        number of rejected candidates and the same reason strings, so its aggregate
        skip counters remain unchanged.
        """
        del i
        self.skipped_signals.append(
            {
                "entry_filter_reason": reason,
                "adx_filter_reason": reason,
            }
        )

    @staticmethod
    def _research_simple_exit_eligible(position) -> bool:
        """Return True only when a position is a stateless fixed SL/TP trade."""
        return bool(
            position.is_open
            and not position.partial_sl_enabled
            and not position.partial_tp_enabled
            and not position.r_step_trailing_enabled
            and not position.atr_checkpoint_extension_enabled
            and not position.trailing_enabled
            and not position.be_enabled
            and position.profile_break_even_activation_r is None
            and position.be_active_after is None
        )

    def _research_bump_exit_stat(self, name: str, amount: int = 1) -> None:
        setattr(self, name, int(getattr(self, name, 0)) + int(amount))

    def research_exit_optimization_stats(self) -> dict[str, int | float | str | bool]:
        """Expose counters/timing so long research runs remain auditable."""
        return {
            "research_exit_kernel": "DIRECT_SIMPLE_INTRABAR_V2_WITH_V1_FALLBACK",
            "research_engine_run_seconds": float(
                getattr(self, "research_engine_run_seconds", 0.0)
            ),
            "research_direct_simple_exit_enabled": bool(
                self.research_enable_direct_simple_exits
            ),
            "research_direct_simple_positions": int(
                getattr(self, "research_direct_simple_positions", 0)
            ),
            "research_direct_simple_tp_sl": int(
                getattr(self, "research_direct_simple_tp_sl", 0)
            ),
            "research_direct_simple_timeouts": int(
                getattr(self, "research_direct_simple_timeouts", 0)
            ),
            "research_direct_simple_end_of_data": int(
                getattr(self, "research_direct_simple_end_of_data", 0)
            ),
            "research_direct_simple_fallback_positions": int(
                getattr(self, "research_direct_simple_fallback_positions", 0)
            ),
            "research_batched_simple_exit_enabled": bool(
                self.research_enable_batched_simple_exits
            ),
            "research_batched_simple_intervals": int(
                getattr(self, "research_batched_simple_intervals", 0)
            ),
            "research_batched_simple_position_intervals": int(
                getattr(self, "research_batched_simple_position_intervals", 0)
            ),
            "research_dynamic_exit_position_intervals": int(
                getattr(self, "research_dynamic_exit_position_intervals", 0)
            ),
            "research_batch_fallback_position_intervals": int(
                getattr(self, "research_batch_fallback_position_intervals", 0)
            ),
        }

    @staticmethod
    def _research_naive_ns(value) -> np.datetime64:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_convert("UTC").tz_localize(None)
        return np.datetime64(timestamp.to_datetime64(), "ns")

    @staticmethod
    def _research_window_arrays(window):
        """Return zero/low-copy arrays for either supported fast-window contract."""
        data = getattr(window, "data", None)
        start = getattr(window, "start", None)
        stop = getattr(window, "stop", None)
        if data is not None and start is not None and stop is not None:
            left = int(start)
            right = int(stop)
            return (
                left,
                np.asarray(data.timestamp[left:right], dtype="datetime64[ns]"),
                np.asarray(data.open[left:right], dtype=float),
                np.asarray(data.high[left:right], dtype=float),
                np.asarray(data.low[left:right], dtype=float),
            )

        left = getattr(window, "left", None)
        right = getattr(window, "right", None)
        values = getattr(window, "timestamp_values", None)
        unit = getattr(window, "timestamp_unit", None)
        opens = getattr(window, "opens", None)
        highs = getattr(window, "highs", None)
        lows = getattr(window, "lows", None)
        if any(
            value is None
            for value in (left, right, values, unit, opens, highs, lows)
        ):
            return None
        left = int(left)
        right = int(right)
        unit_ns = int(pd.Timedelta(1, unit=str(unit)).value)
        timestamps_ns = (
            np.asarray(values[left:right], dtype=np.int64) * unit_ns
        ).astype("datetime64[ns]")
        return (
            left,
            timestamps_ns,
            np.asarray(opens[left:right], dtype=float),
            np.asarray(highs[left:right], dtype=float),
            np.asarray(lows[left:right], dtype=float),
        )

    def _research_intrabar_max_timestamp(self):
        maximum = getattr(self.intrabar_data, "max_timestamp", None)
        if maximum is not None:
            return pd.Timestamp(maximum)
        timestamp_values = getattr(self.intrabar_data, "timestamp", None)
        max_method = getattr(timestamp_values, "max", None)
        if callable(max_method):
            return pd.Timestamp(max_method())
        return None

    def _research_complete_window(self, start, end):
        """Return batchable arrays only when the mature path sees a complete window."""
        minutes = int(self.config.intrabar_timeframe_minutes)
        if start.floor(f"{minutes}min") != start:
            return None
        fast_window = getattr(self.intrabar_data, "fast_window", None)
        if not callable(fast_window):
            return None
        window = fast_window(start, end)
        if window is None:
            return None

        expected = pd.Timedelta(minutes=minutes)
        gaps = window.gap_pairs(expected)
        incomplete = (
            window.empty
            or window.first_timestamp > start + expected
            or bool(gaps)
        )
        if incomplete:
            return None

        intrabar_max = self._research_intrabar_max_timestamp()
        if intrabar_max is not None and intrabar_max < end - expected:
            return None
        return self._research_window_arrays(window)

    def _research_direct_runtime_arrays(self):
        """Cache immutable intrabar arrays and gap boundaries for V2 resolution."""
        cached = getattr(self, "_research_direct_intrabar_cache", None)
        if cached is not None:
            return cached
        data = getattr(self, "intrabar_data", None)
        required = ("timestamp", "open", "high", "low")
        if data is None or any(getattr(data, name, None) is None for name in required):
            return None
        timestamps = np.asarray(data.timestamp, dtype="datetime64[ns]")
        opens = np.asarray(data.open, dtype=float)
        highs = np.asarray(data.high, dtype=float)
        lows = np.asarray(data.low, dtype=float)
        if not (len(timestamps) == len(opens) == len(highs) == len(lows)):
            return None
        expected = pd.Timedelta(
            minutes=int(self.config.intrabar_timeframe_minutes)
        ).to_timedelta64()
        gap_after = np.flatnonzero(np.diff(timestamps) > expected)
        cached = (timestamps, opens, highs, lows, gap_after, expected)
        self._research_direct_intrabar_cache = cached
        return cached

    @staticmethod
    def _research_gap_before(gap_after, left: int, event_index: int) -> bool:
        """Whether a missing intrabar interval lies before an executable event."""
        if event_index <= left or len(gap_after) == 0:
            return False
        offset = int(np.searchsorted(gap_after, left, side="left"))
        return bool(offset < len(gap_after) and int(gap_after[offset]) < event_index)

    def _research_direct_simple_supported(self) -> bool:
        """Use V2 only where resolving a future exit cannot change observability."""
        return bool(
            self.research_enable_direct_simple_exits
            and self.config.use_intrabar_data
            and self.intrabar_data is not None
            and not bool(getattr(self.config, "enable_trade_telemetry", False))
            and self._research_direct_runtime_arrays() is not None
        )

    def _research_resolve_simple_position(self, pair, position) -> bool:
        """Resolve one independent fixed-exit position across its full horizon.

        Returns True when the position was resolved with semantics proven safe.
        Returns False when V1/the mature scanner must remain authoritative.
        """
        arrays = self._research_direct_runtime_arrays()
        if arrays is None:
            return False
        timestamps, opens, highs, lows, gap_after, expected_delta = arrays
        if len(timestamps) == 0:
            return False

        start = pd.Timestamp(position.entry_time)
        minutes = int(self.config.intrabar_timeframe_minutes)
        if start.floor(f"{minutes}min") != start:
            return False

        final_strategy_index = len(self.times) - 1
        if final_strategy_index < 0:
            return False
        end = pd.Timestamp(self.times[final_strategy_index]) + self.entry_delta
        start64 = self._research_naive_ns(start)
        end64 = self._research_naive_ns(end)
        left = int(np.searchsorted(timestamps, start64, side="left"))
        right = int(np.searchsorted(timestamps, end64, side="left"))
        if left >= right:
            return False

        expected = pd.Timedelta(expected_delta)
        first_timestamp = pd.Timestamp(timestamps[left])
        if first_timestamp > start + expected:
            return False

        long_side = position.side == Side.LONG
        target = float(position.tp)
        stop = float(position.sl)
        window_highs = highs[left:right]
        window_lows = lows[left:right]
        if long_side:
            hits = (window_highs >= target) | (window_lows <= stop)
        else:
            hits = (window_lows <= target) | (window_highs >= stop)
        local_hits = np.flatnonzero(hits)
        first_hit = right if len(local_hits) == 0 else left + int(local_hits[0])

        timeout_index = right
        if getattr(pair, "profile_timeout_enabled", False):
            timeout_minutes = getattr(pair, "profile_timeout_minutes", None)
            if timeout_minutes is not None:
                timeout_at = pd.Timestamp(position.entry_time) + pd.Timedelta(
                    minutes=int(timeout_minutes)
                )
                candidate = int(
                    np.searchsorted(
                        timestamps,
                        self._research_naive_ns(timeout_at),
                        side="left",
                    )
                )
                if left <= candidate < right:
                    timeout_index = candidate

        event_index = min(first_hit, timeout_index)
        if event_index < right:
            # A gap after the event is irrelevant because the mature engine would
            # already have closed the observation. A gap before the event forces
            # the exact existing fallback path instead of inventing a price path.
            if self._research_gap_before(gap_after, left, event_index):
                return False
            timestamp = pd.Timestamp(timestamps[event_index])
            if timeout_index <= first_hit:
                self._maybe_timeout_position_at(
                    pair,
                    position,
                    event_index,
                    timestamp,
                    float(opens[event_index]),
                    ExitSource.INTRABAR,
                )
                self._research_bump_exit_stat("research_direct_simple_timeouts")
            else:
                self._maybe_exit_bar(
                    position,
                    event_index,
                    float(highs[event_index]),
                    float(lows[event_index]),
                    timestamp,
                    ExitSource.INTRABAR,
                )
                if position.is_open:
                    # Defensive parity guard: a supposedly fixed TP/SL hit must
                    # be executable by the mature helper. If not, leave V1 in
                    # control rather than publishing a guessed outcome.
                    return False
                self._research_bump_exit_stat("research_direct_simple_tp_sl")
            self._research_bump_exit_stat("research_direct_simple_positions")
            return True

        # No TP/SL/timeout candidate exists. Early end-of-data closure is safe
        # only when the whole remaining execution horizon is gap-free and fully
        # covered. Otherwise keep V1/mature missing-data handling authoritative.
        if self._research_gap_before(gap_after, left, right - 1):
            return False
        intrabar_max = pd.Timestamp(timestamps[-1])
        if intrabar_max < end - expected:
            return False
        self._close_position(
            position,
            final_strategy_index,
            float(self.close[final_strategy_index]),
            ExitReason.END_OF_DATA,
            ExitSource.END_OF_DATA,
            end,
        )
        self._research_bump_exit_stat("research_direct_simple_end_of_data")
        self._research_bump_exit_stat("research_direct_simple_positions")
        return True

    def _research_scan_simple_group(self, pairs, i: int, start: pd.Timestamp) -> bool:
        """V1 fallback: batch one shared strategy interval and execute first event."""
        end = pd.Timestamp(self.times[i]) + self.entry_delta
        if start >= end:
            return False
        arrays = self._research_complete_window(start, end)
        if arrays is None:
            return False

        global_start, timestamps, opens, highs, lows = arrays
        row_count = len(timestamps)
        if row_count == 0:
            return False

        batch_size = max(1, int(self.research_simple_exit_batch_size))
        for offset in range(0, len(pairs), batch_size):
            batch = pairs[offset : offset + batch_size]
            positions = [position for _, position in batch]
            long_mask = np.fromiter(
                (position.side == Side.LONG for position in positions),
                dtype=bool,
                count=len(positions),
            )
            targets = np.fromiter(
                (float(position.tp) for position in positions),
                dtype=float,
                count=len(positions),
            )
            stops = np.fromiter(
                (float(position.sl) for position in positions),
                dtype=float,
                count=len(positions),
            )

            tp_hits = np.where(
                long_mask[:, None],
                highs[None, :] >= targets[:, None],
                lows[None, :] <= targets[:, None],
            )
            sl_hits = np.where(
                long_mask[:, None],
                lows[None, :] <= stops[:, None],
                highs[None, :] >= stops[:, None],
            )
            any_hit = tp_hits | sl_hits
            has_hit = any_hit.any(axis=1)
            first_hit = np.full(len(batch), row_count, dtype=np.int64)
            if has_hit.any():
                first_hit[has_hit] = np.argmax(any_hit[has_hit], axis=1)

            timeout_index = np.full(len(batch), row_count, dtype=np.int64)
            for local_index, (pair, position) in enumerate(batch):
                if not getattr(pair, "profile_timeout_enabled", False):
                    continue
                timeout_minutes = getattr(pair, "profile_timeout_minutes", None)
                if timeout_minutes is None:
                    continue
                timeout_at = pd.Timestamp(position.entry_time) + pd.Timedelta(
                    minutes=int(timeout_minutes)
                )
                timeout_index[local_index] = int(
                    np.searchsorted(
                        timestamps,
                        self._research_naive_ns(timeout_at),
                        side="left",
                    )
                )

            event_index = np.minimum(first_hit, timeout_index)
            for local_index, (pair, position) in enumerate(batch):
                event = int(event_index[local_index])
                if event >= row_count:
                    continue
                absolute_index = global_start + event
                timestamp = pd.Timestamp(timestamps[event])
                # The mature scanner checks timeout before TP/SL on each intrabar.
                if timeout_index[local_index] <= first_hit[local_index]:
                    self._maybe_timeout_position_at(
                        pair,
                        position,
                        absolute_index,
                        timestamp,
                        float(opens[event]),
                        ExitSource.INTRABAR,
                    )
                else:
                    # Preserve all same-bar ambiguity, slippage, fee and close logic
                    # by delegating the actual event to the existing helper.
                    self._maybe_exit_bar(
                        position,
                        absolute_index,
                        float(highs[event]),
                        float(lows[event]),
                        timestamp,
                        ExitSource.INTRABAR,
                    )
        return True

    def _update_positions_to_strategy_index(self, i):
        """Resolve fixed research exits once; delegate every unsafe case unchanged."""
        if not self.research_enable_batched_simple_exits:
            return super()._update_positions_to_strategy_index(i)
        if not self.config.use_intrabar_data or self.intrabar_data is None:
            return super()._update_positions_to_strategy_index(i)
        if not callable(getattr(self.intrabar_data, "fast_window", None)):
            return super()._update_positions_to_strategy_index(i)

        strategy_time = pd.Timestamp(self.times[i])
        simple_groups = defaultdict(list)
        dynamic = []
        direct_supported = self._research_direct_simple_supported()

        for pair in self.active_pairs:
            position = pair.position
            if i <= position.entry_index:
                continue
            if self._research_simple_exit_eligible(position):
                direct_disabled = bool(
                    getattr(position, "_research_direct_simple_disabled", False)
                )
                if direct_supported and not direct_disabled:
                    if self._research_resolve_simple_position(pair, position):
                        continue
                    position._research_direct_simple_disabled = True
                    self._research_bump_exit_stat(
                        "research_direct_simple_fallback_positions"
                    )
                start = max(pd.Timestamp(position.entry_time), strategy_time)
                simple_groups[start].append((pair, position))
            else:
                dynamic.append((pair, position))

        for start, group in simple_groups.items():
            if self._research_scan_simple_group(group, i, start):
                self._research_bump_exit_stat("research_batched_simple_intervals")
                self._research_bump_exit_stat(
                    "research_batched_simple_position_intervals", len(group)
                )
            else:
                self._research_bump_exit_stat(
                    "research_batch_fallback_position_intervals", len(group)
                )
                for pair, position in group:
                    super()._scan_position_exit(pair, position, i)

        for pair, position in dynamic:
            self._research_bump_exit_stat("research_dynamic_exit_position_intervals")
            super()._scan_position_exit(pair, position, i)
