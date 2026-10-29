"""Replay opportunity observations are causal and never confirm positions."""
import json
import shutil
import subprocess
import pytest
from crypto_strategy_lab.visualizer_opportunities import OPPORTUNITY_HELPERS


def js(code):
    node=shutil.which('node')
    if not node: pytest.skip('Node required')
    result=subprocess.run([node],input=OPPORTUNITY_HELPERS+FIXTURE+code,text=True,encoding='utf-8',capture_output=True,check=True)
    return json.loads(result.stdout)


FIXTURE=r'''
const bars=[
 {time:0,open:105,high:108,low:103,close:106},
 {time:900,open:106,high:107,low:101,close:104},
 {time:1800,open:104,high:110,low:104,close:109},
 {time:2700,open:109,high:112,low:108,close:111}
];
const snapshots=bars.map(b=>({availableAt:b.time+900,trend:1,internal:1,
 range:{low:100,high:130,equilibrium:115},low:{price:100,time:0},high:{price:130,time:0},internalLow:{price:102,time:0},internalHigh:{price:120,time:0}}));
const guide={interval:900,snapshots,events:[{kind:'TREND_CHANGE',direction:1,price:105,time:0,availableAt:900}],
 supplyDemand:{zones:[{id:'d',kind:'DEMAND',timeframe:'15m',lower:100,upper:104,availableAt:900,originTime:0}],events:[]}};
const source={candles:bars,photonMapping:{timeframes:{'15m':guide,'4h':{interval:14400,snapshots:[{availableAt:0,trend:1,range:{low:90,high:140,equilibrium:115}}]}}}};
'''


def test_break_touch_then_later_reaction_and_sweep():
    result=js("console.log(JSON.stringify(cslBuildOpportunities(source,900)));" )
    assert any(x['pattern']=='STRUCTURE_BREAK' and x['availableAt']==900 for x in result)
    touch=next(x for x in result if x['pattern']=='ZONE_REACTION' and x['availableAt']==1800)
    reaction=next(x for x in result if x['pattern']=='ZONE_REACTION' and x['availableAt']==2700)
    assert touch['phase']=='WATCH' and reaction['phase']=='CONFIRMED_REACTION'
    assert reaction['touchAt']==1800 and reaction['stop']<100<reaction['entry']<reaction['target']
    assert any(x['pattern']=='SWEEP_RECLAIM' and x['side']=='LONG' for x in result)
    assert all('manualEntry' not in x for x in result)


def test_every_prefix_matches_full_history_before_replay_clock():
    result=js(r'''
const full=cslBuildOpportunities(source,900);const equal=[];
for(let n=1;n<=bars.length;n++){
 const at=n*900,short=JSON.parse(JSON.stringify(source));short.candles=bars.slice(0,n);
 for(const g of Object.values(short.photonMapping.timeframes)){
  g.snapshots=g.snapshots.filter(s=>s.availableAt<=at);g.events=(g.events||[]).filter(e=>e.availableAt<=at);
  if(g.supplyDemand){g.supplyDemand.zones=g.supplyDemand.zones.filter(z=>z.availableAt<=at);g.supplyDemand.events=g.supplyDemand.events.filter(e=>e.availableAt<=at);}
 }
 equal.push(JSON.stringify(cslBuildOpportunities(short,900))===JSON.stringify(full.filter(x=>x.availableAt<=at)));
}
console.log(JSON.stringify(equal));
''')
    assert all(result)


def test_future_zone_invalidation_does_not_hide_known_touch():
    result=js(r'''
guide.supplyDemand.events.push({kind:'INVALIDATED',zoneId:'d',availableAt:3600});
const all=cslBuildOpportunities(source,900);const idea=all.find(x=>x.pattern==='ZONE_REACTION'&&x.availableAt===1800);
console.log(JSON.stringify({before:cslOpportunityNow(idea,source,900,2700),after:cslOpportunityNow(idea,source,900,3600)}));
''')
    assert not result['before']['expired']
    assert result['after']['expired'] and not result['after']['usable']


