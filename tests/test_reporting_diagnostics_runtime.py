from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from crypto_strategy_lab.data_lake_config import (
    DataConfig,
    ExecutionConfig,
    FeatureConfig,
    ReportingConfig,
    ResearchRunConfig,
    StrategyConfig,
)
from crypto_strategy_lab.research_adapters import native_simulator_config
import crypto_strategy_lab.research_reporting as reporting_runtime


ROOT = Path(__file__).resolve().parents[1]


def test_research_runner_passes_reporting_config_to_passive_observation() -> None:
    source = (ROOT / "crypto_strategy_lab" / "research_runner.py").read_text(
        encoding="utf-8"
    )
    assert 'getattr(self.simulator, "configure_observation", None)' in source
    assert "configure_observation(run_config.reporting)" in source


def test_reporting_validation_enforces_module_dependencies() -> None:
    base = ResearchRunConfig()
    with pytest.raises(ValueError, match="Trade Journey Diagnostics"):
        replace(
            base,
            reporting=replace(
                base.reporting,
                enable_trade_telemetry=False,
                save_trade_journey_summary=True,
            ),
        ).validate()

    with pytest.raises(ValueError, match="Lifecycle Diagnostics"):
        replace(
            base,
            reporting=replace(
                base.reporting,
                enable_indicator_lifecycle_analysis=False,
                create_lifecycle_charts=True,
            ),
        ).validate()


def test_reporting_validation_requires_timeframe_compatible_sampling() -> None:
    config = ResearchRunConfig(
        data=DataConfig(strategy_timeframe_minutes=60, intrabar_timeframe_minutes=1),
        reporting=replace(
            ReportingConfig(),
            enable_trade_telemetry=True,
            telemetry_interval_minutes=15,
        ),
    )
    with pytest.raises(ValueError, match="multiple of strategy timeframe"):
        config.validate()


def test_reporting_validation_checks_lifecycle_thresholds() -> None:
    base = ResearchRunConfig()
    with pytest.raises(ValueError, match="unique and increasing"):
        replace(
            base,
            reporting=replace(
                base.reporting,
                enable_indicator_lifecycle_analysis=True,
                lifecycle_early_checkpoints=(30, 15, 30),
            ),
        ).validate()

    with pytest.raises(ValueError, match="minimum bucket sample"):
        replace(
            base,
            reporting=replace(
                base.reporting,
                enable_indicator_lifecycle_analysis=True,
                lifecycle_minimum_bucket_sample=0,
            ),
        ).validate()


def test_passive_telemetry_is_enabled_only_when_diagnostics_need_it() -> None:
    base_args = (DataConfig(), FeatureConfig(), StrategyConfig(), ExecutionConfig())

    normal = native_simulator_config(*base_args, ReportingConfig())
    assert normal.enable_trade_telemetry is False

    journey = native_simulator_config(
        *base_args,
        replace(ReportingConfig(), enable_trade_telemetry=True),
    )
    assert journey.enable_trade_telemetry is True
    assert journey.telemetry_interval_minutes == 15

    lifecycle_only = native_simulator_config(
        *base_args,
        replace(
            ReportingConfig(),
            enable_indicator_lifecycle_analysis=True,
            telemetry_interval_minutes=15,
        ),
    )
    assert lifecycle_only.enable_trade_telemetry is True
    assert lifecycle_only.telemetry_interval_minutes == 15


