"""Strategy Designer stage organization regression tests."""

from test_risk_execution_workspace import _window


def test_fibonacci_stages_reuse_authoritative_widgets():
    app, window = _window()
    try:
        workspace = window.risk_execution_workspace
        assert len(workspace.fib_stage_cards) == 4
        assert [card.title() for card in workspace.fib_stage_cards] == [
            "Signal • Fibonacci Structure",
            "Entry • Fibonacci Holds",
            "Context • Fibonacci EMA",
            "Confirmation • Fibonacci Candles",
        ]
        expected = {
            "fib_structure_quality_mode", "fib_half_swing_mode",
            "fib_inherited_first_held", "fib_first_0786_held",
            "fib_third_retest_entry", "fib_first_zone_hold_entry",
            "fib_ema_trend_gate", "fib_candidate_context_selection",
            "fib_candle_confirmation_enabled", "fib_candle_strong_close",
            "fib_candle_engulfing", "fib_candle_wick_rejection",
            "fib_candle_star",
        }
        actual = {
            key
            for card in workspace.fib_stage_cards
            for key in card.rows
        }
        assert actual == expected
        for card in workspace.fib_stage_cards:
            assert not card.toggle.isChecked()
            for key, (_, widget) in card.rows.items():
                assert widget is window.feature_form.widgets[key]
        assert "ema_320_candle_confirmation_enabled" in workspace.ema320_candle_card.rows
    finally:
        window.close()
        app.processEvents()
