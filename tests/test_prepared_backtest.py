from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.prepared_backtest import (
    IntrabarExecutionData, PreparedBacktestFrame, ResearchContext,
    from_data_lake_bundle,
)


def valid_kwargs(n=3):
    timestamp = pd.date_range("2025-01-01", periods=n, freq="4h", tz="UTC").to_numpy(dtype="datetime64[ns]")
    floats = {
        name: np.arange(n, dtype=float) + 1
        for name in (
            "open", "high", "low", "close", "volume", "atr", "atr_pct", "adx",
            "plus_di", "minus_di", "bb_width", "bb_width_pct", "session_vwap",
            "close_location", "mean_reversion_mean", "mean_reversion_distance_atr",
            "mean_reversion_distance_atr_previous", "mean_reversion_sigma",
            "mean_reversion_bb_upper", "mean_reversion_bb_lower",
            "mean_reversion_bb_zscore", "mean_reversion_rsi",
        )
    }
    return dict(
        timestamp=timestamp, strategy_interval=pd.Timedelta(hours=4), **floats,
        mean_reversion_long_reentry=np.zeros(n, dtype=bool),
        mean_reversion_short_reentry=np.ones(n, dtype=bool),
        decision_available_at=timestamp + np.timedelta64(4, "h"),
    )


def test_required_fields_are_explicit():
    kwargs = valid_kwargs()
    del kwargs["atr"]
    with pytest.raises(TypeError, match="atr"):
        PreparedBacktestFrame(**kwargs)


def test_array_lengths_must_match():
    kwargs = valid_kwargs()
    kwargs["adx"] = np.ones(2)
    with pytest.raises(ValueError, match="adx length"):
        PreparedBacktestFrame(**kwargs)


@pytest.mark.parametrize("timestamps", [
    np.array(["2025-01-01T04:00", "2025-01-01T00:00"], dtype="datetime64[m]"),
    np.array(["2025-01-01T00:00", "2025-01-01T00:00"], dtype="datetime64[m]"),
])
def test_timestamps_are_strictly_ordered_and_unique(timestamps):
    kwargs = valid_kwargs(2)
    kwargs["timestamp"] = timestamps
    with pytest.raises(ValueError, match="strictly increasing and unique"):
        PreparedBacktestFrame(**kwargs)


def test_dtype_and_missing_execution_values_fail_loudly():
    kwargs = valid_kwargs()
    kwargs["atr"] = np.array(["not", "numeric", "values"])
    with pytest.raises(TypeError, match="atr must have a numeric dtype"):
        PreparedBacktestFrame(**kwargs)
    kwargs = valid_kwargs()
    kwargs["close"][1] = np.nan
    with pytest.raises(ValueError, match="close contains missing"):
        PreparedBacktestFrame(**kwargs)


def test_optional_research_is_read_only_and_aligned():
    kwargs = valid_kwargs()
    block = ResearchContext("flow", kwargs["decision_available_at"], {"imbalance": np.ones(3)})
    frame = PreparedBacktestFrame(**kwargs, research=(block,))
    assert frame.research[0].values["imbalance"].flags.writeable is False
    bad = ResearchContext("flow", kwargs["decision_available_at"][:2], {"imbalance": np.ones(2)})
    with pytest.raises(ValueError, match="not aligned"):
        PreparedBacktestFrame(**kwargs, research=(bad,))


def test_causal_feature_rules():
    kwargs = valid_kwargs()
    kwargs["decision_available_at"][0] = kwargs["timestamp"][0] - np.timedelta64(1, "m")
    with pytest.raises(ValueError, match="before their strategy candle opens"):
        PreparedBacktestFrame(**kwargs)
    kwargs = valid_kwargs()
    kwargs["decision_available_at"][0] += np.timedelta64(1, "m")
    with pytest.raises(ValueError, match="unavailable at strategy candle completion"):
        PreparedBacktestFrame(**kwargs)


def test_intrabar_strategy_alignment_and_interval():
    frame = PreparedBacktestFrame(**valid_kwargs())
    times = pd.date_range("2025-01-01", periods=720, freq="1min", tz="UTC").to_numpy(dtype="datetime64[ns]")
    intrabar = IntrabarExecutionData(times, pd.Timedelta(minutes=1), np.ones(720), np.ones(720), np.ones(720))
    intrabar.validate_compatible(frame)
    shifted = IntrabarExecutionData(times + np.timedelta64(30, "s"), pd.Timedelta(minutes=1), np.ones(720), np.ones(720), np.ones(720))
    with pytest.raises(ValueError, match="not aligned"):
        shifted.validate_compatible(frame)
    same_interval = IntrabarExecutionData(frame.timestamp, pd.Timedelta(hours=4), np.ones(3), np.ones(3), np.ones(3))
    with pytest.raises(ValueError, match="must be smaller"):
        same_interval.validate_compatible(frame)


def test_constructs_from_current_data_lake_bundle_path():
    times = pd.date_range("2025-01-01", periods=3, freq="4h", tz="UTC")
    strategy = pd.DataFrame({"timestamp": times, "open": 1.0, "high": 2.0, "low": .5, "close": 1.5, "volume": 10.0})
    technical = pd.DataFrame({
        "timestamp": times, "available_at": times + pd.Timedelta(hours=4),
        "atr": 1.0, "atr_pct": .1, "adx": 20.0, "plus_di": 15.0, "minus_di": 10.0,
    })
    context_names = (
        "bb_width", "bb_width_pct", "session_vwap", "close_location",
        "mean_reversion_mean", "mean_reversion_distance_atr",
        "mean_reversion_distance_atr_previous", "mean_reversion_sigma",
        "mean_reversion_bb_upper", "mean_reversion_bb_lower", "mean_reversion_bb_zscore",
        "mean_reversion_rsi",
    )
    context = pd.DataFrame({"timestamp": times, "available_at": times + pd.Timedelta(hours=4), **{name: 1.0 for name in context_names}, "mean_reversion_long_reentry": False, "mean_reversion_short_reentry": True})
    intrabar_times = pd.date_range(times[0], periods=720, freq="1min", tz="UTC")
    intrabar = pd.DataFrame({"timestamp": intrabar_times, "open": 1.0, "high": 2.0, "low": .5})
    research = pd.DataFrame({"timestamp": times, "available_at": times + pd.Timedelta(hours=4), "funding": .01})
    bundle = SimpleNamespace(
        strategy=strategy, technical_features=technical, context_features=context,
        research_features={"funding": research}, intrabar=intrabar,
        request=SimpleNamespace(strategy_interval="4h", intrabar_interval="1m"),
    )
    prepared, execution = from_data_lake_bundle(bundle)
    assert len(prepared) == 3
    assert prepared.research[0].name == "funding"
    assert execution is not None and len(execution.timestamp) == 720
