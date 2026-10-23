import json
import shutil
import subprocess
import pytest
from crypto_strategy_lab.visualizer_structure import STRUCTURE_HELPERS


def js(code):
    node=shutil.which('node')
    if not node:pytest.skip('Node required for market structure guide')
    result=subprocess.run([node],input=STRUCTURE_HELPERS+'\n'+code,text=True,encoding='utf-8',capture_output=True,check=True)
    return json.loads(result.stdout)


FIXTURE="""
const highs=[21,19.5,16,15,16,17,15,14,14,17,22,15.4,16,17],
 lows=[19,17,14,10,12,12,11,9,10,14.5,13,14.1,15,15.5],
 opens=[20,19,15,12,14,15,12,11,10.5,15,14,14.3,15.1,16],
 closes=[20,17.2,15,12,14,15,12,12,13.5,16,20,15.2,15.8,16.5];
const bars=highs.map((high,i)=>({time:i*900,open:opens[i],high,low:lows[i],close:closes[i]}));
"""


def test_guide_draws_all_reference_types_without_trade_signals():
    result=js(FIXTURE+"const g=cslBuildStructureGuide(bars,900,1);console.log(JSON.stringify({kinds:[...new Set(g.events.map(e=>e.kind))],events:g.events}));")
    assert set(result['kinds'])=={'swing','sweep','break','fvg','ifvg','equilibrium'}
    assert all('trade' not in e and 'entry' not in e for e in result['events'])
    assert any(e['kind']=='sweep' and e['time']==7*900 for e in result['events'])
    assert all(e['availableAt']>e['time'] for e in result['events'])


def test_full_timeline_replay_matches_every_causal_prefix():
    result=js(FIXTURE+"""
const full=cslBuildStructureGuide(bars,900,1);const mismatches=[];
for(let n=1;n<=bars.length;n++) {
 const cutoff=bars[n-1].time+900;
 const a=cslStructureGuideView(full,cutoff),b=cslStructureGuideView(cslBuildStructureGuide(bars.slice(0,n),900,1),cutoff);
 if(JSON.stringify(a)!==JSON.stringify(b))mismatches.push({n,a,b});
}
console.log(JSON.stringify(mismatches));
""")
    assert result==[]


def test_future_pivots_fvgs_and_inversions_are_hidden():
    result=js(FIXTURE+"""
const g=cslBuildStructureGuide(bars,900,1);
console.log(JSON.stringify({before:cslStructureGuideView(g,0).events,
 unconfirmed:cslStructureGuideView(g,2*900).events,
 first:cslStructureGuideView(g,3*900).events}));
""")
    assert result['before']==[]
    assert not any(e['kind']=='fvg' for e in result['unconfirmed'])
    assert any(e['kind']=='fvg' for e in result['first'])


def test_empty_run_and_timeframe_step_supported():
    result=js("console.log(JSON.stringify(cslStructureGuideView(cslBuildStructureGuide([],300,2),1000)));")
    assert result['events']==[]
    result=js(FIXTURE+"const b=bars.map(x=>({...x,time:x.time/3}));console.log(JSON.stringify(cslBuildStructureGuide(b,300,1).events));")
    assert any(e['kind']=='fvg' for e in result)


def test_gap_cannot_create_a_three_candle_fvg():
    result=js("""
const bars=[{time:0,open:1,high:2,low:1,close:2},{time:900,open:2,high:4,low:2,close:4},{time:2700,open:5,high:6,low:5,close:6}];
console.log(JSON.stringify(cslBuildStructureGuide(bars,900,1).events));
""")
    assert result==[]
