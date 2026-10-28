from copy import deepcopy
from dataclasses import asdict, replace
import json

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.photon_quarter_range import quarter_range_setups


def scenario(short=False):
    t = 1767225600
    bars = [dict(time=t+i*60, open=o, high=h, low=l, close=c) for i,(o,h,l,c) in enumerate(
        [(120,122,115,120), (120,121,94,100), (100,145,99,140), (140,141,139,140)])]
    if short:
        for b in bars:
            b.update(open=220-b['open'], high=220-b['low'], low=220-b['high'], close=220-b['close'])
    state = dict(availableAt=t, trend=-1 if short else 1,
                 range=dict(low=80, high=140, equilibrium=110, lowTime=t-28800,
                            highTime=t-14400, knownAt=t))
    return bars, {'4h': dict(interval=14400, snapshots=[state])}


@pytest.mark.parametrize('short', [False, True])
def test_quarter_geometry_and_prefix_invariance(short):
    bars, guides = scenario(short)
    signals, live = quarter_range_setups(bars, np.ones(4), guides)
    setup = signals[0]
    assert setup['entry'] == (125 if short else 95)
    assert setup['stop'] == (140.05 if short else 79.95)
    assert setup['target'] == (80 if short else 140)
    assert live == [0, None, None, None]
    assert sum(s is not None for s in signals) == 1
    for n in range(1, 5):
        assert quarter_range_setups(bars[:n], np.ones(n), guides) == (signals[:n], live[:n])


@pytest.mark.parametrize('change', ['range', 'trend', 'stale', 'gap'])
def test_cancel_unfilled_orders(change):
    bars, guides = scenario()
    for b in bars:
        b.update(open=120, high=121, low=119, close=120)
    if change in ('range', 'trend'):
        state = deepcopy(guides['4h']['snapshots'][0])
        state['availableAt'] = bars[1]['time']+60
        if change == 'range':
            state['range']['high'] = 150
        else:
            state['trend'] = 0
        guides['4h']['snapshots'].append(state)
    elif change == 'stale':
        guides['4h']['snapshots'][0]['availableAt'] = bars[0]['time']-14400+120
    else:
        for b in bars[1:]:
            b['time'] += 60
    signals, live = quarter_range_setups(bars, np.ones(4), guides)
    assert signals[0]
    assert live[1] != 0


def test_config_roundtrip():
    from crypto_strategy_lab.data_lake_config import load_data_lake_config, normalize_data_lake_config
    from crypto_strategy_lab.research_adapters import native_simulator_config
    config = load_data_lake_config('config/data_lake/Photon_4H_Quarter_Range_1m.json')
    config = normalize_data_lake_config(asdict(config))
    assert native_simulator_config(config.data, config.features, config.strategy, config.execution).photon_quarter_range


@pytest.mark.parametrize('short', [False, True])
@pytest.mark.parametrize('collision', [False, True])
def test_engine_touch_stop_target_and_old_options_ignored(monkeypatch, short, collision):
    from crypto_strategy_lab.config import BacktestConfig
    from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine
    from crypto_strategy_lab.strategy_profiles import StrategyProfile
    from crypto_strategy_lab.strategy_rule_model import compile_profiles, MARKET_PERMISSIONS
    from crypto_strategy_lab.photon_trend import MODE
    bars, guides = scenario(short)
    if collision:
        bars[1].update(high=145, low=75)
    pad = [dict(time=bars[0]['time']-(150-i)*60, open=110, high=111, low=109, close=110) for i in range(150)]
    monkeypatch.setattr('crypto_strategy_lab.photon_quarter_range.prepare_quarter_context', lambda bars: guides)
    profiles, _ = compile_profiles(direction_mode=MODE, market_permissions=MARKET_PERMISSIONS)
    native = {k: StrategyProfile(**asdict(p)) for k,p in profiles.items()}
    config = BacktestConfig(strategy_timeframe_minutes=1, strategy_profiles=native,
        photon_quarter_range=True, photon_zone_reversal=True, photon_fixed_target_enabled=True,
        photon_exit_on_15m_change=True, photon_hold_tp_until_15m_reversal=True,
        use_intrabar_data=False, enable_support_resistance_analysis=False,
        market_regime_method='ASSET_RETURN', enable_trade_telemetry=False)
    frame = pd.DataFrame(pad+bars).rename(columns={'time':'timestamp'})
    frame['timestamp'] = pd.to_datetime(frame.timestamp, unit='s', utc=True)
    frame['volume'] = 1.
    engine = RuleAwareDataLakeProductionBacktestEngine(frame, config)
    engine.market_regime_values[:] = 'SIDEWAYS'
    trades = engine.run()
    assert len(trades) == 1
    row = trades.iloc[0]
    setup = json.loads(row.supply_demand_setup)
    assert setup['entryModel'] == 'QUARTER_RANGE'
    assert pd.Timestamp(row.entry_time) == frame.timestamp.iloc[151]
    assert row[row.side.lower()+'_tp'] == (80 if short else 140)
    assert row[row.side.lower()+'_final_exit_reason'] == ('SL' if collision else 'TP')
    if collision:
        assert pd.Timestamp(row.exit_time) == pd.Timestamp(row.entry_time)
