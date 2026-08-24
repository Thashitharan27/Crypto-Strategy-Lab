from __future__ import annotations

from dataclasses import replace

import pandas as pd

from crypto_strategy_lab.data_lake_config import ReportingConfig
import crypto_strategy_lab.research_reporting as reporting_runtime


def test_optional_artifact_analysis_writes_only_selected_post_run_outputs(
    tmp_path, monkeypatch
) -> None:
    calls: list[str] = []

    def marker_frame(name: str):
        def build(*_args, **_kwargs):
            calls.append(name)
            return pd.DataFrame({"value": [1]})
        return build

    monkeypatch.setattr(reporting_runtime, "equity_curve", marker_frame("equity"))

    def plots(_trades, _equity, path):
        calls.append("charts")
        path.mkdir(parents=True, exist_ok=True)
        (path / "chart.png").write_bytes(b"chart")
        return []

    monkeypatch.setattr(reporting_runtime, "save_plots", plots)
    monkeypatch.setattr(
        reporting_runtime, "trailing_profit_analysis", marker_frame("trailing")
    )
    monkeypatch.setattr(
        reporting_runtime,
        "partial_take_profit_analysis",
        marker_frame("partial_take_profit"),
    )
    for name in (
        "adx_analysis",
        "bb_width_analysis",
        "di_spread_analysis",
        "di_pressure_analysis",
        "mean_reversion_analysis",
    ):
        monkeypatch.setattr(reporting_runtime, name, marker_frame(name))

    def indicator_workbook(_tables, path):
        calls.append("indicator_workbook")
        path.mkdir(parents=True, exist_ok=True)
        target = path / "indicator_analysis.xlsx"
        target.write_bytes(b"xlsx")
        return target

    monkeypatch.setattr(reporting_runtime, "build_indicator_workbook", indicator_workbook)

    reporting = replace(
        ReportingConfig(),
        create_standard_charts=True,
        save_indicator_analysis_reports=True,
        save_feature_analysis_reports=True,
        enable_trade_telemetry=False,
        enable_indicator_lifecycle_analysis=False,
    )
    trades = pd.DataFrame({"pair_id": [1], "pair_net_pnl": [1.0]})

    root = reporting_runtime._write_optional_artifact_analysis(
        tmp_path, trades, reporting, 1000.0
    )

    assert root == tmp_path / "diagnostics"
    assert (root / "standard_charts" / "chart.png").exists()
    assert (root / "trade_exit_analysis" / "trailing_profit_analysis.csv").exists()
    assert (root / "trade_exit_analysis" / "partial_take_profit_analysis.csv").exists()
    assert (root / "indicator_analysis" / "indicator_analysis.xlsx").exists()
    assert (root / "indicator_analysis" / "di_mean_reversion_analysis.csv").exists()
    assert "charts" in calls
    assert "indicator_workbook" in calls

    catalog = reporting_runtime._catalog_optional_analysis(root, tmp_path)
    assert catalog
    assert all(entry["optional"] is True for entry in catalog.values())
    assert any(
        entry["path"]
        == "diagnostics/trade_exit_analysis/trailing_profit_analysis.csv"
        for entry in catalog.values()
    )


def test_core_style_reporting_creates_no_optional_analysis_directory(tmp_path) -> None:
    reporting = replace(
        ReportingConfig(),
        create_standard_charts=False,
        save_indicator_analysis_reports=False,
        save_feature_analysis_reports=False,
    )
    root = reporting_runtime._write_optional_artifact_analysis(
        tmp_path, pd.DataFrame(), reporting, 1000.0
    )
    assert root is None
    assert not (tmp_path / "diagnostics").exists()
