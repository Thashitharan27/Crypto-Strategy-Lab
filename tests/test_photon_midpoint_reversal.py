from copy import deepcopy
from dataclasses import asdict
import json

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.photon_midpoint_reversal import midpoint_reversal_setups


def scenario(short=False):
    t = 1767225600
    bars = [dict(time=t+i*60, open=o, high=h, low=l, close=c) for i,(o,h,l,c) in enumerate(
        [(100,101,93,94), (94,111,93,110), (110,111,93,94), (94,111,93,110)])]
    sign = -1 if short else 1
    if short:
        for b in bars:
            b.update(open=220-b['open'], high=220-b['low'], low=220-b['high'], close=220-b['close'])
    state = dict(availableAt=t, trend=sign,
                 range=dict(low=80, high=140, equilibrium=110, lowTime=t-28800,
                            highTime=t-14400, knownAt=t))
    changes = [dict(kind='TREND_CHANGE', direction=sign, availableAt=t+60),
               dict(kind='TREND_CHANGE', direction=sign, availableAt=t+180)]
    return bars, {'4h': dict(interval=14400, snapshots=[state]),
                  '15m': dict(interval=900, events=changes)}


@pytest.mark.parametrize('short', [False, True])
def test_each_fresh_change_can_enter_same_range_and_prefix_invariance(short):
    bars, guides = scenario(short)
    signals, live = midpoint_reversal_setups(bars, guides)
    assert live == [0, None, 2, None]
    for i in (0, 2):
        assert signals[i]['stop'] == (140 if short else 80)
        assert signals[i]['target'] == 110
        assert signals[i]['entry'] == (126 if short else 94)
        assert signals[i]['plannedR'] == pytest.approx(16/14)
    for n in range(1, 5):
        assert midpoint_reversal_setups(bars[:n], guides) == (signals[:n], live[:n])


@pytest.mark.parametrize('failure', ['no_change','opposing','bos','insufficient_r','premium','unknown','stale','gap'])
def test_requires_fresh_aligned_change_valid_value_and_minimum_r(failure):
    bars, guides = scenario()
    if failure == 'no_change':
        guides['15m']['events'] = []
    elif failure in ('opposing', 'bos'):
        for event in guides['15m']['events']:
            event.update(direction=-1) if failure == 'opposing' else event.update(kind='BOS')
    elif failure in ('insufficient_r', 'premium'):
        for b in bars:
            b.update(open=100 if failure == 'insufficient_r' else 120,
                     high=121, low=99, close=100 if failure == 'insufficient_r' else 120)
    elif failure == 'unknown':
        guides['4h']['snapshots'][0]['trend'] = 0
    elif failure == 'stale':
        guides['4h']['snapshots'][0]['availableAt'] -= 14400
    else:
        # Every fresh event lies immediately after a missing minute.
        bars.insert(0, dict(time=bars[0]['time']-120, open=100, high=101, low=99, close=100))
        bars.pop(2)
    assert not any(midpoint_reversal_setups(bars, guides)[0])


def test_exact_one_r_threshold_and_frozen_range():
    bars, guides = scenario()
    bars[0].update(close=95)
    signals, _ = midpoint_reversal_setups(bars, guides)
    assert signals[0]['plannedR'] == 1
    guides['4h']['snapshots'][0]['range']['high'] = 200
    assert signals[0]['range4h']['high'] == 140


def test_config_roundtrip():
    from crypto_strategy_lab.data_lake_config import load_data_lake_config, normalize_data_lake_config
    from crypto_strategy_lab.research_adapters import native_simulator_config
    c = load_data_lake_config('config/data_lake/Photon_15m_Reversal_4H_Midpoint_1m.json')
    c = normalize_data_lake_config(asdict(c))
    assert native_simulator_config(c.data,c.features,c.strategy,c.execution).photon_midpoint_reversal


