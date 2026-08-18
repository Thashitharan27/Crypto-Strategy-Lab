"""Regression coverage for removing hidden pair-management GUI controls."""

from pathlib import Path

from PySide6.QtWidgets import QApplication, QGroupBox

from crypto_strategy_lab.gui.config_logic import default_gui_config
from crypto_strategy_lab.gui.main_window import MainWindow


def app():
    return QApplication.instance() or QApplication([])


def test_hidden_pair_management_widgets_are_not_constructed():
    app()
    window = MainWindow()
    try:
        removed = (
            "both_timeout", "both_timeout_duration", "both_timeout_unit",
            "be_after_sl", "be_mode", "be_offset", "be_same_candle",
            "remaining_leg_timeout", "remaining_leg_timeout_duration", "remaining_leg_timeout_unit",
            "remaining_leg_timeout_profit_extension", "reentry_gate_after_timeout",
            "checkpoint_score_extension", "first_sl_survivor_partial", "zero_score_confirmation",
            "be_label",
        )
        for name in removed:
            assert not hasattr(window, name)
        titles = {box.title() for box in window.findChildren(QGroupBox)}
        assert "Both-Open Timeout" not in titles
        assert "Break-Even After Opposite SL" not in titles
        assert "Remaining Leg Timeout After First SL" not in titles
        assert "Break-Even Calculator" not in titles
    finally:
        window.close()


def test_retired_pair_globals_stay_inert_while_profile_timeout_and_be_survive():
    app()
    window = MainWindow()
    try:
        values = default_gui_config()
        values.update({
            "enable_both_open_timeout": True,
            "max_both_open_minutes": 60,
            "enable_be_after_opposite_sl": True,
            "be_mode": "R_OFFSET",
            "be_offset_r": 0.5,
            "enable_remaining_leg_timeout_after_first_sl": True,
            "enable_remaining_leg_timeout_profit_extension": True,
            "enable_remaining_leg_checkpoint_score_extension": True,
            "enable_first_sl_survivor_partial_close": True,
            "enable_checkpoint_zero_score_confirmation": True,
            "enable_reentry_gate_after_remaining_leg_timeout": True,
        })
        profile = values["strategy_profiles"]["bull_long"]
        profile.update({
            "timeout_enabled": True,
            "timeout_minutes": 180,
            "break_even_enabled": True,
            "break_even_activation_r": 1.5,
            "break_even_offset_r": 0.2,
        })
        window.apply_values(values)
        current = window.values()

        assert current["enable_both_open_timeout"] is False
        assert current["max_both_open_minutes"] == 480
        assert current["enable_be_after_opposite_sl"] is False
        assert current["be_mode"] == "ENTRY_PRICE"
        assert current["enable_remaining_leg_timeout_after_first_sl"] is False
        assert current["enable_remaining_leg_timeout_profit_extension"] is False
        assert current["enable_remaining_leg_checkpoint_score_extension"] is False
        assert current["enable_first_sl_survivor_partial_close"] is False
        assert current["enable_checkpoint_zero_score_confirmation"] is False
        assert current["enable_reentry_gate_after_remaining_leg_timeout"] is False
        bull_long = current["strategy_profiles"]["bull_long"]
        assert bull_long["timeout_enabled"] is True
        assert bull_long["timeout_minutes"] == 180
        assert bull_long["break_even_enabled"] is True
        assert bull_long["break_even_activation_r"] == 1.5
        assert bull_long["break_even_offset_r"] == 0.2
    finally:
        window.close()


def test_main_window_source_has_no_hidden_pair_management_plumbing():
    source = (Path(__file__).resolve().parents[1] / "crypto_strategy_lab" / "gui" / "main_window.py").read_text(encoding="utf-8")
    for fragment in (
        'group("Both-Open Timeout")',
        'group("Break-Even After Opposite SL")',
        'group("Remaining Leg Timeout After First SL")',
        'group("Break-Even Calculator")',
        "self.both_timeout",
        "self.be_after_sl",
        "self.remaining_leg_timeout",
        "_update_checkpoint_score_controls",
    ):
        assert fragment not in source
