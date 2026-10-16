from __future__ import annotations

from types import SimpleNamespace

from crypto_strategy_lab.browser_v2_historical_parity import (
    capture_parity,
    parity_cases,
    representative_trade_indices,
)


class _Trades:
    def __init__(self, sides):
        self._sides = sides

    def iterrows(self):
        for index, side in enumerate(self._sides):
            yield index, {"side": side}


class _Model:
    def __init__(self, sides=("LONG", "LONG", "SHORT", "LONG", "SHORT")):
        self.trade_count = len(sides)
        self.trades = _Trades(sides)
        self.manifest = {"run_id": "BTCUSDT_4h_fixture"}
        self.run_dir = SimpleNamespace(name="BTCUSDT_4h_fixture")
        self.seed = SimpleNamespace(request=SimpleNamespace(strategy_timeframe="4h"))
        self.calls = []

    def available_chart_timeframes(self):
        return [
            {"interval": "1h"},
            {"interval": "4h"},
            {"interval": "1d"},
        ]

    def build_v2_diagnostic_payload(self, *, trade_index=None, chart_timeframe=None):
        self.calls.append((trade_index, chart_timeframe))
        return {
            "run": {"runId": self.manifest["run_id"], "chartTimeframe": chart_timeframe},
            "selectedTradeIndex": trade_index,
            "chartTimeframe": chart_timeframe,
            "candles": [{"time": 1, "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5}],
            "markers": [],
            "overlays": [],
        }


def test_representative_indices_cover_edges_middle_and_both_sides():
    model = _Model()
    assert representative_trade_indices(model) == [0, 2, 4]


def test_parity_cases_cover_required_v2_timeframes():
    model = _Model()
    assert parity_cases(model) == [
        (0, "1h"), (0, "4h"), (0, "1d"),
        (2, "1h"), (2, "4h"), (2, "1d"),
        (4, "1h"), (4, "4h"), (4, "1d"),
    ]


def test_capture_parity_writes_exact_local_evidence(tmp_path):
    desktop = _Model()
    browser = _Model()

    summary = capture_parity(
        desktop,
        browser,
        tmp_path,
        browser_payload=lambda index, timeframe: browser.build_v2_diagnostic_payload(
            trade_index=index,
            chart_timeframe=timeframe,
        ),
    )

    assert summary["pass"] is True
    assert len(summary["cases"]) == 9
    assert all(item["desktop_sha256"] == item["browser_sha256"] for item in summary["cases"])
    assert (tmp_path / "summary.json").is_file()
    assert (tmp_path / "desktop_trade_000_4h.json").is_file()
    assert (tmp_path / "browser_trade_004_1d.json").is_file()


def test_capture_parity_fails_closed_on_payload_difference(tmp_path):
    desktop = _Model()
    browser = _Model()

    def mismatched(index, timeframe):
        payload = browser.build_v2_diagnostic_payload(
            trade_index=index,
            chart_timeframe=timeframe,
        )
        if index == 2 and timeframe == "4h":
            payload["candles"][0]["close"] = 99.0
        return payload

    summary = capture_parity(desktop, browser, tmp_path, browser_payload=mismatched)

    assert summary["pass"] is False
    failed = [item for item in summary["cases"] if not item["exact_match"]]
    assert len(failed) == 1
    assert failed[0]["trade_index"] == 2
    assert failed[0]["timeframe"] == "4h"
    assert any('["candles"][0]["close"]' in item for item in failed[0]["mismatches"])


def test_capture_parity_rejects_mismatched_trade_counts(tmp_path):
    import pytest
    desktop = _Model()
    browser = _Model(sides=("LONG", "SHORT"))
    with pytest.raises(ValueError, match="trade counts differ"):
        capture_parity(desktop, browser, tmp_path, browser_payload=lambda i, tf: {})
    assert not (tmp_path / "summary.json").exists()


def test_capture_parity_rejects_mismatched_run_identity(tmp_path):
    import pytest
    desktop = _Model()
    browser = _Model()
    browser.manifest = {"run_id": "different_run"}
    with pytest.raises(ValueError, match="run identities differ"):
        capture_parity(desktop, browser, tmp_path, browser_payload=lambda i, tf: {})
    assert not (tmp_path / "summary.json").exists()


def test_failed_parity_capture_does_not_leave_stale_pass_summary(tmp_path):
    import json
    import pytest

    summary_path = tmp_path / "summary.json"
    summary_path.write_text(json.dumps({"pass": True, "run_id": "stale"}), encoding="utf-8")
    desktop = _Model()
    browser = _Model(sides=("LONG", "SHORT"))
    with pytest.raises(ValueError, match="trade counts differ"):
        capture_parity(desktop, browser, tmp_path, browser_payload=lambda i, tf: {})
    assert not summary_path.exists()


def test_main_invalidates_stale_pass_when_canonical_loading_fails(tmp_path, monkeypatch):
    import json
    import pytest
    from crypto_strategy_lab import browser_v2_historical_parity as parity

    summary_path = tmp_path / "summary.json"
    summary_path.write_text(json.dumps({"pass": True, "run_id": "previous"}), encoding="utf-8")

    def unavailable(*_args):
        raise ValueError("canonical data unavailable")

    monkeypatch.setattr(parity, "load_models", unavailable)
    with pytest.raises(ValueError, match="canonical data unavailable"):
        parity.main(["--evidence-dir", str(tmp_path), "--output-root", str(tmp_path)])
    assert not summary_path.exists()


def test_review_only_rechecks_frozen_capture_hashes_without_market_data(tmp_path, monkeypatch):
    import pytest
    from crypto_strategy_lab import browser_v2_historical_parity as parity

    desktop = _Model(sides=("LONG",) * 79)
    browser = _Model(sides=("LONG",) * 79)
    desktop.manifest["run_id"] = browser.manifest["run_id"] = "BTCUSDT_4h_ad58a712d8e7492380b99ec96c20c80f"
    capture_parity(
        desktop, browser, tmp_path,
        browser_payload=lambda i, tf: browser.build_v2_diagnostic_payload(
            trade_index=i, chart_timeframe=tf,
        ),
    )
    def no_data_lake(*_args, **_kwargs):
        raise AssertionError("Review must never load market data")
    monkeypatch.setattr(parity, "load_models", no_data_lake)
    report = parity.review_captured_parity(tmp_path)
    assert report == {
        "run_id": parity.DEFAULT_RUN_ID, "trade_count": 79, "cases_checked": 9, "pass": True,
    }
    assert parity.main(["--review-only", "--evidence-dir", str(tmp_path)]) == 0


def test_review_only_rejects_tampering_missing_files_and_false_summary(tmp_path):
    import json
    import pytest
    from crypto_strategy_lab.browser_v2_historical_parity import review_captured_parity

    desktop = _Model(sides=("LONG",) * 79)
    browser = _Model(sides=("LONG",) * 79)
    desktop.manifest["run_id"] = browser.manifest["run_id"] = "BTCUSDT_4h_ad58a712d8e7492380b99ec96c20c80f"
    capture_parity(
        desktop, browser, tmp_path,
        browser_payload=lambda i, tf: browser.build_v2_diagnostic_payload(
            trade_index=i, chart_timeframe=tf,
        ),
    )
    path = tmp_path / "browser_trade_000_4h.json"
    original = path.read_text(encoding="utf-8")
    payload = json.loads(original)
    payload["candles"][0]["close"] = 999.0
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="Captured payload differs"):
        review_captured_parity(tmp_path)
    path.write_text(original, encoding="utf-8")

    path.unlink()
    with pytest.raises(FileNotFoundError):
        review_captured_parity(tmp_path)
    path.write_text(original, encoding="utf-8")

    summary_path = tmp_path / "summary.json"
    original_summary = summary_path.read_text(encoding="utf-8")
    summary = json.loads(original_summary)
    summary["pass"] = False
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(ValueError, match="not PASS"):
        review_captured_parity(tmp_path)
    summary_path.write_text(original_summary, encoding="utf-8")

    summary = json.loads(original_summary)
    summary["cases"].append(summary["cases"][0])
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate parity case"):
        review_captured_parity(tmp_path)


def test_review_rejects_matching_hashes_for_wrong_selected_payload_identity(tmp_path):
    """Hashes and equality cannot substitute for verifying selected run/trade/TF."""
    import json
    import pytest
    from crypto_strategy_lab.browser_chart_parity import canonical_sha256
    from crypto_strategy_lab.browser_v2_historical_parity import review_captured_parity

    desktop = _Model(sides=("LONG",) * 79)
    browser = _Model(sides=("LONG",) * 79)
    frozen = "BTCUSDT_4h_ad58a712d8e7492380b99ec96c20c80f"
    desktop.manifest["run_id"] = browser.manifest["run_id"] = frozen
    capture_parity(
        desktop, browser, tmp_path,
        browser_payload=lambda i, tf: browser.build_v2_diagnostic_payload(
            trade_index=i, chart_timeframe=tf,
        ),
    )
    summary_path = tmp_path / "summary.json"
    pristine_summary = summary_path.read_text(encoding="utf-8")
    case_path = tmp_path / "desktop_trade_000_4h.json"
    browser_path = tmp_path / "browser_trade_000_4h.json"
    pristine_payload = case_path.read_text(encoding="utf-8")
    for field, invalid in (("selectedTradeIndex", 39), ("selectedTradeIndex", False), ("selectedTradeIndex", 0.0), ("chartTimeframe", "1d")):
        payload = json.loads(pristine_payload)
        payload[field] = invalid
        for target in (case_path, browser_path):
            target.write_text(json.dumps(payload), encoding="utf-8")
        summary = json.loads(pristine_summary)
        summary["cases"][1]["desktop_sha256"] = canonical_sha256(payload)
        summary["cases"][1]["browser_sha256"] = canonical_sha256(payload)
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        with pytest.raises(ValueError, match="payload identity mismatch"):
            review_captured_parity(tmp_path)
    for target in (case_path, browser_path):
        target.write_text(pristine_payload, encoding="utf-8")
    summary = json.loads(pristine_summary)
    payload = json.loads(pristine_payload)
    payload["run"]["runId"] = "unrelated_run"
    for target in (case_path, browser_path):
        target.write_text(json.dumps(payload), encoding="utf-8")
    summary["cases"][1]["desktop_sha256"] = canonical_sha256(payload)
    summary["cases"][1]["browser_sha256"] = canonical_sha256(payload)
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(ValueError, match="payload identity mismatch"):
        review_captured_parity(tmp_path)


def test_frozen_capture_requires_complete_timeframe_matrix_before_evidence(tmp_path):
    import pytest
    from crypto_strategy_lab.browser_v2_historical_parity import DEFAULT_RUN_ID

    desktop = _Model(sides=("LONG",) * 79)
    browser = _Model(sides=("LONG",) * 79)
    desktop.manifest["run_id"] = browser.manifest["run_id"] = DEFAULT_RUN_ID
    desktop.available_chart_timeframes = lambda: [{"interval": "4h"}, {"interval": "1h"}]
    with pytest.raises(ValueError, match="requires first/middle/last trades"):
        capture_parity(
            desktop, browser, tmp_path,
            browser_payload=lambda i, tf: browser.build_v2_diagnostic_payload(
                trade_index=i, chart_timeframe=tf,
            ),
        )
    assert not (tmp_path / "summary.json").exists()
    assert not list(tmp_path.glob("desktop_trade_*.json"))


def test_nonfrozen_capture_preserves_existing_available_timeframe_fallback(tmp_path):
    desktop = _Model()
    browser = _Model()
    desktop.available_chart_timeframes = lambda: [{"interval": "4h"}, {"interval": "1h"}]
    summary = capture_parity(
        desktop, browser, tmp_path,
        browser_payload=lambda i, tf: browser.build_v2_diagnostic_payload(
            trade_index=i, chart_timeframe=tf,
        ),
    )
    assert summary["pass"] is True
    assert {case["timeframe"] for case in summary["cases"]} == {"1h", "4h"}


def test_frozen_capture_rejects_equal_wrong_identity_without_pass_summary(tmp_path):
    """Identical wrong payloads must not yield a capture PASS."""
    import pytest
    from crypto_strategy_lab.browser_v2_historical_parity import DEFAULT_RUN_ID

    for field, wrong in (
        ("selectedTradeIndex", False),
        ("selectedTradeIndex", 39),
        ("chartTimeframe", "1d"),
        ("runId", "not_the_frozen_run"),
    ):
        case_dir = tmp_path / (field + "_" + str(wrong))
        desktop = _Model(sides=("LONG",) * 79)
        browser = _Model(sides=("LONG",) * 79)
        desktop.manifest["run_id"] = browser.manifest["run_id"] = DEFAULT_RUN_ID
        original = desktop.build_v2_diagnostic_payload

        def wrong_desktop(*, trade_index, chart_timeframe):
            payload = original(trade_index=trade_index, chart_timeframe=chart_timeframe)
            if field == "runId":
                payload["run"]["runId"] = wrong
            else:
                payload[field] = wrong
            return payload

        desktop.build_v2_diagnostic_payload = wrong_desktop

        def wrong_browser(index, timeframe):
            return wrong_desktop(trade_index=index, chart_timeframe=timeframe)

        with pytest.raises(ValueError, match="payload identity mismatch"):
            capture_parity(desktop, browser, case_dir, browser_payload=wrong_browser)
        assert not (case_dir / "summary.json").exists()


def test_native_manifest_uuid_capture_and_review_require_frozen_market_and_matrix(tmp_path):
    import pytest
    from crypto_strategy_lab.browser_v2_historical_parity import (
        FROZEN_NATIVE_RUN_ID, review_captured_parity,
    )

    desktop = _Model(sides=("LONG",) * 79)
    browser = _Model(sides=("LONG",) * 79)
    desktop.manifest["run_id"] = browser.manifest["run_id"] = FROZEN_NATIVE_RUN_ID
    original = desktop.build_v2_diagnostic_payload

    def payload(*, trade_index, chart_timeframe):
        value = original(trade_index=trade_index, chart_timeframe=chart_timeframe)
        value["run"].update(symbol="BTCUSDT", strategyTimeframe="4h")
        return value

    desktop.build_v2_diagnostic_payload = payload
    get_browser = lambda i, tf: payload(trade_index=i, chart_timeframe=tf)
    capture_parity(desktop, browser, tmp_path / "valid", browser_payload=get_browser)
    assert review_captured_parity(tmp_path / "valid")["pass"] is True

    desktop.available_chart_timeframes = lambda: [{"interval": "4h"}]
    with pytest.raises(ValueError, match="requires first/middle/last"):
        capture_parity(desktop, browser, tmp_path / "missing_tf", browser_payload=get_browser)
    desktop.available_chart_timeframes = browser.available_chart_timeframes

    def wrong_market(*, trade_index, chart_timeframe):
        value = payload(trade_index=trade_index, chart_timeframe=chart_timeframe)
        value["run"]["symbol"] = "ETHUSDT"
        return value

    desktop.build_v2_diagnostic_payload = wrong_market
    with pytest.raises(ValueError, match="payload identity mismatch"):
        capture_parity(desktop, browser, tmp_path / "wrong_market", browser_payload=get_browser)