def test_expiration_uses_only_completed_candles():
    result=js(r'''
const idea=cslBuildOpportunities(source,900).find(x=>x.pattern==='ZONE_REACTION'&&x.availableAt===2700);
bars[3].low=90;bars[3].high=140;
console.log(JSON.stringify({forming:cslOpportunityNow(idea,source,900,3599),closed:cslOpportunityNow(idea,source,900,3600)}));
''')
    assert not result['forming']['expired']
    assert result['closed']['expired']
    assert any('stop has already' in x for x in result['closed']['risks'])


def test_no_same_candle_zone_touch_and_retired_zone_not_usable():
    result=js(r'''
guide.supplyDemand.zones[0].availableAt=1800;
guide.supplyDemand.events.push({kind:'RETIRED',zoneId:'d',availableAt:2700});
console.log(JSON.stringify(cslBuildOpportunities(source,900).filter(x=>x.pattern==='ZONE_REACTION')));
''')
    assert result==[]


def test_missing_target_and_opposing_trends_are_explicit_not_silently_filtered():
    result=js(r'''
const b={time:0,open:100,high:105,low:99,close:104};
const context={'15m':{trend:-1,range:{low:90,high:103,equilibrium:96}},'4h':{trend:-1}};
console.log(JSON.stringify(cslOpportunityPlan('STRUCTURE_BREAK',1,b,context,99,2,null,{entryFee:.0005,exitFee:.0005,slippage:.0005})));
''')
    assert result['target'] is None and not result['usable']
    assert any('4H trend opposes' in x for x in result['risks'])
    assert any('No forward structure target' in x for x in result['risks'])


def test_aggregation_rejects_incomplete_duplicate_and_gapped_minutes():
    result=js(r'''
const minutes=Array.from({length:15},(_,i)=>({time:i*60,open:100,high:102,low:99,close:101}));
console.log(JSON.stringify([cslOpportunityBars(minutes,60).length,cslOpportunityBars(minutes.slice(1),60).length,cslOpportunityBars([...minutes,minutes[0]],60).length,cslOpportunityBars(bars,3600).length]));
''')
    assert result==[1,0,0,0]


def test_visible_ideas_never_include_future_observations():
    result=js("console.log(JSON.stringify(cslVisibleOpportunities(cslBuildOpportunities(source,900),1800).map(x=>x.availableAt)));" )
    assert result and max(result)<=1800


def test_short_symmetry():
    result=js(r'''
const a=cslBuildOpportunities(source,900).find(x=>x.pattern==='ZONE_REACTION'&&x.availableAt===2700);
for(const b of bars){const h=b.high;b.open=230-b.open;b.close=230-b.close;b.high=230-b.low;b.low=230-h;}
for(const g of Object.values(source.photonMapping.timeframes))for(const s of g.snapshots){s.trend=-s.trend;const r=s.range;if(r)s.range={low:230-r.high,high:230-r.low,equilibrium:230-r.equilibrium};const hi=s.high,lo=s.low;s.high=lo?{...lo,price:230-lo.price}:null;s.low=hi?{...hi,price:230-hi.price}:null;}
for(const z of guide.supplyDemand.zones){const lower=z.lower;z.kind='SUPPLY';z.lower=230-z.upper;z.upper=230-lower;}
const b=cslBuildOpportunities(source,900).find(x=>x.pattern==='ZONE_REACTION'&&x.availableAt===2700);
console.log(JSON.stringify({a,b}));
''')
    assert result['b']['side']=='SHORT'
    assert result['b']['stop']>result['b']['entry']>result['b']['target']
    assert result['b']['rewardRisk']==pytest.approx(result['a']['rewardRisk'])


