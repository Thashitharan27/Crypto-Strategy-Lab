import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from crypto_strategy_lab.photon_lesson import options,evidence
from crypto_strategy_lab.photon_structure import build_mapping
from crypto_strategy_lab.visualizer_photon_zones import PHOTON_ZONE_HELPERS
from test_photon_lesson import proof_scenario


def js(code):
    node=shutil.which('node')
    if not node:pytest.skip('Node required for chart annotation checks')
    r=subprocess.run([node],input=PHOTON_ZONE_HELPERS+'\n'+code,encoding='utf-8',capture_output=True,check=True)
    return json.loads(r.stdout)


def fixture():
    z,g=proof_scenario()
    proof=evidence(z,g,3600)
    # Illustrative projection geometry. Rule qualification is tested separately
    # against actual causal candle sequences in test_photon_lesson.py.
    z.update(breakTime=1800,availableAt=2700,brokenLevel=100,lessonModel='PIVOT',baseCandles=1)
    proof['breakReference']=dict(price=109,time=1800,fromTime=0,availableAt=2700)
    proof['departurePrice']=110
    return {**z,'lessonEvidence':proof}


def test_annotation_geometry_is_hidden_before_known_and_retains_presentation_sequence():
    z=fixture()
    data=js('const z='+json.dumps(z)+';console.log(JSON.stringify([cslPhotonLessonMarks(z,2699),cslPhotonLessonMarks(z,2700),cslPhotonLessonMarks(z,3600)]));')
    assert data[0]==[]
    assert [m['kind'] for m in data[1]]==['BASE']  # later evidence cannot appear early
    marks={m['kind']:m for m in data[2]}
    assert set(marks)=={'BASE','DEPARTURE','BOS','SWEEP','INDUCEMENT','FLIP','STACK','RETURN'}
    assert marks['BASE']['t1']==900 and marks['BASE']['t2']==1800
    assert marks['BOS']['p1']==109 and marks['BOS']['knownAt']==2700
    assert marks['SWEEP']['p1']==95
    assert marks['INDUCEMENT']['p1']==105
    assert marks['RETURN']['t1']==2700 and marks['RETURN']['label']=='3 · First mitigation'
    assert all(m['knownAt']<=3600 for m in marks.values())


def test_legacy_origin_box_does_not_expand_to_include_later_candles():
    z=fixture();z.pop('lessonModel');z['breakTime']=9000
    marks=js('console.log(JSON.stringify(cslPhotonLessonMarks('+json.dumps(z)+',3600)));')
    base=marks[0]
    assert base['t2']==1800  # exactly the one originating 15m candle


def test_pivot_departure_is_not_mislabeled_as_a_bos():
    z=fixture();z['confirmedBy']='THRUST';z['state']='FRESH'
    text=js("function formatPrice(p){return String(p)};function fmtTime(t){return String(t)};console.log(JSON.stringify(cslPhotonZoneText("+json.dumps(z)+",null)));")
    assert 'by departure close through' in text


def test_visual_evidence_collection_preserves_structure_and_zone_bounds():
    import math
    bars=[dict(time=i*900,open=100+math.sin(i/4)*5,high=101+math.sin(i/4)*5,
        low=99+math.sin(i/4)*5,close=100.3+math.sin(i/4)*5) for i in range(200)]
    legacy=build_mapping(bars)
    visual=build_mapping(bars,lesson_options=options(None,collect_evidence=True))
    for tf,guide in legacy['timeframes'].items():
        changed=visual['timeframes'][tf]
        for k in ('events','trace','snapshots'):assert changed[k]==guide[k]
        if 'supplyDemand' in guide:
            for k in ('zones','events'):assert changed['supplyDemand'][k]==guide['supplyDemand'][k]
            assert 'qualityEvents' in changed['supplyDemand']


def test_metadata_reference_times_are_no_later_than_evidence_time():
    z,g=proof_scenario()
    for at in (1800,2700,3600):
        p=evidence(z,g,at)
        for k in ('breakReference','flipReference','stackReference'):
            if p[k]:assert p[k]['availableAt']<=at
        if p['returnAvailableAt'] is not None:assert p['returnAvailableAt']<=at


def test_renderer_produces_real_shapes_and_skips_missing_future_or_offscreen_evidence():
    z=fixture();z['breakTime']=1800  # put the departure on the next native candle
    code='''
const shapes=[],labels=[];
const candles={priceToCoordinate:p=>400-(p-80)*10};
function fmtTime(t){return String(t)};
function make(tag,attrs,title){shapes.push({tag,attrs,title})};
function placeLabel(text,x,y,color,title){labels.push(text)};
const z=ZONE;
const count=drawPhotonLessonMarks(z,4500,[{time:0}],900,make,t=>t/10,800,500,placeLabel);
console.log(JSON.stringify({count,shapes,labels}));
'''.replace('ZONE',json.dumps(z))
    result=js(code)
    assert result['count']==8
    assert any(s['tag']=='rect' and s['attrs'].get('data-photon-lesson')=='BASE' for s in result['shapes'])
    assert any(s['tag']=='circle' and s['attrs'].get('data-photon-lesson')=='RETURN' for s in result['shapes'])
    assert 'Structure broken' in result['labels']
