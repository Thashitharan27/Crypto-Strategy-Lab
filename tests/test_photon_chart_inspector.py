import json
import shutil
import subprocess

import pytest

from crypto_strategy_lab.visualizer_photon_inspector import PHOTON_INSPECTOR_HELPERS


def test_label_controls_preserve_type_density_and_pinned_selection():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is unavailable')
    script = PHOTON_INSPECTOR_HELPERS + r"""
const controls={
  'photon-text-bos':{checked:true},'photon-text-choch':{checked:false},
  'photon-text-trend':{checked:false},'photon-label-density':{value:'RECENT'},
  'photon-event-select':{value:'',dataset:{pinned:'false'}}
};
const $=id=>controls[id];
const events=Array.from({length:8},(_,i)=>({kind:'BOS',availableAt:i,direction:1}));
const visible=()=>events.map(e=>cslPhotonTextVisible('15m',e,events));
const recent=visible();
controls['photon-event-select']={value:'15m:0:BOS:1',dataset:{pinned:'true'}};
const pinned=visible();
controls['photon-label-density'].value='ALL';
const all=visible();
controls['photon-text-bos'].checked=false;
console.log(JSON.stringify({recent,pinned,all,hidden:visible(),
  choch:cslPhotonTextVisible('15m',{kind:'CHOCH'},events),
  trend:cslPhotonTextVisible('15m',{kind:'TREND_CHANGE'},events)}));
"""
    result = subprocess.run([node, '-'], input=script, text=True, encoding='utf-8',
                            capture_output=True, check=True)
    actual = json.loads(result.stdout)
    assert actual['recent'] == [False] * 5 + [True] * 3
    assert actual['pinned'] == [True] + [False] * 4 + [True] * 3
    assert actual['all'] == [True] * 8
    assert actual['hidden'] == [False] * 8
    assert actual['choch'] is False
    assert actual['trend'] is False
