from pathlib import Path
import pytest
from crypto_strategy_lab.config import RiskMode, TradeDirectionMode
from crypto_strategy_lab.gui.config_logic import parse_percentage, build_backtest_config, save_config_json, load_config_json, validate_config_values


def base(tmp_path):
    csv = tmp_path / "x.csv"
    csv.write_text("timestamp,open,high,low,close,volume\n2024-01-01,1,1,1,1,1\n")
    return {"input_csv": str(csv), "output_dir": str(tmp_path / "out")}


def test_percent_conversions():
    assert parse_percentage("0.5%") == pytest.approx(0.005)
    assert parse_percentage("0.05%") == pytest.approx(0.0005)


def test_atr_mode_creates_config(tmp_path):
    cfg = build_backtest_config({**base(tmp_path), "risk_mode": "ATR", "atr_period": 14, "atr_multiplier": 1.5})
    assert cfg.risk_mode == RiskMode.ATR
    assert cfg.atr_period == 14
    assert cfg.atr_multiplier == pytest.approx(1.5)


def test_percentage_mode_creates_config(tmp_path):
    cfg = build_backtest_config({**base(tmp_path), "risk_mode": "PERCENT", "percent_r": parse_percentage("0.20%")})
    assert cfg.risk_mode == RiskMode.PERCENT
    assert cfg.percent_r == pytest.approx(0.002)


def test_fixed_mode_creates_config(tmp_path):
    cfg = build_backtest_config({**base(tmp_path), "risk_mode": "FIXED", "fixed_r": 100})
    assert cfg.risk_mode == RiskMode.FIXED
    assert cfg.fixed_r == pytest.approx(100)


def test_invalid_values_rejected(tmp_path):
    with pytest.raises(ValueError, match="SL multiple"):
        build_backtest_config({**base(tmp_path), "sl_mult": 0})
    with pytest.raises(ValueError, match="Risk per leg"):
        build_backtest_config({**base(tmp_path), "risk_per_leg": 1})


def test_saved_configuration_loads_correctly(tmp_path):
    path = tmp_path / "cfg.json"
    save_config_json(path, {**base(tmp_path), "risk_mode": "FIXED", "fixed_r": 123, "risk_per_leg": 0.005})
    loaded = load_config_json(path)
    cfg = build_backtest_config(loaded)
    assert cfg.fixed_r == pytest.approx(123)
    assert cfg.risk_per_leg == pytest.approx(0.005)


def test_optional_report_settings_round_trip(tmp_path):
    path = tmp_path / "report-settings.json"
    save_config_json(path, {
        **base(tmp_path),
        "save_feature_analysis_reports": False,
        "save_indicator_analysis_reports": False,
        "create_standard_charts": False,
    })
    cfg = build_backtest_config(load_config_json(path))
    assert cfg.save_feature_analysis_reports is False
    assert cfg.save_indicator_analysis_reports is False
    assert cfg.create_standard_charts is False


def legacy_entry_filter_options_round_trip(tmp_path):
    path = tmp_path / "entry-filters.json"
    values = {
        **base(tmp_path),
        "enable_bb_width_filter": True,
        "bb_width_filter_mode": "Minimum Width",
        "bb_width_minimum": 0.012,
        "enable_skip_monday_entries": True,
        "skip_monday_timezone": "UTC",
    }
    save_config_json(path, values)
    loaded = load_config_json(path)
    cfg = build_backtest_config(loaded)
    assert cfg.enable_bb_width_filter is True
    assert cfg.bb_width_minimum == pytest.approx(0.012)
    assert cfg.enable_skip_monday_entries is True
    assert cfg.skip_monday_timezone == "UTC"

def test_gui_passes_selected_intrabar_csv_and_enabled_flag(tmp_path):
    strategy = tmp_path / "strategy.csv"
    intrabar = tmp_path / "intrabar.csv"
    content = "timestamp,open,high,low,close,volume\n2024-01-01,1,1,1,1,1\n"
    strategy.write_text(content)
    intrabar.write_text(content)
    cfg = build_backtest_config({**base(tmp_path), "input_csv": str(strategy), "intrabar_csv": str(intrabar), "use_intrabar_data": True})
    assert cfg.intrabar_csv == intrabar
    assert cfg.use_intrabar_data is True
    assert cfg.intrabar_timeframe_minutes == 1


