"""Regression checks for directional EMA 20/100 crossover plans."""
from types import SimpleNamespace
from dataclasses import replace
import unittest

import numpy as np
import pandas as pd

from crypto_strategy_lab.ema_pullback import Ema920PullbackMixin, EMA_920_MODE
from crypto_strategy_lab.data_lake_config import ResearchRunConfig
from crypto_strategy_lab.research_adapters import native_simulator_config
from crypto_strategy_lab.trade import ExitReason, ExitSource, Side


class Base:
    def _configure_signal_features(self):
        pass

    def _scan_pair_exit(self, pair, i):
        self.fallback_scans.append(i)

    def _scan_position_exit(self, pair, position, i):
        self.fallback_scans.append(i)

    def _entry_filter_result(self, i, execution_i=None):
        return True, "passed"

    def _profile_context(self, i):
        direction = getattr(self, "direction", "LONG")
        return ("BULL", direction, f"BULL_{direction}", self.profile)

    def _effective_trade_direction(self, i):
        return getattr(self, "direction", "LONG")

    def _expected_entry_price(self, i, execution_i, direction):
        slip = 1 + self.config.slippage if direction == "LONG" else 1 - self.config.slippage
        return self.open[execution_i] * slip

    def _strategy_profile_rule_group_match(self, i, direction, profile, action, mode):
        return self.flip_matches

    def _close_position(self, pos, i, price, reason, source, timestamp):
        self.exits.append((i, price, reason, source, timestamp))

    def _open_pair(self, i, entry_filter_passed=True, entry_filter_reason="Strategy profile passed", schedule=None):
        self.active_pairs.append(self.pending_pair)


class Engine(Ema920PullbackMixin, Base):
    pass


