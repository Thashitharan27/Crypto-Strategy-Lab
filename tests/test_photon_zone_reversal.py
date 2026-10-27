from copy import deepcopy
from dataclasses import asdict, replace
import json

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.photon_zone_reversal import zone_reversal_setups


def scenario(short=False, context_tf='4h', nested=True):
    t = 1767225600
    rows = [(102,104,101,103),(100,102,95,97),(98,108,97,107),
            (104,105,98,99),(99,100,97,98),(98,104,98,103),
            (103,106,101,104),(103,104,99,101),(101,105,100,104),
            (104,106,102,105),(105,107,103,106)]
    bars = [dict(time=t+i*60,open=o,high=h,low=l,close=c) for i,(o,h,l,c) in enumerate(rows)]
    sign = -1 if short else 1
    if short:
        for b in bars:
            b.update(open=220-b['open'],high=220-b['low'],low=220-b['high'],close=220-b['close'])
    def state(at, trend):
        return dict(availableAt=at,trend=trend,internal=trend,low=dict(time=t-1000,price=80),
                    high=dict(time=t-500,price=140),range=dict(low=80,high=140,equilibrium=110,knownAt=t))
    guides = {tf:dict(interval=sec,events=[],snapshots=[state(t,-sign)])
              for tf,sec in [('1m',60),('15m',900),('4h',14400),('1d',86400),('1w',604800)]}
    guides['1m']['snapshots'] = [state(b['time']+60,-sign if i in (3,4) else sign) for i,b in enumerate(bars)]
    guides['1m']['events'] = [dict(availableAt=t+360,kind='CHOCH',direction=sign)]
    aligned=state(t+180,sign)
    aligned['range']=dict(low=110 if short else 94,high=126 if short else 110,equilibrium=118 if short else 102,knownAt=t+180)
    guides['15m']['snapshots'].append(aligned)
    guides['15m']['events'] = [dict(availableAt=t+180,kind='TREND_CHANGE',direction=sign)]
    kind = 'SUPPLY' if short else 'DEMAND'
    z = dict(id='context',timeframe=context_tf,kind=kind,availableAt=t+60,originTime=t-100,
             lower=115 if short else 90,upper=130 if short else 105)
    guides[context_tf]['supplyDemand'] = dict(zones=[z],events=[])
    if nested:
        guides['15m']['supplyDemand'] = dict(zones=[dict(id='nested',timeframe='15m',kind=kind,
            availableAt=t+60,originTime=t-60,lower=122 if short else 94,upper=126 if short else 98)],events=[])
    return bars,guides


@pytest.mark.parametrize('short',[False,True])
@pytest.mark.parametrize('tf',['4h','1d'])
@pytest.mark.parametrize('nested',[False,True])
def test_reversal_pullback_sequence_and_frozen_midpoint(short,tf,nested):
    bars,guides = scenario(short,tf,nested)
    signals,live = zone_reversal_setups(bars,np.ones(len(bars)),guides)
    assert [i for i,s in enumerate(signals) if s] == [5]
    s = signals[5]
    assert s['side'] == ('SHORT' if short else 'LONG')
    assert s['stopSource'] == ('15M_ZONE' if nested else 'TOUCH_EXTREME')
    assert s['stop'] == pytest.approx((126.05 if nested else 125.05) if short else (93.95 if nested else 94.95))
    assert s['target'] == 110 and s['targetMode'] == '4H_MIDPOINT'
    assert s['contextTouchAt'] < s['alignmentAt'] < s['pullbackAt'] < s['signalAvailableAt']
    assert s['narrative']['4h']['trend'] == (1 if short else -1)  # 4H swing is not an entry gate.
    for end in range(1,len(bars)+1):
        assert zone_reversal_setups(bars[:end],np.ones(end),guides) == (signals[:end],live[:end])
    assert s['entry']==(120 if short else 100)
    assert live[5]==5 and live[6]==5 and live[7] is None
    guides['4h']['snapshots'][0]['range']['equilibrium'] = 999
    assert s['target'] == 110 and s['range4h']['equilibrium'] == 110


