from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace
import json

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.photon_lesson import (options, construct_zones, evidence,
    required_pass, REQUIREMENTS, qualify_setup, context_pass)
from crypto_strategy_lab.photon_structure import build_mapping


def test_single_pivot_accepts_same_colour_origin_and_waits_for_thrust_close():
    bars=[dict(time=0,open=100,high=102,low=99,close=101),
          dict(time=900,open=101,high=105,low=100,close=104)]
    guide=dict(interval=900,events=[],snapshots=[])
    zones=construct_zones(bars,guide,'15m',dict(photon_zone_model='PIVOT'))
    assert len(zones)==1
    assert (zones[0]['lower'],zones[0]['upper'],zones[0]['availableAt'])==(99,102,1800)
    assert zones[0]['kind']=='DEMAND' and zones[0]['confirmedBy']=='THRUST'
    assert construct_zones(bars[:1],guide,'15m',dict(photon_zone_model='PIVOT'))==[]


@pytest.mark.parametrize('model,n',[('PIVOT_TWO',2),('RANGE',3)])
def test_multicandle_bases_use_full_union_and_require_departure(model,n):
    bars=[dict(time=i*900,open=100,high=103+i,low=98-i,close=101) for i in range(n)]
    bars.append(dict(time=n*900,open=101,high=110,low=100,close=109))
    opts=dict(photon_zone_model=model,photon_range_base_bars=n)
    guide=dict(interval=900,events=[],snapshots=[])
    z=construct_zones(bars,guide,'15m',opts)[-1]
    assert (z['lower'],z['upper'],z['baseCandles'])==(99-n,102+n,n)
    bars[-1]['close']=102
    assert not construct_zones(bars,guide,'15m',opts)
    bars[-1]['close']=109; bars[-1]['time']+=900
    assert not construct_zones(bars,guide,'15m',opts)


def proof_scenario():
    zone=dict(id='demand',timeframe='15m',kind='DEMAND',lower=90,upper=100,
        originTime=900,availableAt=1800,confirmedBy='THRUST',creationLocation='DISCOUNT')
    other=dict(id='supply',timeframe='15m',kind='SUPPLY',lower=98,upper=108,
        originTime=0,availableAt=0,confirmedBy='BOS',creationLocation='PREMIUM')
    events=[dict(zoneId='supply',kind='TOUCHED',availableAt=900,candleTime=0),
        dict(zoneId='supply',kind='INVALIDATED',availableAt=1800,candleTime=900),
        dict(zoneId='demand',kind='TOUCHED',availableAt=3600,candleTime=2700)]
    states=[dict(availableAt=t,trend=1,internal=1,close=110,
        internalLow=dict(price=95 if t<2700 else 105,time=0 if t<2700 else 1800)) for t in (900,1800,2700,3600)]
    guides={tf:dict(interval=900,snapshots=deepcopy(states),events=[]) for tf in ('15m','4h','1d','1w')}
    g=guides['15m'];g['supplyDemand']=dict(zones=[zone,other],events=events)
    g['events']=[dict(kind='BOS',direction=1,availableAt=1800,time=900),dict(kind='SWING',availableAt=1800,fromTime=0)]
    g['_lesson_native']=[dict(time=0,low=95,high=105),dict(time=900,low=90,high=100),dict(time=1800,low=105,high=112),dict(time=2700,low=95,high=111)]
    higher={**zone,'id':'higher','timeframe':'4h','lower':85,'upper':101,'availableAt':900}
    guides['4h']['supplyDemand']=dict(zones=[higher],events=[])
    return zone,guides


def test_each_quality_factor_has_positive_causal_evidence():
    z,g=proof_scenario();p=evidence(z,g,3600)
    assert all(p['checks'].values()),p
    assert p['liquidityLevel']==105
    for field in REQUIREMENTS:
        assert required_pass(p['checks'],{field:True})
        failed={**p['checks'],REQUIREMENTS[field]:False}
        assert not required_pass(failed,{field:True})


def test_freshness_is_first_mitigation_not_every_new_visit():
    z,g=proof_scenario()
    assert evidence(z,g,3600)['checks']['fresh']
    g['15m']['supplyDemand']['events'].append(dict(zoneId=z['id'],kind='TOUCHED',availableAt=4500,candleTime=3600))
    # Clear the optional lookup cache after deliberately mutating a test guide.
    for key in list(g['15m']['supplyDemand']):
        if key.startswith('_lesson_'):g['15m']['supplyDemand'].pop(key)
    assert not evidence(z,g,4500)['checks']['fresh']


def test_future_bos_flip_stack_and_liquidity_do_not_qualify_early():
    z,g=proof_scenario();early=evidence(z,g,900)['checks']
    assert not early['bos'] and not early['inducement']
    # A flip is initiation evidence, but is not exposed before zone birth by
    # the replay, which filters the zone itself on availableAt.
    g['4h']['supplyDemand']['zones'][0]['availableAt']=4500
    assert not evidence(z,g,3600)['checks']['stacked']
    g['15m']['supplyDemand']['events'][-1].update(availableAt=4500,candleTime=3600)
    assert not evidence(z,g,4500)['checks']['inducement']


