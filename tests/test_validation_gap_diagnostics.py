from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from crypto_strategy_lab.data import (
    DataQualityIssue,
    DataQualityReport,
    DataQualityStatus,
    DatasetQualityReport,
)


def _dataset(
    interval: str,
    *,
    symbol: str = "DOGEUSDT",
    status: DataQualityStatus = DataQualityStatus.OK,
    issues=(),
    requested_start: str = "2020-01-01T00:00:00+00:00",
    rows: int = 100,
):
    return DatasetQualityReport(
        dataset="klines",
        symbol=symbol,
        interval=interval,
        required=True,
        requested_start=requested_start,
        requested_end="2026-01-01T00:00:00+00:00",
        observed_start=requested_start,
        observed_end="2025-12-31T23:59:00+00:00",
        complete_start=requested_start,
        complete_end="2026-01-01T00:00:00+00:00",
        row_count=rows,
        source_identity="source",
        status=status,
        issues=tuple(issues),
    )


def test_gap_summary_exposes_exact_missing_count_and_bounds():
    from crypto_strategy_lab.gui.validation_diagnostics_install import _gap_summary

    issue = DataQualityIssue(
        "MISSING_INTERNAL_INTERVAL",
        DataQualityStatus.ERROR,
        "Internal fixed-cadence intervals are missing",
        count=3,
        first_timestamp="2022-05-11T03:00:00+00:00",
        last_timestamp="2022-05-11T05:00:00+00:00",
        details={
            "ranges": [
                {
                    "start": "2022-05-11T03:00:00+00:00",
                    "end": "2022-05-11T05:00:00+00:00",
                    "missing_count": 3,
                }
            ]
        },
    )
    missing, first_gap, last_gap, detail = _gap_summary(
        _dataset("1h", status=DataQualityStatus.ERROR, issues=(issue,))
    )

    assert missing == "3"
    assert first_gap == "2022-05-11 03:00:00 UTC"
    assert last_gap == "2022-05-11 05:00:00 UTC"
    assert "3 missing" in detail


def test_installed_renderer_labels_roles_and_distinguishes_benchmark():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    from crypto_strategy_lab.gui.validation_diagnostics_install import (
        QUALITY_HEADERS,
        apply_validation_gap_diagnostics,
    )

    app = widgets.QApplication.instance() or widgets.QApplication([])
    del app

    gap = DataQualityIssue(
        "MISSING_INTERNAL_INTERVAL",
        DataQualityStatus.ERROR,
        "Internal fixed-cadence intervals are missing",
        count=117,
        first_timestamp="2022-05-11T03:14:00+00:00",
        last_timestamp="2022-05-11T05:10:00+00:00",
    )
    strategy = _dataset("1h", status=DataQualityStatus.ERROR, issues=(gap,), rows=51720)
    intrabar = _dataset("1m", status=DataQualityStatus.ERROR, issues=(gap,), rows=3103200)
    benchmark = _dataset(
        "1h",
        symbol="BTCUSDT",
        requested_start="2019-05-09T00:00:00+00:00",
        rows=57528,
    )
    report = DataQualityReport((strategy, intrabar, benchmark))

    class Selector:
        def __init__(self, value):
            self.value = value

        def currentData(self):
            return self.value

    class Window:
        quality = widgets.QLabel()
        quality_table = widgets.QTableWidget(0, 6)
        strategy_tf = Selector("1h")
        intrabar_tf = Selector("1m")
        _validated_report = None

        def _is_benchmark_report(self, dataset):
            return dataset is benchmark

    window = Window()
    apply_validation_gap_diagnostics(window)
    apply_validation_gap_diagnostics(window)  # idempotent
    window.render_data_quality(report)

    headers = [
        window.quality_table.horizontalHeaderItem(i).text()
        for i in range(window.quality_table.columnCount())
    ]
    assert headers == list(QUALITY_HEADERS)
    assert window.quality_table.item(0, 0).text() == "Strategy"
    assert window.quality_table.item(1, 0).text() == "Intrabar / Exits"
    assert window.quality_table.item(2, 0).text() == "Market Regime Benchmark"
    assert window.quality_table.item(0, 1).text() == "DOGEUSDT"
    assert window.quality_table.item(0, 7).text() == "117"
    assert window.quality_table.item(0, 8).text() == "2022-05-11 03:14:00 UTC"
    assert window.quality_table.item(0, 9).text() == "2022-05-11 05:10:00 UTC"
    assert "MISSING_INTERNAL_INTERVAL (117)" == window.quality_table.item(0, 10).text()
    assert window.quality_table.item(2, 7).text() == "—"
