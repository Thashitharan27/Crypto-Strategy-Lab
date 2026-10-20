from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.fvg_htf_targets import opposing_fvg_snapshots, nearest_opposing_zone
from crypto_strategy_lab.fair_value_gap import FairValueGapMixin
from crypto_strategy_lab.data_lake_config import ResearchRunConfig, normalize_data_lake_config


def market():
    times = pd.date_range("2026-01-01", periods=16, freq="15min", tz="UTC")
    high = np.repeat([120., 115., 105., 104.], 4)
    low = np.repeat([110., 100., 95., 94.], 4)
    return times, high, low, (high + low) / 2


def test_htf_target_is_visible_only_after_complete_third_candle_and_is_causal():
    times, high, low, close = market()
    full = opposing_fvg_snapshots(times, high, low, close, 15, 60)
    assert not any(full[:11])
    zone = full[11][0]
    assert zone == {"side": "SHORT", "bottom": 105., "top": 110.,
                    "confirmed_at": "2026-01-01T03:00:00+00:00", "timeframe_minutes": 60}
    for end in range(1, len(times)+1):
        prefix = opposing_fvg_snapshots(times[:end], high[:end], low[:end], close[:end], 15, 60)
        assert prefix == full[:end]


@pytest.mark.parametrize("gap_through", [False, True])
def test_first_wick_touch_or_gap_through_consumes_target(gap_through):
    times, high, low, close = market()
    if gap_through:
        high[12], low[12], close[12] = 114., 111., 112.
    else:
        high[12] = 106.
    snapshots = opposing_fvg_snapshots(times, high, low, close, 15, 60)
    assert snapshots[11]
    assert not any(z["bottom"] == 105. for z in snapshots[12])


def test_incomplete_hour_does_not_bridge_missing_formation_data():
    times, high, low, close = market()
    keep = np.arange(len(times)) != 5
    snapshots = opposing_fvg_snapshots(times[keep], high[keep], low[keep], close[keep], 15, 60)
    assert not any(snapshots)


def test_nearest_opposing_zone_selects_price_not_age_or_same_side():
    zones = [dict(side="SHORT", bottom=120., top=125.),
             dict(side="LONG", bottom=101., top=102.),
             dict(side="SHORT", bottom=105., top=110.),
             dict(side="LONG", bottom=90., top=95.)]
    assert nearest_opposing_zone(zones, "LONG", 100.)[0]["bottom"] == 105.
    assert nearest_opposing_zone(zones, "SHORT", 100.)[0]["top"] == 95.
    assert nearest_opposing_zone(zones, "LONG", 107.)[1] == "FVG_HTF_TARGET_ENTRY_INSIDE_ZONE"


def probe(side="LONG"):
    class Base:
        def _expected_entry_price(self, i, execution_i, direction):
            return 100.

    class Probe(FairValueGapMixin, Base):
        def _effective_trade_direction(self, i):
            return side

        def _sr_stop_plan(self, i, execution_i=None):
            return {"applied": True, "distance": 2.}

        def _profile_context(self, i):
            return None, None, None, SimpleNamespace(reward_risk_ratio=3.)

    p = Probe()
    p.config = SimpleNamespace(fvg_target_mode="HTF_OPPOSING_FVG", fvg_target_minimum_r=1.5,
                              fvg_target_buffer_atr=.05, fvg_target_no_level_policy="REJECT_TRADE",
                              slippage=0., strategy_timeframe_minutes=15)
    p.atr_values = np.array([2.])
    p.fvg_target_boundaries = {"LONG": np.array([120.]), "SHORT": np.array([80.])}
    zone = dict(side="SHORT", bottom=105., top=110., timeframe_minutes=60,
                confirmed_at="2026-01-01T00:00:00+00:00") if side == "LONG" else dict(
                    side="LONG", bottom=90., top=95., timeframe_minutes=60,
                    confirmed_at="2026-01-01T00:00:00+00:00")
    p.fvg_target_htf_snapshots = [(zone,)]
    return p


@pytest.mark.parametrize("side,price", [("LONG", 104.9), ("SHORT", 95.1)])
def test_target_uses_near_edge_buffer_and_actual_risk(side, price):
    p = probe(side)
    plan = p._fvg_target_plan(0)
    assert plan["passed"]
    assert plan["limit_price"] == pytest.approx(price)
    assert plan["target_r"] == pytest.approx(2.45)
    assert plan["zone"]["timeframe_minutes"] == 60
    p._pending_fvg_confirmation_price = 101.
    changed = p._fvg_target_plan(0)
    assert changed["limit_price"] == pytest.approx(price)
    assert changed["target_r"] != plan["target_r"]


