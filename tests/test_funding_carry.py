from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from crypto_strategy_lab.data.schemas import DatasetKind
from crypto_strategy_lab.funding_carry import FundingCarryConfig, backtest_funding_carry


class DummyStore:
    def __init__(self, funding: pd.DataFrame, prices: pd.DataFrame):
        self.funding = funding
        self.prices = prices

    def load_dataset(self, request, dataset):
        if dataset == DatasetKind.FUNDING_RATE:
            return self.funding.copy()
        if dataset == DatasetKind.KLINES:
            return self.prices.copy()
        raise AssertionError(dataset)


def _funding_frame(rates):
    base = pd.Timestamp("2024-01-01T00:00:00Z")
    return pd.DataFrame({
        "event_time": [base + pd.Timedelta(hours=8*i) for i in range(len(rates))],
        "period_start": [base + pd.Timedelta(hours=8*i) for i in range(len(rates))],
        "funding_rate": rates,
    })


def _price_frame(prices):
    base = pd.Timestamp("2024-01-01T00:00:00Z")
    return pd.DataFrame({
        "event_time": [base + pd.Timedelta(hours=8*i) for i in range(len(prices))],
        "open": prices,
    })


def test_funding_carry_does_not_credit_triggering_settlement(tmp_path: Path):
    store = DummyStore(_funding_frame([0.001, 0.001, 0.001]), _price_frame([100, 100, 100]))
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
    # First settlement only triggers entry. Two later settlements pay 0.5 each.
    # Entry fee = 1, funding = 1, exit fee = 1.
    assert ledger.iloc[0]["funding_pnl_usdt"] == pytest.approx(0.0)
    assert summary["ending_equity_usdt"] == pytest.approx(999.0)
    assert summary["funding_received_net_usdt"] == pytest.approx(1.0)
    assert summary["trading_fees_usdt"] == pytest.approx(2.0)
    assert summary["entries"] == 1
    assert summary["exits"] == 1
    assert (output / "summary.json").exists()
    assert (output / "ledger.csv").exists()


def test_funding_carry_revalues_fixed_quantity_at_settlement(tmp_path: Path):
    store = DummyStore(_funding_frame([0.001, 0.001]), _price_frame([100, 110]))
    summary, ledger, _ = backtest_funding_carry(
        store,
        symbol="BTCUSDT",
        start="2024-01-01",
        end="2024-01-02",
        config=FundingCarryConfig(initial_capital_usdt=1000, entry_fee_percent_per_leg=0, exit_fee_percent_per_leg=0),
        output_root=tmp_path,
    )
    # Entry quantity is 500 / 100 = 5 BTC-equivalent units; next notional is 5 * 110.
    assert ledger.iloc[1]["hedged_quantity_btc"] == pytest.approx(5.0)
    assert ledger.iloc[1]["funding_pnl_usdt"] == pytest.approx(0.55)
    assert summary["funding_received_net_usdt"] == pytest.approx(0.55)


def test_funding_carry_can_close_and_reenter_after_negative_funding(tmp_path: Path):
    store = DummyStore(_funding_frame([0.001, -0.001, 0.001]), _price_frame([100, 100, 100]))
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
    assert summary["funding_received_net_usdt"] == pytest.approx(-0.5)
    assert not bool(ledger.iloc[-1]["position_open"])


def test_funding_carry_drawdown_includes_initial_equity(tmp_path: Path):
    store = DummyStore(_funding_frame([0.001]), _price_frame([100]))
    summary, _, _ = backtest_funding_carry(
        store,
        symbol="BTCUSDT",
        start="2024-01-01",
        end="2024-01-02",
        config=FundingCarryConfig(
            initial_capital_usdt=1000,
            entry_fee_percent_per_leg=0.1,
            exit_fee_percent_per_leg=0.1,
        ),
        output_root=tmp_path,
    )
    assert summary["ending_equity_usdt"] == pytest.approx(998.0)
    assert summary["maximum_drawdown_percent"] == pytest.approx(-0.2)
