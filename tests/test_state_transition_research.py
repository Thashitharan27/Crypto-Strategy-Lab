from pathlib import Path

import numpy as np
import pandas as pd

from crypto_strategy_lab.state_transition_research import (
    StateTransitionResearchConfig,
    daily_state_frame,
    generate_state_transition_reports,
    trade_state_analysis,
    transition_matrix,
)


def _strategy_days(count: int = 420) -> pd.DataFrame:
    timestamps = pd.date_range("2024-01-01", periods=count, freq="1D", tz="UTC")
    # Deterministic trend + cyclical component gives all three return regimes.
    x = np.arange(count, dtype=float)
    close = 100.0 * np.exp(0.0008 * x + 0.08 * np.sin(x / 18.0))
    return pd.DataFrame({"timestamp": timestamps, "close": close})


def test_transition_matrix_probabilities_sum_to_one() -> None:
    report = transition_matrix(["BULL", "BULL", "SIDEWAYS", "BEAR", "BEAR", "BULL"])
    totals = report.groupby("current_state")["probability"].sum()
    assert np.allclose(totals.to_numpy(), 1.0)


def test_daily_states_use_expected_regime_thresholds() -> None:
    cfg = StateTransitionResearchConfig(regime_lookback_days=2, bull_return_threshold=0.05, bear_return_threshold=-0.05)
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=7, freq="1D", tz="UTC"),
            "close": [100, 100, 106, 100, 94, 100, 106],
        }
    )
    states = daily_state_frame(frame, cfg)
    assert "BULL" in set(states["regime_state"])
    assert "BEAR" in set(states["regime_state"])
    assert "SIDEWAYS" in set(states["regime_state"])


def test_trade_state_analysis_buckets_di_and_outcome() -> None:
    daily = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=4, freq="1D", tz="UTC"),
            "volatility_state": ["NORMAL", "ELEVATED", "LOW", "NORMAL"],
        }
    )
    trades = pd.DataFrame(
        {
            "strategy_entry_time": pd.date_range("2026-01-01", periods=4, freq="1D", tz="UTC"),
            "directional_di": [7.0, 17.0, 32.0, 32.0],
            "directional_di_change": [1.0, -2.0, 0.1, 2.0],
            "pair_net_r": [1.0, -1.0, 2.0, -0.5],
        }
    )
    result = trade_state_analysis(trades, daily, StateTransitionResearchConfig(minimum_trade_observations=1))
    assert result["trades"].sum() == 4
    assert set(result["di_state"]) == {"RISING", "FALLING", "STABLE"}
    assert set(result["volatility_state"]) == {"NORMAL", "ELEVATED", "LOW"}


def test_generate_reports_writes_research_folder(tmp_path: Path) -> None:
    strategy = _strategy_days()
    trades = pd.DataFrame(
        {
            "strategy_entry_time": strategy["timestamp"].iloc[300:310].to_numpy(),
            "directional_di": [12, 18, 22, 27, 31, 35, 9, 14, 24, 33],
            "directional_di_change": [1, -1, 0, 2, -2, 1, 0, 1, -1, 2],
            "pair_net_r": [1, -1, 1, 1, -1, 2, -1, 1, -1, 1],
        }
    )
    reports = generate_state_transition_reports(strategy, trades, tmp_path, StateTransitionResearchConfig(minimum_trade_observations=1))
    folder = tmp_path / "state_transition_research"
    assert (folder / "daily_states.csv").exists()
    assert (folder / "regime_transition_matrix.csv").exists()
    assert (folder / "volatility_transition_matrix.csv").exists()
    assert (folder / "di_state_volatility_trade_performance.csv").exists()
    assert (folder / "current_regime_probabilities.csv").exists()
    assert not reports["daily_states"].empty
