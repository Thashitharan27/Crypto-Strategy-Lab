from __future__ import annotations

import pandas as pd

from crypto_strategy_lab.trade import Position, Side, TradePair


def _position(side: Side) -> Position:
    return Position(
        side=side,
        entry_time=pd.Timestamp("2026-01-01T00:00:00Z"),
        entry_index=0,
        entry_price=100.0,
        risk=1.0,
        sl=99.0 if side == Side.LONG else 101.0,
        tp=102.0 if side == Side.LONG else 98.0,
        quantity=1.0,
        risk_amount=1.0,
        entry_notional=100.0,
        atr_at_entry=1.0,
    )


def _pair(long=None, short=None) -> TradePair:
    return TradePair(
        pair_id=1,
        long=long,
        short=short,
        equity_before_trade=1000.0,
        strategy_candle_open_time=pd.Timestamp("2026-01-01T00:00:00Z"),
        strategy_entry_time=pd.Timestamp("2026-01-01T00:15:00Z"),
        strategy_entry_price=100.0,
    )


def test_positions_preserves_existing_leg_order_without_generator_filtering() -> None:
    long = _position(Side.LONG)
    short = _position(Side.SHORT)

    assert _pair().positions() == ()
    assert _pair(long=long).positions() == (long,)
    assert _pair(short=short).positions() == (short,)
    assert _pair(long=long, short=short).positions() == (long, short)


def test_is_open_reads_fixed_legs_directly() -> None:
    long = _position(Side.LONG)
    short = _position(Side.SHORT)
    pair = _pair(long=long, short=short)

    assert pair.is_open

    long.exit_time = pd.Timestamp("2026-01-01T00:20:00Z")
    assert pair.is_open

    short.exit_time = pd.Timestamp("2026-01-01T00:21:00Z")
    assert not pair.is_open


def test_single_leg_is_open_semantics_are_unchanged() -> None:
    long = _position(Side.LONG)
    pair = _pair(long=long)
    assert pair.is_open

    long.exit_time = pd.Timestamp("2026-01-01T00:20:00Z")
    assert not pair.is_open

    short = _position(Side.SHORT)
    pair = _pair(short=short)
    assert pair.is_open

    short.exit_time = pd.Timestamp("2026-01-01T00:20:00Z")
    assert not pair.is_open


def test_positions_and_is_open_follow_runtime_leg_reassignment() -> None:
    long = _position(Side.LONG)
    short = _position(Side.SHORT)
    pair = _pair(long=long)

    assert pair.positions() == (long,)
    assert pair.is_open

    pair.long = None
    pair.short = short
    assert pair.positions() == (short,)
    assert pair.is_open

    short.exit_time = pd.Timestamp("2026-01-01T00:30:00Z")
    assert not pair.is_open

    replacement = _position(Side.LONG)
    pair.long = replacement
    assert pair.positions() == (replacement, short)
    assert pair.is_open
