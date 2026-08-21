from __future__ import annotations

import pandas as pd
import pytest

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


def test_trade_pair_requires_exactly_one_position() -> None:
    long = _position(Side.LONG)
    short = _position(Side.SHORT)

    assert _pair(long=long).position is long
    assert _pair(short=short).position is short

    with pytest.raises(ValueError, match="exactly one position"):
        _pair()
    with pytest.raises(ValueError, match="simultaneous LONG\\+SHORT trades are retired"):
        _pair(long=long, short=short)


def test_positions_is_single_leg_compatibility_tuple() -> None:
    long = _position(Side.LONG)
    short = _position(Side.SHORT)

    assert _pair(long=long).positions() == (long,)
    assert _pair(short=short).positions() == (short,)


def test_is_open_tracks_the_single_position() -> None:
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
