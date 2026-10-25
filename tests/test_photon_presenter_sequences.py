"""Normalized, authored OHLC scenarios for the narrated rules, NOT video OHLC.

These validate the event relationships in docs/photon_presenter_reference.md.
They do not establish exact candle/price equivalence to the EURUSD source feed.
"""
import json
import shutil
import subprocess

import pytest

from crypto_strategy_lab.photon_structure import aggregate_closed, build_mapping, map_structure
from crypto_strategy_lab.visualizer_photon import PHOTON_HELPERS


def reference_bars():
    # Part 1's ordering: bearish BOS -> bullish CHoCH -> bearish CHoCH ->
    # failed continuation / bullish CHoCH -> bullish swing change.
    prices = [110,108,106,108,105,103,101,102,100,98,99,97,
              99,101,104,103,105,102,100,101,99,102,104,108,111,113]
    return [dict(time=i*900, open=p, high=p+.4, low=p-.4, close=p)
            for i,p in enumerate(prices)]


def mapping(source):
    return map_structure(source, qualification="CHOCH_PULLBACK")


def js(expression):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node needed for replay presentation checks")
    result = subprocess.run([node], input=PHOTON_HELPERS+"\nconsole.log(JSON.stringify("+expression+"));",
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def test_part1_event_relationships_include_failed_continuation():
    result = mapping(reference_bars())
    events = [(e["time"]//900, e["kind"], e["direction"]) for e in result["events"]
              if e["kind"] in ("BOS", "TREND_CHANGE", "CHOCH")]
    assert events == [(5,"BOS",-1),(13,"CHOCH",1),(17,"CHOCH",-1),
                      (21,"CHOCH",1),(24,"TREND_CHANGE",1)]
    snapshots = result["snapshots"]
    assert snapshots[13]["phase"] == "POSSIBLE_PULLBACK"
    assert snapshots[17]["phase"] == "POSSIBLE_CONTINUATION"
    assert snapshots[21]["phase"] == "POSSIBLE_PULLBACK"
    assert all(s["trend"] == -1 for s in snapshots[5:24])
    assert snapshots[24]["trend"] == 1
    assert snapshots[21]["high"]["strong"]
    # A CHoCH qualifies a possible endpoint, not a confirmed lower swing low.
    assert snapshots[13]["low"]["eligible"]
    assert not snapshots[13]["low"]["confirmed"]
    assert [e["availableAt"] for e in result["trace"]] == [5400,5400,22500,22500]


def test_part2_wick_choch_precedes_close_confirmed_swing_change():
    source = reference_bars()
    # Make the first bullish internal break wick-only; retain the broken level
    # at the close. This cannot change the larger bearish swing direction.
    source[13] = dict(source[13], open=99.4, low=99, close=99.4)
    # Mirror for Part 2's bullish swing -> bearish internal shift -> bearish swing.
    mirror = [dict(time=b["time"],open=300-b["open"],close=300-b["close"],
                   high=300-b["low"],low=300-b["high"]) for b in source]
    result = mapping(mirror)
    e = next(e for e in result["events"] if e["kind"]=="CHOCH")
    assert e["time"] == 13*900 and e["direction"] == -1
    assert mirror[13]["close"] == e["price"]
    assert mirror[13]["low"] < e["price"]
    assert result["snapshots"][13]["trend"] == 1
    assert result["snapshots"][24]["trend"] == -1


def test_inside_bar_alone_is_not_choch_but_later_minor_high_break_is():
    values = [(10,8),(9,7),(8,6),(7.9,6.1),(7.8,5.5),(8.1,5.9)]
    source = [dict(time=i*900,open=(h+l)/2,close=(h+l)/2,high=h,low=l)
              for i,(h,l) in enumerate(values)]
    result = mapping(source)
    assert not any(e["kind"]=="CHOCH" and e["time"]<=4*900 for e in result["events"])
    e = next(e for e in result["events"] if e["kind"]=="CHOCH")
    assert (e["time"],e["fromTime"],e["price"],e["direction"]) == (4500,2700,7.9,1)


def test_weak_swing_wick_sweep_does_not_change_swing_direction():
    source = reference_bars()
    source[23] = dict(source[23], high=109, close=108)
    result = mapping(source)
    assert result["snapshots"][23]["trend"] == -1
    assert result["snapshots"][24]["trend"] == 1


def test_event_qualified_mapping_is_prefix_safe_and_strength_independent():
    source = reference_bars()
    full = mapping(source)
    assert full == map_structure(source,strength=7,qualification="CHOCH_PULLBACK")
    for n in range(1,len(source)+1):
        prefix = mapping(source[:n])
        assert prefix["snapshots"] == full["snapshots"][:n]
        for key in ("events","trace"):
            assert prefix[key] == [e for e in full[key] if e["availableAt"]<=n*900]


def test_daily_and_monday_weekly_buckets_wait_for_complete_source():
    # Monday 1970-01-05. First source candle starts exactly on weekly boundary.
    start = 345600
    source = [dict(time=start+i*900,open=100,high=101,low=99,close=100)
              for i in range(7*96)]
    assert len(aggregate_closed(source[:95],target_seconds=86400)) == 0
    assert len(aggregate_closed(source[:96],target_seconds=86400)) == 1
    assert aggregate_closed(source[:-1],target_seconds=604800,offset=start) == []
    week = aggregate_closed(source,target_seconds=604800,offset=start)
    assert len(week)==1 and week[0]["time"]==start
    assert aggregate_closed(source[:10]+source[11:],target_seconds=604800,offset=start)==[]
    result = build_mapping(source)
    assert result["timeframes"]["1w"]["snapshots"][0]["availableAt"] == start+604800
    view = js('cslPhotonView('+json.dumps(result)+','+str(start+604799)+')')
    assert view["1w"]["state"] is None


def test_narrative_does_not_force_parent_direction_or_claim_confirmed_pullback():
    view = {"1w":{"state":{"trend":-1,"internal":-1,"availableAt":1}},
            "1d":{"state":{"trend":-1,"internal":1,"availableAt":1}},
            "4h":{"state":{"trend":1,"internal":1,"availableAt":1}},
            "15m":{"state":{"trend":-1,"internal":1,"availableAt":1}}}
    rows = js('cslPhotonNarrative('+json.dumps(view)+')')
    assert [r["direction"] for r in rows] == ["Bearish","Bearish","Bullish","Bearish"]
    assert rows[2]["relation"] == "Possible Daily pullback"
    assert rows[3]["relation"] == "Possible 4H pullback"
    assert rows[3]["phase"] == "Possible internal pullback"
    unknown = js('cslPhotonNarrative({})')
    assert all(r["direction"]=="Unknown" for r in unknown)


def test_next_event_is_bounded_by_day_and_never_selects_pivot_noise():
    fixture = {"timeframes":{"15m":{"events":[
        dict(kind="PIVOT",availableAt=110),dict(kind="CHOCH",availableAt=120),
        dict(kind="BOS",availableAt=200)]}}}
    serialized = json.dumps(fixture)
    assert js('cslPhotonNextEvent('+serialized+',100,150)') == 120
    assert js('cslPhotonNextEvent('+serialized+',120,150)') is None
    assert js('cslPhotonNextEvent('+serialized+',120,200)') == 200


def test_developing_path_preserves_run_extreme_before_current_reaction():
    result = mapping(reference_bars()[:19])
    segments = js('cslPhotonSwingLines('+json.dumps(result)+',17100)')
    path = js('cslPhotonDevelopingLeg('+json.dumps(result)+',17100,'+json.dumps(segments)+')')
    assert [(p["time"],p["price"]) for p in path] == [(2700,108.4),(9900,96.6),(16200,100)]
    assert all(p["availableAt"]<=17100 for p in path)


def test_context_history_can_be_longer_than_detail_history_without_new_orders():
    source = reference_bars()
    result = build_mapping(source, detail_start=10*900)
    assert result["mappingOnly"]
    assert result["schemaVersion"] == 2
    assert all(s["availableAt"]>10*900 for s in result["timeframes"]["15m"]["snapshots"])
    assert set(result["timeframes"]) == {"1w","1d","4h","15m"}


def test_real_mtf_closes_are_prefix_safe_across_week_boundaries():
    import math
    start = 345600
    source = []
    for i in range(8*672):
        p = 100+15*math.sin(i/420)+3*math.sin(i/17)
        source.append(dict(time=start+i*900,open=p,high=p+1,low=p-1,close=p))
    full = build_mapping(source)
    for n in (95,96,671,672,673,1343,1344,4*672-1,4*672,7*672,8*672-1):
        prefix = build_mapping(source[:n])
        cutoff = start+n*900
        for tf in full["timeframes"]:
            for key in ("snapshots","events","trace"):
                assert prefix["timeframes"][tf][key] == [
                    item for item in full["timeframes"][tf][key] if item["availableAt"]<=cutoff]


def test_two_sided_internal_cross_is_unknown_not_a_guessed_choch():
    source = reference_bars()[:13]
    # Both active references are crossed with no intrabar ordering evidence.
    source.append(dict(time=13*900,open=99,close=99,high=110,low=90))
    result = mapping(source)
    at = 14*900
    assert any(e["kind"]=="AMBIGUOUS" and e["availableAt"]==at for e in result["events"])
    assert not any(e["kind"]=="CHOCH" and e["availableAt"]==at for e in result["events"])
    assert result["snapshots"][-1]["internal"]==0


def test_gap_cannot_carry_candidate_or_internal_references_forward():
    source = reference_bars()
    source = source[:18]+[dict(b,time=b["time"]+900) for b in source[18:]]
    state = mapping(source)["snapshots"][18]
    assert state["trend"]==0 and state["internal"]==0
    assert state["internalHigh"] is None and state["internalLow"] is None
    assert state["developing"]==[]


def test_event_qualification_is_symmetric_for_bulls_and_bears():
    source = reference_bars()
    mirror = [dict(time=b["time"],open=300-b["open"],close=300-b["close"],
                   high=300-b["low"],low=300-b["high"]) for b in source]
    a,b = mapping(source),mapping(mirror)
    assert [(s["trend"],s["internal"]) for s in a["snapshots"]] == [
        (-s["trend"],-s["internal"]) for s in b["snapshots"]]
    assert [(e["kind"],e["direction"],e["availableAt"]) for e in a["events"]] == [
        (e["kind"],-e["direction"],e["availableAt"]) for e in b["events"]]
