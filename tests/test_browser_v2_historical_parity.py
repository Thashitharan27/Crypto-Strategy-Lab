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
            "run": {"runId": "BTCUSDT_4h_fixture"},
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
