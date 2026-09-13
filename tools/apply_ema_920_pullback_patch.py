from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one match in {path}, found {count}: {old[:80]!r}")
    write(path, text.replace(old, new, 1))


def replace_count(path: str, old: str, new: str, expected: int) -> None:
    text = read(path)
    if text.count(new) >= expected:
        return
    count = text.count(old)
    if count != expected:
        raise RuntimeError(f"Expected {expected} matches in {path}, found {count}: {old[:80]!r}")
    write(path, text.replace(old, new))


# Canonical rule contract: expose EMA 9/20 and volume research evidence.
replace_once(
    "crypto_strategy_core/rules.py",
    '    "ATR_PCT",\n    "EMA_50_DISTANCE_ATR",',
    '    "ATR_PCT",\n'
    '    "EMA_9_DISTANCE_ATR",\n'
    '    "EMA_20_DISTANCE_ATR",\n'
    '    "EMA_9_20_SPREAD_ATR",\n'
    '    "EMA_9_SLOPE_ATR",\n'
    '    "EMA_20_SLOPE_ATR",\n'
    '    "VOLUME_RATIO_20",\n'
    '    "VOLUME_CHANGE_PCT",\n'
    '    "EMA_50_DISTANCE_ATR",',
)

# Strategy authoring: add the new sparse signal strategy and persist it as a native marker.
replace_once(
    "crypto_strategy_lab/strategy_rule_model.py",
    'SIGNAL_STRATEGIES = ("DI", "DMI_TREND", "MACD_PULLBACK")',
    'SIGNAL_STRATEGIES = ("DI", "DMI_TREND", "MACD_PULLBACK", "EMA_9_20_PULLBACK")',
)
replace_once(
    "crypto_strategy_lab/strategy_rule_model.py",
    '\n\ndef compile_profiles(\n',
    '''\n\ndef _ema_9_20_pullback_native_rules() -> tuple[dict, ...]:\n    """Persist the causal 9/20 EMA pullback signal-strategy choice.\n\n    Runtime direction is produced only when the completed confirmation candle\n    follows a low-volume pullback into the EMA band. This marker remains a\n    no-op rule so every threshold can still be researched independently.\n    """\n    return (\n        {\n            "action": "REJECT",\n            "indicator": "EMA_9_20_SPREAD_ATR",\n            "condition": "OUTSIDE",\n            "minimum": LOW,\n            "maximum": HIGH,\n            f"{_META_PREFIX}kind": "REQUIRED",\n            _DMI_TREND_MODE_MARKER: "EMA_9_20_PULLBACK",\n            _DMI_TREND_RULE_MARKER: "EMA_9_20_PULLBACK_SIGNAL",\n        },\n    )\n\n\ndef compile_profiles(\n''',
)
replace_once(
    "crypto_strategy_lab/strategy_rule_model.py",
    '''        elif mode == "MACD_PULLBACK":\n            native_rules = list(_macd_pullback_native_rules())\n        else:\n            native_rules = []''',
    '''        elif mode == "MACD_PULLBACK":\n            native_rules = list(_macd_pullback_native_rules())\n        elif mode == "EMA_9_20_PULLBACK":\n            native_rules = list(_ema_9_20_pullback_native_rules())\n        else:\n            native_rules = []''',
)

