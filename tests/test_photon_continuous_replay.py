"""Mapping replay crosses UTC midnight; manual trading review stays day-bounded."""
import json
import shutil
import subprocess

import pytest

from crypto_strategy_lab.visualizer_photon import PHOTON_HELPERS
from crypto_strategy_lab.visualizer_replay import REPLAY_HELPERS


def run_js(code):
    node=shutil.which("node")
    if not node:
        pytest.skip("Node needed for browser replay checks")
    result=subprocess.run([node],input=REPLAY_HELPERS+PHOTON_HELPERS+code,
                          text=True,encoding="utf-8",capture_output=True,check=True)
    return json.loads(result.stdout)


def test_mapping_step_and_play_can_cross_midnight_without_reset_or_future_bars():
    result=run_js("""
const day=86400,interval=900;
const bars=[day+84600,day+85500,day+86400,day+87300].map(time=>({time,open:100,high:101,low:99,close:100}));
const source={candles:bars,selectedTrade:{Entry:100,'Entry Time':new Date((day+84600)*1000).toISOString()}};
let cutoff=day+85500;const states=[];
for(let i=0;i<4;i++) {
 const next=cslNextReplayCutoff(bars,cutoff,interval,cslReplayEnd(bars,interval,day,true));
 if(next==null)break;
 cutoff=next;
 const projected=cslReplayView(source,cutoff,interval,day+84600).view;
 states.push({cutoff,day:cslReplayDisplayDay(cutoff,day+84600),last:projected.candles.at(-1).time,closed:projected.candles.every(b=>b.time+interval<=cutoff)});
}
console.log(JSON.stringify({states,end:cslNextReplayCutoff(bars,cutoff,interval,cslReplayEnd(bars,interval,day,true))}));
""")
    assert [s["cutoff"] for s in result["states"]]==[172800,173700,174600]
    assert [s["day"] for s in result["states"]]==[86400,172800,172800]
    assert all(s["closed"] for s in result["states"])
    assert [s["last"] for s in result["states"]]==[171900,172800,173700]
    assert result["end"] is None


def test_manual_day_replay_still_stops_at_midnight():
    result=run_js("""
const bars=[{time:85500},{time:86400},{time:87300}];
const end=cslReplayEnd(bars,900,0,false);
console.log(JSON.stringify({end,last:cslNextReplayCutoff(bars,85500,900,end),next:cslNextReplayCutoff(bars,86400,900,end)}));
""")
    assert result==dict(end=86400,last=86400,next=None)


def test_mapping_next_event_search_reaches_the_following_day():
    result=run_js("""
const bars=[{time:85500},{time:86400},{time:87300}];
const mapping={timeframes:{'15m':{events:[{kind:'CHOCH',availableAt:87300},{kind:'BOS',availableAt:88200}]}}};
console.log(JSON.stringify({continuous:cslPhotonNextEvent(mapping,86400,cslReplayEnd(bars,900,0,true)),dayBounded:cslPhotonNextEvent(mapping,86400,cslReplayEnd(bars,900,0,false))}));
""")
    assert result==dict(continuous=87300,dayBounded=None)


def test_replay_date_handles_start_midnight_and_missing_calendar_days():
    result=run_js("""
const bars=[{time:85500},{time:259200}];
console.log(JSON.stringify({start:cslReplayDisplayDay(86400,86400),gapNext:cslNextReplayCutoff(bars,86400,900,cslReplayEnd(bars,900,0,true)),gapDay:cslReplayDisplayDay(260100,0),empty:cslReplayEnd([],900,0,true)}));
""")
    assert result==dict(start=86400,gapNext=260100,gapDay=259200,empty=None)