def test_no_level_fallback_is_explicit_and_does_not_bypass_close_obstacle():
    p = probe()
    p.fvg_target_htf_snapshots = [()]
    assert p._fvg_target_plan(0)["reason"] == "FVG_HTF_TARGET_UNAVAILABLE"
    p.config.fvg_target_no_level_policy = "USE_FIXED_TP"
    fallback = p._fvg_target_plan(0)
    assert fallback["mode"] == "FIXED_R" and fallback["target_r"] == 3.
    p.config.fvg_target_minimum_r = 4.
    assert p._fvg_target_plan(0)["reason"] == "FVG_HTF_TARGET_INSUFFICIENT_ROOM"
    p.config.fvg_target_minimum_r = 1.5
    p.fvg_target_htf_snapshots = [(dict(side="SHORT", bottom=102., top=103.),)]
    assert p._fvg_target_plan(0)["reason"] == "FVG_HTF_TARGET_INSUFFICIENT_ROOM"


def test_confirmation_wick_consumes_target_before_delayed_fill():
    p = probe()
    p.times = [pd.Timestamp("2026-01-01T00:00:00")]
    p._pending_fvg_confirmation_time = pd.Timestamp("2026-01-01T00:16:00Z")
    p.intrabar_data = pd.DataFrame({"timestamp": [pd.Timestamp("2026-01-01T00:15:00Z")],
                                   "high": [106.], "low": [100.]})
    assert not p._fvg_target_zones_at_entry(0)
    p.intrabar_data.loc[0, "high"] = 104.
    assert p._fvg_target_zones_at_entry(0)


def test_htf_target_cannot_precede_configured_partial_take_profit():
    p = probe()
    p._profile_context = lambda i: (None, None, None, SimpleNamespace(
        reward_risk_ratio=3., partial_profit_enabled=True, tp1_r=2.5))
    assert p._fvg_target_plan(0)["reason"] == "FVG_HTF_TARGET_BEFORE_PARTIAL_TP"
    p.fvg_target_htf_snapshots = [()]
    p.config.fvg_target_no_level_policy = "USE_FIXED_TP"
    assert p._fvg_target_plan(0)["passed"]


def test_target_settings_round_trip_and_reject_bad_timeframe_and_minimum():
    config = ResearchRunConfig()
    config = replace(config, execution=replace(config.execution, fvg_target_mode="HTF_OPPOSING_FVG",
                                              fvg_target_timeframe_minutes=60))
    config.validate()
    assert normalize_data_lake_config(config.to_dict()) == config
    for changes in ({"fvg_target_timeframe_minutes": 15}, {"fvg_target_timeframe_minutes": 61},
                    {"fvg_target_minimum_r": float("nan")}, {"fvg_target_mode": "UNKNOWN"}):
        with pytest.raises(ValueError):
            replace(config, execution=replace(config.execution, **changes)).validate()


def test_native_adapter_preserves_target_mode_and_nondefault_buffer():
    from crypto_strategy_lab.research_adapters import native_simulator_config
    config = ResearchRunConfig()
    execution = replace(config.execution, fvg_target_mode="HTF_OPPOSING_FVG",
                        fvg_target_timeframe_minutes=60, fvg_target_buffer_atr=.2,
                        fvg_target_minimum_r=2., fvg_target_no_level_policy="USE_FIXED_TP",
                        fvg_reject_ema100_in_tp=True)
    native = native_simulator_config(config.data, config.features, config.strategy, execution)
    assert native.fvg_target_mode == "HTF_OPPOSING_FVG"
    assert native.fvg_target_timeframe_minutes == 60
    assert native.fvg_target_buffer_atr == .2
    assert native.fvg_target_minimum_r == 2.
    assert native.fvg_target_no_level_policy == "USE_FIXED_TP"
    assert native.fvg_reject_ema100_in_tp


@pytest.mark.parametrize("side,ema,reject", [
    ("LONG", 103., True), ("LONG", 100., True), ("LONG", 106., True),
    ("LONG", 107., False), ("LONG", 99., False),
    ("SHORT", 97., True), ("SHORT", 94., True), ("SHORT", 100., True),
    ("SHORT", 93., False), ("SHORT", 101., False),
])
def test_ema100_filter_uses_actual_profit_box_not_swing_room(side, ema, reject):
    p = probe(side)
    p.ema_100_values = np.array([ema, 99999.])
    target = {"target_r": 3., "limit_price": 120. if side == "LONG" else 80.}
    passed, reason = p._fvg_ema100_tp_filter(0, 1, target, "passed")
    assert passed != reject
    assert reason == ("FVG_EMA100_INSIDE_TP_BOX" if reject else "passed")


def test_ema_filter_uses_confirmed_entry_and_rejects_missing_ema():
    p = probe()
    p.ema_100_values = np.array([100.5])
    target = {"target_r": 3.}
    assert not p._fvg_ema100_tp_filter(0, 1, target, "passed")[0]
    p._pending_fvg_confirmation_price = 101.
    assert p._fvg_ema100_tp_filter(0, 1, target, "passed")[0]
    p.ema_100_values[0] = np.nan
    assert p._fvg_ema100_tp_filter(0, 1, target, "passed")[1] == "FVG_EMA100_UNAVAILABLE"
