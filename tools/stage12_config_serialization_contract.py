from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

config_path = ROOT / "crypto_strategy_lab" / "gui" / "config_logic.py"
text = config_path.read_text(encoding="utf-8")

if "_OBSOLETE_EXACT = {" not in text or "_OBSOLETE_PREFIXES = (" not in text:
    raise RuntimeError("Stage 12 expected legacy serialization constants were not found")
text = text.replace("_OBSOLETE_EXACT = {", "_PROFILE_OWNED_LEGACY_EXACT = {", 1)
text = text.replace("_OBSOLETE_PREFIXES = (", "_PROFILE_OWNED_LEGACY_PREFIXES = (", 1)

text, regime_count = re.subn(
    r'\n_REGIME_CONFIG_KEYS = \{"market_regime_method","structural_regime_sma_days","structural_regime_slope_lookback_days","structural_regime_benchmark_csv","bull_regime_lookback_days","bull_regime_return_threshold"\}\n',
    "\n",
    text,
    count=1,
)
if regime_count != 1:
    raise RuntimeError("Stage 12 expected redundant regime serialization exception was not found")

pattern = re.compile(
    r'def canonical_config_values\(values: dict\[str, Any\]\) -> dict\[str, Any\]:\n'
    r'    """Return the compact, profile-only public configuration format\."""\n'
    r'    result=\{\}\n'
    r'    for key,value in values\.items\(\):\n'
    r'        if key not in DEFAULT_GUI_CONFIG:\n'
    r'            continue\n'
    r'        if key in _REGIME_CONFIG_KEYS or \(key not in _OBSOLETE_EXACT and not key\.startswith\(_OBSOLETE_PREFIXES\)\): result\[key\]=value\n'
    r'    result\["enable_strategy_profiles"\]=True\n'
    r'    return result\n'
)
replacement = '''def _is_profile_owned_legacy_key(key: str) -> bool:\n    """Return True for hidden global settings superseded by Strategy Profiles."""\n    return key in _PROFILE_OWNED_LEGACY_EXACT or key.startswith(_PROFILE_OWNED_LEGACY_PREFIXES)\n\n\ndef canonical_config_values(values: dict[str, Any]) -> dict[str, Any]:\n    """Return the saved-config contract: shared settings plus Strategy Profiles."""\n    result = {\n        key: value\n        for key, value in values.items()\n        if key in DEFAULT_GUI_CONFIG and not _is_profile_owned_legacy_key(key)\n    }\n    result["enable_strategy_profiles"] = True\n    return result\n'''
text, canonical_count = pattern.subn(replacement, text, count=1)
if canonical_count != 1:
    raise RuntimeError("Stage 12 expected canonical_config_values implementation was not found")

config_path.write_text(text, encoding="utf-8")

test_path = ROOT / "tests" / "test_gui_config_logic.py"
tests = test_path.read_text(encoding="utf-8")

tests, first_count = re.subn(
    r'\n\ndef legacy_entry_filter_options_round_trip\(tmp_path\):.*?(?=\n\ndef test_gui_passes_selected_intrabar_csv_and_enabled_flag)',
    "",
    tests,
    count=1,
    flags=re.S,
)
if first_count != 1:
    raise RuntimeError("Stage 12 expected dormant legacy entry-filter test was not found")

tests, second_count = re.subn(
    r'\n\ndef legacy_remaining_leg_timeout_json_round_trip_and_validation\(tmp_path\):.*?(?=\n\ndef test_support_resistance_settings_round_trip_and_validation)',
    "",
    tests,
    count=1,
    flags=re.S,
)
if second_count != 1:
    raise RuntimeError("Stage 12 expected dormant remaining-leg legacy test was not found")

test_path.write_text(tests, encoding="utf-8")

