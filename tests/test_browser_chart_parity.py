import json

from crypto_strategy_lab.browser_chart_parity import (
    canonical_sha256, compare_payloads, main,
)


def test_exact_chart_payload_parity_is_order_independent_for_object_keys():
    desktop = {"run": {"runId": "BTCUSDT_4h"}, "candles": [{"time": 1, "open": 10.0}],
               "overlays": [{"kind": "ema", "values": [10.0]}],
               "positionBox": {"entry": 10.0, "stop": 9.0, "target": 12.0},
               "fibDerivation": {"levels": [{"level": 0.618, "price": 9.5}]}}
    browser = {"fibDerivation": desktop["fibDerivation"], "positionBox": desktop["positionBox"],
               "overlays": desktop["overlays"], "candles": desktop["candles"],
               "run": desktop["run"]}
    assert compare_payloads(desktop, browser) == []
    assert canonical_sha256(desktop) == canonical_sha256(browser)


def test_chart_payload_detects_trade_geometry_and_candle_time_differences():
    left = {"candles": [{"time": 10}], "positionBox": {"stop": 90},
            "markers": [{"time": 10}], "inspect": {"ADX": 20}}
    right = {"candles": [{"time": 11}], "positionBox": {"stop": 91},
             "markers": [{"time": 10}], "inspect": {"ADX": 21}}
    issues = compare_payloads(left, right)
    assert len(issues) == 3
    assert any('["candles"][0]["time"]' in line for line in issues)
    assert any('["positionBox"]["stop"]' in line for line in issues)
    assert any('["inspect"]["ADX"]' in line for line in issues)


def test_chart_parity_detects_missing_fields_and_list_items():
    issues = compare_payloads({"overlays": [1, 2], "srZones": []}, {"overlays": [1]})
    assert any("length" in item for item in issues)
    assert any("srZones" in item for item in issues)


def test_cli_exits_nonzero_on_mismatch(tmp_path):
    a, b = tmp_path / "desktop.json", tmp_path / "browser.json"
    a.write_text(json.dumps({"candles": [1]}), encoding="utf-8")
    b.write_text(json.dumps({"candles": [2]}), encoding="utf-8")
    assert main([str(a), str(b)]) == 1
    b.write_text(a.read_text(encoding="utf-8"), encoding="utf-8")
    assert main([str(a), str(b)]) == 0


def test_signed_zero_mismatch_is_not_a_false_pass():
    desktop = {"positionBox": {"realizedR": -0.0}}
    browser = {"positionBox": {"realizedR": 0.0}}
    mismatches = compare_payloads(desktop, browser)
    assert len(mismatches) == 1
    assert "signed zero" in mismatches[0]
    assert canonical_sha256(desktop) != canonical_sha256(browser)
