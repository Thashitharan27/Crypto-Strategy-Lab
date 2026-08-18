import json
from pathlib import Path

from crypto_strategy_lab.gui.config_logic import (
    canonical_config_values,
    default_gui_config,
    load_config_json,
    save_config_json,
)


def test_canonical_config_preserves_shared_settings_and_strategy_profiles():
    values = default_gui_config()
    values.update({
        "market_symbol": "SOLUSDT",
        "risk_mode": "FIXED",
        "fixed_r": 125.0,
        "maker_fee": 0.00017,
        "enable_di_pressure_analysis": True,
        "di_pressure_lookback": 7,
        "enable_support_resistance_analysis": True,
        "sr_filter_mode": "APPLY_ENTRY_RULES",
        "market_regime_method": "BTC_STRUCTURAL",
        "structural_regime_sma_days": 210,
    })
    bull_long = values["strategy_profiles"]["bull_long"]
    bull_long["reward_risk_ratio"] = 2.75
    bull_long["adx_enabled"] = True
    bull_long["adx_minimum"] = 22.0
    bull_long["adx_maximum"] = 35.0

    saved = canonical_config_values(values)

    assert saved["market_symbol"] == "SOLUSDT"
    assert saved["risk_mode"] == "FIXED"
    assert saved["fixed_r"] == 125.0
    assert saved["maker_fee"] == 0.00017
    assert saved["di_pressure_lookback"] == 7
    assert saved["sr_filter_mode"] == "APPLY_ENTRY_RULES"
    assert saved["structural_regime_sma_days"] == 210
    assert saved["strategy_profiles"]["bull_long"]["reward_risk_ratio"] == 2.75
    assert saved["strategy_profiles"]["bull_long"]["adx_enabled"] is True
    assert saved["enable_strategy_profiles"] is True


def test_canonical_config_excludes_profile_owned_hidden_globals_and_unknown_keys():
    values = default_gui_config()
    retired = {
        "sl_mult": 9.0,
        "tp_mult": 11.0,
        "enable_partial_take_profit": True,
        "enable_trailing_profit": True,
        "enable_adx_filter": True,
        "enable_bb_width_filter": True,
        "enable_di_spread_filter": True,
        "enable_random_entry": True,
        "vwap_breakout_lookback_hours": 99.0,
        "enable_remaining_leg_timeout_after_first_sl": True,
        "checkpoint_score_min_conditions": 1,
        "unknown_setting": "discard-me",
    }
    values.update(retired)

    saved = canonical_config_values(values)

    for key in retired:
        assert key not in saved


def test_save_load_round_trip_keeps_current_contract_and_no_dormant_legacy_tests(tmp_path):
    values = default_gui_config()
    values.update({
        "market_symbol": "ETHUSDT",
        "risk_mode": "PERCENT",
        "percent_r": 0.004,
        "enable_support_resistance_analysis": True,
        "sr_near_distance_atr": 1.25,
        "sl_mult": 99.0,
    })
    values["strategy_profiles"]["sideways_short"]["enabled"] = True
    values["strategy_profiles"]["sideways_short"]["reward_risk_ratio"] = 3.25
    values["strategy_profiles"]["sideways_short"]["bb_width_enabled"] = True
    values["strategy_profiles"]["sideways_short"]["bb_width_minimum"] = 0.04
    values["strategy_profiles"]["sideways_short"]["bb_width_maximum"] = 0.10

    path = tmp_path / "strategy-config.json"
    save_config_json(path, values)
    raw = json.loads(path.read_text(encoding="utf-8"))
    loaded = load_config_json(path)

    assert raw["enable_strategy_profiles"] is True
    assert "sl_mult" not in raw
    assert raw["market_symbol"] == "ETHUSDT"
    assert raw["sr_near_distance_atr"] == 1.25
    assert raw["strategy_profiles"]["sideways_short"]["reward_risk_ratio"] == 3.25
    assert loaded["market_symbol"] == "ETHUSDT"
    assert loaded["percent_r"] == 0.004
    assert loaded["strategy_profiles"]["sideways_short"]["bb_width_minimum"] == 0.04

    gui_tests = (Path(__file__).resolve().parent / "test_gui_config_logic.py").read_text(encoding="utf-8")
    assert "def legacy_entry_filter_options_round_trip" not in gui_tests
    assert "def legacy_remaining_leg_timeout_json_round_trip_and_validation" not in gui_tests
