"""Close-break experiment applies uniformly to every mapped timeframe."""
import pytest

from crypto_strategy_lab.photon_structure import map_structure


@pytest.mark.parametrize("interval", [900, 14400, 86400, 604800])
@pytest.mark.parametrize("mirror", [False, True])
def test_continuation_needs_close_not_counter_choch(interval, mirror):
    prices = [110, 108, 106, 108, 105, 103, 101]
    bars = [dict(time=i*interval, open=p, high=p+.4, low=p-.4, close=p)
            for i, p in enumerate(prices)]
    if mirror:
        bars = [dict(time=b["time"], open=300-b["open"], close=300-b["close"],
                     high=300-b["low"], low=300-b["high"]) for b in bars]
    result = map_structure(bars, interval, qualification="CHOCH_PULLBACK")
    assert not any(e["kind"] == "CHOCH" for e in result["events"])
    bos = [e for e in result["events"] if e["kind"] == "BOS"]
    assert [e["availableAt"] for e in bos] == [6*interval, 7*interval]
    assert all(e["direction"] == (1 if mirror else -1) for e in bos)
    assert result["snapshots"][-2]["high" if mirror else "low"]["eligible"]
    prefix = map_structure(bars[:-1], interval, qualification="CHOCH_PULLBACK")
    for key in ("events", "trace", "snapshots"):
        assert prefix[key] == [e for e in result[key] if e["availableAt"] <= 6*interval]
