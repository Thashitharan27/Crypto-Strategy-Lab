"""Temporary Stage 19 helper for large test files that need small exact migrations."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_exact(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        return
    target.write_text(text.replace(old, new), encoding="utf-8")


def replace_between(path: str, start: str, end: str, replacement: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    start_i = text.find(start)
    if start_i < 0:
        return
    end_i = text.find(end, start_i)
    if end_i < 0:
        raise SystemExit(f"Stage 19 test migration end marker missing in {path}: {end!r}")
    target.write_text(text[:start_i] + replacement + text[end_i:], encoding="utf-8")


replace_exact(
    "tests/test_gui_main_window.py",
    '''        values=window.values()\n        assert values["enable_strategy_profiles"] is True\n        assert values["di_execution_mode"] == "PREFERRED_SIDE_ONLY"\n''',
    '''        values=window.values()\n        assert "enable_strategy_profiles" not in values\n        assert "di_execution_mode" not in values\n        assert set(values["strategy_profiles"]) == {\n            "bull_long", "bull_short", "bear_long", "bear_short", "sideways_long", "sideways_short"\n        }\n''',
)

replace_between(
    "tests/test_gui_main_window.py",
    "def test_gui_reset_restores_all_default_values_and_run_name():\n",
    "def test_new_run_confirmation_resets_defaults_refreshes_path_and_clears_results",
    '''def test_gui_reset_restores_all_current_default_values_and_profiles():\n    from crypto_strategy_lab.gui.config_logic import default_gui_config, format_percentage\n\n    app()\n    window = MainWindow()\n    defaults = default_gui_config()\n    try:\n        changed = {\n            "run_name": "custom",\n            "atr_period": 7,\n            "atr_multiplier": 2.5,\n            "initial_equity": 555,\n            "risk_per_leg": 0.123,\n            "maker_fee": 0.1,\n            "taker_fee": 0.2,\n            "slippage": 0.3,\n            "strategy_timeframe_minutes": 60,\n            "intrabar_timeframe_minutes": 5,\n            "use_intrabar_data": False,\n        }\n        changed["strategy_profiles"] = defaults["strategy_profiles"]\n        changed["strategy_profiles"]["bull_long"]["reward_risk_ratio"] = 4.0\n        window.apply_values(changed)\n        assert window.values()["run_name"] == "custom"\n        assert window.values()["strategy_profiles"]["bull_long"]["reward_risk_ratio"] == 4.0\n\n        window.reset_defaults()\n        values = window.values()\n\n        for key in (\n            "run_name", "input_csv", "intrabar_csv", "use_intrabar_data", "output_dir",\n            "entry_mode", "entry_interval", "max_active_pairs", "tie_policy", "risk_mode",\n            "atr_period", "atr_multiplier", "trading_start_date", "trading_end_date",\n            "max_effective_leverage_per_leg", "max_combined_effective_leverage",\n            "intrabar_missing_policy", "zero_cost_comparison", "percent_r", "fixed_r",\n            "initial_equity", "risk_per_leg", "maker_fee", "taker_fee", "use_maker_entry",\n            "use_maker_exit", "slippage", "strategy_profiles",\n        ):\n            assert values[key] == defaults[key]\n\n        assert "strategy_csv" not in values\n        assert "sl_mult" not in values\n        assert "tp_mult" not in values\n        assert window.atr_period.value() == 14\n        assert window.atr_mult.value() == 1.0\n        assert window.equity.value() == 1000\n        assert window.risk_leg.text() == format_percentage(0.01)\n        assert window.maker.text() == format_percentage(0.0002)\n        assert window.taker.text() == format_percentage(0.0005)\n        assert window.slippage.text() == format_percentage(0.0005)\n        assert values["use_intrabar_data"] is True\n    finally:\n        window.close()\n\n\n''',
)

print("Applied Stage 19 current-contract test migrations.")
