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


def test_79_trade_frozen_shape_requires_every_field_and_order():
    """79-row parity rehearsal; synthetic rows are NOT the archived BTC run."""
    baseline = [trade(trade_id=f"T{i:03d}", pnl=float(i), slippage=0.02)
                for i in range(79)]
    replay = [dict(row) for row in baseline]
    assert compare_trades(baseline, replay, abs_tol=0, rel_tol=0) == []
    replay[47]["slippage"] = 0.03
    differences = compare_trades(baseline, replay, abs_tol=0, rel_tol=0)
    assert [(d.trade_index, d.field) for d in differences] == [(47, "slippage")]
    replay[47] = dict(baseline[47])
    del replay[62]["target_price"]
    assert [(d.trade_index, d.field) for d in compare_trades(baseline, replay)] == [
        (62, "target_price")
    ]


def test_79_trade_rehearsal_rejects_missing_last_trade():
    baseline = [trade(trade_id=f"T{i:03d}") for i in range(79)]
    differences = compare_trades(baseline, baseline[:-1])
    assert differences[0].field == "trade_count"
    assert (differences[0].expected, differences[0].actual) == (79, 78)


def test_matching_duplicate_trade_ids_are_not_a_parity_pass():
    rows = [trade(trade_id="DUP", pnl=1.0), trade(trade_id="DUP", pnl=2.0)]
    differences = compare_trades(rows, [dict(row) for row in rows])
    assert {(d.trade_index, d.field) for d in differences} == {
        (1, "expected_trade_id_duplicate"), (1, "actual_trade_id_duplicate")
    }


def test_invalid_trade_identity_is_rejected_even_on_both_sides():
    rows = [trade(trade_id="")]
    differences = compare_trades(rows, [dict(row) for row in rows])
    assert {d.field for d in differences} == {
        "expected_trade_id_valid", "actual_trade_id_valid"
    }


@pytest.mark.parametrize("field", ["side", "signal_time", "entry_time", "exit_time", "exit_reason"])
def test_equal_blank_required_trade_text_cannot_pass(field):
    record = trade(**{field: "  "})
    differences = compare_trades([record], [dict(record)])
    assert {d.field for d in differences} == {
        f"expected_{field}_valid", f"actual_{field}_valid"
    }
