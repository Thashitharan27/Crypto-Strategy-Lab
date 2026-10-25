from pathlib import Path
from types import SimpleNamespace

import numpy as np

from crypto_strategy_lab.photon_structure import (
    MODE, PhotonStructureMixin, aggregate_closed, build_mapping, map_structure,
)
from crypto_strategy_lab.strategy_rule_model import compile_profiles, infer_direction_mode, MARKET_PERMISSIONS


def bars(n=160):
    prices = 100 + np.sin(np.arange(n) * .55) * 5 + np.sin(np.arange(n) * .09) * 12
    return [dict(time=i*900, open=float(p-.1), high=float(p+1), low=float(p-1), close=float(p))
            for i, p in enumerate(prices)]


def test_prefix_invariance_for_every_candle_including_mtf():
    source = bars()
    full = build_mapping(source)
    for n in range(1, len(source)+1):
        prefix = build_mapping(source[:n])
        cutoff = n*900
        for tf in ("15m", "4h"):
            assert prefix["timeframes"][tf]["snapshots"] == [s for s in full["timeframes"][tf]["snapshots"] if s["availableAt"] <= cutoff]
            assert prefix["timeframes"][tf]["events"] == [e for e in full["timeframes"][tf]["events"] if e["availableAt"] <= cutoff]
            assert prefix["timeframes"][tf]["trace"] == [e for e in full["timeframes"][tf]["trace"] if e["availableAt"] <= cutoff]