@pytest.mark.parametrize('short', [False, True])
@pytest.mark.parametrize('fill', ['normal','insufficient_r','collision','favorable_gap'])
@pytest.mark.parametrize('fixed_1r', [False, True])
def test_engine_next_minute_market_fill_and_actual_r(monkeypatch, short, fill, fixed_1r):
    from crypto_strategy_lab.config import BacktestConfig
    from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine
    from crypto_strategy_lab.strategy_profiles import StrategyProfile
    from crypto_strategy_lab.strategy_rule_model import compile_profiles, MARKET_PERMISSIONS
    from crypto_strategy_lab.photon_trend import MODE
    bars, guides = scenario(short)
    guides['15m']['events'] = guides['15m']['events'][:1]
    if fill == 'insufficient_r':
        bars[1].update(open=120 if short else 100)
    if fill == 'collision':
        bars[1].update(high=145, low=75)
    if fill == 'favorable_gap':
        bars[1].update(open=130 if short else 90, high=131 if short else 111, low=109 if short else 89)
    pad = [dict(time=bars[0]['time']-(150-i)*60, open=110, high=111, low=109, close=110) for i in range(150)]
    monkeypatch.setattr('crypto_strategy_lab.photon_midpoint_reversal.prepare_midpoint_context', lambda bars: guides)
    profiles, _ = compile_profiles(direction_mode=MODE, market_permissions=MARKET_PERMISSIONS)
    native = {k: StrategyProfile(**asdict(p)) for k,p in profiles.items()}
    config = BacktestConfig(strategy_timeframe_minutes=1, strategy_profiles=native,
        photon_midpoint_reversal=True, photon_midpoint_fixed_1r=fixed_1r, photon_quarter_range=True, photon_zone_reversal=True,
        photon_fixed_target_enabled=True, photon_exit_on_15m_change=True,
        photon_hold_tp_until_15m_reversal=True,
        use_intrabar_data=False, enable_support_resistance_analysis=False,
        market_regime_method='ASSET_RETURN', enable_trade_telemetry=False)
    frame = pd.DataFrame(pad+bars).rename(columns={'time':'timestamp'})
    frame['timestamp'] = pd.to_datetime(frame.timestamp, unit='s', utc=True)
    frame['volume'] = 1.
    engine = RuleAwareDataLakeProductionBacktestEngine(frame, config)
    engine.market_regime_values[:] = 'SIDEWAYS'
    trades = engine.run()
    if fill == 'insufficient_r':
        assert trades.empty
        return
    assert len(trades) == 1
    row = trades.iloc[0]
    assert pd.Timestamp(row.entry_time) == frame.timestamp.iloc[151]
    assert row[row.side.lower()+'_sl'] == (140 if short else 80)
    target=row[row.side.lower()+'_tp']
    expected=row.actual_entry_price+(-1 if short else 1)*abs(row.actual_entry_price-(140 if short else 80)) if fixed_1r else 110
    assert target == pytest.approx(expected)
    assert target >= 110 if short else target <= 110
    saved=json.loads(row.supply_demand_setup)
    assert saved['target'] == target
    assert saved['targetMode'] == ('FIXED_1R_BEFORE_MIDPOINT' if fixed_1r else '4H_MIDPOINT')
    assert row[row.side.lower()+'_final_exit_reason'] == ('SL' if fill == 'collision' else 'TP')
    assert json.loads(row.supply_demand_setup)['entryModel'] == 'MIDPOINT_15M_REVERSAL'


@pytest.mark.parametrize('short', [False, True])
def test_fixed_one_r_target_inside_midpoint_and_exact_boundary(short):
    bars, guides = scenario(short)
    setups, _ = midpoint_reversal_setups(bars, guides, fixed_1r=True)
    assert setups[0]['target'] == (112 if short else 108)
    assert setups[0]['plannedR'] == 1.
    assert setups[0]['midpointRoomR'] == pytest.approx(16/14)
    bars[0]['close'] = 125 if short else 95
    setups, _ = midpoint_reversal_setups(bars, guides, fixed_1r=True)
    assert setups[0]['target'] == 110


def test_fixed_one_r_config_roundtrip():
    from crypto_strategy_lab.data_lake_config import load_data_lake_config, normalize_data_lake_config
    from crypto_strategy_lab.research_adapters import native_simulator_config
    c = load_data_lake_config('config/data_lake/Photon_15m_Reversal_Fixed_1R_1m.json')
    c = normalize_data_lake_config(asdict(c))
    native = native_simulator_config(c.data,c.features,c.strategy,c.execution)
    assert native.photon_midpoint_reversal and native.photon_midpoint_fixed_1r
