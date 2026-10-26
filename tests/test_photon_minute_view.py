"""Minute structure is lazy, causal and visible only on the minute chart."""
import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from crypto_strategy_lab.photon_structure import map_structure
from crypto_strategy_lab.strategy_visualizer import CompletedRunVisualizer
from crypto_strategy_lab.visualizer_photon import PHOTON_HELPERS
from crypto_strategy_lab.photon_zones import attach_ranges


def minute_bars():
    return [dict(time=i*60, open=p, close=p, high=p+.4, low=p-.4)
            for i, p in enumerate([110,108,106,108,105,103,101,102,100,98,99,97,99])]


def test_minute_guide_is_lazy_cached_and_does_not_mutate_parent_mapping():
    base = dict(timeframes={"15m": {"interval": 900}})
    model = SimpleNamespace(_photon_mapping_payload=lambda: base)
    load = lambda tf, bars: CompletedRunVisualizer._photon_chart_mapping_payload(model, tf, bars)
    bars = minute_bars()
    assert load("15m", bars) is base
    assert not hasattr(model, "_photon_minute_mapping_cache")
    minute = load("1m", bars)
    expected = map_structure(bars, 60, qualification="CHOCH_PULLBACK")
    attach_ranges(expected)
    assert minute["timeframes"]["1m"] == expected
    assert load("1m", bars)["timeframes"]["1m"] is minute["timeframes"]["1m"]
    assert load("4h", bars) is base and "1m" not in base["timeframes"]
    for n in range(1, len(bars)):
        prefix = load("1m", bars[:n])["timeframes"]["1m"]
        for key in ("events", "trace", "snapshots"):
            assert prefix[key] == [e for e in expected[key] if e["availableAt"] <= n*60]
    assert load("1m", bars)["timeframes"]["1m"] == expected


def test_minute_renderer_switches_labels_inspector_and_hides_future_events():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for chart renderer")
    script = r'''
const nodes=[],option={hidden:true,disabled:true};
const elements={'photon-view':{value:'BOTH'},'photon-labels':{checked:true},'photon-developing':{checked:false},
 'photon-event-timeframe':{value:'15m',querySelector:()=>option},'photon-event-select':{value:'',dataset:{}},'photon-status':{}};
const $=id=>elements[id];
const document={createElementNS:(ns,tag)=>({tag,attrs:{},children:[],setAttribute(k,v){this.attrs[k]=v},appendChild(n){this.children.push(n)}}),createTextNode:text=>({text})};
const chartWrap={clientWidth:1000},chart={timeScale:()=>({getVisibleRange:()=>({from:0,to:300}),timeToCoordinate:t=>50+t*2,options:()=>({barSpacing:120})}),panes:()=>[{getHeight:()=>440}]};
const candles={priceToCoordinate:p=>360-(p-100)*10},formatPrice=p=>String(p),fmtTime=t=>String(t);
const layer={style:{},appendChild(n){nodes.push(n)}};
''' + PHOTON_HELPERS + r'''
drawPhotonValueAreas=()=>{};
let narrative;
drawPhotonContext=(mapping,cutoff,view)=>{narrative=cslPhotonNarrative(view);};
const guide={interval:60,traceBasis:'BOS_CONFIRMED',trace:[],snapshots:[{availableAt:180,close:110,trend:1,internal:1,phase:'POSSIBLE_CONTINUATION',high:null,low:null}],events:[
 {kind:'CHOCH',direction:1,price:110,time:60,fromTime:0,availableAt:120,label:'CHOCH'},
 {kind:'BOS',direction:1,price:115,time:120,fromTime:60,availableAt:180,label:'BOS'},
 {kind:'TREND_CHANGE',direction:-1,price:105,time:180,fromTime:120,availableAt:240}]};
const mapping={mappingOnly:true,timeframes:{'1m':guide}};
drawPhotonMapping(mapping,180,[{time:0}],60,layer);
const flatten=()=>nodes.flatMap(n=>n.children),labels=flatten().filter(n=>n.tag==='text').flatMap(n=>n.children.filter(c=>c.text).map(c=>c.text));
const minute={labels,polygons:flatten().filter(n=>n.tag==='polygon').length,hidden:option.hidden,selected:elements['photon-event-timeframe'].value,narrative:narrative.map(n=>n.tf)};
nodes.length=0;
drawPhotonMapping(mapping,180,[{time:0}],900,layer);
console.log(JSON.stringify({minute,other:{text:flatten().filter(n=>n.tag==='text').length,hidden:option.hidden,disabled:option.disabled,selected:elements['photon-event-timeframe'].value,narrative:narrative.map(n=>n.tf)}}));
'''
    result = json.loads(subprocess.run([node], input=script, encoding="utf-8", capture_output=True, check=True).stdout)
    assert any("1m CHoCH" in label for label in result["minute"]["labels"])
    assert any("1m BOS" in label for label in result["minute"]["labels"])
    assert result["minute"]["polygons"] == 0  # future trend change is not visible
    assert result["minute"]["selected"] == "1m" and not result["minute"]["hidden"]
    assert "1m" in result["minute"]["narrative"]
    assert result["other"]["text"] == 0
    assert result["other"]["hidden"] and result["other"]["disabled"]
    assert result["other"]["selected"] == "15m" and "1m" not in result["other"]["narrative"]
