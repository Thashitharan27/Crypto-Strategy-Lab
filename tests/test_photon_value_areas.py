"""Crypto mapping semantics: causal ranges, structural origins and zone lifecycle."""
import json
import shutil
import subprocess

import pytest

from crypto_strategy_lab.photon_structure import build_mapping
from crypto_strategy_lab.photon_zones import attach_ranges, build_zones, range_position, zone_location
from crypto_strategy_lab.visualizer_photon import PHOTON_HELPERS


def native_bars(interval=900):
    values=[(12,13,8,12.5),(11,12,9,10),(10,12.8,10,12.5),
            (12.5,14.5,12.2,14),(14,14.1,12.4,13),(13,13.2,11,11.5),
            (11.5,11.9,9.5,10),(10,13.1,9.8,13),(13,14.5,12.5,14),
            (14,14.2,10.5,11),(11,11.3,8,8.5),(8.5,11.2,8.3,11)]
    return [dict(time=i*interval,open=o,high=h,low=l,close=c) for i,(o,h,l,c) in enumerate(values)]


def guide_for(source,interval=900):
    result=dict(interval=interval,events=[
        dict(kind="BOS",direction=1,time=3*interval,fromTime=0,price=13,availableAt=4*interval),
        dict(kind="SWING",direction=1,time=3*interval,fromTime=interval,price=9,availableAt=4*interval)],
        snapshots=[dict(availableAt=b["time"]+interval,trend=1,close=b["close"],
                        high=dict(time=3*interval,price=14.5,eligible=True),
                        low=dict(time=interval,price=9,strong=True)) for b in source])
    attach_ranges(result)
    return result


def js(expression):
    node=shutil.which("node")
    if not node:
        pytest.skip("Node required for replay projection")
    result=subprocess.run([node],input=PHOTON_HELPERS+'\nconsole.log(JSON.stringify('+expression+'));',
                          encoding="utf-8",text=True,capture_output=True,check=True)
    return json.loads(result.stdout)


def test_range_math_and_independent_timeframe_classifications():
    higher=dict(low=60000,high=80000,equilibrium=70000)
    lower=dict(low=66000,high=70000,equilibrium=68000)
    assert range_position(69000,higher)=="DISCOUNT"
    assert range_position(69000,lower)=="PREMIUM"
    assert range_position(70000,higher)=="EQ"
    assert range_position(81000,higher)=="ABOVE_RANGE"
    assert range_position(59000,higher)=="BELOW_RANGE"
    assert zone_location(67000,69000,higher)=="DISCOUNT"
    assert zone_location(69000,71000,higher)=="STRADDLES_EQ"
    assert zone_location(71000,72000,higher)=="PREMIUM"
    assert range_position(None,higher)=="UNKNOWN"
    assert js('cslPhotonRangePosition(69000,'+json.dumps(higher)+')')=="DISCOUNT"
    assert js('cslPhotonZoneLocation({lower:69000,upper:71000},'+json.dumps(higher)+')')=="STRADDLES_EQ"


def test_range_versions_are_known_only_when_bounds_change_and_reset_on_unknown():
    states=[dict(availableAt=900,trend=0,high=None,low=None),
            dict(availableAt=1800,trend=1,close=12,high=dict(time=900,price=14),low=dict(time=0,price=8)),
            dict(availableAt=2700,trend=1,close=11,high=dict(time=900,price=14),low=dict(time=0,price=8)),
            dict(availableAt=3600,trend=1,close=15,high=dict(time=2700,price=16),low=dict(time=0,price=8)),
            dict(availableAt=4500,trend=0,high=None,low=None)]
    guide=dict(snapshots=states)
    attach_ranges(guide)
    assert states[0]["range"] is None and states[-1]["range"] is None
    assert [s["range"]["knownAt"] for s in states[1:4]]==[1800,1800,3600]
    assert [s["range"]["equilibrium"] for s in states[1:4]]==[11,11,12]


