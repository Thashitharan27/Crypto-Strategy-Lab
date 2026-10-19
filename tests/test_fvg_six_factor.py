import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.fair_value_gap import FairValueGapMixin
from crypto_strategy_lab.fvg_six_factor import six_factor_context
from crypto_strategy_lab.strategy_rule_model import compile_profiles, infer_direction_mode, MARKET_PERMISSIONS
from crypto_strategy_lab.strategy_visualizer import CompletedRunVisualizer


def candles():
    rng = np.random.default_rng(82)
    close = 100 + np.cumsum(rng.normal(0, .8, 3000))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + rng.uniform(.05, .4, len(close))
    low = np.minimum(open_, close) - rng.uniform(.05, .4, len(close))
    return high, low, close, np.ones(len(close)), open_


def run(arrays, end=None):
    high, low, close, atr, open_ = [a[:end] for a in arrays]
    times = pd.date_range("2026-01-01", periods=len(close), freq="15min", tz="UTC")
    return six_factor_context(high, low, close, atr, open_=open_, times=times)


def test_six_factors_are_causal_with_saved_long_and_short_decisions():
    arrays = candles()
    signals, features, stops, targets, reviews = run(arrays)
    indices = np.flatnonzero(signals != None)
    assert len(indices) > 10
    assert set(signals[indices]) == {"LONG", "SHORT"}
    formed = set()
    inside_close = False
    for i in indices:
        review = reviews[i]
        assert len(review["checks"]) == 6 and all(review["checks"].values())
        assert pd.Timestamp(review["formedTime"]) < pd.Timestamp(review["signalTime"])
        assert len(review["formationCandles"]) == 3
        assert review["formationCandles"][-1]["time"] == review["formedTime"]
        assert pd.Timestamp(review["structurePivotTime"]) < pd.Timestamp(review["structureBreakTime"])
        assert pd.Timestamp(review["structureBreakTime"]) <= pd.Timestamp(review["formedTime"])
        key = (review["side"], review["formedTime"])
        assert key not in formed
        formed.add(key)
        assert np.isfinite(stops[signals[i]][i]) and np.isfinite(targets[signals[i]][i])
        assert np.isfinite(features[signals[i]]["FVG_GAP_SIZE_ATR"][i])
        inside_close |= review["bottom"] <= arrays[2][i] <= review["top"]
        # Adding future candles cannot change an accepted decision or its levels.
        prefix = run(arrays, i+1)
        assert list(prefix[0]) == list(signals[:i+1])
        assert prefix[4][-1] == review
    assert inside_close, "preset must accept closes inside the gap"


def test_mirroring_prices_mirrors_six_factor_signals():
    high, low, close, atr, open_ = candles()
    original = run((high, low, close, atr, open_))
    mirror = run((200-low, 200-high, 200-close, atr, 200-open_))
    expected = [{"LONG": "SHORT", "SHORT": "LONG", None: None}[x] for x in original[0]]
    assert list(mirror[0]) == expected


def test_new_mode_round_trips_and_native_mixin_uses_it():
    profiles, _ = compile_profiles(direction_mode="FVG_SIX_FACTOR", market_permissions=MARKET_PERMISSIONS)
    assert infer_direction_mode(profiles) == "FVG_SIX_FACTOR"

    class Base:
        def _configure_signal_features(self):
            pass

    class Probe(FairValueGapMixin, Base):
        pass

    probe = Probe()
    probe.high, probe.low, probe.close, probe.atr_values, probe.open = candles()
    probe.times = pd.date_range("2026-01-01", periods=len(probe.close), freq="15min", tz="UTC")
    probe.config = SimpleNamespace(strategy_profiles=profiles)
    probe._configure_signal_features()
    probe.signal_strategy_mode = probe._infer_signal_strategy_mode()
    assert probe.signal_strategy_mode == "FVG_SIX_FACTOR"
    indices = np.flatnonzero(probe.fvg_first_revisit != None)
    assert len(indices) > 10
    assert probe._selected_direction(indices[0]) in {"LONG", "SHORT"}


