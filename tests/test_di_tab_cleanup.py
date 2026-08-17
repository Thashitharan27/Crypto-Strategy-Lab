import ast
from dataclasses import asdict
from pathlib import Path

from crypto_strategy_lab.config import BacktestConfig
from crypto_strategy_lab.gui.config_logic import canonical_config_values, default_gui_config


def _di_tab_source():
    path = Path("crypto_strategy_lab/gui/main_window.py")
    tree = ast.parse(path.read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MainWindow")
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "_build_di_strategy_tab")
    return ast.get_source_segment(path.read_text(), method)


def test_di_tab_is_direction_and_pressure_only():
    source = _di_tab_source()
    assert "enable_di_direction_selection" in source
    assert "enable_di_pressure_analysis" in source
    assert "di_pressure_lookback" in source
    for obsolete in ("flip_filtered_di_direction", "di_execution_mode", "reward_risk", "Regime-Specific"):
        assert obsolete not in source


def test_legacy_di_strategy_fields_are_not_serialized():
    saved = canonical_config_values(default_gui_config())
    for obsolete in (
        "di_execution_mode", "di_reward_risk_ratio", "di_long_reward_risk_ratio",
        "di_short_reward_risk_ratio", "enable_di_regime_reward_risk",
        "flip_filtered_di_direction", "di_direction_minimum_spread",
        "directional_long_di_spread_minimum", "allow_bull_long",
    ):
        assert obsolete not in saved
    assert "enable_di_direction_selection" in saved
    assert "enable_di_pressure_analysis" in saved
    assert "di_pressure_lookback" in saved
    assert "bear_regime_return_threshold" in asdict(BacktestConfig())
