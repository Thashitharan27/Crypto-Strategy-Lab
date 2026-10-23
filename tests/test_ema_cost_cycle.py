from dataclasses import asdict, replace

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.config import BacktestConfig
from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine
from crypto_strategy_lab.strategy_profiles import StrategyProfile
from crypto_strategy_lab.strategy_rule_model import compile_profiles, MARKET_PERMISSIONS


def engine(short=False, enabled=True, intrabar=False, fee=.001, slip=0.):
    n = 125
    times = pd.date_range("2026-01-01", periods=n, freq="15min")
    frame = pd.DataFrame(dict(timestamp=times, open=np.full(n, 100.), high=np.full(n, 101.),
                              low=np.full(n, 99.), close=np.full(n, 100.), volume=np.ones(n)))
    bars = {
        111: (100, 111, 99, 105), 112: (105, 106, 99, 105),
        113: (105, 111, 104, 110), 114: (115, 121, 111, 115),
        115: (115, 116, 109, 115), 116: (115, 121, 114, 120),
        117: (125, 126, 121, 125), 118: (125, 126, 124, 125),
    }
    for i, row in bars.items():
        frame.loc[i, ["open", "high", "low", "close"]] = row
    minute = None
    if intrabar:
        rows = [(100,111,99,105), (105,106,99,105), (105,111,104,110),
                (115,121,111,115), (115,116,109,115), (115,121,114,120)]
        rows += [(125,126,121,125)] * 9
        minute = pd.DataFrame(rows, columns=["open","high","low","close"])
        minute["timestamp"] = pd.date_range(times[111], periods=15, freq="min")
        # Supply complete execution rows for every strategy interval.
        other = []
        for i in range(n):
            if i == 111:
                continue
            for t in pd.date_range(times[i], periods=15, freq="min"):
                other.append(dict(timestamp=t, open=125., high=126., low=121., close=125.))
        minute = pd.concat([minute, pd.DataFrame(other)]).sort_values("timestamp").reset_index(drop=True)
    if short:
        for f in (frame, minute):
            if f is None:
                continue
            o,h,l,c = (f[x].copy() for x in ("open","high","low","close"))
            f["open"],f["high"],f["low"],f["close"] = 200-o,200-l,200-h,200-c
    profiles, _ = compile_profiles(direction_mode="EMA_9_20_PULLBACK", market_permissions=MARKET_PERMISSIONS)
    profiles = {k: replace(StrategyProfile(**asdict(p)), ema_cross_stop_buffer_atr=0.) for k,p in profiles.items()}
    config = BacktestConfig(strategy_profiles=profiles, ema_920_trade_plan="EMA_20_100_CROSS_SHORT" if short else "EMA_20_100_CROSS",
                            ema_cross_cost_cycle_enabled=enabled, entry_timing_mode="NEXT_CANDLE_OPEN",
                            use_intrabar_data=intrabar, enable_support_resistance_analysis=False,
                            market_regime_method="ASSET_RETURN", enable_trade_telemetry=False,
                            slippage=slip, taker_fee=fee, use_maker_entry=False, use_maker_exit=False)
    e = RuleAwareDataLakeProductionBacktestEngine(frame, config, intrabar_data=minute)
    e.market_regime_values[:] = "SIDEWAYS"
    e.ema_100_values[:] = 90.
    e.ema_20_values[:] = 89.
    e.ema_20_values[110:117] = 91.
    if short:
        e.ema_100_values[:] = 200-e.ema_100_values
        e.ema_20_values[:] = 200-e.ema_20_values
    return e