def test_optional_diagnostics_generate_only_requested_downstream_outputs(
    tmp_path, monkeypatch
) -> None:
    calls: list[str] = []

    def marker_frame(name: str):
        def build(*_args, **_kwargs):
            calls.append(name)
            return pd.DataFrame({"value": [1]})
        return build

    monkeypatch.setattr(reporting_runtime, "equity_curve", marker_frame("equity"))
    monkeypatch.setattr(
        reporting_runtime,
        "save_plots",
        lambda _trades, _equity, path: (
            calls.append("standard_charts"),
            path.mkdir(parents=True, exist_ok=True),
            (path / "chart.png").write_bytes(b"chart"),
        )[-1],
    )
    monkeypatch.setattr(
        reporting_runtime, "trailing_profit_analysis", marker_frame("trailing")
    )
    monkeypatch.setattr(
        reporting_runtime, "partial_take_profit_analysis", marker_frame("partial")
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
    monkeypatch.setattr(
        reporting_runtime,
        "add_journey_columns",
        lambda trades, _telemetry: calls.append("journey_columns") or trades.copy(),
    )
    monkeypatch.setattr(
        reporting_runtime, "trade_journey_analysis", marker_frame("journey_summary")
    )
    monkeypatch.setattr(
        reporting_runtime,
        "winner_loser_journey_analysis",
        marker_frame("winner_loser"),
    )
    monkeypatch.setattr(
        reporting_runtime, "stop_loss_journey_analysis", marker_frame("stop_loss")
    )

    def journey_charts(_trades, _telemetry, path):
        calls.append("journey_charts")
        path.mkdir(parents=True, exist_ok=True)
        (path / "journey.png").write_bytes(b"chart")
        return []

    monkeypatch.setattr(reporting_runtime, "save_journey_charts", journey_charts)

    def lifecycle(_trades, _telemetry, path, **_kwargs):
        calls.append("lifecycle")
        path.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"value": [1]}).to_csv(path / "lifecycle.csv", index=False)
        return {}

    monkeypatch.setattr(reporting_runtime, "export_lifecycle_reports", lifecycle)

    reporting = replace(
        ReportingConfig(),
        enable_trade_telemetry=True,
        save_full_telemetry_csv=True,
        save_trade_journey_summary=True,
        save_trade_journey_charts=True,
        enable_indicator_lifecycle_analysis=True,
        create_lifecycle_charts=True,
        save_feature_analysis_reports=True,
        save_indicator_analysis_reports=True,
        create_standard_charts=True,
    )
    trades = pd.DataFrame({"pair_id": [1], "pair_net_pnl": [1.0]})
    telemetry = pd.DataFrame({"pair_id": [1], "timestamp": [pd.Timestamp("2024-01-01")]})

    root = reporting_runtime._write_optional_diagnostics(
        tmp_path, trades, telemetry, reporting, 1000.0
    )
    assert root == tmp_path / "diagnostics"
    assert (root / "feature_analysis" / "trailing_profit_analysis.csv").exists()
    assert (root / "feature_analysis" / "partial_take_profit_analysis.csv").exists()
    assert (root / "indicator_analysis" / "indicator_analysis.xlsx").exists()
    assert (root / "trade_journey" / "trade_telemetry.csv").exists()
    assert (root / "trade_journey" / "trade_journey_analysis.csv").exists()
    assert (root / "trade_journey" / "charts" / "journey.png").exists()
    assert (root / "indicator_lifecycle" / "lifecycle.csv").exists()
    assert "lifecycle" in calls

    catalog = reporting_runtime._catalog_diagnostics(root, tmp_path)
    assert catalog
    assert all(entry["optional"] is True for entry in catalog.values())
    assert any(
        entry["path"] == "diagnostics/trade_journey/trade_telemetry.csv"
        for entry in catalog.values()
    )


def test_optional_diagnostics_require_collected_telemetry_for_real_trades(tmp_path) -> None:
    reporting = replace(
        ReportingConfig(),
        enable_trade_telemetry=True,
        create_standard_charts=False,
        save_indicator_analysis_reports=False,
    )
    with pytest.raises(ValueError, match="did not receive passive trade telemetry"):
        reporting_runtime._write_optional_diagnostics(
            tmp_path,
            pd.DataFrame({"pair_id": [1]}),
            pd.DataFrame(),
            reporting,
            1000.0,
        )
