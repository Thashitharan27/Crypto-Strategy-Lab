"""Strict configuration loader for the forward Data Lake backtest path.

The Data Lake runner owns market-data selection through DataRequest/MarketDataStore,
so its strategy JSON deliberately has no CSV filename fields. BacktestConfig still
contains a few legacy path attributes while the GUI migration is in progress; this
loader supplies inert internal placeholders for those attributes and never exposes
them as part of the Data Lake configuration contract.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from crypto_strategy_lab.gui.config_logic import CONFIG_VERSION, DEFAULT_GUI_CONFIG, build_backtest_config
from crypto_strategy_lab.strategy_profiles import normalize_profiles, profiles_to_dict


# Market data and report destinations are runtime concerns for the Data Lake path,
# not strategy settings. structural_regime_benchmark_csv is also excluded because
# BTC/asset benchmark candles are loaded through MarketDataStore.
_DATA_LAKE_EXCLUDED_FIELDS = {
    "input_csv",
    "intrabar_csv",
    "output_dir",
    "structural_regime_benchmark_csv",
}

DATA_LAKE_CONFIG_FIELDS = frozenset(DEFAULT_GUI_CONFIG) - _DATA_LAKE_EXCLUDED_FIELDS


def default_data_lake_config() -> dict[str, Any]:
    values = {
        key: value
        for key, value in DEFAULT_GUI_CONFIG.items()
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
        raise ValueError(
            f"Data Lake configuration version {CONFIG_VERSION} is required."
        )
    merged["strategy_profiles"] = profiles_to_dict(
        normalize_profiles(merged["strategy_profiles"])
    )
    return merged


def build_data_lake_backtest_config(values: dict[str, Any]):
    """Build the current simulator config without accepting market-data paths."""

    cleaned = normalize_data_lake_config(values)
    bridge = dict(DEFAULT_GUI_CONFIG)
    bridge.update(cleaned)
    # Transitional internal values only. DataLakeBacktestEngine and the bundle
    # service never resolve these paths.
    bridge["input_csv"] = "__DATA_LAKE_STRATEGY__"
    bridge["intrabar_csv"] = None
    bridge["output_dir"] = "output"
    bridge["structural_regime_benchmark_csv"] = None
    return build_backtest_config(bridge, require_paths=False)


def load_data_lake_config(path: str | Path):
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return build_data_lake_backtest_config(raw)