@pytest.mark.parametrize("short", [False, True])
@pytest.mark.parametrize("intrabar", [False, True])
def test_repeated_native_cycles_and_opposite_cross_exit(short, intrabar):
    e = engine(short, intrabar=intrabar)
    rows = e.run()
    assert len(rows) == 3
    positions = [p.position for p in e.completed_pairs]
    sign = -1 if short else 1
    assert [p.entry_price for p in positions] == [100., 100+sign*10, 100+sign*20]
    assert [p.original_sl for p in positions] == [100-sign*10, 100., 100+sign*10]
    assert list(rows.ema_cycle_number) == [0,1,2]
    assert list(rows.ema_cycle_parent_id.iloc[1:]) == [1,2]
    assert set(rows.ema_cycle_root_id) == {1}
    assert [p.exit_reason.value for p in positions] == ["BE", "BE", "EMA_20_100_CROSS"]
    assert positions[0].net_pnl == pytest.approx(0, abs=1e-9)
    assert positions[1].net_pnl == pytest.approx(0, abs=1e-9)
    assert positions[0].tp1_quantity / positions[0].original_quantity < 1
    assert positions[1].tp1_quantity / positions[1].original_quantity != positions[0].tp1_quantity / positions[0].original_quantity
    assert all(p.exit_time >= pd.Timestamp(p.entry_time).tz_localize("UTC") for p in positions)
    assert e.current_equity == pytest.approx(e.config.initial_equity + sum(p.net_pnl for p in positions))


def test_disabled_preserves_original_runner_without_partial_or_reentry():
    e = engine(enabled=False)
    rows = e.run()
    assert len(rows) == 1
    assert not e.completed_pairs[0].position.tp1_hit
    assert rows.iloc[0].ema_cost_cycle_enabled == False


def test_bearish_alignment_cancels_armed_reentry():
    e = engine()
    e.ema_20_values[112:] = 89.
    rows = e.run()
    assert len(rows) == 1
    assert e._ema_cycle_pending is None


@pytest.mark.parametrize("short", [False, True])
def test_slippage_cost_cover_nets_zero_on_normal_be_exit(short):
    e = engine(short, slip=.001)
    e.run()
    first = e.completed_pairs[0].position
    assert first.tp1_hit
    assert first.net_pnl == pytest.approx(0, abs=1e-9)
    assert first.exit_price != first.entry_price


def test_original_stop_wins_ambiguous_first_target_bar():
    e = engine()
    e.low[111] = 89.
    e.run()
    assert len(e.completed_pairs) == 1
    assert e.completed_pairs[0].position.exit_reason.value == "SL"
    assert not e.completed_pairs[0].position.tp1_hit


def test_insufficient_profit_does_not_move_stop_or_close_entire_position():
    e = engine(fee=.1)
    e.ema_20_values[111:] = 89.
    e.run()
    pos = e.completed_pairs[0].position
    assert pos.ema_cycle_cost_cover_rejected
    assert not pos.tp1_hit
    assert not pos.be_triggered


def test_reentry_gap_uses_actual_fill_and_previous_entry_stop():
    e = engine()
    e.open[113] = 115.
    e.high[113] = 116.
    e.low[113] = 114.
    e.ema_20_values[113:] = 89.
    e.run()
    pos = e.completed_pairs[1].position
    assert pos.entry_price == 115.
    assert pos.original_sl == 100.
    assert pos.ema_cycle_trigger == 130.


def test_future_bearish_cross_cannot_cancel_earlier_reentry():
    e = engine()
    # The execution candle EMA is unknown until its close; 113 still enters.
    e.ema_20_values[113:] = 89.
    e.run()
    assert e.completed_pairs[1].position.entry_time == pd.Timestamp(e.times[113])
    assert e.completed_pairs[1].position.exit_time == pd.Timestamp(e.times[114]).tz_localize("UTC")


