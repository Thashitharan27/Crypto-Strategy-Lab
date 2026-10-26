"""Every close break updates structure; child wick times affect geometry only."""
import pytest

from crypto_strategy_lab.photon_structure import map_structure


def source():
    return [dict(time=i*900, open=p, close=p, high=p+.4, low=p-.4)
            for i, p in enumerate([110, 108, 106, 108, 105, 103, 101])]


def mirror(bars):
    return [dict(time=b["time"], open=300-b["open"], close=300-b["close"],
                 high=300-b["low"], low=300-b["high"]) for b in bars]


@pytest.mark.parametrize("bullish", [False, True])
@pytest.mark.parametrize("evidence", ["matching", "none", "missing", "duplicate", "mismatch", "same_child"])
def test_extreme_times_do_not_change_prices_or_close_confirmation(bullish, evidence):
    bars = source()
    children = [dict(time=5400, open=101, high=101.4, low=100.9, close=101.1),
                dict(time=5700, open=101.1, high=101.2, low=100.8, close=101),
                dict(time=6000, open=101, high=101.1, low=100.6, close=101)]
    if evidence == "none":
        children = None
    elif evidence == "missing":
        children.pop()
    elif evidence == "duplicate":
        children.append(dict(children[-1]))
    elif evidence == "mismatch":
        children[-1]["close"] = 101.05
    elif evidence == "same_child":
        children[0]["low"] = 100.6
    if bullish:
        bars = mirror(bars)
        children = mirror(children) if children else None
    baseline = map_structure(bars, qualification="CHOCH_PULLBACK")
    result = map_structure(bars, qualification="CHOCH_PULLBACK", intrabars=children,
                           intrabar_interval=300)
    # Consecutive breaks once again admit a new protected origin.
    latest = [e for e in result["events"] if e["availableAt"] == 6300]
    assert [e["kind"] for e in latest] == ["BOS", "SWING"]
    assert [(e["kind"], e["price"], e["availableAt"]) for e in result["events"]] == [
        (e["kind"], e["price"], e["availableAt"]) for e in baseline["events"]]
    weak = result["snapshots"][-1]["high" if bullish else "low"]
    protected = result["snapshots"][-1]["low" if bullish else "high"]
    assert weak["time"] == (6000 if evidence == "matching" else 5400)
    assert protected["time"] == 5400
    assert protected["price"] != baseline["snapshots"][-2]["low" if bullish else "high"]["price"]
    # Full child history must not expose an unclosed parent's structure early.
    prefix = map_structure(bars[:-1], qualification="CHOCH_PULLBACK", intrabars=children,
                           intrabar_interval=300)
    for key in ("events", "trace", "snapshots"):
        assert prefix[key] == [e for e in result[key] if e["availableAt"] <= 5400]


def test_actual_4h_points_use_1600_low_and_1945_high():
    import json
    from pathlib import Path
    from test_photon_presenter_sequences import js

    root = Path(__file__).parent / "fixtures"
    initial = json.loads((root / "photon_btc_april_2020.json").read_text())
    later = json.loads((root / "photon_btc_april6_extremes.json").read_text())
    bars = initial["parents"] + later["parents"]
    children = initial["children"] + later["children"]
    result = map_structure(bars, 14400, qualification="CHOCH_PULLBACK", intrabars=children)
    points = result["trace"]
    assert any(p["price"] == 7070 and p["fromTime"] == 1586188800
               and p["availableAt"] == 1586203200 for p in points)
    assert any(p["price"] == 7302 and p["fromTime"] == 1586202300
               and p["availableAt"] == 1586217600 for p in points)
    lines = js('cslPhotonSwingLines('+json.dumps(result)+',1586217600)')
    actual = [(p["time"], p["price"]) for line in lines for p in line]
    assert (1586188800, 7070) in actual
    assert (1586202300, 7302) in actual
    assert (1586188800, 7302) not in actual
