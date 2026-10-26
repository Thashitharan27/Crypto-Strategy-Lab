"""Actual BTC replay regression and conservative lower-timeframe evidence rules."""
import json
from pathlib import Path

import pytest

from crypto_strategy_lab.photon_structure import build_mapping, map_structure
from test_photon_presenter_sequences import js


def fixture():
    return json.loads((Path(__file__).parent / "fixtures/photon_btc_april_2020.json").read_text())


def guide(parents, children):
    return map_structure(parents, 14400, qualification="CHOCH_PULLBACK", intrabars=children)


def test_actual_april_pullback_is_retained_after_parent_close():
    data = fixture()
    result = guide(data["parents"], data["children"])
    at = 1586116800  # April 5 20:00: candle starting 16:00 has closed.
    events = [e for e in result["events"] if e["availableAt"] == at]
    assert [(e["kind"], e["direction"]) for e in events] == [("CHOCH", -1), ("CHOCH", 1)]
    assert all(e["orderBasis"] == "LOWER_TIMEFRAME" and e["sourceInterval"] == 900 for e in events)
    state = next(s for s in result["snapshots"] if s["availableAt"] == at)
    assert state["high"]["price"] == 7020 and state["high"]["eligible"]
    assert not state["high"]["confirmed"]
    bos = next(e for e in result["events"] if e["kind"] == "BOS" and e["price"] == 7020)
    assert bos["availableAt"] == 1586160000  # April 6 08:00.
    assert result["snapshots"][-1]["low"]["price"] == 6668.02
    segments = js('cslPhotonSwingLines(' + json.dumps(result) + ',1586160000)')
    assert [(p["time"], p["price"]) for p in segments[-1]][-3:] == [
        (1585987200, 6629.99), (1586030400, 7020), (1586102400, 6668.02)]
    before = js('cslPhotonSwingLines(' + json.dumps(result) + ',1586159999)')
    assert all(p["price"] != 6668.02 for line in before for p in line)
    for n in range(1, len(data["parents"]) + 1):
        parents = data["parents"][:n]
        cutoff = parents[-1]["time"] + 14400
        prefix = guide(parents, [c for c in data["children"] if c["time"] + 900 <= cutoff])
        for key in ("events", "trace", "snapshots"):
            assert prefix[key] == [v for v in result[key] if v["availableAt"] <= cutoff]


@pytest.mark.parametrize("damage", ["missing", "duplicate", "mismatch", "same_child", "none"])
def test_unreliable_or_unordered_source_remains_ambiguous(damage):
    data = fixture()
    children = [c for c in data["children"] if c["time"] >= 1586102400]
    if damage == "missing":
        children.pop()
    elif damage == "duplicate":
        children.append(dict(children[-1]))
    elif damage == "mismatch":
        children[-1]["close"] += 1
    elif damage == "same_child":
        children[0]["high"] = 6853.15
        children[0]["low"] = 6668.02
    else:
        children = None
    result = guide(data["parents"], children)
    assert any(e["kind"] == "AMBIGUOUS" and e["availableAt"] == 1586116800 for e in result["events"])
    assert not any(e["kind"] == "BOS" and e["price"] == 7020 for e in result["events"])


def test_ordered_crossings_are_symmetric():
    data = fixture()
    def mirror(bars):
        return [dict(time=b["time"], open=15000-b["open"], close=15000-b["close"],
                     high=15000-b["low"], low=15000-b["high"]) for b in bars]
    a = guide(data["parents"], data["children"])
    b = guide(mirror(data["parents"]), mirror(data["children"]))
    assert [(e["kind"], e["direction"], e["availableAt"]) for e in a["events"]] == [
        (e["kind"], -e["direction"], e["availableAt"]) for e in b["events"]]


def test_mapping_builder_supplies_only_closed_4h_source_evidence():
    data = fixture()
    actual = {c["time"]: c for c in data["children"]}
    # Fill other parent buckets with authored child candles preserving OHLC.
    source = [actual.get(p["time"] + i*900, dict(p, time=p["time"] + i*900))
              for p in data["parents"] for i in range(16)]
    full = build_mapping(source)["timeframes"]["4h"]
    assert any(e["kind"] == "BOS" and e["price"] == 7020 for e in full["events"])
    cutoff = 1586116800 - 900
    prefix = build_mapping([c for c in source if c["time"] + 900 <= cutoff])["timeframes"]["4h"]
    for key in ("events", "trace", "snapshots"):
        assert prefix[key] == [v for v in full[key] if v["availableAt"] <= cutoff]