def test_cost_cycle_gui_and_native_config_roundtrip():
    from crypto_strategy_lab.gui.config_logic import default_gui_config, build_backtest_config
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig
    from crypto_strategy_lab.research_adapters import native_simulator_config
    values = default_gui_config()
    assert not values["ema_cross_cost_cycle_enabled"]
    values["ema_cross_cost_cycle_enabled"] = True
    assert build_backtest_config(values, require_paths=False).ema_cross_cost_cycle_enabled
    c = ResearchRunConfig()
    c = replace(c, execution=replace(c.execution, ema_cross_cost_cycle_enabled=True))
    assert native_simulator_config(c.data,c.features,c.strategy,c.execution).ema_cross_cost_cycle_enabled


def test_array_backed_intrabar_path_preserves_same_interval_cycles():
    from crypto_strategy_lab.prepared_backtest import IntrabarExecutionData
    e = engine(intrabar=True)
    f = e.intrabar_data
    e.intrabar_data = IntrabarExecutionData(
        f.timestamp.to_numpy(), pd.Timedelta(minutes=1),
        f.open.to_numpy(), f.high.to_numpy(), f.low.to_numpy(), f.close.to_numpy())
    rows = e.run()
    assert list(rows.ema_cycle_number) == [0,1,2]
    assert rows.iloc[0].partial_tp_enabled
    assert rows.iloc[0].tp1_close_pct > 0


def test_missing_intrabar_error_is_respected():
    from crypto_strategy_lab.config import IntrabarMissingPolicy
    e = engine(intrabar=True)
    e.intrabar_data = e.intrabar_data.drop(index=111*15+2)
    e.config = replace(e.config, intrabar_missing_policy=IntrabarMissingPolicy.ERROR)
    with pytest.raises(ValueError, match="Missing intrabar"):
        e.run()


def test_zero_costs_move_stop_without_partial_quantity():
    e = engine(fee=0.)
    e.run()
    p = e.completed_pairs[0].position
    assert p.be_triggered and p.tp1_hit
    assert p.tp1_quantity == 0.
    assert p.net_pnl == 0.


def test_direction_neutral_report_config_does_not_activate_ema_cycles():
    from crypto_strategy_lab.bayesian_sampling import _research_native_config
    e = engine()
    # Reproduce Deep Research's report-time transformation: selection markers
    # are removed and independent observations may overlap.
    report_config = _research_native_config(e.config, 100)
    assert report_config.max_active_pairs == 202
    assert report_config.ema_cross_cost_cycle_enabled
    assert all(not p.entry_rules for p in report_config.strategy_profiles.values())
    # The real EMA portfolio still retains the single-active-trade constraint.
    with pytest.raises(ValueError, match="one active trade"):
        replace(e.config, max_active_pairs=202)


def test_optional_strategy_sampling_retains_portfolio_artifacts_for_cycles(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from crypto_strategy_lab import research_sampling_reporting as report
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig
    c = ResearchRunConfig()
    c = replace(c, reporting=replace(c.reporting, research_sampling_mode="EVERY_VIABLE_ENTRY"))
    native = engine().config
    monkeypatch.setattr(report, "native_simulator_config", lambda *a, **kw: native)
    def unexpected(*a, **kw):
        raise AssertionError("Chain execution must not enter independent observation sampling")
    monkeypatch.setattr(report, "generate_strategy_research_samples", unexpected)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"artifacts": {"trades": "retained"}, "research": {"existing": True}}))
    events = []
    context = SimpleNamespace(config=c, progress_callback=events.append)
    result = SimpleNamespace(output_dir=tmp_path, request=SimpleNamespace(start=None, end=None))
    report.append_research_sampling_artifacts(result, context)
    saved = json.loads(manifest.read_text())
    assert saved["artifacts"]["trades"] == "retained"
    assert saved["research"]["existing"]
    status = saved["research"]["strategy_research_sampling"]
    assert status["enabled"] is False
    assert status["requested_mode"] == "EVERY_VIABLE_ENTRY"
    assert status["status"] == "UNAVAILABLE_FOR_EMA_COST_CYCLES"
    assert "sequential portfolio" in status["reason"]
    assert "Portfolio reports retained" == events[0]["label"]
