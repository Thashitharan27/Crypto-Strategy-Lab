"""Opt-in DI ladder execution built on the existing single-position trade engine.

The ladder deliberately keeps each executed child as its own TradePair.  That
preserves the repository's single-direction TradePair invariant while allowing
one initial DI signal to own several linked opposite-side positions.
"""
from __future__ import annotations

from copy import deepcopy

import numpy as np
import pandas as pd

from crypto_strategy_lab.config import IntrabarMissingPolicy, TiePolicy
from crypto_strategy_lab.strategy_profiles import profile_key
from crypto_strategy_lab.trade import ExitSource, Position, Side, TradePair


class DILadderExecutionMixin:
    """Execution helpers mixed into BacktestEngine; inert unless explicitly enabled."""

    def _initialize_di_ladder_state(self) -> None:
        self._di_ladder_episode = None
        self._di_ladder_episode_history = {}
        self.ladder_event_rows = []

    def _di_ladder_enabled(self) -> bool:
        return bool(getattr(self.config, "di_ladder_enabled", False))

    def _di_ladder_layers(self):
        return tuple(
            deepcopy(layer)
            for layer in getattr(self.config, "di_ladder_layers", ())
            if bool(layer.get("enabled", True))
        )

    @staticmethod
    def _ladder_pair_is_child(pair) -> bool:
        return bool(getattr(pair, "ladder_is_child", False))

    def _maybe_start_di_ladder_episode(self, pair, profile) -> None:
        if not self._di_ladder_enabled() or self._ladder_pair_is_child(pair):
            return
        signal_mode = str(getattr(self, "signal_strategy_mode", "DI")).upper()
        if not signal_mode.startswith("DI"):
            raise ValueError("DI ladder execution requires the DI signal strategy")
        if self._di_ladder_episode is not None:
            raise ValueError("cannot start a second DI ladder episode while one is active")

        position = pair.position
        sizing_reference = float(
            getattr(position, "position_sizing_reference_distance", 0.0)
            or 0.0
        )
        if not np.isfinite(sizing_reference) or sizing_reference <= 0:
            raise ValueError("DI ladder requires a finite positive sizing reference distance")
        level_r = float(getattr(self.config, "di_ladder_level_r", 0.20))
        level_distance = sizing_reference * level_r
        if not np.isfinite(level_distance) or level_distance <= 0:
            raise ValueError("DI ladder level price distance must be positive")

        initial_direction = position.side.value
        direction_sign = 1.0 if position.side == Side.LONG else -1.0
        layers = self._di_ladder_layers()
        episode_id = int(pair.pair_id)
        episode = {
            "episode_id": episode_id,
            "initial_pair": pair,
            "initial_pair_id": int(pair.pair_id),
            "initial_direction": initial_direction,
            "child_direction": "SHORT" if initial_direction == "LONG" else "LONG",
            "direction_sign": direction_sign,
            "anchor_price": float(position.entry_price),
            "sizing_reference_distance": sizing_reference,
            "level_r": level_r,
            "level_distance": level_distance,
            "quantity": float(position.quantity),
            "risk_amount": float(position.risk_amount),
            "equity_before_trade": float(pair.equity_before_trade),
            "allow_new_layers": True,
            "layers": [
                {
                    **layer,
                    "reached": False,
                    "entered": False,
                    "skipped": False,
                    "decision": None,
                    "decision_reason": None,
                    "trigger_timestamp": None,
                }
                for layer in layers
            ],
            "deepest_reached_level": 0.0,
            "reached_layers": [],
            "entered_layers": [],
            "skipped_layers": [],
            "finished": False,
        }
        self._di_ladder_episode = episode
        self._di_ladder_episode_history[episode_id] = episode

        pair.ladder_episode_id = episode_id
        pair.ladder_layer = "INITIAL"
        pair.ladder_is_initial = True
        pair.ladder_is_child = False
        pair.ladder_initial_direction = initial_direction
        pair.ladder_entry_level = 0.0
        pair.ladder_target_level = (
            direction_sign * (float(position.tp) - float(position.entry_price))
            / level_distance
        )
        pair.ladder_stop_level = (
            direction_sign * (float(position.sl) - float(position.entry_price))
            / level_distance
        )
        pair.ladder_filter_decision = "INITIAL"
        pair.ladder_filter_reason = "Initial DI strategy entry"
        pair.ladder_level_r = level_r
        pair.ladder_level_distance_price = level_distance
        pair.ladder_anchor_price = float(position.entry_price)
        pair.ladder_frozen_quantity = float(position.quantity)
        pair.ladder_sizing_budget_dollars = float(position.risk_amount)
        pair.ladder_decision_strategy_index = int(position.entry_index)
        pair.ladder_trigger_timestamp = pair.strategy_entry_time

    def _ladder_level_price(self, episode, level: float) -> float:
        return float(episode["anchor_price"]) + (
            float(episode["direction_sign"])
            * float(level)
            * float(episode["level_distance"])
        )

    def _ladder_trigger_crossed(self, episode, layer, high: float, low: float) -> bool:
        trigger = self._ladder_level_price(episode, float(layer["entry_level"]))
        if episode["initial_direction"] == "LONG":
            return float(low) <= trigger
        return float(high) >= trigger

    def _ladder_initial_tp_hit(self, episode, high: float, low: float) -> bool:
        initial = episode["initial_pair"].position
        if not initial.is_open:
            return False
        return (
            float(high) >= float(initial.tp)
            if initial.side == Side.LONG
            else float(low) <= float(initial.tp)
        )

    def _ladder_child_profile(self, decision_i: int, child_direction: str):
        regime = self._regime_at(decision_i)
        if regime is None:
            return None, None
        key = profile_key(regime, child_direction)
        return key, self.config.strategy_profiles[key]

    def _ladder_filter_result(self, decision_i: int, episode, layer):
        rules = tuple(layer.get("entry_rules") or ())
        if not rules:
            return True, "Mechanical ladder entry", None
        child_direction = str(episode["child_direction"])
        key, profile = self._ladder_child_profile(decision_i, child_direction)
        if profile is None:
            return False, "Ladder filter evidence unavailable during regime warm-up", key
        matches = []
        for rule in rules:
            # Ladder rules are positive entry conditions. Remove the builder kind
            # because REQUIRED profile rules use inverse reject semantics internally.
            observed_rule = dict(rule)
            observed_rule.pop("_builder_kind", None)
            _value, matched = self._strategy_profile_entry_rule_observation(
                decision_i, child_direction, profile, observed_rule
            )
            matches.append(bool(matched))
        mode = str(layer.get("filter_match_mode", "ALL")).upper()
        passed = all(matches) if mode == "ALL" else any(matches)
        detail = f"{sum(matches)}/{len(matches)} ladder conditions matched ({mode})"
        return passed, detail, key

    def _ladder_raw_entry_fill(self, episode, trigger_price: float, raw_open: float) -> float:
        # A gap beyond the trigger is filled at the worse observable 1m open.
        if episode["initial_direction"] == "LONG":
            return min(float(trigger_price), float(raw_open))
        return max(float(trigger_price), float(raw_open))

    def _ladder_capacity_reason(self, episode, entry_price: float):
        qty = float(episode["quantity"])
        equity = float(episode["equity_before_trade"])
        if equity <= 0:
            return "LADDER_INVALID_EQUITY"
        per_leg = getattr(self.config, "max_effective_leverage_per_leg", None)
        if per_leg is not None and qty * float(entry_price) > float(per_leg) * equity + 1e-12:
            return "LADDER_PER_LEG_LEVERAGE_CAP"
        combined = getattr(self.config, "max_combined_effective_leverage", None)
        if combined is not None:
            open_notional = sum(
                float(p.position.entry_notional)
                for p in self.active_pairs
                if p.position.is_open
            )
            if open_notional + qty * float(entry_price) > float(combined) * equity + 1e-12:
                return "LADDER_COMBINED_LEVERAGE_CAP"
        return None

    def _record_ladder_skip(
        self,
        episode,
        layer,
        decision_i: int,
        timestamp,
        trigger_price: float,
        reason: str,
        profile_key_value=None,
    ) -> None:
        child_direction = str(episode["child_direction"])
        stop_price = self._ladder_level_price(episode, float(layer["stop_level"]))
        target_price = self._ladder_level_price(episode, float(layer["target_level"]))
        row = {
            "strategy_candle_open_time": self.times[decision_i],
            "strategy_entry_time": pd.Timestamp(timestamp),
            "strategy_entry_price": float(trigger_price),
            "side": child_direction,
            "strategy_profile_key": profile_key_value,
            "entry_filter_passed": False,
            "entry_filter_reason": reason,
            "plus_di": float(self.plus_di_values[decision_i]) if np.isfinite(self.plus_di_values[decision_i]) else np.nan,
            "minus_di": float(self.minus_di_values[decision_i]) if np.isfinite(self.minus_di_values[decision_i]) else np.nan,
            "proposed_stop": float(stop_price),
            "proposed_target": float(target_price),
            "ladder_episode_id": int(episode["episode_id"]),
            "ladder_layer": str(layer.get("name")),
            "ladder_entry_level": float(layer["entry_level"]),
            "ladder_target_level": float(layer["target_level"]),
            "ladder_stop_level": float(layer["stop_level"]),
            "ladder_decision": "SKIP",
        }
        self.skipped_signals.append(row)
        self.ladder_event_rows.append(dict(row))

    def _open_ladder_leg(
        self,
        episode,
        layer,
        execution_i: int,
        decision_i: int,
        timestamp,
        raw_open: float,
        trigger_price: float,
        filter_reason: str,
        profile_key_value=None,
    ):
        child_direction = str(episode["child_direction"])
        side = Side.LONG if child_direction == "LONG" else Side.SHORT
        raw_fill = self._ladder_raw_entry_fill(episode, trigger_price, raw_open)
        entry = raw_fill * (
            1 + self.config.slippage if side == Side.LONG
            else 1 - self.config.slippage
        )
        stop_price = self._ladder_level_price(episode, float(layer["stop_level"]))
        target_price = self._ladder_level_price(episode, float(layer["target_level"]))
        risk_distance = abs(float(stop_price) - float(entry))
        if risk_distance <= 0:
            raise ValueError("DI ladder child stop distance must be positive")

        capacity_reason = self._ladder_capacity_reason(episode, entry)
        if capacity_reason is not None:
            self._record_ladder_skip(
                episode, layer, decision_i, timestamp, trigger_price,
                capacity_reason, profile_key_value
            )
            return None

        qty = float(episode["quantity"])
        risk_amount = float(episode["risk_amount"])
        sizing_reference = float(episode["sizing_reference_distance"])
        entry_fee_rate = (
            self.config.maker_fee if self.config.use_maker_entry
            else self.config.taker_fee
        )
        entry_fee = entry * qty * entry_fee_rate
        pos = Position(
            side=side,
            entry_time=pd.Timestamp(timestamp),
            entry_index=int(execution_i),
            entry_price=float(entry),
            risk=float(risk_distance),
            sl=float(stop_price),
            tp=float(target_price),
            quantity=qty,
            risk_amount=risk_amount,
            entry_notional=float(entry * qty),
            atr_at_entry=float(self.atr_values[decision_i]),
            uncapped_quantity=qty,
            effective_leverage=float(entry * qty / episode["equity_before_trade"]),
            distance_unit=sizing_reference,
            position_sizing_stop_override_enabled=True,
            position_sizing_stop_override_applied=True,
            position_sizing_stop_multiple=1.0,
            position_sizing_reference_distance=sizing_reference,
            entry_fee=float(entry_fee),
            fees=float(entry_fee),
            original_sl=float(stop_price),
        )

        long = pos if side == Side.LONG else None
        short = pos if side == Side.SHORT else None
        pair = TradePair(
            self.next_pair_id,
            long,
            short,
            self.current_equity,
            pd.Timestamp(self.times[decision_i]),
            pd.Timestamp(timestamp),
            float(raw_fill),
            False,
        )
        pair.trade_direction = child_direction
        pair.signal_strategy_mode = "DI_LADDER"
        pair.entry_timing_mode = "LADDER_INTRABAR"
        pair.signal_candle_time = pd.Timestamp(self.times[decision_i])
        pair.signal_available_at = pd.Timestamp(self.times[decision_i]) + self.entry_delta
        pair.signal_close_price = float(self.close[decision_i])
        pair.next_bar_open_price = np.nan
        pair.entry_gap_pct = 0.0
        pair.entry_gap_atr = 0.0
        pair.daily_schedule_enabled = False
        pair.scheduled_entry_time = None
        pair.scheduled_entry_timezone = None
        pair.scheduled_entry_timestamp = None
        pair.actual_entry_timestamp = pd.Timestamp(timestamp)
        pair.entry_schedule_status = "LADDER_TRIGGER"
        pair.strategy_profile_key = profile_key_value
        pair.applied_stop_loss_multiple = (
            abs(float(layer["stop_level"]) - float(layer["entry_level"]))
            * float(episode["level_r"])
        )
        pair.applied_partial_sl_enabled = False
        pair.applied_sl1_r = 0.0
        pair.applied_sl1_close_pct = 0.0
        pair.applied_sl2_r = pair.applied_stop_loss_multiple
        pair.applied_partial_tp_enabled = False
        pair.applied_tp1_r = 0.0
        pair.applied_tp1_close_pct = 0.0
        pair.applied_tp2_r = 0.0
        pair.profile_timeout_enabled = False
        pair.profile_timeout_minutes = None
        pair.di_sizing_direction = str(episode["initial_direction"])
        pair.sizing_direction = child_direction
        pair.long_size_multiplier = 1.0 if child_direction == "LONG" else 0.0
        pair.short_size_multiplier = 1.0 if child_direction == "SHORT" else 0.0
        pair.di_reward_risk_regime = self._regime_at(decision_i)
        child_target_r = (
            abs(float(layer["target_level"]) - float(layer["entry_level"]))
            * float(episode["level_r"])
        )
        pair.di_applied_long_reward_risk_ratio = child_target_r if child_direction == "LONG" else np.nan
        pair.di_applied_short_reward_risk_ratio = child_target_r if child_direction == "SHORT" else np.nan
        pair.market_regime_return = (
            float(self.bull_regime_return_values[decision_i])
            if np.isfinite(self.bull_regime_return_values[decision_i]) else np.nan
        )
        pair.entry_atr_pct = (
            float(self.atr_pct_values[decision_i])
            if np.isfinite(self.atr_pct_values[decision_i]) else np.nan
        )
        pair.entry_close_location = (
            float(self.close_location_values[decision_i])
            if np.isfinite(self.close_location_values[decision_i]) else np.nan
        )
        pair.market_regime = self._regime_at(decision_i)
        pair.market_regime_method = self.config.market_regime_method
        pair.bull_regime = pair.market_regime == "BULL"
        pair.adx = float(self.adx_values[decision_i]) if np.isfinite(self.adx_values[decision_i]) else np.nan
        pair.plus_di = float(self.plus_di_values[decision_i]) if np.isfinite(self.plus_di_values[decision_i]) else np.nan
        pair.minus_di = float(self.minus_di_values[decision_i]) if np.isfinite(self.minus_di_values[decision_i]) else np.nan
        for key, value in self._di_pressure_snapshot(decision_i, child_direction).items():
            setattr(pair, key, value)
        for key, value in self._mean_reversion_snapshot(
            decision_i, child_direction, child_direction
        ).items():
            setattr(pair, key, value)
        self._attach_market_state(pair, decision_i)
        pair.entry_filter_passed = True
        pair.entry_filter_reason = filter_reason

        pair.ladder_episode_id = int(episode["episode_id"])
        pair.ladder_layer = str(layer.get("name"))
        pair.ladder_is_initial = False
        pair.ladder_is_child = True
        pair.ladder_initial_direction = str(episode["initial_direction"])
        pair.ladder_entry_level = float(layer["entry_level"])
        pair.ladder_target_level = float(layer["target_level"])
        pair.ladder_stop_level = float(layer["stop_level"])
        pair.ladder_filter_decision = "ENTER"
        pair.ladder_filter_reason = filter_reason
        pair.ladder_level_r = float(episode["level_r"])
        pair.ladder_level_distance_price = float(episode["level_distance"])
        pair.ladder_anchor_price = float(episode["anchor_price"])
        pair.ladder_frozen_quantity = qty
        pair.ladder_sizing_budget_dollars = risk_amount
        pair.ladder_decision_strategy_index = int(decision_i)
        pair.ladder_trigger_timestamp = pd.Timestamp(timestamp)

        self.active_pairs.append(pair)
        attach = getattr(self, "_attach_research_features_to_pair", None)
        if callable(attach):
            attach(pair, decision_i)
        self._record_pair_telemetry(pair, execution_i)
        self.next_pair_id += 1
        self.ladder_event_rows.append({
            "ladder_episode_id": int(episode["episode_id"]),
            "ladder_layer": str(layer.get("name")),
            "ladder_decision": "ENTER",
            "strategy_candle_open_time": self.times[decision_i],
            "strategy_entry_time": pd.Timestamp(timestamp),
            "strategy_entry_price": float(raw_fill),
        })
        return pair

    def _trigger_ladder_layers(
        self, episode, execution_i: int, timestamp, raw_open: float,
        high: float, low: float
    ) -> None:
        if not episode.get("allow_new_layers", False):
            return
        decision_i = int(execution_i) - 1
        if decision_i < 0:
            return
        for layer in episode["layers"]:
            if layer["reached"]:
                continue
            if not self._ladder_trigger_crossed(episode, layer, high, low):
                continue
            layer["reached"] = True
            layer["trigger_timestamp"] = pd.Timestamp(timestamp)
            entry_level = float(layer["entry_level"])
            episode["deepest_reached_level"] = min(
                float(episode["deepest_reached_level"]), entry_level
            )
            episode["reached_layers"].append(str(layer.get("name")))
            trigger_price = self._ladder_level_price(episode, entry_level)
            passed, reason, profile_key_value = self._ladder_filter_result(
                decision_i, episode, layer
            )
            if not passed:
                layer["skipped"] = True
                layer["decision"] = "SKIP"
                layer["decision_reason"] = reason
                episode["skipped_layers"].append(str(layer.get("name")))
                self._record_ladder_skip(
                    episode, layer, decision_i, timestamp, trigger_price,
                    f"LADDER_FILTER_SKIP: {reason}", profile_key_value
                )
                continue
            pair = self._open_ladder_leg(
                episode, layer, execution_i, decision_i, timestamp, raw_open,
                trigger_price, f"LADDER_ENTRY: {reason}", profile_key_value
            )
            if pair is None:
                layer["skipped"] = True
                layer["decision"] = "SKIP"
                layer["decision_reason"] = "capacity limit"
                episode["skipped_layers"].append(str(layer.get("name")))
                continue
            layer["entered"] = True
            layer["decision"] = "ENTER"
            layer["decision_reason"] = reason
            episode["entered_layers"].append(str(layer.get("name")))

    def _process_ladder_intrabar_row(
        self, episode, execution_i: int, j: int, timestamp,
        raw_open: float, high: float, low: float
    ) -> None:
        initial = episode["initial_pair"].position
        optimistic_tp_first = (
            self.config.tie_policy == TiePolicy.OPTIMISTIC
            and self._ladder_initial_tp_hit(episode, high, low)
        )

        if optimistic_tp_first:
            for pair in list(self.active_pairs):
                if getattr(pair, "ladder_episode_id", None) != episode["episode_id"]:
                    continue
                pos = pair.position
                if pos.is_open:
                    self._maybe_exit_bar(
                        pos, j, float(high), float(low), timestamp, ExitSource.INTRABAR
                    )
            if not initial.is_open:
                episode["allow_new_layers"] = False
                return

        self._trigger_ladder_layers(
            episode, execution_i, timestamp, raw_open, high, low
        )

        for pair in list(self.active_pairs):
            if getattr(pair, "ladder_episode_id", None) != episode["episode_id"]:
                continue
            pos = pair.position
            if pos.is_open:
                self._maybe_exit_bar(
                    pos, j, float(high), float(low), timestamp, ExitSource.INTRABAR
                )

        if not initial.is_open:
            episode["allow_new_layers"] = False

    def _ladder_intrabar_rows(self, start, end):
        expected = pd.Timedelta(minutes=self.config.intrabar_timeframe_minutes)
        fast_window = getattr(self.intrabar_data, "fast_window", None)
        if callable(fast_window):
            window = fast_window(start, end)
            if window is None:
                return None, (), ()
            gaps = tuple(window.gap_pairs(expected))
            rows = tuple(window.rows()) if not window.empty else ()
            first = None if window.empty else window.first_timestamp
            incomplete = (
                not rows or first > start + expected or bool(gaps)
            )
            return incomplete, gaps, rows

        frame = self.intrabar_data
        sub = frame[(frame.timestamp >= start) & (frame.timestamp < end)]
        if sub.empty:
            return True, (), ()
        diffs = sub.timestamp.diff().dropna()
        gaps = tuple(
            (sub.loc[index - 1, "timestamp"], sub.loc[index, "timestamp"])
            for index in diffs[diffs > expected].index
        )
        rows = tuple(
            (j, pd.Timestamp(row.timestamp), float(row.open), float(row.high), float(row.low))
            for j, row in sub.iterrows()
        )
        incomplete = (
            pd.Timestamp(sub.timestamp.iloc[0]) > start + expected or bool(gaps)
        )
        return incomplete, gaps, rows

    def _update_di_ladder_positions_to_strategy_index(self, i: int) -> bool:
        episode = self._di_ladder_episode
        if episode is None:
            return False
        initial = episode["initial_pair"].position
        if i <= int(initial.entry_index):
            return True
        if not self.config.use_intrabar_data or self.intrabar_data is None:
            raise ValueError("DI ladder execution requires intrabar data")

        start = pd.Timestamp(self.times[i])
        end = start + self.entry_delta
        incomplete, gaps, rows = self._ladder_intrabar_rows(start, end)
        if incomplete:
            for previous, current in gaps:
                self.missing_intrabar_intervals.append((previous, current))
            for pair in self.active_pairs:
                if getattr(pair, "ladder_episode_id", None) == episode["episode_id"]:
                    pair.position.missing_intrabar_data = True
            if self.config.intrabar_missing_policy == IntrabarMissingPolicy.ERROR:
                raise ValueError(
                    "Missing 1-minute intrabar candles during DI ladder episode"
                )
            if self.config.intrabar_missing_policy == IntrabarMissingPolicy.WARN_AND_USE_15M:
                # Preserve existing fallback semantics for already-open positions.
                # Missing intervals cannot safely manufacture new ladder triggers.
                for pair in list(self.active_pairs):
                    if getattr(pair, "ladder_episode_id", None) == episode["episode_id"] and pair.position.is_open:
                        self._fallback_exit(pair.position, i, "di_ladder_intrabar_gap")
                return True
            if not rows:
                return True

        for j, timestamp, raw_open, high, low in rows:
            self._process_ladder_intrabar_row(
                episode, i, j, timestamp, raw_open, high, low
            )
        return True

    def _update_di_ladder_episode_lifecycle(self) -> None:
        episode = self._di_ladder_episode
        if episode is None:
            return
        episode_id = episode["episode_id"]
        still_open = any(
            getattr(pair, "ladder_episode_id", None) == episode_id and pair.is_open
            for pair in self.active_pairs
        )
        if still_open:
            return
        episode["finished"] = True
        exits = [
            pd.Timestamp(pair.position.exit_time)
            for pair in self.completed_pairs
            if getattr(pair, "ladder_episode_id", None) == episode_id
            and pair.position.exit_time is not None
        ]
        episode["finished_at"] = max(exits) if exits else None
        self._di_ladder_episode = None

    def _decorate_ladder_result_row(self, pair, row: dict) -> dict:
        episode_id = getattr(pair, "ladder_episode_id", None)
        if episode_id is None:
            return row
        primary = pair.position
        row.update({
            "ladder_episode_id": int(episode_id),
            "ladder_layer": getattr(pair, "ladder_layer", None),
            "ladder_is_initial": bool(getattr(pair, "ladder_is_initial", False)),
            "ladder_is_child": bool(getattr(pair, "ladder_is_child", False)),
            "ladder_initial_direction": getattr(pair, "ladder_initial_direction", None),
            "ladder_entry_level": getattr(pair, "ladder_entry_level", np.nan),
            "ladder_target_level": getattr(pair, "ladder_target_level", np.nan),
            "ladder_stop_level": getattr(pair, "ladder_stop_level", np.nan),
            "ladder_filter_decision": getattr(pair, "ladder_filter_decision", None),
            "ladder_filter_reason": getattr(pair, "ladder_filter_reason", None),
            "ladder_level_r": getattr(pair, "ladder_level_r", np.nan),
            "ladder_level_distance_price": getattr(pair, "ladder_level_distance_price", np.nan),
            "ladder_anchor_price": getattr(pair, "ladder_anchor_price", np.nan),
            "ladder_frozen_quantity": getattr(pair, "ladder_frozen_quantity", np.nan),
            "ladder_sizing_budget_dollars": getattr(pair, "ladder_sizing_budget_dollars", np.nan),
            "ladder_decision_strategy_index": getattr(pair, "ladder_decision_strategy_index", np.nan),
            "ladder_trigger_timestamp": getattr(pair, "ladder_trigger_timestamp", None),
        })
        if bool(getattr(pair, "ladder_is_child", False)):
            sizing_reference = float(
                getattr(primary, "position_sizing_reference_distance", 0.0)
            )
            target_distance = abs(float(primary.tp) - float(primary.entry_price))
            stop_distance = abs(float(primary.sl) - float(primary.entry_price))
            row["applied_reward_risk_ratio"] = (
                target_distance / sizing_reference if sizing_reference > 0 else np.nan
            )
            row["stop_distance_units"] = (
                stop_distance / sizing_reference if sizing_reference > 0 else np.nan
            )
            row["actual_stop_as_sizing_r"] = row["stop_distance_units"]
            row["final_target_as_sizing_r"] = row["applied_reward_risk_ratio"]
            row["physical_reward_risk_ratio"] = (
                target_distance / stop_distance if stop_distance > 0 else np.nan
            )
        return row

    def _decorate_ladder_results_frame(self, frame):
        if frame.empty or "ladder_episode_id" not in frame.columns:
            return frame
        grouped = frame.groupby("ladder_episode_id", dropna=False)
        frame["ladder_episode_gross_pnl"] = grouped["pair_gross_pnl"].transform("sum")
        frame["ladder_episode_total_fees"] = grouped["pair_total_fees"].transform("sum")
        frame["ladder_episode_net_pnl"] = grouped["pair_net_pnl"].transform("sum")
        frame["ladder_episode_trade_count"] = grouped["pair_id"].transform("count")
        frame["ladder_episode_net_r"] = frame["ladder_episode_net_pnl"] / frame[
            "ladder_sizing_budget_dollars"
        ]
        deepest = {
            int(episode_id): float(episode.get("deepest_reached_level", 0.0))
            for episode_id, episode in self._di_ladder_episode_history.items()
        }
        frame["ladder_deepest_reached_level"] = frame["ladder_episode_id"].map(deepest)
        frame["ladder_episode_summary_row"] = frame["ladder_is_initial"].astype(bool)
        return frame