@pytest.mark.parametrize('missing',['htf','fresh_change','choch_only','bos_only','minute','value','minimum_r','expired','invalidated','gap','created_on_touch','unreversed'])
def test_rejects_incomplete_or_unknown_sequence(missing):
    bars,guides = scenario();t=bars[0]['time'];kwargs={}
    if missing=='htf':guides['4h']['supplyDemand']['zones']=[]
    if missing=='fresh_change':guides['15m']['events']=[]
    if missing in ('choch_only','bos_only'):guides['15m']['events'][0]['kind']='CHOCH' if missing=='choch_only' else 'BOS'
    if missing=='minute':
        for s in guides['1m']['snapshots']:s['internal']=-1
    if missing=='value':guides['4h']['snapshots'][0]['range']['equilibrium']=90
    if missing=='minimum_r':kwargs['minimum_r']=100
    if missing=='expired':kwargs['confirmation_minutes']=1;guides['15m']['events'][0]['availableAt']=t+300
    if missing=='invalidated':guides['4h']['supplyDemand']['events']=[dict(zoneId='context',kind='INVALIDATED',availableAt=t+180)]
    if missing=='gap':bars[2]['time']+=1
    if missing=='created_on_touch':guides['4h']['supplyDemand']['zones'][0]['availableAt']=t+10000
    if missing=='unreversed':
        for b in bars[2:]:b.update(open=96,high=98,low=95,close=96)
    assert not any(zone_reversal_setups(bars,np.ones(len(bars)),guides,**kwargs)[0])


def test_fresh_minute_change_and_both_pullbacks_are_required():
    for missing in ('15m_pullback', 'fresh_1m_change', '1m_bos', 'origin'):
        bars,guides=scenario()
        if missing=='15m_pullback':
            for state in guides['1m']['snapshots']:state['internal']=1
        if missing=='fresh_1m_change':guides['1m']['events']=[]
        if missing=='1m_bos':guides['1m']['events'][0]['kind']='BOS'
        if missing=='origin':
            for bar in bars[3:5]:bar['open']=bar['close']
        assert not any(zone_reversal_setups(bars,np.ones(len(bars)),guides)[0])


def test_unfilled_retest_expires_and_future_zone_does_not_set_stop():
    bars,guides=scenario()
    guides['15m']['supplyDemand']['zones'][0]['availableAt']=bars[-1]['time']+600
    signals,live=zone_reversal_setups(bars,np.ones(len(bars)),guides,retest_minutes=1)
    assert signals[5]['stopSource']=='TOUCH_EXTREME'
    assert live[5]==5 and live[6] is None