def test_zone_uses_last_opposing_candle_full_wicks_and_waits_for_bos_close():
    source=native_bars();guide=guide_for(source)
    result=build_zones(source,source,guide,"15m")
    assert len(result["zones"])==1
    zone=result["zones"][0]
    assert (zone["originTime"],zone["availableAt"],zone["lower"],zone["upper"],zone["kind"])==(900,3600,9,12,"DEMAND")
    assert zone["creationRange"]["equilibrium"]==11.75
    assert zone["creationLocation"]=="STRADDLES_EQ"
    assert all(e["availableAt"]>zone["availableAt"] for e in result["events"])
    data=json.dumps(dict(supplyDemand=result))
    assert js('cslPhotonZoneView('+data+',3599)')==[]
    assert js('cslPhotonZoneView('+data+',3600)')[0]["state"]=="FRESH"


def test_zone_touch_is_one_visit_until_price_leaves_and_invalidity_is_strict():
    source=native_bars();guide=guide_for(source)
    result=build_zones(source,source,guide,"15m")
    assert [(e["kind"],e["availableAt"]) for e in result["events"]]==[
        ("TOUCHED",5400),("TOUCHED",9000),("INVALIDATED",9900)]
    data=json.dumps(dict(supplyDemand=result))
    before=js('cslPhotonZoneView('+data+',9000)')[0]
    after=js('cslPhotonZoneView('+data+',9900)')[0]
    assert (before["state"],before["touches"])==("TOUCHED",2)
    assert after["state"]=="INVALIDATED" and after["endedAt"]==9900
    source[10]=dict(source[10],close=9)
    result=build_zones(source,source,guide,"15m")
    assert not any(e["kind"]=="INVALIDATED" for e in result["events"])


@pytest.mark.parametrize("interval",[3600,86400])
def test_htf_touch_uses_15m_but_invalidation_waits_for_own_close(interval):
    native=native_bars(interval)[:4]
    native += [dict(time=4*interval,open=14,high=14.2,low=8,close=10),
               dict(time=5*interval,open=10,high=11,low=8,close=8.5)]
    count=interval//900
    source=[dict(b,time=b["time"]+j*900) for b in native[:4] for j in range(count)]
    source += [dict(time=4*interval+j*900,open=14 if j==0 else 10,high=14.2,low=8,
                    close=10 if j==count-1 else 8.5) for j in range(count)]
    source += [dict(time=5*interval+j*900,open=10,high=11,low=8,close=8.5) for j in range(count)]
    guide=guide_for(native,interval)
    result=build_zones(source,native,guide,"1d" if interval==86400 else "4h")
    touches=[e for e in result["events"] if e["kind"]=="TOUCHED"]
    invalid=[e for e in result["events"] if e["kind"]=="INVALIDATED"]
    assert touches[0]["availableAt"]==4*interval+900
    assert [e["availableAt"] for e in invalid]==[6*interval]
    data=json.dumps(dict(supplyDemand=result))
    assert js('cslPhotonZoneView('+data+','+str(5*interval)+')')[0]["state"]=="TOUCHED"


def test_no_zone_from_choch_alone_or_without_opposing_candle_or_departure():
    source=native_bars();guide=guide_for(source)
    guide["events"][0]["kind"]="CHOCH"
    assert build_zones(source,source,guide,"15m")["zones"]==[]
    guide=guide_for(source)
    source[1]=dict(source[1],open=9.5)
    assert build_zones(source,source,guide,"15m")["zones"]==[]
    source=native_bars();source[1]=dict(source[1],high=15)
    assert build_zones(source,source,guide_for(source),"15m")["zones"]==[]


def test_repeated_bos_from_same_origin_does_not_create_duplicate_fresh_zones():
    source=native_bars();guide=guide_for(source)
    guide["events"] += [dict(e,time=4*900,availableAt=5*900) for e in guide["events"]]
    # A second confirmation still departs above the zone.
    source[4]=dict(source[4],close=14)
    assert len(build_zones(source,source,guide,"15m")["zones"])==1