def test_default_gui_config_returns_copy_and_does_not_mutate_source():
    from crypto_strategy_lab.gui.config_logic import DEFAULT_GUI_CONFIG, default_gui_config

    first = default_gui_config()
    second = default_gui_config()

    assert first == DEFAULT_GUI_CONFIG
    assert first is not DEFAULT_GUI_CONFIG
    assert first is not second

    first["atr_period"] = 99
    assert DEFAULT_GUI_CONFIG["atr_period"] == 14
    assert second["atr_period"] == 14


def test_standard_analysis_preset_is_default():
    from crypto_strategy_lab.gui.config_logic import default_gui_config

    values = default_gui_config()
    assert values["enable_trade_telemetry"] is False
    assert values["enable_indicator_lifecycle_analysis"] is False
    assert values["save_feature_analysis_reports"] is False
    assert values["analysis_level"] == "STANDARD"
    assert values["save_indicator_analysis_reports"] is True
    assert values["create_standard_charts"] is True


def test_new_gui_defaults_to_btc_structural_regime():
    from crypto_strategy_lab.gui.config_logic import default_gui_config

    values = default_gui_config()
    assert values["market_regime_method"] == "BTC_STRUCTURAL"
    assert values["structural_regime_sma_days"] == 200
    assert values["structural_regime_slope_lookback_days"] == 30


def test_old_saved_config_keeps_legacy_return_regime(tmp_path):
    from crypto_strategy_lab.gui.config_logic import load_config_json

    path = tmp_path / "old.json"
    path.write_text('{"bull_regime_lookback_days": 90}')
    assert load_config_json(path)["market_regime_method"] == "ASSET_RETURN"


def test_configurable_timeframes_are_passed_to_backtest_config(tmp_path):
    cfg = build_backtest_config({
        **base(tmp_path),
        "strategy_timeframe_minutes": 60,
        "intrabar_timeframe_minutes": 5,
        "telemetry_interval_minutes": 60,
    })

    assert cfg.strategy_timeframe_minutes == 60
    assert cfg.intrabar_timeframe_minutes == 5


def test_intrabar_timeframe_must_be_lower_only_when_enabled(tmp_path):
    values = {**base(tmp_path), "strategy_timeframe_minutes": 5, "intrabar_timeframe_minutes": 5}
    with pytest.raises(ValueError, match="Intrabar timeframe must be less"):
        build_backtest_config(values)

    cfg = build_backtest_config({**values, "use_intrabar_data": False})
    assert cfg.use_intrabar_data is False


def legacy_remaining_leg_timeout_json_round_trip_and_validation(tmp_path):
    path = tmp_path / "remaining-timeout.json"
    values = {**base(tmp_path), "enable_remaining_leg_timeout_after_first_sl": True,
              "remaining_leg_timeout_after_first_sl_minutes": 120,
              "remaining_leg_timeout_after_first_sl_unit": "Hours",
              "enable_remaining_leg_timeout_profit_extension": True,
              "remaining_leg_timeout_profit_threshold_r": 10,
              "enable_reentry_gate_after_remaining_leg_timeout": True}
    save_config_json(path, values)
    loaded = load_config_json(path)
    cfg = build_backtest_config(loaded)
    assert cfg.enable_remaining_leg_timeout_after_first_sl is True
    assert cfg.remaining_leg_timeout_after_first_sl_minutes == 120
    assert cfg.enable_remaining_leg_timeout_profit_extension is True
    assert cfg.remaining_leg_timeout_profit_threshold_r == 10
    assert cfg.enable_reentry_gate_after_remaining_leg_timeout is True
    assert loaded["remaining_leg_timeout_after_first_sl_unit"] == "Hours"

    score_values = {
        **values,
        "enable_remaining_leg_timeout_profit_extension": False,
        "enable_remaining_leg_checkpoint_score_extension": True,
        "checkpoint_score_min_conditions": 3,
    }
    score_cfg = build_backtest_config(score_values)
    assert score_cfg.enable_remaining_leg_checkpoint_score_extension
    assert score_cfg.checkpoint_score_max_atr_pct == pytest.approx(0.08)

    combined = build_backtest_config({
        **score_values,
        "enable_first_sl_survivor_partial_close": True,
        "first_sl_survivor_partial_close_pct": 25,
        "enable_checkpoint_zero_score_confirmation": True,
        "checkpoint_zero_score_confirmations_required": 2,
        "checkpoint_zero_score_recheck_minutes": 120,
    })
    assert combined.first_sl_survivor_partial_close_pct == 25
    assert combined.checkpoint_zero_score_recheck_minutes == 120

    with pytest.raises(ValueError, match="Remaining-Leg Timeout After First SL"):
        build_backtest_config({**values, "remaining_leg_timeout_after_first_sl_minutes": -1})
    with pytest.raises(ValueError, match="requires Remaining-Leg Timeout"):
        build_backtest_config({**values, "enable_remaining_leg_timeout_after_first_sl": False})
    with pytest.raises(ValueError, match="Threshold"):
        build_backtest_config({**values, "remaining_leg_timeout_profit_threshold_r": -1})