@pytest.mark.parametrize('short',[False,True])
@pytest.mark.parametrize('case',['normal','minimum_r','stop_gap','target_gap','exit_on','exit_off','stop_collision','prepared','entry_tp','entry_collision'])
def test_engine_pullback_entry_and_optional_confirmed_trend_exit(monkeypatch,short,case):
    from crypto_strategy_lab.config import BacktestConfig
    from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine
    from crypto_strategy_lab.strategy_profiles import StrategyProfile
    from crypto_strategy_lab.strategy_rule_model import compile_profiles,MARKET_PERMISSIONS
    from crypto_strategy_lab.photon_trend import MODE
    bars,guides=scenario(short,nested=False);t=bars[0]['time'];sign=-1 if short else 1
    if case in ('exit_on','exit_off','stop_collision','intrabar'):
        guides['15m']['events'].append(dict(availableAt=t+540,kind='TREND_CHANGE',direction=-sign))
    if case=='stop_gap':bars[7].update(open=126 if short else 94,high=128 if short else 95,low=125 if short else 93,close=126 if short else 94)
    if case=='target_gap':bars[7].update(open=109 if short else 111,high=110 if short else 112,low=108 if short else 110,close=109 if short else 111)
    if case in ('entry_tp','entry_collision'):
        bars[7]['low' if short else 'high']=109 if short else 111
        if case=='entry_collision':bars[7]['high' if short else 'low']=126 if short else 94
    if case=='stop_collision':bars[9].update(open=126 if short else 94,high=128 if short else 95,low=125 if short else 93,close=126 if short else 94)
    pad=[dict(time=t-(150-i)*60,open=110,high=111,low=109,close=110) for i in range(150)]
    monkeypatch.setattr('crypto_strategy_lab.photon_trend.prepare_context',lambda *a,**kw:deepcopy(guides))
    profiles,_=compile_profiles(direction_mode=MODE,market_permissions=MARKET_PERMISSIONS)
    native={k:StrategyProfile(**asdict(p)) for k,p in profiles.items()}
    config=BacktestConfig(strategy_timeframe_minutes=1,telemetry_interval_minutes=1,strategy_profiles=native,
        use_intrabar_data=False,enable_support_resistance_analysis=False,market_regime_method='ASSET_RETURN',
        enable_trade_telemetry=False,photon_zone_reversal=True,photon_exit_on_15m_change=case in ('exit_on','stop_collision','intrabar'),
        sd_minimum_r=100 if case=='minimum_r' else 1.2)
    frame=pd.DataFrame(pad+bars).rename(columns={'time':'timestamp'});frame['timestamp']=pd.to_datetime(frame.timestamp,unit='s',utc=True);frame['volume']=1.
    if case=='prepared':
        from test_prepared_backtest import valid_kwargs
        from crypto_strategy_lab.prepared_backtest import PreparedBacktestFrame
        kwargs=valid_kwargs(len(frame));times=frame.timestamp.to_numpy(dtype='datetime64[ns]')
        kwargs.update(timestamp=times,strategy_interval=pd.Timedelta(minutes=1),decision_available_at=times+np.timedelta64(1,'m'),atr=np.ones(len(frame)))
        kwargs.update({key:frame[key].to_numpy(float) for key in ('open','high','low','close','volume')})
        config=replace(config,trading_start_date=frame.timestamp.iloc[0].tz_localize(None).isoformat())
        engine=RuleAwareDataLakeProductionBacktestEngine.from_prepared(PreparedBacktestFrame(**kwargs),None,config)
    else:
        engine=RuleAwareDataLakeProductionBacktestEngine(frame,config,frame if case=='intrabar' else None)
        engine.market_regime_values[:]='SIDEWAYS'
    trades=engine.run()
    if case in ('minimum_r','stop_gap','target_gap'):
        assert len(trades)==0
        return
    assert len(trades)==1
    row=trades.iloc[0];s=json.loads(row.supply_demand_setup)
    from types import SimpleNamespace
    from crypto_strategy_lab.strategy_visualizer import CompletedRunVisualizer
    evidence=CompletedRunVisualizer.supply_demand_derivation(SimpleNamespace(trade_count=1,_trade_row=lambda i:row.to_dict()),0)
    assert evidence['status']=='AVAILABLE' and evidence['entryModel']=='HTF_ZONE_PULLBACK'
    assert len(evidence['review']['checks'])==8
    assert pd.to_datetime(row.entry_time,utc=True)==frame.timestamp.iloc[157]
    assert row.actual_entry_price==pytest.approx((120 if short else 100)*(1-config.slippage if short else 1+config.slippage))
    assert row[row.side.lower()+'_tp']==110
    assert row[row.side.lower()+'_sl']==pytest.approx(s['stop'])
    if case in ('exit_on','stop_collision','intrabar'):
        assert pd.to_datetime(row.exit_time,utc=True)==frame.timestamp.iloc[159]
        assert row[row.side.lower()+'_final_exit_reason']==('SL' if case=='stop_collision' else 'PHOTON_15M_TREND_CHANGE')
    if case=='entry_collision':
        assert pd.to_datetime(row.exit_time,utc=True)==frame.timestamp.iloc[157]
        assert row[row.side.lower()+'_final_exit_reason']=='SL'
    if case=='entry_tp':assert pd.to_datetime(row.exit_time,utc=True)>frame.timestamp.iloc[157]
    if case=='exit_off':assert row[row.side.lower()+'_final_exit_reason']=='END_OF_DATA'


def test_new_preset_roundtrip_and_old_default_unchanged():
    from crypto_strategy_lab.data_lake_config import load_data_lake_config,ResearchRunConfig
    from crypto_strategy_lab.research_adapters import native_simulator_config
    c=load_data_lake_config('config/data_lake/Photon_Zone_Reversal_1m.json')
    native=native_simulator_config(c.data,c.features,c.strategy,c.execution)
    assert native.photon_zone_reversal and not native.photon_exit_on_15m_change
    assert native.sd_minimum_r==2
    assert not ResearchRunConfig().execution.photon_zone_reversal