def test_saved_trade_context_round_trips_to_visualizer_without_recalculation():
    reviews = run(candles())[4]
    review = next(r for r in reviews if r)
    model = object.__new__(CompletedRunVisualizer)
    model.trades = pd.DataFrame([{"fvg_six_factor_context": json.dumps(review)}])
    payload = model.fvg_six_factor_derivation(0)
    assert payload["status"] == "AVAILABLE"
    assert payload["bottom"] == review["bottom"]
    assert payload["checks"] == review["checks"]
    assert payload["signalTime"] == int(pd.Timestamp(review["signalTime"]).timestamp())
    assert payload["formationCandles"][-1]["time"] == payload["formedTime"]
    # Earlier completed runs lack the additional anchors and remain readable.
    legacy = {k: v for k, v in review.items() if k not in {"formationCandles", "structurePivotTime", "structureBreakTime"}}
    model.trades = pd.DataFrame([{"fvg_six_factor_context": json.dumps(legacy)}])
    assert model.fvg_six_factor_derivation(0)["status"] == "AVAILABLE"
    model.trades = pd.DataFrame([{"fvg_six_factor_context": "bad-json"}])
    assert model.fvg_six_factor_derivation(0)["status"] == "NOT_AVAILABLE"


def test_production_engine_executes_next_open_and_persists_review():
    from dataclasses import asdict, replace
    from crypto_strategy_lab.config import BacktestConfig
    from crypto_strategy_lab.strategy_profiles import StrategyProfile
    from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine

    high, low, close, atr, open_ = candles()
    times = pd.date_range("2026-01-01", periods=len(close), freq="15min", tz="UTC")
    data = pd.DataFrame(dict(timestamp=times, open=open_, high=high, low=low, close=close, volume=atr))
    profiles, _ = compile_profiles(direction_mode="FVG_SIX_FACTOR", market_permissions=MARKET_PERMISSIONS)
    native = {key: replace(StrategyProfile(**asdict(p)), reward_risk_ratio=.5) for key, p in profiles.items()}
    config = BacktestConfig(
        strategy_profiles=native, use_intrabar_data=False,
        market_regime_method="ASSET_RETURN", enable_support_resistance_analysis=False,
        entry_timing_mode="NEXT_CANDLE_OPEN", enable_trade_telemetry=False,
    )
    engine = RuleAwareDataLakeProductionBacktestEngine(data, config)
    engine.market_regime_values[:] = "SIDEWAYS"
    trades = engine.run()
    assert len(trades) > 0
    assert set(trades["signal_strategy"]) == {"FVG_SIX_FACTOR"}
    for _, row in trades.iterrows():
        review = json.loads(row["fvg_six_factor_context"])
        assert pd.Timestamp(row["entry_time"]) == pd.Timestamp(review["signalTime"]) + pd.Timedelta(minutes=15)
        assert row["fvg_stop_applied"]
        assert row["fvg_stop_boundary_price"] == review["stopBoundary"]
        assert all(review["checks"].values())


@pytest.mark.parametrize("side,opening,closing,expected", [
    ("LONG", 12, 10.5, True),   # red body closes inside
    ("SHORT", 9, 10.5, True),   # green body closes inside
    ("LONG", 11.2, 11.8, True), # bullish wick rejection above
    ("LONG", 12, 11.8, False),  # bearish wick-only touch above
    ("LONG", 11.8, 11.8, False),# doji outside
    ("SHORT", 9.8, 9.2, True),  # bearish wick rejection below
    ("SHORT", 9, 9.2, False),   # bullish wick-only touch below
    ("SHORT", 9.2, 9.2, False), # doji outside
    ("LONG", 8, 9, False),      # wrong-side close even if bullish
    ("SHORT", 13, 12, False),   # wrong-side close even if bearish
    ("LONG", 12, 10, True),     # inclusive lower boundary
    ("SHORT", 9, 11, True),     # inclusive upper boundary
])
def test_revisit_body_and_wick_confirmation(side, opening, closing, expected):
    from crypto_strategy_lab.fvg_six_factor import revisit_close_confirms
    assert revisit_close_confirms(side, 10, 11, opening, closing) == expected


def test_opposite_wick_candle_is_rejected_by_signal_engine():
    arrays = candles()
    signals, _, _, _, reviews = run(arrays)
    for i, review in enumerate(reviews):
        if not review:
            continue
        side = review["side"]
        close = arrays[2][i]
        outside = close > review["top"] if side == "LONG" else close < review["bottom"]
        if not outside:
            continue
        changed = [a.copy() for a in arrays]
        # Change only the revisit's body colour; keep its high/low and close.
        changed[4][i] = (close + arrays[0][i])/2 if side == "LONG" else (close + arrays[1][i])/2
        altered = run(changed, i+1)
        assert altered[0][i] != side
        assert review["confirmationRule"] == "INSIDE_OR_DIRECTIONAL_REJECTION_V2"
        return
    pytest.fail("fixture must contain a directional outside-close rejection")