def test_data_gap_retires_zone_instead_of_claiming_price_invalidation():
    source=native_bars();guide=guide_for(source)
    gapped=source[:5]+[dict(b,time=b["time"]+900) for b in source[5:]]
    result=build_zones(gapped,source,guide,"15m")
    assert [(e["kind"],e.get("reason")) for e in result["events"]]==[("RETIRED","DATA_GAP")]


def test_supply_and_demand_rules_are_price_mirrors():
    source=native_bars();guide=guide_for(source)
    a=build_zones(source,source,guide,"15m")
    mirror=[dict(time=b["time"],open=30-b["open"],close=30-b["close"],high=30-b["low"],low=30-b["high"]) for b in source]
    mirrored_guide=guide_for(mirror)
    for e in mirrored_guide["events"]:
        e["direction"]=-1;e["price"]=30-e["price"]
    b=build_zones(mirror,mirror,mirrored_guide,"15m")
    assert b["zones"][0]["kind"]=="SUPPLY"
    assert b["zones"][0]["lower"]==18 and b["zones"][0]["upper"]==21
    assert [(e["kind"],e["availableAt"]) for e in a["events"]]==[(e["kind"],e["availableAt"]) for e in b["events"]]


def test_nearby_projection_defaults_to_active_and_preserves_explicit_selection():
    zones=[dict(id=str(i),timeframe="4h",kind="DEMAND",lower=i,upper=i+.5,
                availableAt=i,endedAt=20 if i==9 else None) for i in range(10)]
    value=json.dumps(zones)
    assert [z["id"] for z in js('cslPhotonNearbyZones('+value+',10)')]==['8','7']
    assert [z["id"] for z in js('cslPhotonNearbyZones('+value+',10,"9")')]==['8','7','9']
    assert [z["id"] for z in js('cslPhotonNearbyZones('+value+',10,null,true)')]==['9','8']


def test_value_area_payload_is_prefix_safe_and_does_not_change_structure():
    import math
    source=[]
    for i in range(140):
        p=100+9*math.sin(i*.3)
        source.append(dict(time=i*900,open=p+(.8 if i%3 else -.8),high=p+1,low=p-1,close=p))
    full=build_mapping(source)
    assert "supplyDemand" not in full["timeframes"]["1w"]
    assert full["mappingOnly"]
    for n in (20,45,90,95,96,120,139):
        prefix=build_mapping(source[:n]);cutoff=n*900
        for tf,g in prefix["timeframes"].items():
            assert g["snapshots"]==[s for s in full["timeframes"][tf]["snapshots"] if s["availableAt"]<=cutoff]
            if tf=="1w":continue
            for key in ("zones","events"):
                assert g["supplyDemand"][key]==[e for e in full["timeframes"][tf]["supplyDemand"][key] if e["availableAt"]<=cutoff]


def test_daily_and_4h_zone_history_is_prefix_safe_across_partial_closes():
    import math
    source=[]
    for i in range(70*96):
        p=100+i/192+20*math.sin(i/(96*3))+2*math.sin(i/11)
        source.append(dict(time=i*900,open=p+(.5 if i%2 else -.5),high=p+1,low=p-1,close=p))
    full=build_mapping(source)
    assert full["timeframes"]["1d"]["supplyDemand"]["zones"]
    assert full["timeframes"]["4h"]["supplyDemand"]["zones"]
    for n in (24*96-1,24*96,36*96+15,48*96,60*96-1):
        prefix=build_mapping(source[:n]);cutoff=n*900
        for tf in ("1d","4h","15m"):
            for key in ("zones","events"):
                assert prefix["timeframes"][tf]["supplyDemand"][key]==[
                    e for e in full["timeframes"][tf]["supplyDemand"][key] if e["availableAt"]<=cutoff]
