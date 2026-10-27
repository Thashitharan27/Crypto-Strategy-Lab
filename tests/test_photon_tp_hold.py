from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from test_photon_zone_reversal import scenario
from crypto_strategy_lab.photon_trend import MODE, PhotonTrendMixin


@pytest.mark.parametrize('short', [False, True])
@pytest.mark.parametrize('case', ['hold', 'disabled', 'opposing_at_tp', 'unknown_at_tp',
    'stop_after_tp', 'stop_on_reversal', 'stop_collision', 'reversal_before_tp', 'early_exit', 'end_of_data',
    'entry_bar_target', 'gap_after_tp', 'prepared', 'legacy', 'legacy_entry_target'])
def test_tp_hold_preserves_stops_and_uses_confirmed_trend(monkeypatch, short, case):
    from crypto_strategy_lab.config import BacktestConfig
    from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine
    from crypto_strategy_lab.strategy_profiles import StrategyProfile
    from crypto_strategy_lab.strategy_rule_model import compile_profiles, MARKET_PERMISSIONS
    bars, guides = scenario(short, nested=False)
    t = bars[0]['time']
    sign = -1 if short else 1
    # Mirror all changes so LONG and SHORT exercise the same price path.
    def bar(i, o, h, l, c):
        bars[i].update(open=220-o if short else o, high=220-l if short else h,
                       low=220-h if short else l, close=220-c if short else c)
    bar(8, 103, 112, 100, 108)
    reversal = deepcopy(guides['15m']['snapshots'][-1])
    reversal.update(availableAt=t+600, trend=-sign, internal=-sign)
    if case == 'opposing_at_tp': reversal['availableAt'] = t+480
    if case == 'unknown_at_tp': reversal.update(availableAt=t+480, trend=0, internal=0)
    if case in ('reversal_before_tp', 'early_exit'): reversal['availableAt'] = t+480; bar(8,103,105,100,104)
    if case not in ('end_of_data', 'unknown_at_tp'):
        guides['15m']['snapshots'].append(reversal)
        guides['15m']['events'].append(dict(availableAt=reversal['availableAt'], kind='TREND_CHANGE', direction=-sign))
    elif case == 'unknown_at_tp':
        guides['15m']['snapshots'].append(reversal)
    if case == 'stop_after_tp': bar(9,94,95,93,94)
    if case == 'stop_on_reversal': bar(10,94,95,93,94)
    if case == 'stop_collision': bar(8,103,112,93,104)
    if case == 'entry_bar_target': bar(7,103,112,99,104); bar(8,103,105,100,104)
    if case == 'gap_after_tp': bar(10,115,116,114,115)
    if case == 'legacy_entry_target': bar(3,104,112,98,108)
    pad = [dict(time=t-(150-i)*60,open=110,high=111,low=109,close=110) for i in range(150)]
    monkeypatch.setattr('crypto_strategy_lab.photon_trend.prepare_context', lambda *a, **kw: deepcopy(guides))
    profiles, _ = compile_profiles(direction_mode=MODE, market_permissions=MARKET_PERMISSIONS)
    native = {k: StrategyProfile(**asdict(p)) for k,p in profiles.items()}
    config = BacktestConfig(strategy_timeframe_minutes=1, telemetry_interval_minutes=1,
        strategy_profiles=native, use_intrabar_data=False,
        enable_support_resistance_analysis=False, enable_trade_telemetry=False,
        photon_zone_reversal=True, photon_hold_tp_until_15m_reversal=case!='disabled',
        photon_exit_on_15m_change=case=='early_exit', photon_legacy_entry_and_stop=case in ('legacy','legacy_entry_target'),
        sd_minimum_r=.1 if case in ('legacy','legacy_entry_target') else 1.2)
    frame = pd.DataFrame(pad+bars).rename(columns={'time':'timestamp'})
    frame['timestamp'] = pd.to_datetime(frame.timestamp, unit='s', utc=True)
    frame['volume'] = 1.
    if case == 'prepared':
        from test_prepared_backtest import valid_kwargs
        from crypto_strategy_lab.prepared_backtest import PreparedBacktestFrame
        kwargs=valid_kwargs(len(frame)); times=frame.timestamp.to_numpy(dtype='datetime64[ns]')
        kwargs.update(timestamp=times, strategy_interval=pd.Timedelta(minutes=1),
            decision_available_at=times+np.timedelta64(1,'m'), atr=np.ones(len(frame)))
        kwargs.update({key:frame[key].to_numpy(float) for key in ('open','high','low','close','volume')})
        config=replace(config,trading_start_date=frame.timestamp.iloc[0].tz_localize(None).isoformat())
        engine=RuleAwareDataLakeProductionBacktestEngine.from_prepared(PreparedBacktestFrame(**kwargs),None,config)
    else:
        engine=RuleAwareDataLakeProductionBacktestEngine(frame, config)
        engine.market_regime_values[:] = 'SIDEWAYS'
    trades=engine.run()
    assert len(trades)==1
    row=trades.iloc[0]; reason=row[row.side.lower()+'_final_exit_reason']
    expected = 'TP' if case in ('disabled','opposing_at_tp','unknown_at_tp') else 'SL' if case in ('stop_after_tp','stop_on_reversal','stop_collision') else 'END_OF_DATA' if case in ('end_of_data','entry_bar_target','reversal_before_tp') else 'PHOTON_15M_TREND_CHANGE'
    assert reason==expected
    held = case not in ('disabled','opposing_at_tp','unknown_at_tp','stop_collision','early_exit','entry_bar_target','reversal_before_tp')
    assert bool(row.photon_tp_hold_activated)==held
    assert row[row.side.lower()+'_tp']==110  # the saved target never becomes infinity
    if reason=='PHOTON_15M_TREND_CHANGE':
        index=158 if case=='early_exit' else 160
        assert pd.to_datetime(row.exit_time,utc=True)==frame.timestamp.iloc[index]
        opening=frame.open.iloc[index]
        assert row[row.side.lower()+'_exit_price']==pytest.approx(opening*(1+config.slippage if short else 1-config.slippage))
    if held:
        assert pd.to_datetime(row.photon_tp_first_hit_time,utc=True)==frame.timestamp.iloc[153 if case=='legacy_entry_target' else 158]
    if case == 'stop_on_reversal':
        assert row[row.side.lower()+'_exit_price']==pytest.approx(frame.open.iloc[160]*(1+config.slippage if short else 1-config.slippage))


def test_trend_lookup_does_not_use_future_or_stale_snapshots():
    obj=SimpleNamespace(photon_15m_snapshot_times=[900,1800],
        photon_15m_snapshots=[{'trend':1},{'trend':-1}])
    trend=lambda at: PhotonTrendMixin._photon_15m_trend(obj,at)
    assert [trend(t) for t in (899,900,1799,1800,2699,2700)]==[0,1,1,-1,-1,0]


def test_tp_hold_option_json_native_roundtrip():
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig, normalize_data_lake_config
    from crypto_strategy_lab.research_adapters import native_simulator_config
    config=ResearchRunConfig()
    config=replace(config, execution=replace(config.execution, photon_hold_tp_until_15m_reversal=True))
    config=normalize_data_lake_config(asdict(config))
    native=native_simulator_config(config.data,config.features,config.strategy,config.execution)
    assert native.photon_hold_tp_until_15m_reversal