@pytest.mark.parametrize('short', [False, True])
def test_original_option_uses_existing_swing_alignment_and_original_stop(short):
    bars, guides = scenario(short)
    t = bars[0]['time']
    # A fresh reversal zone outside the original context must not replace the
    # original nested-zone stop, even though current stops prefer it.
    guides['15m']['supplyDemand']['zones'].append(dict(
        id='fresh', timeframe='15m', kind='SUPPLY' if short else 'DEMAND',
        availableAt=t+180, originTime=t+120,
        lower=111 if short else 106, upper=114 if short else 109))
    signals, live = zone_reversal_setups(bars, np.ones(len(bars)), guides,
                                       minimum_r=.1, legacy_entry_and_stop=True)
    assert [i for i, s in enumerate(signals) if s] == [2]
    s = signals[2]
    assert s['entryModel'] == 'HTF_ZONE_REVERSAL'
    assert s.get('entryExecution') != 'LIMIT_RETEST'
    assert s['entry'] == bars[2]['close']
    assert s['parentZone']['id'] == 'nested'
    assert s['stop'] == pytest.approx(126.05 if short else 93.95)
    assert live[2] == 2 and live[3] is None
    for end in range(1, len(bars)+1):
        assert zone_reversal_setups(bars[:end], np.ones(end), guides,
            minimum_r=.1, legacy_entry_and_stop=True) == (signals[:end], live[:end])


def test_original_preset_survives_json_and_native_config_roundtrip():
    from crypto_strategy_lab.data_lake_config import load_data_lake_config, ResearchRunConfig, normalize_data_lake_config
    from crypto_strategy_lab.research_adapters import native_simulator_config
    original = load_data_lake_config('config/data_lake/Photon_Original_Entry_SL_68c5fa4f.json')
    original = normalize_data_lake_config(json.loads(json.dumps(asdict(original))))
    native = native_simulator_config(original.data, original.features, original.strategy, original.execution)
    assert native.photon_legacy_entry_and_stop and native.photon_zone_reversal
    assert not ResearchRunConfig().execution.photon_legacy_entry_and_stop


def test_real_context_retains_minute_swings_and_daily_zones_without_future_bars():
    from crypto_strategy_lab.photon_trend import prepare_context
    t=1767225600
    bars=[]
    for i in range(3000):
        price=100+5*np.sin(i/50)+i/1000
        bars.append(dict(time=t+i*60,open=price,high=price+1,low=price-1,close=price+.1))
    full=prepare_context(bars,zone_reversal=True)
    prefix=prepare_context(bars[:2400],zone_reversal=True)
    assert len(full['1m']['snapshots'])==len(bars)
    assert 'supplyDemand' in full['1d']
    cutoff=bars[2399]['time']+60
    for tf in full:
        assert [s for s in full[tf]['snapshots'] if s['availableAt']<=cutoff]==prefix[tf]['snapshots']
        assert [e for e in full[tf]['events'] if e['availableAt']<=cutoff]==prefix[tf]['events']

def test_automated_review_explains_actual_model_without_future_checks():
    import shutil,subprocess
    from crypto_strategy_lab.visualizer_photon import PHOTON_HELPERS
    node=shutil.which('node')
    if not node:pytest.skip('Node required for review projection')
    bars,guides=scenario()
    s=zone_reversal_setups(bars,np.ones(len(bars)),guides)[0][5]
    s['status']='AVAILABLE';at=s['signalAvailableAt']
    script=PHOTON_HELPERS+'\nconst sd='+json.dumps(s)+f';console.log(JSON.stringify([cslPhotonReviewView(sd,{at-1}),cslPhotonReviewView(sd,{at})]));'
    before,now=json.loads(subprocess.run([node],input=script,text=True,encoding="utf-8",capture_output=True,check=True).stdout)
    assert before is None
    assert now['label']=='Automated zone reversal · entry checks'
    assert len(now['checks'])==8 and now['entryModel']=='HTF_ZONE_PULLBACK'


def test_minute_internal_change_qualifies_without_a_minute_swing_change():
    bars,guides=scenario()
    for state in guides['1m']['snapshots']:state['trend']=-1
    signals,live=zone_reversal_setups(bars,np.ones(len(bars)),guides)
    assert signals[5] and signals[5]['narrative']['1m']['trend']==-1
    assert signals[5]['narrative']['1m']['internal']==1 and live[6]==5


