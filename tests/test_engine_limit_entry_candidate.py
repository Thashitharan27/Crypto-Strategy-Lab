"""Engine integration tests for causal limit-order candidates."""
from types import SimpleNamespace

import numpy as np

from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.entry_plan import EntryIntent, EntryPlan, EntryTiming, schedule_entry


def test_engine_limit_candidate_uses_engine_bars_and_expiry():
    engine = SimpleNamespace(
        times=np.arange(4),
        open=np.array([100., 102., 98., 102.]),
        low=np.array([99., 97., 97., 101.]),
        high=np.array([103., 104., 103., 104.]),
    )
    order = schedule_entry(
        EntryIntent("LONG", 0, limit_price=100),
        EntryPlan(EntryTiming.LIMIT_LEVEL, limit_timeout_bars=2),
    )
    assert BacktestEngine._limit_entry_candidate(engine, order, 0) is None
    candidate = BacktestEngine._limit_entry_candidate(engine, order, 1)
    assert candidate is not None
    assert candidate.execution_index == 1
    assert candidate.price == 100
    assert BacktestEngine._limit_entry_candidate(engine, order, 2).price == 98
    assert BacktestEngine._limit_entry_candidate(engine, order, 3) is None
    assert BacktestEngine._limit_entry_candidate(engine, order, 4) is None