contract_test = ROOT / "tests" / "test_stage12_config_serialization_contract.py"
contract_test.write_text('''import json\nfrom pathlib import Path\n\nfrom crypto_strategy_lab.gui.config_logic import (\n    canonical_config_values,\n    default_gui_config,\n    load_config_json,\n    save_config_json,\n)\n\n\ndef test_canonical_config_preserves_shared_settings_and_strategy_profiles():\n    values = default_gui_config()\n    values.update({\n        "market_symbol": "SOLUSDT",\n        "risk_mode": "FIXED",\n        "fixed_r": 125.0,\n        "maker_fee": 0.00017,\n        "enable_di_pressure_analysis": True,\n        "di_pressure_lookback": 7,\n        "enable_support_resistance_analysis": True,\n        "sr_filter_mode": "APPLY_ENTRY_RULES",\n        "market_regime_method": "BTC_STRUCTURAL",\n        "structural_regime_sma_days": 210,\n    })\n    bull_long = values["strategy_profiles"]["bull_long"]\n    bull_long["reward_risk_ratio"] = 2.75\n    bull_long["adx_enabled"] = True\n    bull_long["adx_minimum"] = 22.0\n    bull_long["adx_maximum"] = 35.0\n\n    saved = canonical_config_values(values)\n\n    assert saved["market_symbol"] == "SOLUSDT"\n    assert saved["risk_mode"] == "FIXED"\n    assert saved["fixed_r"] == 125.0\n    assert saved["maker_fee"] == 0.00017\n    assert saved["di_pressure_lookback"] == 7\n    assert saved["sr_filter_mode"] == "APPLY_ENTRY_RULES"\n    assert saved["structural_regime_sma_days"] == 210\n    assert saved["strategy_profiles"]["bull_long"]["reward_risk_ratio"] == 2.75\n    assert saved["strategy_profiles"]["bull_long"]["adx_enabled"] is True\n    assert saved["enable_strategy_profiles"] is True\n\n\ndef test_canonical_config_excludes_profile_owned_hidden_globals_and_unknown_keys():\n    values = default_gui_config()\n    retired = {\n        "sl_mult": 9.0,\n        "tp_mult": 11.0,\n        "enable_partial_take_profit": True,\n        "enable_trailing_profit": True,\n        "enable_adx_filter": True,\n        "enable_bb_width_filter": True,\n        "enable_di_spread_filter": True,\n        "enable_random_entry": True,\n        "vwap_breakout_lookback_hours": 99.0,\n        "enable_remaining_leg_timeout_after_first_sl": True,\n        "checkpoint_score_min_conditions": 1,\n        "unknown_setting": "discard-me",\n    }\n    values.update(retired)\n\n    saved = canonical_config_values(values)\n\n    for key in retired:\n        assert key not in saved\n\n\ndef test_save_load_round_trip_keeps_current_contract_and_no_dormant_legacy_tests(tmp_path):\n    values = default_gui_config()\n    values.update({\n        "market_symbol": "ETHUSDT",\n        "risk_mode": "PERCENT",\n        "percent_r": 0.004,\n        "enable_support_resistance_analysis": True,\n        "sr_near_distance_atr": 1.25,\n        "sl_mult": 99.0,\n    })\n    values["strategy_profiles"]["sideways_short"]["enabled"] = True\n    values["strategy_profiles"]["sideways_short"]["reward_risk_ratio"] = 3.25\n    values["strategy_profiles"]["sideways_short"]["bb_width_enabled"] = True\n    values["strategy_profiles"]["sideways_short"]["bb_width_minimum"] = 0.04\n    values["strategy_profiles"]["sideways_short"]["bb_width_maximum"] = 0.10\n\n    path = tmp_path / "strategy-config.json"\n    save_config_json(path, values)\n    raw = json.loads(path.read_text(encoding="utf-8"))\n    loaded = load_config_json(path)\n\n    assert raw["enable_strategy_profiles"] is True\n    assert "sl_mult" not in raw\n    assert raw["market_symbol"] == "ETHUSDT"\n    assert raw["sr_near_distance_atr"] == 1.25\n    assert raw["strategy_profiles"]["sideways_short"]["reward_risk_ratio"] == 3.25\n    assert loaded["market_symbol"] == "ETHUSDT"\n    assert loaded["percent_r"] == 0.004\n    assert loaded["strategy_profiles"]["sideways_short"]["bb_width_minimum"] == 0.04\n\n    gui_tests = (Path(__file__).resolve().parent / "test_gui_config_logic.py").read_text(encoding="utf-8")\n    assert "def legacy_entry_filter_options_round_trip" not in gui_tests\n    assert "def legacy_remaining_leg_timeout_json_round_trip_and_validation" not in gui_tests\n''', encoding="utf-8")

print("Stage 12 config serialization contract applied")
