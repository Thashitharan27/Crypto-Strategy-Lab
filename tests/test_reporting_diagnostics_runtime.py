from __future__ import annotations

from dataclasses import replace

import pytest

from crypto_strategy_lab.data_lake_config import (
    DataConfig,
    ExecutionConfig,
    FeatureConfig,
    ReportingConfig,
    ResearchRunConfig,
    StrategyConfig,
)
from crypto_strategy_lab.gui.ux_presentation import (
    apply_report_profile,
    detect_report_profile,
)
from crypto_strategy_lab.research_adapters import native_simulator_config


def test_reporting_defaults_are_the_recommended_review_profile() -> None:
    reporting = ReportingConfig()
    assert detect_report_profile(reporting) == "REVIEW"
    assert reporting.create_human_workbook is True
    assert reporting.create_standard_charts is True
    assert reporting.enable_trade_telemetry is False
    assert reporting.save_indicator_analysis_reports is False


def test_core_and_deep_profiles_are_deterministic() -> None:
    base = ReportingConfig(run_name="keep-me")
    core = apply_report_profile(base, "CORE")
    assert core.run_name == "keep-me"
    assert core.create_human_workbook is False
    assert core.create_standard_charts is False
    assert detect_report_profile(core) == "CORE"

    deep = apply_report_profile(base, "DEEP_DIAGNOSTICS")
    assert deep.create_human_workbook is True
    assert deep.enable_trade_telemetry is True
    assert deep.save_full_telemetry_csv is True
    assert deep.save_trade_journey_summary is True
    assert deep.save_trade_journey_charts is True
    assert deep.enable_indicator_lifecycle_analysis is True
    assert deep.create_lifecycle_charts is True
    assert deep.save_indicator_analysis_reports is True
    assert detect_report_profile(deep) == "DEEP_DIAGNOSTICS"


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