def test_replay_notification_controls_and_manual_handoff_are_wired():
    from test_strategy_visualizer_browser_v2 import _Model
    from crypto_strategy_lab.strategy_visualizer_browser_v2 import build_browser_visualizer_v2_html
    html=build_browser_visualizer_v2_html(_Model(),'ideas')
    for identifier in ['opportunity-enabled','opportunity-pause','opportunity-pattern','opportunity-side','opportunity-watch','opportunity-next','opportunity-select','opportunity-use','opportunity-skip']:
        assert f'id="{identifier}"' in html
    assert 'opportunityDecisions,exportedAt:' in html
    assert 'id="opportunity-quality"' in html
    assert 'Why this score?' in html
    assert 'not a win probability' in html
    assert 'original signal score' in html
    assert 'record.opportunityOrigins=' in html
    assert 'No automatic entries.' in html
    handler=html.split("$('opportunity-use').addEventListener('click',()=>{",1)[1].split("$('opportunity-next')",1)[0]
    assert 'loadManualPlan(' in handler and 'storeManualPlan()' in handler
    assert 'cslConfirmManualEntry(' not in handler
    assert 'manualPlanLocked()' in handler
    node=shutil.which('node')
    if node:
        script=html.split('<script>',1)[1].split('</script>',1)[0]
        subprocess.run([node,'-e',"new(require('vm').Script)(require('fs').readFileSync(0,'utf8'))"],input=script,text=True,encoding='utf-8',capture_output=True,check=True)


QUALITY_FIXTURE=r'''
const good={side:'LONG',entry:100,stop:98,target:104,usable:true,rewardRisk:2,costRisk:.05,phase:'CONFIRMED_REACTION',
qualityFacts:{trends:{'4h':1,'15m':1,'1d':1,'1w':1},minuteInternal:1,zoneKnown:true,zoneVisits:1,zoneAgeSeconds:900,inValue:true,opposingBeforeTarget:false,stopAtr:1}};
'''


def test_quality_full_breakdown_totals_one_hundred():
    result=js(QUALITY_FIXTURE+'console.log(JSON.stringify(cslOpportunityQuality(good)));')
    assert result['score']==100 and result['grade']=='Strong'
    assert sum(x['max'] for x in result['rows'])==100
    assert sum(x['points'] for x in result['rows'])==100
    assert result['version']=='STRUCTURE_QUALITY_V1'
    assert 'not a probability' in result['basis']


@pytest.mark.parametrize('change,ceiling',[("good.phase='WATCH'",59),("good.qualityFacts.trends['4h']=-1",59),("good.rewardRisk=.9",39),("good.costRisk=.3",59),("good.qualityFacts.stopAtr=4",59),("good.usable=false",0)])
def test_quality_risk_ceilings(change,ceiling):
    result=js(QUALITY_FIXTURE+change+';console.log(JSON.stringify(cslOpportunityQuality(good)));')
    assert result['score']<=ceiling
    assert result['grade']!='Strong'


def test_unknown_quality_evidence_never_earns_alignment_points():
    result=js(QUALITY_FIXTURE+"good.qualityFacts={};good.costRisk=null;console.log(JSON.stringify(cslOpportunityQuality(good)));")
    assert result['score']==35  # Known reaction + room only.
    assert all(x['points']==0 for x in result['rows'] if x['key'] not in ['confirmation','room'])


def test_quality_is_frozen_on_expiration_and_manual_level_edits_are_separate():
    result=js(r'''
const item=cslBuildOpportunities(source,900).find(x=>x.pattern==='ZONE_REACTION'&&x.phase==='CONFIRMED_REACTION');
const original=JSON.stringify(item.quality);
bars[3].low=90;const expired=cslOpportunityNow(item,source,900,3600);
const manualPlan={entry:item.entry,stop:item.stop-5,target:item.target+10};
console.log(JSON.stringify({expired:expired.expired,frozen:JSON.stringify(expired.quality)===original,originalUnchanged:JSON.stringify(item.quality)===original,manualPlan}));
''')
    assert result['expired'] and result['frozen'] and result['originalUnchanged']


@pytest.mark.parametrize('change',["good.target=99","good.stop=101","good.entry=NaN","good.target=null"])
def test_quality_rejects_invalid_geometry_even_with_stale_usable_flag(change):
    result=js(QUALITY_FIXTURE+change+';console.log(JSON.stringify(cslOpportunityQuality(good)));')
    assert result['score']==0 and result['grade']=='Incomplete'