@pytest.mark.parametrize('model',['LEGACY','PIVOT','PIVOT_TWO','RANGE'])
def test_mapping_quality_and_zone_history_are_prefix_causal(model):
    bars=[]
    for i in range(160):
        p=100+4*np.sin(i/5)
        bars.append(dict(time=i*900,open=p,high=p+1,low=p-1,close=p+.3))
    opts={**options(SimpleNamespace()),'photon_zone_model':model,'photon_fresh_zone_only':True}
    full=build_mapping(bars,lesson_options=opts)
    for n in (80,120):
        prefix=build_mapping(bars[:n],lesson_options=opts);cutoff=n*900
        for tf,g in prefix['timeframes'].items():
            if 'supplyDemand' not in g:continue
            a=full['timeframes'][tf]['supplyDemand'];b=g['supplyDemand']
            for key in ('zones','events','qualityEvents'):
                assert [x for x in a[key] if x['availableAt']<=cutoff]==b[key]


def test_default_mapping_unchanged_and_settings_roundtrip():
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig,normalize_data_lake_config
    from crypto_strategy_lab.research_adapters import native_simulator_config
    c=ResearchRunConfig();e=replace(c.execution,photon_zone_model='RANGE',photon_require_sweep=True,
        photon_fresh_zone_only=True,photon_fixed_target_enabled=True,photon_fixed_target_r=3.)
    c=normalize_data_lake_config(asdict(replace(c,execution=e)))
    native=native_simulator_config(c.data,c.features,c.strategy,c.execution)
    assert native.photon_zone_model=='RANGE' and native.photon_require_sweep
    assert native.photon_fixed_target_r==3.
    assert build_mapping([])==build_mapping([],lesson_options=options(ResearchRunConfig().execution))


@pytest.mark.parametrize('gap',[False,True])
def test_indexed_lifecycle_matches_reference_on_realistic_minute_paths(gap):
    from crypto_strategy_lab.photon_structure import aggregate_closed
    from crypto_strategy_lab.photon_zones import zone_lifecycle
    from crypto_strategy_lab.photon_lesson import indexed_lifecycle
    source=[]
    for i in range(1800):
        p=100+5*np.sin(i/35)+np.sin(i/3)
        source.append(dict(time=i*60,open=p,high=p+1,low=p-1,close=p+.25))
    if gap:source.pop(800)
    native=aggregate_closed(source,60,900)
    guide=dict(interval=900,snapshots=[],events=[])
    zones=construct_zones(native,guide,'15m',dict(photon_zone_model='PIVOT'))
    legacy=[{k:v for k,v in z.items() if k!='lessonModel'} for z in zones]
    expected=zone_lifecycle(source,native,guide,legacy,60)['events']
    actual=indexed_lifecycle(source,native,guide,zones,60)['events']
    sort=lambda es:sorted(es,key=lambda e:(e['availableAt'],e['zoneId'],e['kind']))
    assert sort(actual)==sort(expected)


@pytest.mark.parametrize('patch',[dict(photon_zone_model='BAD'),dict(photon_range_base_bars=1),
    dict(photon_fixed_target_r=float('nan')),dict(photon_fixed_target_enabled=True,photon_hold_tp_until_15m_reversal=True),
    dict(photon_fixed_target_enabled=True,photon_exit_on_15m_change=True),dict(photon_fixed_target_enabled=True,photon_fixed_target_r=.5)])
def test_invalid_lesson_configs_fail_before_execution(patch):
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig
    c=ResearchRunConfig()
    with pytest.raises(ValueError):replace(c,execution=replace(c.execution,photon_zone_reversal=True,**patch)).validate()


