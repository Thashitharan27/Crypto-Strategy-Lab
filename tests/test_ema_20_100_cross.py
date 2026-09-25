"""Regression checks for the optional long-only EMA 20/100 plan."""
from types import SimpleNamespace
from dataclasses import replace
import unittest

import numpy as np
import pandas as pd

from crypto_strategy_lab.ema_pullback import Ema920PullbackMixin, EMA_920_MODE
from crypto_strategy_lab.data_lake_config import ResearchRunConfig
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
        return ("BULL", "LONG", "BULL_LONG", self.profile)

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
        engine.config = SimpleNamespace(ema_920_trade_plan="EMA_20_100_CROSS", slippage=0.001)
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
        engine.profile = SimpleNamespace(flip_direction=False, entry_rules=(), flip_rule_match_mode="ANY")
        engine.flip_matches = False

    def test_completed_bullish_cross_is_a_long_entry_signal_only_once(self):
        e = self.engine
        e.ema_20_values[99:103] = [99, 99, 101, 102]
        e.ema_100_values[99:103] = [100, 100, 100, 100]
        self.assertIsNone(e._selected_direction(100))
        self.assertEqual(e._selected_direction(101), "LONG")
        self.assertIsNone(e._selected_direction(102))

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
        pos = SimpleNamespace(tp=101.0, entry_price=100.0, risk=1.0, side=Side.LONG)
        e.pending_pair = SimpleNamespace(positions=lambda: [pos])
        e._open_pair(101)
        self.assertTrue(np.isnan(pos.tp))
        self.assertIsNone(pos.ema_920_fixed_target_r)


if __name__ == "__main__":
    unittest.main()