def test_breaks_require_close_but_internal_choch_can_be_wick_only():
    source = bars()
    mapping = map_structure(source)
    breaks = [e for e in mapping["events"] if e["kind"] in ("BOS", "TREND_CHANGE")]
    chochs = [e for e in mapping["events"] if e["kind"] == "CHOCH"]
    assert breaks and chochs
    for e in breaks:
        candle = source[e["time"]//900]
        assert candle["close"] > e["price"] if e["direction"] == 1 else candle["close"] < e["price"]
    # Replace the first breaking candle with a wick-only excursion. No swing
    # break can occur there although it penetrates the exact same swing level.
    e = breaks[0]
    index = e["time"]//900
    changed = source[:index+1]
    changed[-1] = dict(changed[-1], open=e["price"], close=e["price"])
    at = e["availableAt"]
    assert not any(x["availableAt"] == at and x["kind"] in ("BOS", "TREND_CHANGE") for x in map_structure(changed)["events"])
    # Keep the CHoCH-triggering wick but place the close on its level.
    e = chochs[0]
    index = e["time"]//900
    changed = source[:index+1]
    changed[-1] = dict(changed[-1], open=e["price"], close=e["price"])
    assert any(x["availableAt"] == e["availableAt"] and x["kind"] == "CHOCH" for x in map_structure(changed)["events"])


def test_aggregate_waits_for_all_sixteen_candles_and_rejects_gaps():
    source = bars(32)
    assert aggregate_closed(source[:15]) == []
    assert len(aggregate_closed(source[:16])) == 1
    assert len(aggregate_closed(source[:31])) == 1
    assert len(aggregate_closed(source)) == 2
    assert len(aggregate_closed(source[:3]+source[4:])) == 1
    assert len(aggregate_closed(source[:3]+[source[2]]+source[4:])) == 1
    assert all(s["availableAt"] % 14400 == 0 for s in build_mapping(source)["timeframes"]["4h"]["snapshots"])


def test_gap_resets_old_levels_and_directions():
    source = bars()
    gapped = source[:80] + [dict(b, time=b["time"]+900) for b in source[80:]]
    result = map_structure(gapped)
    s = result["snapshots"][80]
    assert s["trend"] == 0 and s["internal"] == 0
    assert s["high"] is None and s["low"] is None


def test_bull_bear_symmetry():
    source = bars()
    mirror = [dict(time=b["time"], open=300-b["open"], high=300-b["low"], low=300-b["high"], close=300-b["close"]) for b in source]
    a, b = map_structure(source), map_structure(mirror)
    assert [(s["trend"], s["internal"]) for s in a["snapshots"]] == [(-s["trend"], -s["internal"]) for s in b["snapshots"]]


def test_strategy_roundtrip_and_hard_no_entry_gate():
    profiles, _ = compile_profiles(direction_mode=MODE, market_permissions=MARKET_PERMISSIONS)
    assert infer_direction_mode(profiles) == MODE
    class UnsafeParent:
        def _selected_direction(self, i): return "LONG"
        def _should_enter(self, i): return True
        def _open_pair(self, *a, **k): raise AssertionError("Must never open")
    class Engine(PhotonStructureMixin, UnsafeParent): pass
    engine = Engine()
    engine.config = SimpleNamespace(strategy_profiles=profiles)
    engine.signal_strategy_mode = engine._infer_signal_strategy_mode()
    assert engine.signal_strategy_mode == MODE
    assert engine._selected_direction(1) is None
    assert engine._should_enter(1) is False
    assert engine._open_pair(1, schedule={}) is None
    engine.signal_strategy_mode = "DI"
    assert engine._should_enter(1) is True


def test_saved_preset_and_both_discovery_surfaces():
    from crypto_strategy_lab.data_lake_config import load_data_lake_config
    from crypto_strategy_lab.control_rule_workspace import SIGNAL_STRATEGIES as DIRECTION_LABELS
    from crypto_strategy_lab.gui.rule_strategy_builder import DIRECTION_LABELS as GUI_LABELS
    path = Path(__file__).parents[1]/"config/data_lake/Photon_Structure_Parts_1_2.json"
    config = load_data_lake_config(path)
    assert infer_direction_mode(config.strategy.profiles) == MODE
    assert config.data.strategy_timeframe_minutes == 15
    assert DIRECTION_LABELS[MODE] == GUI_LABELS[MODE]


def test_visualizer_attaches_mapping_from_canonical_15m_source(tmp_path):
    import pandas as pd
    from crypto_strategy_lab.strategy_visualizer import CompletedRunVisualizer
    profiles, _ = compile_profiles(direction_mode=MODE, market_permissions=MARKET_PERMISSIONS)
    model = object.__new__(CompletedRunVisualizer)
    model.seed = SimpleNamespace(config=SimpleNamespace(strategy=SimpleNamespace(profiles=profiles)),
        request=SimpleNamespace(period_start="2026-01-01", period_end="2026-01-02"))
    seen = []
    def market(start, end, *, chart_timeframe):
        seen.append(chart_timeframe)
        frame = pd.DataFrame(bars())
        frame["period_start"] = pd.to_datetime(frame.time, unit="s", utc=True)
        return frame
    model._market_frame = market
    payload = model._photon_mapping_payload()
    assert payload["mappingOnly"] is True
    assert set(payload["timeframes"]) == {"4h", "15m"}
    assert seen == ["15m"]
    assert model._photon_mapping_payload() is payload


def test_browser_mapping_view_hides_future_and_stale_htf_states():
    import json
    import shutil
    import subprocess
    from crypto_strategy_lab.visualizer_photon import PHOTON_HELPERS
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("Node required for visualizer projection")
    mapping = build_mapping(bars(32))
    code = PHOTON_HELPERS + "\nconst m=" + json.dumps(mapping) + ";" + """
console.log(JSON.stringify([cslPhotonView(m,14399),cslPhotonView(m,14400),cslPhotonView(m,43200)]));
"""
    result = subprocess.run([node], input=code, capture_output=True, text=True, check=True)
    before, first, stale = json.loads(result.stdout)
    assert before["4h"]["state"] is None
    assert first["4h"]["state"]["availableAt"] == 14400
    assert stale["4h"]["state"] is None
    assert all(e["availableAt"] <= 14399 for e in before["15m"]["events"])


def test_mapping_browser_startup_disables_trade_controls():
    from crypto_strategy_lab.strategy_visualizer_browser_v2 import build_browser_visualizer_v2_html
    profiles, _ = compile_profiles(direction_mode=MODE, market_permissions=MARKET_PERMISSIONS)
    model = SimpleNamespace(trade_count=0, manifest={}, run_dir=Path("example"),
        seed=SimpleNamespace(request=SimpleNamespace(symbol="BTCUSDT", strategy_timeframe="15m"),
            config=SimpleNamespace(strategy=SimpleNamespace(profiles=profiles))))
    html = build_browser_visualizer_v2_html(model, "test")
    assert '"mappingOnly":true' in html
    assert "$('manual-confirm').disabled=true" in html
    assert "body.mapping-only #trade-panel" in html
    assert "__PHOTON_HELPERS__" not in html
    assert 'aria-label="Structure display"' in html
    assert 'value="LINES">Structure lines' in html
    assert 'value="BOTH">Candles + structure lines' in html
    assert "applyPhotonDisplay();" in html


def _swing_lines(guide, cutoff):
    import json
    import shutil
    import subprocess
    from crypto_strategy_lab.visualizer_photon import PHOTON_HELPERS
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("Node required for swing-line geometry")
    code = PHOTON_HELPERS + "\nconsole.log(JSON.stringify(cslPhotonSwingLines(" + json.dumps(guide) + "," + str(cutoff) + ")));"
    result = subprocess.run([node], input=code, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_swing_lines_use_origin_only_after_confirmation_and_ignore_choch():
    guide = {"events": [
        dict(kind="PIVOT", direction=1, fromTime=100, price=12, availableAt=300),
        dict(kind="PIVOT", direction=-1, fromTime=200, price=8, availableAt=500),
        dict(kind="CHOCH", direction=-1, fromTime=250, price=9, availableAt=550),
        dict(kind="BOS", direction=1, fromTime=100, price=12, availableAt=600),
        dict(kind="SWING", direction=1, fromTime=200, price=8, availableAt=600),
        dict(kind="PIVOT", direction=1, fromTime=400, price=15, availableAt=700),
        dict(kind="BOS", direction=1, fromTime=400, price=15, availableAt=800),
        dict(kind="SWING", direction=1, fromTime=500, price=10, availableAt=800),
    ]}
    assert _swing_lines(guide, 599) == []
    assert [p["time"] for p in _swing_lines(guide, 600)[0]] == [100, 200]
    assert _swing_lines(guide, 700) == _swing_lines(guide, 600)
    points = _swing_lines(guide, 800)[0]
    assert [p["time"] for p in points] == [100, 200, 400, 500]
    assert [p["side"] for p in points] == [1, -1, 1, -1]
    assert all(p["availableAt"] in (600, 800) for p in points)


def test_swing_lines_split_gaps_and_ambiguous_same_candle_extremes():
    def point(time, direction, price):
        return dict(kind="BOS_SWING", direction=direction, fromTime=time, price=price, availableAt=time+100)
    guide = {"events": [point(100, 1, 12), point(200, -1, 8),
        dict(kind="GAP", availableAt=350), point(400, 1, 16),
        point(500, 1, 18), point(500, -1, 9), point(600, -1, 10), point(700, 1, 20)]}
    paths = _swing_lines(guide, 900)
    assert [[p["time"] for p in line] for line in paths] == [[100, 200], [400], [600, 700]]


def test_swing_line_projection_matches_mapping_from_historical_prefix():
    source = bars(80)
    full = map_structure(source)
    prefix = map_structure(source[:40])
    assert _swing_lines(full, 40*900) == _swing_lines(prefix, 40*900)


def test_swing_lines_collapse_same_side_to_more_extreme_price():
    guide = {"events": [dict(kind="BOS_SWING", direction=d, fromTime=t, price=p, availableAt=t+1)
        for t, d, p in [(10, 1, 12), (20, 1, 11), (30, 1, 14), (40, -1, 8), (50, -1, 9), (60, -1, 7)]]}
    assert [p["price"] for p in _swing_lines(guide, 100)[0]] == [14, 7]


def test_historical_trace_only_admits_points_at_close_confirmed_swing_breaks():
    mapping = map_structure(bars())
    breaks = {e["availableAt"] for e in mapping["events"] if e["kind"] in ("BOS", "TREND_CHANGE")}
    assert breaks and len(mapping["trace"]) == len(breaks)*2
    assert mapping["traceBasis"] == "BOS_CONFIRMED"
    assert all(e["kind"] == "BOS_SWING" and e["availableAt"] in breaks for e in mapping["trace"])
    for i in range(1, len(mapping["snapshots"])):
        at = mapping["snapshots"][i]["availableAt"]
        if at not in breaks:
            # Raw pivots and internal CHoCH cannot change the solid path.
            before = [e for e in mapping["trace"] if e["availableAt"] <= at-900]
            after = [e for e in mapping["trace"] if e["availableAt"] <= at]
            assert before == after


def test_legacy_raw_pivot_trace_cannot_reintroduce_noisy_lines():
    guide = dict(trace=[dict(kind="PIVOT", direction=1, fromTime=100, price=12, availableAt=300)], events=[])
    assert _swing_lines(guide, 500) == []


def test_bullish_bos_confirms_pullback_low_only_when_high_closes_through():
    values = [(100,98,99),(104,100,102),(110,103,108),(108,101,105),
              (105,99,102),(103,95,98),(105,98,103),(108,100,106),
              (113,105,112),(112,108,110),(111,107,109),(110,104,106),
              (111,106,109),(112,107,110),(116,109,115)]
    source = [dict(time=i*900, open=c, high=h, low=l, close=c) for i,(h,l,c) in enumerate(values)]
    result = map_structure(source)
    assert [e["availableAt"] for e in result["events"] if e["kind"] == "BOS"] == [8100,13500]
    assert _swing_lines(result, 8099) == []
    first = _swing_lines(result, 8100)[0]
    assert [(p["time"],p["price"]) for p in first] == [(1800,110),(4500,95)]
    # The next two-bar high and internal changes do not extend the solid line.
    assert _swing_lines(result, 13499)[0] == first
    second = _swing_lines(result, 13500)[0]
    assert [(p["time"],p["price"]) for p in second] == [(1800,110),(4500,95),(7200,113),(9900,104)]
    assert [p["availableAt"] for p in second] == [8100,8100,13500,13500]
    # Exact inverse rule for bearish structure.
    mirror = [dict(time=b["time"], open=300-b["open"], close=300-b["close"],
                   high=300-b["low"], low=300-b["high"]) for b in source]
    bearish = _swing_lines(map_structure(mirror),13500)[0]
    assert [p["price"] for p in bearish] == [190,205,187,196]
    assert [p["side"] for p in bearish] == [-1,1,-1,1]


def test_developing_leg_ends_at_closed_candle_and_does_not_cross_gaps():
    import json
    import shutil
    import subprocess
    from crypto_strategy_lab.visualizer_photon import PHOTON_HELPERS
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("Node required for developing-leg geometry")
    guide = dict(interval=900, traceBasis="BOS_CONFIRMED", events=[], trace=[dict(kind="BOS_SWING", direction=1, fromTime=0, price=110, availableAt=2700)],
        snapshots=[dict(availableAt=3600, close=105), dict(availableAt=4500, close=104)])
    code = PHOTON_HELPERS + "\nconst g=" + json.dumps(guide) + ";" + """
const a=cslPhotonDevelopingLeg(g,3600,cslPhotonSwingLines(g,3600));
const before=cslPhotonDevelopingLeg(g,2699,cslPhotonSwingLines(g,2699));
g.trace.push({kind:'GAP',availableAt:4500});
g.events.push({kind:'GAP',availableAt:4500});
const gap=cslPhotonDevelopingLeg(g,4500,cslPhotonSwingLines(g,4500));
console.log(JSON.stringify([a,before,gap]));
"""
    result = subprocess.run([node], input=code, capture_output=True, text=True, check=True)
    leg, before, gap = json.loads(result.stdout)
    assert leg[-1] == dict(time=2700, price=105, availableAt=3600)
    assert before is None and gap is None
