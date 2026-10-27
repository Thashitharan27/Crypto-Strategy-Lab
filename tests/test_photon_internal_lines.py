import json
import shutil
import subprocess

import pytest

from crypto_strategy_lab.visualizer_photon import PHOTON_HELPERS


def evaluate(script):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is unavailable')
    return json.loads(subprocess.run([node], input=PHOTON_HELPERS + script,
                                    encoding='utf-8', capture_output=True,
                                    check=True).stdout)


def test_internal_turns_are_visible_without_a_swing_break_and_only_when_known():
    result = evaluate(r"""
const point=(time,price)=>({time,price});
const h0=point(0,110),l0=point(10,95),h1=point(20,108),l1=point(30,96);
const guide={interval:10,trace:[],events:[],snapshots:[
 {availableAt:30,internalHigh:h0},
 {availableAt:40,internalHigh:h0,internalLow:l0},
 {availableAt:50,internalHigh:h1,internalLow:l0},
 {availableAt:60,internalHigh:h1,internalLow:l1}]};
console.log(JSON.stringify({before:cslPhotonInternalLines(guide,39),
 middle:cslPhotonInternalLines(guide,50),after:cslPhotonInternalLines(guide,60),
 cropped:cslPhotonInternalLines(guide,60,25),swings:cslPhotonSwingLines(guide,60)}));
""")
    assert result['before'] == []
    assert [p['time'] for p in result['middle'][0]] == [0, 10, 20]
    assert [p['availableAt'] for p in result['middle'][0]] == [30, 40, 50]
    assert [p['time'] for p in result['after'][0]] == [0, 10, 20, 30]
    assert [p['time'] for p in result['cropped'][0]] == [20, 30]
    assert result['swings'] == []


@pytest.mark.parametrize('explicit_gap', [False, True])
def test_internal_lines_do_not_connect_across_missing_data(explicit_gap):
    result = evaluate(r"""
const guide={interval:10,events:GAPS,snapshots:[
 {availableAt:20,internalHigh:{time:0,price:110}},
 {availableAt:30,internalHigh:{time:0,price:110},internalLow:{time:10,price:90}},
 {availableAt:RESET,internalHigh:{time:RESET-10,price:120}},
 {availableAt:RESET+10,internalHigh:{time:RESET-10,price:120},internalLow:{time:RESET,price:100}}]};
console.log(JSON.stringify(cslPhotonInternalLines(guide,100)));
""".replace('GAPS', '[{kind:"GAP",availableAt:40}]' if explicit_gap else '[]')
        .replace('RESET', '40' if explicit_gap else '60'))
    assert len(result) == 2
    assert [p['price'] for p in result[0]] == [110, 90]
    assert [p['price'] for p in result[1]] == [120, 100]


def test_same_candle_high_low_order_is_not_invented():
    result = evaluate(r"""
console.log(JSON.stringify(cslPhotonInternalLines({interval:10,events:[],snapshots:[
 {availableAt:20,internalHigh:{time:0,price:110}},
 {availableAt:30,internalHigh:{time:0,price:110},internalLow:{time:0,price:90}},
 {availableAt:40,internalHigh:{time:20,price:108},internalLow:{time:0,price:90}}
]},40)));
""")
    assert result == []