def test_zero_bull_regime_threshold_is_valid(tmp_path):
    values = {
        **base(tmp_path),
        "enable_di_direction_sizing": True,
        "enable_bull_regime_short_filter": True,
        "bull_regime_return_threshold": 0.0,
    }
    assert not validate_config_values(values)
    cfg = build_backtest_config(values)
    assert cfg.bull_regime_return_threshold == 0.0


def test_negative_bull_regime_threshold_is_valid(tmp_path):
    values = {
        **base(tmp_path),
        "enable_di_direction_sizing": True,
        "enable_bull_regime_short_filter": True,
        "bull_regime_return_threshold": -0.10,
    }
    assert not validate_config_values(values)
    cfg = build_backtest_config(values)
    assert cfg.bull_regime_return_threshold == pytest.approx(-0.10)

    with pytest.raises(ValueError, match="-100%"):
        build_backtest_config({**values, "bull_regime_return_threshold": -1.0})


def test_biased_short_adx_cap_config(tmp_path):
    values = {
        **base(tmp_path),
        "enable_di_direction_sizing": True,
        "enable_biased_short_adx_cap": True,
        "biased_short_adx_maximum": 50.0,
    }
    cfg = build_backtest_config(values)
    assert cfg.enable_biased_short_adx_cap
    assert cfg.biased_short_adx_maximum == 50.0


def test_short_vwap_distance_filter_config(tmp_path):
    cfg = build_backtest_config({
        **base(tmp_path),
        "enable_di_direction_sizing": True,
        "enable_short_vwap_distance_filter": True,
        "short_vwap_minimum_distance_atr": 2.25,
    })
    assert cfg.enable_short_vwap_distance_filter
    assert cfg.short_vwap_minimum_distance_atr == pytest.approx(2.25)


def test_long_momentum_filter_config_supports_long_only_di_selection(tmp_path):
    cfg = build_backtest_config({
        **base(tmp_path),
        "trade_direction": "LONG_ONLY",
        "enable_di_direction_sizing": True,
        "enable_long_momentum_filter": True,
        "long_momentum_lookback_hours": 24,
        "long_momentum_minimum_return": 0.06,
    })
    assert cfg.trade_direction == TradeDirectionMode.LONG_ONLY
    assert cfg.enable_long_momentum_filter
    assert cfg.long_momentum_lookback_hours == 24
    assert cfg.long_momentum_minimum_return == pytest.approx(0.06)


def test_bear_regime_adx_filter_config(tmp_path):
    cfg = build_backtest_config({
        **base(tmp_path),
        "enable_di_direction_sizing": True,
        "enable_bear_regime_adx_filter": True,
        "bear_regime_adx_minimum": 25.0,
    })
    assert cfg.enable_bear_regime_adx_filter
    assert cfg.bear_regime_adx_minimum == 25.0


def test_separate_di_direction_minimums_and_legacy_fallback(tmp_path):
    cfg = build_backtest_config({
        **base(tmp_path),
        "enable_di_direction_sizing": True,
        "di_direction_long_minimum_spread": 30,
        "di_direction_short_minimum_spread": 38,
    })
    assert cfg.di_direction_long_minimum_spread == 30
    assert cfg.di_direction_short_minimum_spread == 38

    legacy = build_backtest_config({
        **base(tmp_path),
        "enable_di_direction_sizing": True,
        "di_direction_minimum_spread": 35,
    })
    assert legacy.di_direction_long_minimum_spread == 35
    assert legacy.di_direction_short_minimum_spread == 35


