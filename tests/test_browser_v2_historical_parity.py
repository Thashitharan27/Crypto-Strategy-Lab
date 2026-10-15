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
