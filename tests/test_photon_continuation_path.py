"""Consecutive closing breaks extend the run without manufacturing a turn."""
import json

import pytest

from crypto_strategy_lab.photon_structure import map_structure
from test_photon_presenter_sequences import js


def bars():
    return [dict(time=i*900, open=p, close=p, high=p+.4, low=p-.4)
            for i, p in enumerate([110, 108, 106, 108, 105, 103, 101])]


def guide(source, children=None):
    return map_structure(source, qualification="CHOCH_PULLBACK", intrabars=children,
                         intrabar_interval=300)


def mirror(source):
    return [dict(time=b["time"], open=300-b["open"], close=300-b["close"],
                 high=300-b["low"], low=300-b["high"]) for b in source]


@pytest.mark.parametrize("bullish", [False, True])
def test_adjacent_break_retains_protected_origin_and_direct_path(bullish):
    source = mirror(bars()) if bullish else bars()
    prefix = guide(source[:-1])
    full = guide(source)
    key = "low" if bullish else "high"
    assert full["snapshots"][-1][key] == prefix["snapshots"][-1][key]
    latest = [e for e in full["events"] if e["availableAt"] == 6300]
    assert any(e["kind"] == "BOS" for e in latest)
    assert not any(e["kind"] == "SWING" for e in latest)
    assert len(full["trace"]) == len(prefix["trace"]) + 1
    lines = js('cslPhotonSwingLines('+json.dumps(full)+',6300)')
    # The extension follows the retained protected origin without a new turn.
    assert len(lines[-1]) == 3
    assert lines[-1][-2]["time"] == prefix["snapshots"][-1][key]["time"]
    assert lines[-1][-1]["time"] == 4500
    assert all(p["availableAt"] <= 6300 for p in lines[-1])


@pytest.mark.parametrize("bullish", [False, True])
@pytest.mark.parametrize("evidence", ["none", "ordered", "same_child", "missing", "opposite_order"])
def test_dual_boundary_candle_requires_ordered_extreme_evidence(bullish, evidence):
    source = bars()[:-1] + [dict(time=5400, open=103, high=110, low=100, close=101)]
    children = [dict(time=5400, open=103, high=110, low=102, close=104),
                dict(time=5700, open=104, high=105, low=100, close=101),
                dict(time=6000, open=101, high=102, low=100.5, close=101)]
    if evidence == "none":
        children = None
    elif evidence == "missing":
        children.pop()
    elif evidence == "same_child":
        children[0]["low"] = 100
    elif evidence == "opposite_order":
        children[0].update(high=104, low=100, close=101)
        children[1].update(open=101, high=110, low=100.5)
    if bullish:
        source = mirror(source)
        children = mirror(children) if children else None
    result = guide(source, children)
    key = "low" if bullish else "high"
    latest = [e for e in result["events"] if e["availableAt"] == 6300]
    assert any(e["kind"] == "BOS" for e in latest)
    assert any(e["kind"] == "SWING" for e in latest) == (evidence == "ordered")
    if evidence == "ordered":
        assert result["snapshots"][-1][key]["time"] == 5400
        weak = result["snapshots"][-1]["high" if bullish else "low"]
        assert weak["time"] == 5700
    else:
        assert result["snapshots"][-1][key] == result["snapshots"][-2][key]
    assert any(e["kind"] == "AMBIGUOUS" for e in latest) == (evidence in ("none", "missing", "same_child"))
    # Full source cannot leak a later parent candle into an earlier prefix.
    prefix = guide(source[:-1], children)
    for k in ("events", "trace", "snapshots"):
        assert prefix[k] == [e for e in result[k] if e["availableAt"] <= 5400]


def test_april6_4h_continuation_does_not_insert_7070_low():
    from pathlib import Path
    data = json.loads((Path(__file__).parent / "fixtures/photon_btc_april_2020.json").read_text())
    source = data["parents"] + [
        dict(time=1586160000, open=7024.45, high=7142.04, low=7010.64, close=7095.36),
        dict(time=1586174400, open=7095.09, high=7159.69, low=7026.77, close=7139.13),
        dict(time=1586188800, open=7138.74, high=7302, low=7070, close=7263.84),
        dict(time=1586203200, open=7263.15, high=7370, low=7185.52, close=7325.73),
    ]
    result = map_structure(source, 14400, qualification="CHOCH_PULLBACK")
    before = next(s for s in result["snapshots"] if s["availableAt"] == 1586188800)
    after = next(s for s in result["snapshots"] if s["availableAt"] == 1586203200)
    assert after["low"] == before["low"]
    assert not any(e["kind"] == "SWING" and e["price"] in (7070, 7185.52) for e in result["events"])
    lines = js('cslPhotonSwingLines('+json.dumps(result)+',1586217600)')
    assert not any(p["price"] in (7070, 7185.52) for line in lines for p in line)
