from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pandas.testing as pdt

from crypto_strategy_lab.data import DataRequest
from crypto_strategy_lab.data.schemas import DatasetKind
from crypto_strategy_lab.features.cache import FeatureFrameCache
from crypto_strategy_lab.features.technical import CoreDirectionalFeatureProvider


UTC = timezone.utc


def source_frame() -> pd.DataFrame:
    times = pd.date_range("2026-01-01", periods=40, freq="1h", tz="UTC")
    close = 100 + np.linspace(0, 10, len(times)) + np.sin(np.arange(len(times)))
    return pd.DataFrame(
        {
            "period_start": times,
            "available_at": times + pd.Timedelta(hours=1),
            "high": close + 2,
            "low": close - 2,
            "close": close,
            "source_fingerprint": "archive-fingerprint-a",
        }
    )


def request() -> DataRequest:
    return DataRequest(
        symbol="BTCUSDT",
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 3, tzinfo=UTC),
        strategy_interval="1h",
    )


def test_feature_cache_roundtrip_and_invalidation(tmp_path: Path) -> None:
    provider = CoreDirectionalFeatureProvider()
    source = source_frame()
    params = {"atr_period": 7, "adx_period": 6, "di_pressure_lookback": 3}
    req = request()
    frame = provider.compute(req, {DatasetKind.KLINES: source}, params)
    cache = FeatureFrameCache(tmp_path)
    key = cache.key(provider.definition, req, params, source)

    assert cache.load(provider.definition, req, key) is None
    cache.store(provider.definition, req, key, frame)
    loaded = cache.load(provider.definition, req, key)
    assert loaded is not None
    assert loaded.attrs["feature_cache_hit"] is True
    assert loaded.attrs["feature_cache_key"] == key
    pdt.assert_frame_equal(loaded, frame, check_dtype=False)

    changed_params = {**params, "adx_period": 7}
    assert cache.key(provider.definition, req, changed_params, source) != key

    changed_source = source.copy()
    changed_source["source_fingerprint"] = "archive-fingerprint-b"
    assert cache.key(provider.definition, req, params, changed_source) != key