def test_direction_specific_adx_config(tmp_path):
    cfg = build_backtest_config({
        **base(tmp_path),
        "enable_di_direction_sizing": True,
        "enable_directional_adx_filter": True,
        "directional_long_adx_maximum": 60,
        "directional_short_adx_minimum": 25,
    })
    assert cfg.enable_directional_adx_filter
    assert cfg.directional_long_adx_maximum == 60
    assert cfg.directional_short_adx_minimum == 25

    with pytest.raises(ValueError, match="requires DI-direction sizing"):
        build_backtest_config({
            **base(tmp_path),
            "enable_directional_adx_filter": True,
        })


def test_di_reward_risk_ratio_config(tmp_path):
    cfg = build_backtest_config({
        **base(tmp_path),
        "enable_di_direction_sizing": True,
        "di_reward_risk_ratio": 2,
    })
    assert cfg.di_reward_risk_ratio == 2

    with pytest.raises(ValueError, match="reward/risk ratio"):
        build_backtest_config({
            **base(tmp_path),
            "di_reward_risk_ratio": 0,
        })


def test_asymmetric_di_reward_risk_ratio_config_and_legacy_fallback(tmp_path):
    cfg = build_backtest_config({
        **base(tmp_path),
        "enable_di_direction_sizing": True,
        "di_long_reward_risk_ratio": 2,
        "di_short_reward_risk_ratio": 1,
    })
    assert cfg.di_long_reward_risk_ratio == 2
    assert cfg.di_short_reward_risk_ratio == 1

    legacy = build_backtest_config({
        **base(tmp_path),
        "enable_di_direction_sizing": True,
        "di_reward_risk_ratio": 1.5,
    })
    assert legacy.di_long_reward_risk_ratio == 1.5
    assert legacy.di_short_reward_risk_ratio == 1.5


def test_regime_specific_di_reward_risk_config(tmp_path):
    cfg = build_backtest_config({
        **base(tmp_path),
        "enable_di_direction_sizing": True,
        "enable_di_regime_reward_risk": True,
        "bull_regime_return_threshold": 0.20,
        "di_regime_bear_return_threshold": -0.20,
        "di_long_bull_reward_risk_ratio": 2,
        "di_long_bear_reward_risk_ratio": 1,
        "di_long_sideways_reward_risk_ratio": 2,
        "di_short_bull_reward_risk_ratio": 1,
        "di_short_bear_reward_risk_ratio": 1,
        "di_short_sideways_reward_risk_ratio": 2,
    })
    assert cfg.enable_di_regime_reward_risk
    assert cfg.di_long_bear_reward_risk_ratio == 1
    assert cfg.di_short_sideways_reward_risk_ratio == 2

    with pytest.raises(ValueError, match="bear threshold"):
        build_backtest_config({
            **base(tmp_path),
            "enable_di_direction_sizing": True,
            "enable_di_regime_reward_risk": True,
            "bull_regime_return_threshold": 0.20,
            "di_regime_bear_return_threshold": 0.20,
        })


def test_conditional_bull_long_reward_risk_config(tmp_path):
    cfg = build_backtest_config({
        **base(tmp_path),
        "enable_di_direction_sizing": True,
        "enable_di_regime_reward_risk": True,
        "enable_bull_long_conditional_reward_risk": True,
        "bull_long_conditional_bb_width_minimum": 0.05,
        "bull_long_conditional_adx_maximum": 40,
        "bull_long_conditional_reward_risk_ratio": 1,
    })
    assert cfg.enable_bull_long_conditional_reward_risk
    assert cfg.bull_long_conditional_bb_width_minimum == pytest.approx(0.05)
    assert cfg.bull_long_conditional_adx_maximum == 40
    assert cfg.bull_long_conditional_reward_risk_ratio == 1

    with pytest.raises(ValueError, match="requires regime-specific"):
        build_backtest_config({
            **base(tmp_path),
            "enable_di_direction_sizing": True,
            "enable_bull_long_conditional_reward_risk": True,
        })
