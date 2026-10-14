"""A price-touch candidate must not become a fill at an invented bar timestamp."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.engine import BacktestEngine


def test_limit_candidate_without_intrabar_timestamp_is_rejected_before_profile_lookup():
    engine = SimpleNamespace(
        config=SimpleNamespace(enable_daily_entry_schedule=False),
        open=np.array([100.]),
        close=np.array([101.]),
        times=np.array(pd.date_range("2026-01-01", periods=1, freq="h")),
    )
    schedule = {
        "indicator_index": 0,
        "fill_price_source": "LIMIT_LEVEL_CANDIDATE",
        "fill_price": 100.,
        "actual_entry_timestamp": None,
    }
    with pytest.raises(ValueError, match="verified intrabar fill timestamp"):
        BacktestEngine._open_pair(engine, 0, schedule=schedule)
