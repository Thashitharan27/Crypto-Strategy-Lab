"""Presentation metadata for the native v3 research configuration.

This module deliberately contains no research logic. Values are converted only
at the widget boundary; the dataclasses continue to store their canonical units.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from copy import deepcopy


@dataclass(frozen=True)
class FieldPresentation:
    label: str
    help: str = ""
    unit: str = ""
    scale: float = 1.0
    decimals: int = 4

    def display(self, value: float) -> float:
        return value * self.scale

    def native(self, value: float) -> float:
        return value / self.scale


PERCENT_FIELDS = {"risk_per_leg", "maker_fee", "taker_fee", "slippage", "percent_r"}
FIELDS = {
    "initial_equity": FieldPresentation("Starting Equity", unit="$", decimals=2),
    "risk_per_leg": FieldPresentation("Base Risk Per Trade", "Fraction of equity risked at a full stop.", "%", 100, 4),
    "maker_fee": FieldPresentation("Maker Fee", unit="%", scale=100, decimals=4),
    "taker_fee": FieldPresentation("Taker Fee", unit="%", scale=100, decimals=4),
    "slippage": FieldPresentation("Slippage", unit="%", scale=100, decimals=4),
    "percent_r": FieldPresentation("Price Distance", unit="%", scale=100, decimals=4),
    "reward_risk_ratio": FieldPresentation("Profit Target", unit=" R", decimals=2),
    "stop_loss_multiple": FieldPresentation("Stop Distance", unit=" distance units", decimals=2),
    "risk_multiplier": FieldPresentation("Risk Multiplier", unit="x", decimals=2),
    "timeout_minutes": FieldPresentation("Maximum Holding Time", unit=" min", decimals=0),
    "strategy_profile_run_mode": FieldPresentation("Profile Test Mode"),
    "tie_policy": FieldPresentation("Same-bar Resolution"),
    "run_name": FieldPresentation("Run Name", "Optional friendly name stored with this run."),
    "create_human_workbook": FieldPresentation("Performance Workbook"),
    "create_standard_charts": FieldPresentation("Standard Charts"),
    "enable_trade_telemetry": FieldPresentation("Trade Journey Diagnostics"),
    "save_full_telemetry_csv": FieldPresentation("Save Raw Telemetry CSV"),
    "save_trade_journey_summary": FieldPresentation("Trade Journey Summary"),
    "save_trade_journey_charts": FieldPresentation("Trade Journey Charts"),
    "telemetry_interval_minutes": FieldPresentation("Journey Sampling Interval", unit=" min", decimals=0),
    "enable_indicator_lifecycle_analysis": FieldPresentation("Indicator Lifecycle Diagnostics"),
    "lifecycle_phases": FieldPresentation("Lifecycle Phases", decimals=0),
    "lifecycle_minimum_bucket_sample": FieldPresentation("Minimum Trades Per Bucket", decimals=0),
    "create_lifecycle_charts": FieldPresentation("Lifecycle Charts"),
    "lifecycle_flat_pattern_threshold_pct": FieldPresentation("Flat Pattern Threshold", unit="%", decimals=2),
    "save_indicator_analysis_reports": FieldPresentation("Indicator Analysis Workbook"),
}

ENUM_LABELS = {
    "strategy_profile_run_mode": {"COMBINED_SHARED_CAPITAL": "Combined — Shared Account", "ISOLATED_PROFILES": "Each Profile Independently", "BOTH": "Combined + Independent Comparison"},
    "tie_policy": {"PESSIMISTIC": "Conservative — Stop First", "OPTIMISTIC": "Optimistic — Target First", "INTRABAR": "Resolve Using Intrabar Data"},
    "market_regime_method": {"BTC_STRUCTURAL": "BTC Structural Trend", "ASSET_STRUCTURAL": "Selected Asset Structural Trend", "ASSET_RETURN": "Selected Asset Trailing Return"},
    "sr_filter_mode": {"ANALYSIS_ONLY": "Analysis Only — Do Not Block Trades", "APPLY_ENTRY_RULES": "Use S/R Entry Filters"},
    "risk_mode": {"ATR": "ATR Volatility", "PERCENT": "Percent of Price", "FIXED": "Fixed Price Distance"},
    "trade_flow_source": {"AGG_TRADES": "Aggregate Trades", "TRADES": "Trades"},
    "flip_rule_match_mode": {"ANY": "Any Rule (OR)", "ALL": "All Rules (AND)"},
    "reject_rule_match_mode": {"ANY": "Any Rule (OR)", "ALL": "All Rules (AND)"},
    "sr_take_profit_mode": {"FIXED_R": "Fixed R Target", "SR_CAPPED_R": "Cap Target at Support/Resistance"},
    "sr_take_profit_no_level_policy": {"USE_FIXED_TP": "Use Fixed Target When No Level Exists", "REJECT_TRADE": "Reject Trade When No Valid Level Exists"},
}

PROFILE_LABELS = {"bull_long": "Bull Long", "bull_short": "Bull Short", "bear_long": "Bear Long", "bear_short": "Bear Short", "sideways_long": "Sideways Long", "sideways_short": "Sideways Short"}


def metadata(name: str) -> FieldPresentation:
    return FIELDS.get(name, FieldPresentation(name.replace("_", " ").title()))


def display_percentage(native: float, decimals: int = 2) -> str:
    return f"{native * 100:.{decimals}f}%"


def parse_percentage(display: str | float) -> float:
    return float(str(display).strip().removesuffix("%").strip()) / 100


# Reporting profiles are presentation policy. Canonical machine-readable artifacts
# are always written by the native reporter; these settings control optional human
# review and passive diagnostic work only.
REPORT_PROFILES = {
    "CORE": dict(
        analysis_level="QUICK",
        create_human_workbook=False,
        create_standard_charts=False,
        enable_trade_telemetry=False,
        save_full_telemetry_csv=False,
        save_trade_journey_summary=False,
        save_trade_journey_charts=False,
        telemetry_interval_minutes=15,
        enable_indicator_lifecycle_analysis=False,
        lifecycle_phases=4,
        lifecycle_early_checkpoints=(15, 30, 60),
        lifecycle_minimum_bucket_sample=20,
        create_lifecycle_charts=False,
        lifecycle_flat_pattern_threshold_pct=5.0,
        save_feature_analysis_reports=False,
        save_indicator_analysis_reports=False,
    ),
    "REVIEW": dict(
        analysis_level="STANDARD",
        create_human_workbook=True,
        create_standard_charts=True,
        enable_trade_telemetry=False,
        save_full_telemetry_csv=False,
        save_trade_journey_summary=False,
        save_trade_journey_charts=False,
        telemetry_interval_minutes=15,
        enable_indicator_lifecycle_analysis=False,
        lifecycle_phases=4,
        lifecycle_early_checkpoints=(15, 30, 60),
        lifecycle_minimum_bucket_sample=20,
        create_lifecycle_charts=False,
        lifecycle_flat_pattern_threshold_pct=5.0,
        save_feature_analysis_reports=False,
        save_indicator_analysis_reports=False,
    ),
    "DEEP_DIAGNOSTICS": dict(
        analysis_level="DEEP",
        create_human_workbook=True,
        create_standard_charts=True,
        enable_trade_telemetry=True,
        save_full_telemetry_csv=True,
        save_trade_journey_summary=True,
        save_trade_journey_charts=True,
        telemetry_interval_minutes=15,
        enable_indicator_lifecycle_analysis=True,
        lifecycle_phases=4,
        lifecycle_early_checkpoints=(15, 30, 60),
        lifecycle_minimum_bucket_sample=20,
        create_lifecycle_charts=True,
        lifecycle_flat_pattern_threshold_pct=5.0,
        save_feature_analysis_reports=False,
        save_indicator_analysis_reports=True,
    ),
}

REPORT_PROFILE_LABELS = {
    "CORE": "Core — canonical artifacts only",
    "REVIEW": "Review — recommended",
    "DEEP_DIAGNOSTICS": "Deep Diagnostics — slower",
    "CUSTOM": "Custom",
}


def apply_report_profile(reporting, profile: str):
    """Apply one immediate researcher-facing output profile."""
    if profile == "CUSTOM":
        return reporting
    return replace(reporting, **REPORT_PROFILES[profile])


def detect_report_profile(reporting) -> str:
    """Return the exact matching profile, otherwise CUSTOM."""
    for profile, values in REPORT_PROFILES.items():
        if all(getattr(reporting, name) == value for name, value in values.items()):
            return profile
    return "CUSTOM"


# Keep the old preset helper as a bounded compatibility surface for the hidden
# generic v2 page. The active Reports & Diagnostics workspace uses REPORT_PROFILES.
REPORT_PRESETS = {
    "QUICK": REPORT_PROFILES["CORE"],
    "STANDARD": REPORT_PROFILES["REVIEW"],
    "DEEP_RESEARCH": REPORT_PROFILES["DEEP_DIAGNOSTICS"],
}


def apply_report_preset(reporting, preset: str):
    """Return a new ReportingConfig using the bounded legacy preset names."""
    return replace(reporting, **REPORT_PRESETS[preset])


def clone_profile_pair(strategy, execution):
    """Copy profile values without sharing mutable rule payloads."""
    return deepcopy(strategy), deepcopy(execution)