# Rule builder labels/menu.
replace_once(
    "crypto_strategy_lab/gui/rule_strategy_builder.py",
    '    "ATR_PCT": "ATR % (decimal)",\n    "EMA_50_DISTANCE_ATR": "Price − EMA 50 (ATR)",',
    '    "ATR_PCT": "ATR % (decimal)",\n'
    '    "EMA_9_DISTANCE_ATR": "Price − EMA 9 (ATR)",\n'
    '    "EMA_20_DISTANCE_ATR": "Price − EMA 20 (ATR)",\n'
    '    "EMA_9_20_SPREAD_ATR": "EMA 9 − EMA 20 (ATR)",\n'
    '    "EMA_9_SLOPE_ATR": "EMA 9 Slope (ATR / bar)",\n'
    '    "EMA_20_SLOPE_ATR": "EMA 20 Slope (ATR / bar)",\n'
    '    "VOLUME_RATIO_20": "Volume / Prior 20-Bar Average",\n'
    '    "VOLUME_CHANGE_PCT": "Volume Change (1 bar, decimal)",\n'
    '    "EMA_50_DISTANCE_ATR": "Price − EMA 50 (ATR)",',
)
replace_count(
    "crypto_strategy_lab/gui/rule_strategy_builder.py",
    '            "ADX", "ADX_CHANGE", "ATR_PCT", "BB_WIDTH",\n            "EMA_50_DISTANCE_ATR", "EMA_100_DISTANCE_ATR", "EMA_200_DISTANCE_ATR",',
    '            "ADX", "ADX_CHANGE", "ATR_PCT", "BB_WIDTH",\n'
    '            "EMA_9_DISTANCE_ATR", "EMA_20_DISTANCE_ATR", "EMA_9_20_SPREAD_ATR",\n'
    '            "EMA_9_SLOPE_ATR", "EMA_20_SLOPE_ATR",\n'
    '            "VOLUME_RATIO_20", "VOLUME_CHANGE_PCT",\n'
    '            "EMA_50_DISTANCE_ATR", "EMA_100_DISTANCE_ATR", "EMA_200_DISTANCE_ATR",',
    2,
)
replace_once(
    "crypto_strategy_lab/gui/rule_strategy_builder.py",
    '    "MACD_PULLBACK": "MACD Pullback — 12/26/9",\n}',
    '    "MACD_PULLBACK": "MACD Pullback — 12/26/9",\n'
    '    "EMA_9_20_PULLBACK": "EMA 9/20 Pullback — Scalping",\n}',
)

# 1m and 5m become real strategy timeframes, not intrabar-only choices.
replace_once(
    "crypto_strategy_lab/gui/v2_main_window.py",
    'STRATEGY_TIMEFRAMES = ("15m", "1h", "4h", "1d")',
    'STRATEGY_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")',
)

# Compose the new signal/stop behavior into the current production rule runtime.
replace_once(
    "crypto_strategy_lab/rule_native_engine.py",
    'from crypto_strategy_lab.data_lake_production_engine import (\n    DataLakeProductionBacktestEngine,\n)\nfrom crypto_strategy_lab.strategy_rule_model import CATEGORICAL_VALUE_CODES',
    'from crypto_strategy_lab.data_lake_production_engine import (\n    DataLakeProductionBacktestEngine,\n)\n'
    'from crypto_strategy_lab.ema_pullback import Ema920PullbackMixin\n'
    'from crypto_strategy_lab.strategy_rule_model import CATEGORICAL_VALUE_CODES',
)
replace_once(
    "crypto_strategy_lab/rule_native_engine.py",
    'class RuleAwareDataLakeProductionBacktestEngine(DataLakeProductionBacktestEngine):',
    'class RuleAwareDataLakeProductionBacktestEngine(Ema920PullbackMixin, DataLakeProductionBacktestEngine):',
)

