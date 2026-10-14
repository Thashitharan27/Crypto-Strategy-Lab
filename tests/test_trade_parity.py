"""Synthetic tests of the independent trade-parity comparator (not backtests)."""
from dataclasses import replace

import pytest

from crypto_strategy_lab.trade_parity import TRADE_FIELDS, compare_trades


def trade(**changes):
    row = {
        "trade_id": "T1", "side": "LONG",
        "signal_time": "2026-01-01T00:00:00Z",
        "entry_time": "2026-01-01T00:01:00Z",
        "exit_time": "2026-01-01T00:04:00Z",
        "entry_price": 100.0, "exit_price": 102.0,
        "quantity": 1.0, "stop_price": 99.0, "target_price": 102.0,
        "exit_reason": "TAKE_PROFIT", "fees": 0.1, "slippage": 0.02,
        "realized_r": 2.0, "pnl": 1.88,
    }
    row.update(changes)
    assert set(row) == set(TRADE_FIELDS)
    return row


def test_identical_trades_and_small_roundoff():
    assert compare_trades([trade()], [trade()]) == []
    assert compare_trades([trade()], [trade(pnl=1.88000000001)]) == []


@pytest.mark.parametrize("field,value", [
    ("side", "SHORT"), ("signal_time", "2026-01-01T00:01:00Z"),
    ("entry_time", "2026-01-01T00:02:00Z"),
    ("exit_time", "2026-01-01T00:05:00Z"),
    ("entry_price", 101.0), ("stop_price", 98.0),
    ("quantity", 1.5), ("fees", 0.3), ("exit_reason", "STOP"),
])
def test_material_differences_are_detected(field, value):
    result = compare_trades([trade()], [trade(**{field: value})])
    assert [x.field for x in result] == [field]


def test_missing_field_is_not_silently_ignored():
    row = trade()
    del row["fees"]
    assert compare_trades([trade()], [row])[0].field == "fees"


def test_count_and_order_mismatches():
    assert compare_trades([trade()], [])[0].field == "trade_count"
    assert compare_trades([trade(trade_id="A"), trade(trade_id="B")],
                          [trade(trade_id="B"), trade(trade_id="A")])[0].field == "trade_id"


def test_reject_nonfinite_and_invalid_tolerance():
    assert compare_trades([trade()], [trade(fees=float("nan"))])[0].field == "fees"
    with pytest.raises(ValueError):
        compare_trades([], [], abs_tol=-1)
    with pytest.raises(ValueError):
        compare_trades([], [], rel_tol=float("inf"))


def test_strict_numeric_mode():
    assert compare_trades([trade()], [trade(pnl=1.88000000001)],
                          abs_tol=0, rel_tol=0)[0].field == "pnl"