def test_failed_internal_attempt_can_retry_while_15m_confirmation_survives():
    bars,guides=scenario();t=bars[0]['time']
    # First limit remains untouched; internal direction turns down at 22:45-equivalent.
    bars[7].update(open=104,high=105,low=101,close=102)
    guides['1m']['snapshots'][6]['internal']=-1
    guides['1m']['snapshots'][7]['internal']=-1
    bars[7].update(open=100,high=101,low=98,close=99)
    guides['1m']['events'].append(dict(availableAt=t+540,kind='CHOCH',direction=1))
    signals,live=zone_reversal_setups(bars,np.ones(len(bars)),guides,minimum_r=.5)
    assert signals[5] and live[6] is None
    assert signals[8] and signals[8]['alignmentAt']==signals[5]['alignmentAt']
    assert signals[8]['pullbackAt']>signals[5]['signalAvailableAt']

@pytest.mark.parametrize('reason',['context','stop_zone','15m_direction','1m_internal','expiry','gap'])
def test_pending_limit_cancels_before_a_later_retest(reason):
    bars,guides=scenario();t=bars[0]['time'];kwargs={}
    if reason in ('context','stop_zone'):
        tf='4h' if reason=='context' else '15m'
        guides[tf]['supplyDemand']['events']=[dict(zoneId='context' if reason=='context' else 'nested',kind='INVALIDATED',availableAt=t+420)]
    if reason=='15m_direction':
        changed=deepcopy(guides['15m']['snapshots'][-1]);changed.update(availableAt=t+420,trend=-1)
        guides['15m']['snapshots'].append(changed)
    if reason=='1m_internal':guides['1m']['snapshots'][6]['internal']=-1
    if reason=='expiry':kwargs['retest_minutes']=1
    if reason=='gap':bars[6]['time']+=1
    signals,live=zone_reversal_setups(bars,np.ones(len(bars)),guides,**kwargs)
    assert signals[5] and live[5]==5 and live[6] is None

@pytest.mark.parametrize('short',[False,True])
@pytest.mark.parametrize('tf',['4h','1d'])
def test_reversal_zone_outside_initial_context_replaces_old_nested_stop(short,tf):
    bars,guides=scenario(short,tf);t=bars[0]['time']
    context=guides[tf]['supplyDemand']['zones'][0]
    context['lower' if short else 'upper']=122 if short else 98
    reversal=dict(id='reversal',timeframe='15m',kind='SUPPLY' if short else 'DEMAND',
                  lower=120.5 if short else 98.5,upper=121.5 if short else 99.5,
                  originTime=t+120,availableAt=t+180)
    guides['15m']['supplyDemand']['zones'].append(reversal)
    signals,live=zone_reversal_setups(bars,np.ones(len(bars)),guides)
    s=signals[5]
    assert s['parentZone']['id']=='reversal' and s['stopSource']=='15M_ZONE'
    assert s['stopBoundary']==(121.5 if short else 98.5)
    assert s['stop']==pytest.approx(121.55 if short else 98.45)
    assert s['target']==110 and live[6]==5
    for end in range(1,len(bars)+1):
        assert zone_reversal_setups(bars[:end],np.ones(end),guides)==(signals[:end],live[:end])


@pytest.mark.parametrize('rejection',['future','invalidated','retired','wrong_side','wrong_kind','before_alignment','old_origin'])
@pytest.mark.parametrize('short',[False,True])
def test_unqualified_reversal_zone_keeps_valid_context_stop(rejection,short):
    bars,guides=scenario(short);t=bars[0]['time']
    context=guides['4h']['supplyDemand']['zones'][0]
    context['lower' if short else 'upper']=122 if short else 98
    z=dict(id='reversal',timeframe='15m',kind='SUPPLY' if short else 'DEMAND',
           lower=120.5 if short else 98.5,upper=121.5 if short else 99.5,
           originTime=t+120,availableAt=t+180)
    if rejection=='future':z['availableAt']=t+420
    if rejection in ('invalidated','retired'):
        guides['15m']['supplyDemand']['events']=[dict(zoneId='reversal',kind=rejection.upper(),availableAt=t+300)]
    if rejection=='wrong_side':z.update(lower=118 if short else 101,upper=119 if short else 102)
    if rejection=='wrong_kind':z['kind']='DEMAND' if short else 'SUPPLY'
    if rejection=='before_alignment':z['availableAt']=t+120
    if rejection=='old_origin':z['originTime']=t-1000
    guides['15m']['supplyDemand']['zones'].append(z)
    s=zone_reversal_setups(bars,np.ones(len(bars)),guides)[0][5]
    assert s['parentZone']['id']=='nested'
    assert s['stop']==pytest.approx(126.05 if short else 93.95)