class EmaCrossTests(unittest.TestCase):
    def test_run_requires_causal_entry_timing(self):
        config = ResearchRunConfig()
        profiles = dict(config.strategy.profiles)
        key = next(iter(profiles))
        profiles[key] = replace(profiles[key], entry_rules=(
            {"_strategy_direction_mode": EMA_920_MODE},
        ))
        config = replace(config, strategy=replace(config.strategy, profiles=profiles))
        with self.assertRaisesRegex(ValueError, "next-candle-open"):
            replace(config, execution=replace(config.execution,
                ema_920_trade_plan="EMA_20_100_CROSS")).validate()
        replace(config, execution=replace(config.execution,
            entry_timing_mode="NEXT_CANDLE_OPEN",
            ema_920_trade_plan="EMA_20_100_CROSS")).validate()

    def test_config_allows_partial_profit_runner_for_cross_mode(self):
        config = ResearchRunConfig()
        strategy_profiles = dict(config.strategy.profiles)
        execution_profiles = dict(config.execution.profiles)
        key = next(iter(strategy_profiles))
        strategy_profiles[key] = replace(
            strategy_profiles[key],
            entry_rules=({"_strategy_direction_mode": EMA_920_MODE},),
        )
        execution_profiles[key] = replace(
            execution_profiles[key],
            partial_profit_enabled=True,
            tp1_r=0.5,
            tp1_close_pct=50.0,
            position_sizing_stop_override_enabled=True,
            position_sizing_stop_multiple=2.0,
            ema_cross_stop_multiplier=1.0,
        )
        replace(
            config,
            strategy=replace(config.strategy, profiles=strategy_profiles),
            execution=replace(
                config.execution,
                profiles=execution_profiles,
                entry_timing_mode="NEXT_CANDLE_OPEN",
                ema_920_trade_plan="EMA_20_100_CROSS",
            ),
        ).validate()

    def test_native_adapter_ignores_hidden_tp2_for_cross_runner(self):
        config = ResearchRunConfig()
        strategy_profiles = dict(config.strategy.profiles)
        execution_profiles = dict(config.execution.profiles)
        key = next(iter(strategy_profiles))
        strategy_profiles[key] = replace(
            strategy_profiles[key],
            entry_rules=({"_strategy_direction_mode": EMA_920_MODE},),
        )
        execution_profiles[key] = replace(
            execution_profiles[key],
            partial_profit_enabled=True,
            tp1_r=2.0,
            tp1_close_pct=50.0,
            tp2_r=2.0,  # hidden / unused in EMA-cross runner mode
        )
        config = replace(
            config,
            strategy=replace(config.strategy, profiles=strategy_profiles),
            execution=replace(
                config.execution,
                profiles=execution_profiles,
                entry_timing_mode="NEXT_CANDLE_OPEN",
                ema_920_trade_plan="EMA_20_100_CROSS",
            ),
        )
        native = native_simulator_config(
            config.data, config.features, config.strategy, config.execution
        )
        self.assertGreater(native.strategy_profiles[key].tp2_r, 2.0)

    def test_cross_config_allows_stale_hidden_tp_values_when_partial_disabled(self):
        config = ResearchRunConfig()
        strategy_profiles = dict(config.strategy.profiles)
        execution_profiles = dict(config.execution.profiles)
        key = next(iter(strategy_profiles))
        strategy_profiles[key] = replace(
            strategy_profiles[key],
            entry_rules=({"_strategy_direction_mode": EMA_920_MODE},),
        )
        execution_profiles[key] = replace(
            execution_profiles[key],
            partial_profit_enabled=False,
            tp1_r=2.0,
            tp2_r=2.0,
        )
        replace(
            config,
            strategy=replace(config.strategy, profiles=strategy_profiles),
            execution=replace(
                config.execution,
                profiles=execution_profiles,
                entry_timing_mode="NEXT_CANDLE_OPEN",
                ema_920_trade_plan="EMA_20_100_CROSS",
            ),
        ).validate()

    def test_config_accepts_short_and_both_cross_modes(self):
        config = ResearchRunConfig()
        profiles = dict(config.strategy.profiles)
        key = next(iter(profiles))
        profiles[key] = replace(profiles[key], entry_rules=(
            {"_strategy_direction_mode": EMA_920_MODE},
        ))
        config = replace(
            config,
            strategy=replace(config.strategy, profiles=profiles),
            execution=replace(config.execution, entry_timing_mode="NEXT_CANDLE_OPEN"),
        )
        for plan in ("EMA_20_100_CROSS_SHORT", "EMA_20_100_CROSS_BOTH"):
            replace(config, execution=replace(config.execution, ema_920_trade_plan=plan)).validate()

    def test_config_rejects_active_flip_rules_but_ignores_muted_ones(self):
        config = ResearchRunConfig()
        profiles = dict(config.strategy.profiles)
        key = next(iter(profiles))
        marker = {"_strategy_direction_mode": EMA_920_MODE}
        flip = {"action": "FLIP", "_builder_group_enabled": True}
        profiles[key] = replace(profiles[key], entry_rules=(marker, flip))
        config = replace(config,
            strategy=replace(config.strategy, profiles=profiles),
            execution=replace(config.execution,
                entry_timing_mode="NEXT_CANDLE_OPEN", ema_920_trade_plan="EMA_20_100_CROSS"))
        with self.assertRaisesRegex(ValueError, "disable direction FLIP"):
            config.validate()
        profiles[key] = replace(profiles[key], entry_rules=(marker, {**flip, "_builder_group_enabled": False}))
        replace(config, strategy=replace(config.strategy, profiles=profiles)).validate()

    def setUp(self):
        self.engine = Engine()
        engine = self.engine
        engine.signal_strategy_mode = EMA_920_MODE
        engine.config = SimpleNamespace(
            ema_920_trade_plan="EMA_20_100_CROSS",
            ema_cross_entry_confirmation_enabled=False,
            ema_cross_entry_confirmation_r=1.0,
            enable_daily_entry_schedule=False,
            max_active_pairs=1,
            use_intrabar_data=False,
            slippage=0.001,
        )
        engine.close = np.full(104, 100.0)
        engine.open = np.full(104, 100.0)
        engine.high = engine.close + 1
        engine.low = engine.close - 1
        engine.volume = np.full(104, 100.0)
        engine.atr_values = np.ones(104)
        engine.times = pd.date_range("2025-01-01", periods=104, freq="15min", tz="UTC")
        engine._configure_signal_features()
        engine.fallback_scans = []
        engine.exits = []
        engine.active_pairs = []
        engine.profile = SimpleNamespace(
            flip_direction=False, entry_rules=(), flip_rule_match_mode="ANY",
            ema_cross_stop_buffer_atr=0.05, ema_cross_stop_multiplier=1.0,
            partial_profit_enabled=False,
            tp1_r=1.0, tp1_close_pct=50.0,
        )
        engine.flip_matches = False
        engine.direction = "LONG"

    def test_composed_config_preserves_ema_cross_confirmation_into_native_simulator(self):
        from dataclasses import replace
        from crypto_strategy_lab.data_lake_config import ResearchRunConfig
        from crypto_strategy_lab.research_adapters import native_simulator_config

        config = ResearchRunConfig()
        execution = replace(
            config.execution,
            entry_timing_mode="NEXT_CANDLE_OPEN",
            ema_920_trade_plan="EMA_20_100_CROSS",
            ema_cross_entry_confirmation_enabled=True,
            ema_cross_entry_confirmation_r=2.0,
        )
        native = native_simulator_config(
            config.data, config.features, config.strategy, execution
        )
        self.assertTrue(native.ema_cross_entry_confirmation_enabled)
        self.assertEqual(native.ema_cross_entry_confirmation_r, 2.0)

    def test_config_accepts_positive_ema_cross_entry_confirmation_r(self):
        config = ResearchRunConfig()
        replace(
            config,
            execution=replace(
                config.execution,
                ema_cross_entry_confirmation_enabled=True,
                ema_cross_entry_confirmation_r=1.0,
            ),
        ).validate()
        with self.assertRaisesRegex(ValueError, "confirmation R must be positive"):
            replace(
                config,
                execution=replace(
                    config.execution,
                    ema_cross_entry_confirmation_enabled=True,
                    ema_cross_entry_confirmation_r=0.0,
                ),
            ).validate()

    def test_confirmation_fill_waits_for_trigger(self):
        e = self.engine
        e.entry_delta = pd.Timedelta(minutes=15)
        e.config.ema_cross_entry_confirmation_enabled = True
        e.high[101] = 104.9
        e.low[101] = 99.0
        self.assertIsNone(e._ema_cross_confirmation_fill(101, 105.0, "LONG"))
        e.high[101] = 105.1
        raw, timestamp = e._ema_cross_confirmation_fill(101, 105.0, "LONG")
        self.assertAlmostEqual(raw, 105.0)
        self.assertEqual(timestamp, pd.Timestamp(e.times[101]))

    def test_confirmation_distance_uses_original_cross_r(self):
        e = self.engine
        e.entry_delta = pd.Timedelta(minutes=15)
        e.config.ema_cross_entry_confirmation_enabled = True
        e.config.strategy_timeframe_minutes = 15
        e.ema_20_values[99:102] = [99, 99, 101]
        e.ema_100_values[99:102] = [100, 100, 100]
        e.atr_values[101] = 2.0
        e.open[102] = 101.0
        e.risk = np.ones(104)
        e.times = pd.date_range("2025-01-01", periods=104, freq="15min", tz="UTC")
        e._should_enter = lambda i: True
        e._entry_filter_result = lambda i, execution_i=None: (True, "passed")
        decision = e._entry_decision(101)
        self.assertTrue(decision["ema_cross_confirmation"])
        original_entry = 101.0 * 1.001
        base_stop = 100.0 - 0.05 * 2.0
        expected_r = original_entry - base_stop
        self.assertAlmostEqual(decision["ema_cross_confirmation_original_r"], expected_r)
        self.assertAlmostEqual(
            decision["ema_cross_confirmation_trigger_price"],
            original_entry + expected_r,
        )

    def test_completed_bullish_cross_is_a_long_entry_signal_only_once(self):
        e = self.engine
        e.ema_20_values[99:103] = [99, 99, 101, 102]
        e.ema_100_values[99:103] = [100, 100, 100, 100]
        self.assertIsNone(e._selected_direction(100))
        self.assertEqual(e._selected_direction(101), "LONG")
        self.assertIsNone(e._selected_direction(102))


    def test_short_only_plan_uses_bearish_cross_once(self):
        e = self.engine
        e.config.ema_920_trade_plan = "EMA_20_100_CROSS_SHORT"
        e.direction = "SHORT"
        e.ema_20_values[99:103] = [101, 101, 99, 98]
        e.ema_100_values[99:103] = [100, 100, 100, 100]
        self.assertIsNone(e._selected_direction(100))
        self.assertEqual(e._selected_direction(101), "SHORT")
        self.assertIsNone(e._selected_direction(102))

    def test_both_plan_maps_each_cross_to_native_direction(self):
        e = self.engine
        e.config.ema_920_trade_plan = "EMA_20_100_CROSS_BOTH"
        e.ema_20_values[99:103] = [99, 99, 101, 99]
        e.ema_100_values[99:103] = [100, 100, 100, 100]
        self.assertEqual(e._selected_direction(101), "LONG")
        self.assertEqual(e._selected_direction(102), "SHORT")

    def test_bearish_cross_exits_at_next_open_even_if_bar_later_recovers(self):
        e = self.engine
        e.ema_20_values[100:104] = [101, 99, 102, 103]
        e.ema_100_values[100:104] = [100, 100, 100, 100]
        e.open[102] = 98.0
        pos = SimpleNamespace(is_open=True, side=Side.LONG, sl=95.0)
        pair = SimpleNamespace(positions=lambda: [pos])
        e._scan_pair_exit(pair, 102)
        self.assertEqual(e.exits, [(102, 97.902, ExitReason.EMA_20_100_CROSS,
                                    ExitSource.STRATEGY_OPEN, e.times[102])])
        self.assertEqual(e.fallback_scans, [])
        e._scan_pair_exit(pair, 103)
        self.assertEqual(e.fallback_scans, [103])

    def test_production_position_exit_dispatches_bearish_cross(self):
        e = self.engine
        e.ema_20_values[100:102] = [101, 99]
        e.ema_100_values[100:102] = [100, 100]
        pos = SimpleNamespace(is_open=True, side=Side.LONG, sl=95.0)
        e._scan_position_exit(SimpleNamespace(position=pos), pos, 102)
        self.assertEqual(e.exits[0][2], ExitReason.EMA_20_100_CROSS)
        self.assertEqual(e.fallback_scans, [])


    def test_bullish_cross_exits_short_at_next_open(self):
        e = self.engine
        e.config.ema_920_trade_plan = "EMA_20_100_CROSS_SHORT"
        e.ema_20_values[100:102] = [99, 101]
        e.ema_100_values[100:102] = [100, 100]
        e.open[102] = 102.0
        pos = SimpleNamespace(is_open=True, side=Side.SHORT, sl=105.0)
        e._scan_position_exit(SimpleNamespace(position=pos), pos, 102)
        self.assertEqual(e.exits, [(102, 102.102, ExitReason.EMA_20_100_CROSS,
                                    ExitSource.STRATEGY_OPEN, e.times[102])])
        self.assertEqual(e.fallback_scans, [])

    def test_runtime_filter_rejects_a_flipped_long(self):
        e = self.engine
        e.profile = SimpleNamespace(flip_direction=True, entry_rules=(), flip_rule_match_mode="ANY")
        self.assertEqual(e._entry_filter_result(101)[0], False)
        e.profile.flip_direction = False
        e.profile.entry_rules = ({"action": "FLIP"},)
        e.flip_matches = True
        self.assertEqual(e._entry_filter_result(101)[0], False)

    def test_gap_through_protective_stop_is_reported_as_stop(self):
        e = self.engine
        e.ema_20_values[100:102] = [101, 99]
        e.ema_100_values[100:102] = [100, 100]
        e.open[102] = 94.0
        pos = SimpleNamespace(is_open=True, side=Side.LONG, sl=95.0)
        e._scan_pair_exit(SimpleNamespace(positions=lambda: [pos]), 102)
        self.assertEqual(e.exits[0][2], ExitReason.SL)

    def test_cross_plan_has_no_fixed_profit_target(self):
        e = self.engine
        pos = SimpleNamespace(
            tp=101.0, entry_price=100.0, risk=1.0, side=Side.LONG,
            partial_tp_enabled=False,
        )
        e.pending_pair = SimpleNamespace(positions=lambda: [pos])
        e._open_pair(101)
        self.assertTrue(np.isnan(pos.tp))
        self.assertIsNone(pos.ema_920_fixed_target_r)

    def test_cross_stop_buffer_is_profile_configurable(self):
        e = self.engine
        e.profile.ema_cross_stop_buffer_atr = 0.25
        e.config.strategy_timeframe_minutes = 15
        e.ema_100_values[101] = 95.0
        e.atr_values[101] = 2.0
        e.open[102] = 100.0
        plan = e._sr_stop_plan(101, 102)
        self.assertTrue(plan["passed"])
        self.assertAlmostEqual(plan["base_stop_price"], 94.5)

    def test_cross_stop_multiplier_widens_actual_stop_from_entry(self):
        e = self.engine
        e.profile.ema_cross_stop_multiplier = 2.0
        e.config.strategy_timeframe_minutes = 15
        e.ema_100_values[101] = 95.1
        e.atr_values[101] = 2.0
        e.open[102] = 100.0
        plan = e._sr_stop_plan(101, 102)
        self.assertTrue(plan["passed"])
        self.assertAlmostEqual(plan["base_stop_price"], 95.0)
        entry = 100.0 * 1.001
        self.assertAlmostEqual(plan["base_distance"], entry - 95.0)
        self.assertAlmostEqual(plan["distance"], 2.0 * (entry - 95.0))
        self.assertAlmostEqual(plan["stop_price"], entry - plan["distance"])

    def test_cross_separate_sizing_stop_can_be_wider_than_actual_ema_stop(self):
        e = self.engine
        e.profile.position_sizing_stop_override_enabled = True
        e.profile.position_sizing_stop_multiple = 2.0
        e._ema_cross_sizing_distance = 5.0
        sizing_distance, sizing_multiple, applied = e._position_sizing_stop_distance(
            e.profile, 2.0, 5.0
        )
        self.assertAlmostEqual(sizing_distance, 10.0)
        self.assertAlmostEqual(sizing_multiple, 2.0)
        self.assertTrue(applied)

    def test_cross_partial_tp_is_sizing_r_and_runner_has_no_tp2(self):
        e = self.engine
        e.profile.partial_profit_enabled = True
        e.profile.tp1_r = 0.5
        pos = SimpleNamespace(
            tp=120.0, entry_price=100.0, risk=10.0, side=Side.LONG,
            partial_tp_enabled=True, position_sizing_reference_distance=5.0,
            tp1_price=105.0, tp2_price=110.0, tp2_quantity=1.0,
        )
        e.pending_pair = SimpleNamespace(positions=lambda: [pos])
        e._open_pair(101)
        self.assertAlmostEqual(pos.tp1_price, 102.5)
        self.assertTrue(np.isinf(pos.tp2_price))
        self.assertEqual(pos.tp2_quantity, 0.0)
        self.assertTrue(np.isnan(pos.tp))

    def test_cross_stop_uses_signal_ema_100_not_micro_swing_or_1_5_atr_cap(self):
        e = self.engine
        e.config.strategy_timeframe_minutes = 15
        e.ema_100_values[101] = 100.0
        e.ema_100_values[102] = 110.0  # The execution candle is not yet known.
        e.atr_values[101] = 2.0
        e.open[102] = 103.0
        plan = e._sr_stop_plan(101, 102)
        self.assertTrue(plan["passed"])
        self.assertEqual(plan["reason"], "EMA100_CROSS_STOP")
        self.assertAlmostEqual(plan["stop_price"], 99.9)
        self.assertAlmostEqual(plan["distance"], 103.0 * 1.001 - 99.9)
        self.assertGreater(plan["distance_atr"], 1.5)
        self.assertNotIn("micro_swing_index", plan)

    def test_cross_entry_gapping_below_ema_100_stop_is_rejected(self):
        e = self.engine
        e.ema_100_values[101] = 100.0
        e.atr_values[101] = 2.0
        e.open[102] = 99.0
        self.assertEqual(e._sr_stop_plan(101, 102)["reason"], "ENTRY_INVALIDATED_GAP_THROUGH_STOP")


    def test_short_cross_stop_uses_signal_ema_100_above_entry(self):
        e = self.engine
        e.config.ema_920_trade_plan = "EMA_20_100_CROSS_SHORT"
        e.config.strategy_timeframe_minutes = 15
        e.direction = "SHORT"
        e.ema_100_values[101] = 100.0
        e.atr_values[101] = 2.0
        e.open[102] = 97.0
        plan = e._sr_stop_plan(101, 102)
        self.assertTrue(plan["passed"])
        self.assertAlmostEqual(plan["stop_price"], 100.1)
        self.assertAlmostEqual(plan["distance"], 100.1 - 97.0 * 0.999)

    def test_short_cross_entry_gapping_above_ema_100_stop_is_rejected(self):
        e = self.engine
        e.config.ema_920_trade_plan = "EMA_20_100_CROSS_SHORT"
        e.config.strategy_timeframe_minutes = 15
        e.direction = "SHORT"
        e.ema_100_values[101] = 100.0
        e.atr_values[101] = 2.0
        e.open[102] = 101.0
        self.assertEqual(e._sr_stop_plan(101, 102)["reason"], "ENTRY_INVALIDATED_GAP_THROUGH_STOP")



if __name__ == "__main__":
    unittest.main()
