"""Bound chart work without truncating execution history or leaking future bars."""
import json
import shutil
import subprocess

import pytest

from crypto_strategy_lab.visualizer_replay import REPLAY_HELPERS
from crypto_strategy_lab.visualizer_photon import PHOTON_HELPERS
from crypto_strategy_lab.strategy_visualizer_browser_v2 import build_browser_visualizer_v2_html
from test_strategy_visualizer_browser_v2 import _Model


def js(code):
    node=shutil.which('node')
    if not node:
        pytest.skip('Node needed for replay performance checks')
    return json.loads(subprocess.run([node],input=REPLAY_HELPERS+code,encoding='utf-8',capture_output=True,check=True).stdout)


def test_large_minute_history_projects_only_closed_window_and_keeps_execution_source():
    result=js('''
const candles=Array.from({length:100000},(_,i)=>({time:i*60,open:100,high:i===100?105:101,low:99,close:100}));
const source={candles,selectedTrade:{Side:'LONG',Entry:100,'Entry Time':'1970-01-01T00:00:00Z'},overlays:[{data:candles.map(b=>({time:b.time,value:100}))}]};
const view=cslReplayView(source,90000*60,60,0,false,true,2000).view;
const record={side:'LONG',manualEntry:{entry:100,stop:98,target:104,candleTime:0,interval:60}};
const settled=cslAdvanceManualPosition(record,source.candles,90000*60,60,'now');
console.log(JSON.stringify({source:source.candles.length,length:view.candles.length,first:view.candles[0].time,last:view.candles.at(-1).time,
 indicators:view.overlays[0].data.length,windowed:view.chartWindowed,exit:settled.manualExit,
 full:cslReplayView(source,90000*60,60,0,false,true,0).view.candles.length}));
''')
    assert result['source']==100000 and result['length']==2000 and result['indicators']==2000
    assert result['first']==88000*60 and result['last']==89999*60 and result['windowed']
    assert result['exit']['price']==104 and result['exit']['candleTime']==100*60
    assert result['full']==90000


def test_timeframe_cache_shares_inflight_requests_reuses_and_retries_failures():
    result=js('''
(async()=>{
 const calls=[];const get=cslPayloadCache(async key=>{calls.push(key);if(key==='bad')throw Error('temporary');return {key};},3);
 const first=get('trade1:1m'),same=get('trade1:1m');await first;
 await get('trade1:15m');await get('trade1:4h');await get('trade1:1m');
 await get('trade2:1m');await get('trade1:15m');
 for(let i=0;i<2;i++){try{await get('bad')}catch{}}
 console.log(JSON.stringify({same:first===same,calls}));
})().catch(e=>{process.stderr.write(e.stack);process.exit(1)});
''')
    assert result['same']
    assert result['calls'].count('trade1:1m')==1
    assert result['calls'].count('trade1:15m')==2  # bounded LRU eviction
    assert result['calls'].count('trade2:1m')==1 and result['calls'].count('bad')==2


def test_quick_buttons_use_existing_switch_handler_without_changing_replay_clock():
    html=build_browser_visualizer_v2_html(_Model(),'quick-timeframes')
    code=html[html.index('  function updateQuickTimeframes('):html.index("  $('replay-candle-limit').addEventListener")]
    result=js('''
let currentTimeframe='15m',replayCutoff=123456,changes=0;
const quick={children:[],replaceChildren(){this.children=[]},appendChild(b){this.children.push(b)}};
const $=()=>quick,document={createElement:()=>({attrs:{},setAttribute(k,v){this.attrs[k]=v},addEventListener(t,fn){this.click=fn}})};
const timeframeSelect={value:'15m',dispatchEvent(){changes++;currentTimeframe=this.value}};
''' + code + '''
updateQuickTimeframes([{interval:'1m'},{interval:'15m'},{interval:'4h'}],'15m');
const selected=quick.children.find(b=>b.attrs['aria-pressed']==='true').textContent;
quick.children[0].click();quick.children[0].click();
console.log(JSON.stringify({selected,changes,currentTimeframe,replayCutoff,buttons:quick.children.map(b=>b.textContent)}));
''')
    assert result=={'selected':'15m','changes':1,'currentTimeframe':'1m','replayCutoff':123456,'buttons':['1m','15m','4h']}


def test_photon_window_and_recent_event_indexes_preserve_known_results():
    result=js(PHOTON_HELPERS+'''
const events=Array.from({length:10000},(_,i)=>({kind:i%3===0?'SWING':i%3===1?'BOS':'CHOCH',direction:1,time:Math.floor(i/2)*60,availableAt:Math.floor(i/2)*60+60,fromTime:i*30,price:100+i%5}));
const trace=Array.from({length:10000},(_,i)=>({kind:'BOS_SWING',direction:i%2?1:-1,fromTime:i*60,availableAt:i*60+600,price:i%2?110:90}));
const guide={events,trace,traceBasis:'BOS_CONFIRMED'},cutoff=240000,start=230000;
const expected=events.filter(e=>e.availableAt<=cutoff&&['BOS','TREND_CHANGE','CHOCH'].includes(e.kind)).sort((a,b)=>b.availableAt-a.availableAt).slice(0,80);
const recent=cslPhotonRecentEvents(guide,cutoff);
const full=cslPhotonSwingLines(guide,cutoff).flat().filter(p=>p.time>=start);
const window=cslPhotonSwingLines(guide,cutoff,start).flat();
console.log(JSON.stringify({recent:JSON.stringify(expected)===JSON.stringify(recent),points:JSON.stringify(full)===JSON.stringify(window.filter(p=>p.time>=start)),bounded:window.length,
 next:cslPhotonNextEvent({timeframes:{'1m':guide}},cutoff,cutoff+120),expectedNext:events.find(e=>e.availableAt>cutoff&&['BOS','TREND_CHANGE','CHOCH'].includes(e.kind)).availableAt}));
''')
    assert result['recent'] and result['points']
    assert result['bounded'] < 200 and result['next']==result['expectedNext']