# New mixin: causal signal, research evidence, micro-swing stop and exact 1R target.
write(
    "crypto_strategy_lab/ema_pullback.py",
    '''"""Causal 9/20 EMA pullback scalping signal and structural micro-swing stop."""\nfrom __future__ import annotations\n\nimport numpy as np\nimport pandas as pd\n\nfrom crypto_strategy_lab.engine import _signal_ema\n\n\nEMA_920_MODE = "EMA_9_20_PULLBACK"\nEMA_920_RULE_INDICATORS = frozenset({\n    "EMA_9_DISTANCE_ATR",\n    "EMA_20_DISTANCE_ATR",\n    "EMA_9_20_SPREAD_ATR",\n    "EMA_9_SLOPE_ATR",\n    "EMA_20_SLOPE_ATR",\n    "VOLUME_RATIO_20",\n    "VOLUME_CHANGE_PCT",\n})\n\n\nclass Ema920PullbackMixin:\n    """Add a sparse 9/20 EMA continuation signal without forking the simulator.\n\n    The completed strategy candle is the confirmation candle. The previous\n    completed candle must overlap the EMA9/EMA20 band on below-normal volume.\n    A trade is then allowed only when trend, candle direction and returning\n    volume all agree. Stops use the latest confirmed 2-left/2-right micro swing.\n    """\n\n    ema_920_volume_lookback = 20\n    ema_920_swing_span = 2\n    ema_920_swing_lookback = 20\n    ema_920_stop_buffer_atr = 0.05\n    ema_920_stop_maximum_atr = 1.50\n\n    def _configure_signal_features(self):\n        super()._configure_signal_features()\n        self.ema_9_values = _signal_ema(self.close, 9)\n        self.ema_20_values = _signal_ema(self.close, 20)\n\n        previous_ema9 = np.roll(self.ema_9_values, 1)\n        previous_ema20 = np.roll(self.ema_20_values, 1)\n        previous_ema9[0] = np.nan\n        previous_ema20[0] = np.nan\n        atr = np.asarray(self.atr_values, dtype=float)\n        valid_atr = np.isfinite(atr) & (atr > 0)\n        self.ema_9_slope_atr = np.divide(\n            self.ema_9_values - previous_ema9,\n            atr,\n            out=np.full(len(atr), np.nan, dtype=float),\n            where=valid_atr,\n        )\n        self.ema_20_slope_atr = np.divide(\n            self.ema_20_values - previous_ema20,\n            atr,\n            out=np.full(len(atr), np.nan, dtype=float),\n            where=valid_atr,\n        )\n        self.ema_9_20_spread_atr = np.divide(\n            self.ema_9_values - self.ema_20_values,\n            atr,\n            out=np.full(len(atr), np.nan, dtype=float),\n            where=valid_atr,\n        )\n\n        volume = np.asarray(self.volume, dtype=float)\n        baseline = (\n            pd.Series(volume, dtype=float)\n            .rolling(self.ema_920_volume_lookback, min_periods=self.ema_920_volume_lookback)\n            .mean()\n            .shift(1)\n            .to_numpy(float)\n        )\n        self.volume_ratio_20 = np.divide(\n            volume,\n            baseline,\n            out=np.full(len(volume), np.nan, dtype=float),\n            where=np.isfinite(baseline) & (baseline > 0),\n        )\n        previous_volume = np.roll(volume, 1)\n        previous_volume[0] = np.nan\n        self.volume_change_pct = np.divide(\n            volume - previous_volume,\n            previous_volume,\n            out=np.full(len(volume), np.nan, dtype=float),\n            where=np.isfinite(previous_volume) & (previous_volume > 0),\n        )\n\n    def _infer_signal_strategy_mode(self):\n        for profile in self.config.strategy_profiles.values():\n            for rule in getattr(profile, "entry_rules", ()):\n                if str(rule.get("_strategy_direction_mode", "")).upper() == EMA_920_MODE:\n                    return EMA_920_MODE\n        return super()._infer_signal_strategy_mode()\n\n    def _ema_920_direction(self, i: int):\n        if i <= self.ema_920_volume_lookback:\n            return None\n        previous = i - 1\n        values = (\n            self.ema_9_values[i], self.ema_20_values[i],\n            self.ema_9_values[previous], self.ema_20_values[previous],\n            self.ema_9_slope_atr[i], self.ema_20_slope_atr[i],\n            self.volume_ratio_20[previous], self.volume[i], self.volume[previous],\n            self.open[i], self.close[i], self.close[previous],\n            self.low[previous], self.high[previous],\n        )\n        if not all(np.isfinite(float(value)) for value in values):\n            return None\n\n        prev_fast = float(self.ema_9_values[previous])\n        prev_slow = float(self.ema_20_values[previous])\n        band_low = min(prev_fast, prev_slow)\n        band_high = max(prev_fast, prev_slow)\n        pulled_into_band = (\n            float(self.low[previous]) <= band_high\n            and float(self.high[previous]) >= band_low\n        )\n        if not pulled_into_band or float(self.volume_ratio_20[previous]) >= 1.0:\n            return None\n        if float(self.volume[i]) <= float(self.volume[previous]):\n            return None\n\n        fast = float(self.ema_9_values[i])\n        slow = float(self.ema_20_values[i])\n        close = float(self.close[i])\n        open_ = float(self.open[i])\n        previous_close = float(self.close[previous])\n        fast_slope = float(self.ema_9_slope_atr[i])\n        slow_slope = float(self.ema_20_slope_atr[i])\n\n        long_setup = (\n            fast > slow\n            and fast_slope > 0\n            and slow_slope > 0\n            and previous_close >= prev_slow\n            and close > open_\n            and close > fast\n        )\n        if long_setup:\n            return "LONG"\n\n        short_setup = (\n            fast < slow\n            and fast_slope < 0\n            and slow_slope < 0\n            and previous_close <= prev_slow\n            and close < open_\n            and close < fast\n        )\n        if short_setup:\n            return "SHORT"\n        return None\n\n    def _selected_direction(self, i):\n        if getattr(self, "signal_strategy_mode", "DI") == EMA_920_MODE:\n            return self._ema_920_direction(i)\n        return super()._selected_direction(i)\n\n    def _should_enter(self, i):\n        if getattr(self, "signal_strategy_mode", "DI") == EMA_920_MODE:\n            if self._selected_direction(i) is None:\n                return False\n        return super()._should_enter(i)\n\n    def _strategy_profile_rule_value(self, i, direction, profile, indicator):\n        if indicator not in EMA_920_RULE_INDICATORS:\n            return super()._strategy_profile_rule_value(i, direction, profile, indicator)\n\n        atr = float(self.atr_values[i])\n        if indicator in {"EMA_9_DISTANCE_ATR", "EMA_20_DISTANCE_ATR"}:\n            if not np.isfinite(atr) or atr <= 0:\n                return np.nan\n            mean = self.ema_9_values[i] if indicator == "EMA_9_DISTANCE_ATR" else self.ema_20_values[i]\n            if not np.isfinite(mean):\n                return np.nan\n            return (float(self.close[i]) - float(mean)) / atr\n        if indicator == "EMA_9_20_SPREAD_ATR":\n            return float(self.ema_9_20_spread_atr[i])\n        if indicator == "EMA_9_SLOPE_ATR":\n            return float(self.ema_9_slope_atr[i])\n        if indicator == "EMA_20_SLOPE_ATR":\n            return float(self.ema_20_slope_atr[i])\n        if indicator == "VOLUME_RATIO_20":\n            return float(self.volume_ratio_20[i])\n        if indicator == "VOLUME_CHANGE_PCT":\n            return float(self.volume_change_pct[i])\n        raise KeyError(indicator)\n\n    def _latest_confirmed_micro_swing(self, i: int, direction: str):\n        span = self.ema_920_swing_span\n        start = max(span, i - self.ema_920_swing_lookback + 1)\n        stop = i - span\n        if stop < start:\n            return None\n        candidate = None\n        for j in range(start, stop + 1):\n            if direction == "LONG":\n                value = float(self.low[j])\n                if value < float(np.min(self.low[j - span:j])) and value < float(np.min(self.low[j + 1:j + span + 1])):\n                    candidate = (j, value)\n            else:\n                value = float(self.high[j])\n                if value > float(np.max(self.high[j - span:j])) and value > float(np.max(self.high[j + 1:j + span + 1])):\n                    candidate = (j, value)\n        return candidate\n\n    def _ema_920_micro_swing_stop_plan(self, i: int, execution_i: int | None = None):\n        direction = self._effective_trade_direction(i)\n        if direction not in {"LONG", "SHORT"}:\n            return {"passed": False, "applied": False, "reason": "EMA920_NO_DIRECTION", "distance": None}\n        swing = self._latest_confirmed_micro_swing(i, direction)\n        if swing is None:\n            return {"passed": False, "applied": False, "reason": "EMA920_NO_CONFIRMED_MICRO_SWING", "distance": None}\n        swing_i, level = swing\n        atr = float(self.atr_values[i])\n        if not np.isfinite(atr) or atr <= 0:\n            return {"passed": False, "applied": False, "reason": "EMA920_ATR_UNAVAILABLE", "distance": None}\n        entry = float(self._expected_entry_price(i, execution_i, direction))\n        buffer_price = atr * self.ema_920_stop_buffer_atr\n        stop_price = level - buffer_price if direction == "LONG" else level + buffer_price\n        distance = entry - stop_price if direction == "LONG" else stop_price - entry\n        if not np.isfinite(distance) or distance <= 0:\n            return {"passed": False, "applied": False, "reason": "EMA920_SWING_ON_WRONG_SIDE", "distance": None}\n        distance_atr = distance / atr\n        if distance_atr > self.ema_920_stop_maximum_atr:\n            return {\n                "passed": False, "applied": False, "reason": "EMA920_MICRO_SWING_STOP_TOO_WIDE",\n                "distance": distance, "distance_atr": distance_atr,\n                "level_price": level, "boundary_price": level, "stop_price": stop_price,\n                "timeframe_minutes": int(getattr(self.config, "strategy_timeframe_minutes", 0)),\n                "micro_swing_index": swing_i, "micro_swing": True,\n            }\n        return {\n            "passed": True, "applied": True, "reason": "EMA920_MICRO_SWING_STOP",\n            "distance": distance, "distance_atr": distance_atr,\n            "level_price": level, "boundary_price": level, "stop_price": stop_price,\n            "timeframe_minutes": int(getattr(self.config, "strategy_timeframe_minutes", 0)),\n            "micro_swing_index": swing_i, "micro_swing": True,\n        }\n\n    def _sr_stop_plan(self, i: int, execution_i: int | None = None):\n        if getattr(self, "signal_strategy_mode", "DI") == EMA_920_MODE:\n            return self._ema_920_micro_swing_stop_plan(i, execution_i)\n        return super()._sr_stop_plan(i, execution_i)\n\n    def _annotate_sr_stop(self, positions, plan):\n        super()._annotate_sr_stop(positions, plan)\n        if not plan.get("micro_swing"):\n            return\n        for pos in positions:\n            pos.micro_swing_stop_applied = bool(plan.get("applied", False))\n            pos.micro_swing_index = plan.get("micro_swing_index")\n            pos.micro_swing_level_price = plan.get("level_price", np.nan)\n            pos.micro_swing_stop_price = plan.get("stop_price", np.nan)\n            pos.micro_swing_stop_distance_atr = plan.get("distance_atr", np.nan)\n\n    def _open_pair(self, i, entry_filter_passed=True, entry_filter_reason="Strategy profile passed", schedule=None):\n        before = len(self.active_pairs)\n        result = super()._open_pair(i, entry_filter_passed, entry_filter_reason, schedule)\n        if getattr(self, "signal_strategy_mode", "DI") != EMA_920_MODE or len(self.active_pairs) <= before:\n            return result\n        pair = self.active_pairs[-1]\n        for pos in pair.positions():\n            side_sign = 1.0 if str(getattr(pos.side, "value", pos.side)).upper() == "LONG" else -1.0\n            pos.tp = float(pos.entry_price) + side_sign * float(pos.risk)\n            if getattr(pos, "partial_tp_enabled", False):\n                pos.tp2_price = pos.tp\n            pos.ema_920_fixed_target_r = 1.0\n        return result\n''',
)

