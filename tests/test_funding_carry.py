from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from crypto_strategy_lab.funding_carry import FundingCarryConfig, backtest_funding_carry


class DummyStore:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame

    def load_dataset(self, request, dataset):
        return self.frame.copy()


def _funding_frame(rates):
    base = pd.Timestamp("2024-01-01T00:00:00Z")
    return pd.DataFrame({
        "event_time": [base + pd.Timedelta(hours=8*i) for i in range(len(rates))],
        "period_start": [base + pd.Timedelta(hours=8*i) for i in range(len(rates))],
        "funding_rate": rates,
    })


def test_funding_carry_collects_positive_funding_and_fees(tmp_path: Path):
    store = DummyStore(_funding_frame([0.001, 0.001, 0.001]))
    summary, ledger, output = backtest_funding_carry(
        store,
        symbol="BTCUSDT",
        start="2024-01-01",
        end="2024-01-02",
        config=FundingCarryConfig(
            initial_capital_usdt=1000,
            minimum_funding_rate=0.0,
            entry_fee_percent_per_leg=0.1,
            exit_fee_percent_per_leg=0.1,
        ),
        output_root=tmp_path,
    )
    # 500 USDT per leg. Entry fee = 1, funding = 1.5, exit fee = 1.
    assert summary["ending_equity_usdt"] == pytest.approx(999.5)
    assert summary["funding_received_net_usdt"] == pytest.approx(1.5)
    assert summary["trading_fees_usdt"] == pytest.approx(2.0)
    assert summary["entries"] == 1
    assert summary["exits"] == 1
    assert len(ledger) == 3
    assert (output / "summary.json").exists()
    assert (output / "ledger.csv").exists()


def test_funding_carry_can_close_and_reenter_after_negative_funding(tmp_path: Path):
    store = DummyStore(_funding_frame([0.001, -0.001, 0.001]))
    summary, ledger, _ = backtest_funding_carry(
        store,
        symbol="BTCUSDT",
        start="2024-01-01",
        end="2024-01-02",
        config=FundingCarryConfig(
            initial_capital_usdt=1000,
            minimum_funding_rate=0.0,
            entry_fee_percent_per_leg=0.0,
            exit_fee_percent_per_leg=0.0,
            close_on_negative_funding=True,
        ),
        output_root=tmp_path,
    )
    assert summary["entries"] == 2
    assert summary["exits"] == 2
    assert summary["positive_funding_events"] == 2
    assert summary["negative_funding_events"] == 1
    assert summary["funding_received_net_usdt"] == pytest.approx(0.5)
    assert not bool(ledger.iloc[-1]["position_open"])
