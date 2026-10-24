import json
import shutil
import subprocess
import re
from types import SimpleNamespace

import pytest

from crypto_strategy_lab.visualizer_drawings import DRAWING_HELPERS


def shapes(tool, points=None):
    node=shutil.which('node')
    if not node:pytest.skip('Node required for drawing geometry')
    item={'tool':tool,'points':points or [{'time':10,'price':100},{'time':20,'price':80}],'text':'<b>plain text</b>'}
    script=DRAWING_HELPERS+'\nconst item='+json.dumps(item)+";console.log(JSON.stringify(cslDrawingShapes(item,p=>({x:p.time*2,y:200-p.price}),200,200)));"
    return json.loads(subprocess.run([node],input=script,text=True,encoding='utf-8',capture_output=True,check=True).stdout)


def test_delete_guard_preserves_typing_and_modified_shortcuts():
    node=shutil.which('node')
    if not node:pytest.skip('Node required for Delete keyboard guard')
    script=DRAWING_HELPERS+'''
const field={closest:()=>({})},plain={closest:()=>null},event={key:'Delete',target:plain};
console.log(JSON.stringify({normal:cslChartDeleteAllowed(event,plain),input:cslChartDeleteAllowed({...event,target:field},plain),focusedInput:cslChartDeleteAllowed(event,field),editable:cslChartDeleteAllowed(event,{isContentEditable:true}),ctrl:cslChartDeleteAllowed({...event,ctrlKey:true},plain),composing:cslChartDeleteAllowed({...event,isComposing:true},plain),handled:cslChartDeleteAllowed({...event,defaultPrevented:true},plain),backspace:cslChartDeleteAllowed({...event,key:'Backspace'},plain)}));
'''
    result=json.loads(subprocess.run([node],input=script,text=True,encoding='utf-8',capture_output=True,check=True).stdout)
    assert result.pop('normal')
    assert not any(result.values())


def test_trend_ray_and_fixed_price_lines_use_chart_coordinates():
    trend=shapes('trend')[0]['attrs']
    assert (trend['x1'],trend['y1'],trend['x2'],trend['y2'])==(20,100,40,120)
    ray=shapes('ray')[0]['attrs']
    assert (ray['x2'],ray['y2'])==(200,280)
    horizontal=shapes('hline')[0]['attrs']
    assert (horizontal['x1'],horizontal['x2'],horizontal['y1'])==(0,200,100)
    vertical=shapes('vline')[0]['attrs']
    assert (vertical['x1'],vertical['y1'],vertical['y2'])==(20,0,200)


def test_rectangle_and_fibonacci_work_in_both_anchor_directions():
    for points in ([{'time':10,'price':100},{'time':20,'price':80}],[{'time':20,'price':80},{'time':10,'price':100}]):
        rect=shapes('rect',points)[0]['attrs']
        assert (rect['x'],rect['y'],rect['width'],rect['height'])==(20,100,20,20)
        fib=shapes('fib',points)
        assert len(fib)==16
        half=next(item for item in fib if item.get('text','').startswith('0.5 '))
        assert half['text']=='0.5 · 90.00'
        assert half['attrs']['y']==106


def test_measure_and_note_preserve_values_without_html_markup():
    measure=shapes('measure')[-1]['text']
    assert '-20.00 (-20.00%)' in measure
    note=shapes('text')[0]
    assert note['tag']=='text' and note['text']=='<b>plain text</b>'


@pytest.mark.parametrize('follow',[False,True])
def test_replay_chart_updates_only_the_tail_and_preserves_view(follow):
    from crypto_strategy_lab.strategy_visualizer_browser_v2 import build_browser_visualizer_v2_html
    from crypto_strategy_lab.visualizer_replay import REPLAY_HELPERS
    node=shutil.which('node')
    if not node:pytest.skip('Node required for chart update checks')
    model=SimpleNamespace(seed=SimpleNamespace(request=SimpleNamespace(symbol='BTCUSDT',strategy_timeframe='15m')),
                          manifest={},run_dir=SimpleNamespace(name='test'),trade_count=0)
    html=build_browser_visualizer_v2_html(model,'update')
    function=re.search(r'  function updateReplayChart\(\) \{.*?\n  \}',html,re.S).group(0)
    script=REPLAY_HELPERS+function+'''
const old=Array.from({length:1000},(_,time)=>({time,close:1}));
const next=old.map(point=>({...point}));next[999].close=2;next.push({time:1000,close:3});
const updates=[];let resets=0,range;
const series={update:point=>updates.push(point),setData:()=>resets++};
const replaySeries=[{series,kind:'candles',data:old}];
const payload={candles:next},scale={getVisibleLogicalRange:()=>({from:900,to:1010}),setVisibleLogicalRange:value=>range=value};
const chart={timeScale:()=>scale},$=()=>({checked:FOLLOW});
const redrawOverlays=()=>{},requestAnimationFrame=callback=>callback();
updateReplayChart();console.log(JSON.stringify({updates,resets,range}));
'''.replace('FOLLOW',str(follow).lower())
    result=json.loads(subprocess.run([node],input=script,text=True,encoding='utf-8',capture_output=True,check=True).stdout)
    assert result['resets']==0
    assert result['updates']==[{'time':999,'close':2},{'time':1000,'close':3}]
    shift=int(follow)
    assert result['range']=={'from':900+shift,'to':1010+shift}
