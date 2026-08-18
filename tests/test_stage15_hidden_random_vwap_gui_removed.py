from pathlib import Path

from PySide6.QtWidgets import QApplication, QGroupBox

from crypto_strategy_lab.gui.config_logic import default_gui_config
from crypto_strategy_lab.gui.main_window import MainWindow


def app():
    return QApplication.instance() or QApplication([])


def test_hidden_random_vwap_widgets_are_not_constructed():
    app()
    window = MainWindow()
    try:
        removed = (
            "vwap_breakout_hours", "vwap_volume_lookback", "vwap_volume_multiplier", "vwap_slope_lookback",
            "vwap_atr_min", "vwap_atr_max", "vwap_confirmation_mode", "vwap_retest_window", "vwap_retest_tolerance",
            "enable_random_entry", "entry_timing_mode", "random_probability", "random_seed", "random_start_mode",
            "randomize_first", "max_random_wait", "enable_random_batch", "random_seed_start", "random_seed_count",
            "enable_coin_flip_sizing", "coin_flip_seed",
        )
        for name in removed:
            assert not hasattr(window, name)
        titles = {box.title() for box in window.findChildren(QGroupBox)}
        assert "VWAP Volume Breakout" not in titles
        assert "Random Entry Timing" not in titles
    finally:
        window.close()


def test_retired_random_and_breakout_globals_stay_inert_while_profile_vwap_rule_survives():
    app()
    window = MainWindow()
    try:
        values = default_gui_config()
        values.update({
            "enable_random_entry": True,
            "entry_timing_mode": "RANDOM_AFTER_PAIR_CLOSE",
            "random_entry_probability": 0.9,
            "enable_random_entry_batch": True,
            "enable_coin_flip_sizing": True,
            "vwap_breakout_lookback_hours": 24.0,
            "vwap_confirmation_mode": "RETEST",
        })
        profile = values["strategy_profiles"]["bull_short"]
        profile.update({
            "vwap_distance_enabled": True,
            "vwap_distance_minimum": -0.5,
            "vwap_distance_maximum": 1.5,
        })
        window.apply_values(values)
        current = window.values()

        assert current["enable_random_entry"] is False
        assert current["entry_timing_mode"] == "CURRENT"
        assert current["random_entry_probability"] == 0.5
        assert current["enable_random_entry_batch"] is False
        assert current["enable_coin_flip_sizing"] is False
        assert current["vwap_breakout_lookback_hours"] == 4.0
        assert current["vwap_confirmation_mode"] == "IMMEDIATE"
        bull_short = current["strategy_profiles"]["bull_short"]
        assert bull_short["vwap_distance_enabled"] is True
        assert bull_short["vwap_distance_minimum"] == -0.5
        assert bull_short["vwap_distance_maximum"] == 1.5
    finally:
        window.close()


def test_main_window_source_has_no_hidden_random_vwap_plumbing():
    source = (Path(__file__).resolve().parents[1] / "crypto_strategy_lab" / "gui" / "main_window.py").read_text(encoding="utf-8")
    for fragment in (
        'group("VWAP Volume Breakout")',
        'group("Random Entry Timing")',
        "self.vwap_confirmation_mode",
        "self.enable_random_entry",
        "self.enable_coin_flip_sizing",
    ):
        assert fragment not in source
