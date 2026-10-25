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