@pytest.mark.parametrize('legacy',[False,True])
@pytest.mark.parametrize('short',[False,True])
def test_exact_fixed_r_is_from_actual_fill_not_midpoint(monkeypatch,legacy,short):
    from test_photon_zone_reversal import scenario
    from crypto_strategy_lab.config import BacktestConfig
    from crypto_strategy_lab.photon_trend import MODE
    from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine
    from crypto_strategy_lab.strategy_profiles import StrategyProfile
    from crypto_strategy_lab.strategy_rule_model import compile_profiles,MARKET_PERMISSIONS
    bars,guides=scenario(short,nested=False);t=bars[0]['time']
    bars[-1].update(open=115 if short else 105,high=116 if short else 160,low=60 if short else 104,close=65 if short else 155)
    pad=[dict(time=t-(150-i)*60,open=110,high=111,low=109,close=110) for i in range(150)]
    monkeypatch.setattr('crypto_strategy_lab.photon_trend.prepare_context',lambda *a,**kw:deepcopy(guides))
    profiles,_=compile_profiles(direction_mode=MODE,market_permissions=MARKET_PERMISSIONS)
    native={k:StrategyProfile(**asdict(p)) for k,p in profiles.items()}
    c=BacktestConfig(strategy_timeframe_minutes=1,strategy_profiles=native,use_intrabar_data=False,
        enable_support_resistance_analysis=False,enable_trade_telemetry=False,photon_zone_reversal=True,
        photon_legacy_entry_and_stop=legacy,photon_fixed_target_enabled=True,photon_fixed_target_r=3.,sd_minimum_r=3.)
    frame=pd.DataFrame(pad+bars).rename(columns={'time':'timestamp'});frame['timestamp']=pd.to_datetime(frame.timestamp,unit='s',utc=True);frame['volume']=1.
    engine=RuleAwareDataLakeProductionBacktestEngine(frame,c);engine.market_regime_values[:]='SIDEWAYS'
    d=engine.run();assert len(d)==1
    r=d.iloc[0];side=r.side.lower();sign=-1 if short else 1
    ratio=sign*(r[side+'_tp']-r.actual_entry_price)/abs(r.actual_entry_price-r[side+'_original_sl'])
    assert ratio==pytest.approx(3.)
    assert r[side+'_final_exit_reason']=='TP'
    setup=json.loads(r.supply_demand_setup)
    assert setup['targetMode']=='FIXED_R' and setup['target']==r[side+'_tp']


def test_lesson_card_visible_in_mapping_and_fixed_exit_controls_are_exclusive():
    from test_risk_execution_workspace import _window
    app,window=_window()
    try:
        selector=window.rule_builder.direction_mode
        selector.setCurrentIndex(selector.findData('PHOTON_STRUCTURE_MAP'));selector.activated.emit(selector.currentIndex());app.processEvents()
        w=window.risk_execution_workspace;w.refresh_visibility()
        assert not w.lesson_card.isHidden()
        assert window.execution_form.widgets['photon_fixed_target_enabled'].isHidden()
        model=window.execution_form.widgets['photon_zone_model'];model.setCurrentIndex(model.findData('RANGE'))
        window.execution_form.widgets['photon_fresh_zone_only'].setChecked(True)
        config=window.build_config();window.apply_config(config)
        assert window.build_config().execution.photon_zone_model=='RANGE'
        assert window.build_config().execution.photon_fresh_zone_only
        selector.setCurrentIndex(selector.findData('PHOTON_4H_TREND'));selector.activated.emit(selector.currentIndex());app.processEvents()
        window.execution_form.widgets['photon_hold_tp_until_15m_reversal'].setChecked(True)
        window.execution_form.widgets['photon_fixed_target_enabled'].setChecked(True)
        assert not window.build_config().execution.photon_hold_tp_until_15m_reversal
        window.execution_form.widgets['photon_exit_on_15m_change'].setChecked(True)
        assert not window.build_config().execution.photon_fixed_target_enabled
    finally:window.close()


@pytest.mark.parametrize('legacy',[False,True])
@pytest.mark.parametrize('short',[False,True])
@pytest.mark.parametrize('required',['photon_require_4h_alignment','photon_require_daily_alignment',
    'photon_require_weekly_alignment','photon_require_15m_internal_alignment'])
def test_required_alignment_reaches_the_actual_engine_entry_gate(monkeypatch,legacy,short,required):
    from test_photon_zone_reversal import scenario
    from crypto_strategy_lab.config import BacktestConfig
    from crypto_strategy_lab.photon_trend import MODE
    from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine
    from crypto_strategy_lab.strategy_profiles import StrategyProfile
    from crypto_strategy_lab.strategy_rule_model import compile_profiles,MARKET_PERMISSIONS
    bars,guides=scenario(short,nested=False);t=bars[0]['time'];sign=-1 if short else 1
    guides['15m']['snapshots'][-1]['internal']=-sign
    monkeypatch.setattr('crypto_strategy_lab.photon_trend.prepare_context',lambda *a,**kw:deepcopy(guides))
    profiles,_=compile_profiles(direction_mode=MODE,market_permissions=MARKET_PERMISSIONS)
    native={k:StrategyProfile(**asdict(p)) for k,p in profiles.items()}
    pad=[dict(time=t-(150-i)*60,open=110,high=111,low=109,close=110) for i in range(150)]
    frame=pd.DataFrame(pad+bars).rename(columns={'time':'timestamp'});frame['timestamp']=pd.to_datetime(frame.timestamp,unit='s',utc=True);frame['volume']=1.
    c=BacktestConfig(strategy_timeframe_minutes=1,strategy_profiles=native,use_intrabar_data=False,
        enable_support_resistance_analysis=False,enable_trade_telemetry=False,photon_zone_reversal=True,
        photon_legacy_entry_and_stop=legacy,sd_minimum_r=.1)
    engine=RuleAwareDataLakeProductionBacktestEngine(frame,c);engine.market_regime_values[:]='SIDEWAYS'
    assert len(engine.run())==1
    engine=RuleAwareDataLakeProductionBacktestEngine(frame,replace(c,**{required:True}));engine.market_regime_values[:]='SIDEWAYS'
    assert len(engine.run())==0