# Targeted acceptance tests for the new strategy path.
write(
    "tests/test_ema_920_pullback_strategy.py",
    '''from types import SimpleNamespace\n\nimport numpy as np\n\nfrom crypto_strategy_core.rules import RULE_INDICATORS\nfrom crypto_strategy_lab.ema_pullback import EMA_920_MODE, Ema920PullbackMixin\nfrom crypto_strategy_lab.gui.rule_strategy_builder import DIRECTION_LABELS, EVIDENCE_LABELS\nfrom crypto_strategy_lab.gui.v2_main_window import STRATEGY_TIMEFRAMES\nfrom crypto_strategy_lab.strategy_rule_model import (\n    MARKET_PERMISSIONS,\n    compile_profiles,\n    infer_direction_mode,\n)\n\n\ndef test_ema_920_strategy_is_first_class_authoring_option():\n    strategy, _execution = compile_profiles(\n        direction_mode=EMA_920_MODE,\n        market_permissions=MARKET_PERMISSIONS,\n    )\n    assert infer_direction_mode(strategy) == EMA_920_MODE\n    assert all(\n        any(rule.get("_strategy_direction_mode") == EMA_920_MODE for rule in profile.entry_rules)\n        for profile in strategy.values()\n    )\n    assert DIRECTION_LABELS[EMA_920_MODE] == "EMA 9/20 Pullback — Scalping"\n\n\ndef test_ema_920_evidence_and_scalping_timeframes_are_exposed():\n    expected = {\n        "EMA_9_DISTANCE_ATR", "EMA_20_DISTANCE_ATR", "EMA_9_20_SPREAD_ATR",\n        "EMA_9_SLOPE_ATR", "EMA_20_SLOPE_ATR",\n        "VOLUME_RATIO_20", "VOLUME_CHANGE_PCT",\n    }\n    assert expected <= set(RULE_INDICATORS)\n    assert expected <= set(EVIDENCE_LABELS)\n    assert STRATEGY_TIMEFRAMES[:2] == ("1m", "5m")\n\n\nclass _Base:\n    def _configure_signal_features(self):\n        return None\n\n    def _infer_signal_strategy_mode(self):\n        return "DI"\n\n    def _selected_direction(self, _i):\n        return "LONG"\n\n\nclass _Engine(Ema920PullbackMixin, _Base):\n    pass\n\n\ndef _signal_engine():\n    engine = _Engine()\n    n = 30\n    engine.config = SimpleNamespace(strategy_profiles={})\n    engine.close = np.linspace(100.0, 103.0, n)\n    engine.open = engine.close - 0.05\n    engine.high = engine.close + 0.20\n    engine.low = engine.close - 0.20\n    engine.volume = np.full(n, 100.0)\n    engine.atr_values = np.ones(n)\n    engine._configure_signal_features()\n    engine.signal_strategy_mode = EMA_920_MODE\n    return engine\n\n\ndef test_ema_920_signal_requires_low_volume_pullback_then_volume_return():\n    engine = _signal_engine()\n    i = 25\n    previous = i - 1\n    # Force an unambiguous rising EMA trend and one pullback candle overlapping the band.\n    engine.ema_9_values[i] = 102.0\n    engine.ema_20_values[i] = 101.5\n    engine.ema_9_values[previous] = 101.8\n    engine.ema_20_values[previous] = 101.4\n    engine.ema_9_slope_atr[i] = 0.2\n    engine.ema_20_slope_atr[i] = 0.1\n    engine.low[previous] = 101.6\n    engine.high[previous] = 102.0\n    engine.close[previous] = 101.6\n    engine.volume_ratio_20[previous] = 0.7\n    engine.volume[previous] = 70.0\n    engine.volume[i] = 120.0\n    engine.open[i] = 102.05\n    engine.close[i] = 102.30\n    assert engine._selected_direction(i) == "LONG"\n\n    engine.volume[i] = 60.0\n    assert engine._selected_direction(i) is None\n\n\ndef test_latest_micro_swing_uses_only_confirmed_pivots():\n    engine = _signal_engine()\n    engine.low[:] = 10.0\n    engine.high[:] = 20.0\n    # Pivot low at 10 is confirmed by bars 11 and 12; a newer low at 14 is not\n    # a pivot because its right-hand confirmation bars are lower/equal.\n    engine.low[8:13] = [9.0, 8.0, 5.0, 8.0, 9.0]\n    swing = engine._latest_confirmed_micro_swing(14, "LONG")\n    assert swing == (10, 5.0)\n''',
)

print("EMA 9/20 pullback patch applied")
