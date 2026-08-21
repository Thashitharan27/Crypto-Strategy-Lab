"""Strict configuration loader for the forward Data Lake backtest path.

Market-data selection belongs to DataRequest/MarketDataStore, while every strategy,
research and execution setting exposed by the normal GUI remains part of the Data
Lake configuration contract. Filename/path fields are deliberately excluded.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from crypto_strategy_lab.gui.config_logic import CONFIG_VERSION
from crypto_strategy_lab.gui.enhanced_config import (
    enhanced_default_gui_config,
    build_enhanced_backtest_config,
)
from crypto_strategy_lab.strategy_profiles import normalize_profiles, profiles_to_dict


_DATA_LAKE_EXCLUDED_FIELDS = {
    "input_csv",
    "intrabar_csv",
    "output_dir",
    "structural_regime_benchmark_csv",
}

DATA_LAKE_CONFIG_FIELDS = frozenset(enhanced_default_gui_config()) - _DATA_LAKE_EXCLUDED_FIELDS


def default_data_lake_config() -> dict[str, Any]:
    values = {
        key: value
        for key, value in enhanced_default_gui_config().items()
        if key in DATA_LAKE_CONFIG_FIELDS
    }
    values["strategy_profiles"] = profiles_to_dict(normalize_profiles(values["strategy_profiles"]))
    return values


def normalize_data_lake_config(values: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(values, dict):
        raise ValueError("Data Lake configuration JSON must contain an object")
    unknown = sorted(set(values) - DATA_LAKE_CONFIG_FIELDS)
    if unknown:
        raise ValueError("Unknown Data Lake configuration settings: " + ", ".join(unknown))

    merged = default_data_lake_config()
    merged.update(values)
    if int(merged.get("config_version", -1)) != CONFIG_VERSION:
        raise ValueError(f"Data Lake configuration version {CONFIG_VERSION} is required.")
    merged["strategy_profiles"] = profiles_to_dict(normalize_profiles(merged["strategy_profiles"]))
    return merged


def build_data_lake_backtest_config(values: dict[str, Any]):
    """Build the production EnhancedBacktestConfig without accepting data paths."""

    cleaned = normalize_data_lake_config(values)
    bridge = enhanced_default_gui_config()
    bridge.update(cleaned)
    # Transitional inert placeholders only. Data Lake services never resolve them.
    bridge["input_csv"] = "__DATA_LAKE_STRATEGY__"
    bridge["intrabar_csv"] = None
    bridge["output_dir"] = "output"
    bridge["structural_regime_benchmark_csv"] = None
    return build_enhanced_backtest_config(bridge, require_paths=False)


def load_data_lake_config(path: str | Path):
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return build_data_lake_backtest_config(raw)
