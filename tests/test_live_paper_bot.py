import json
from pathlib import Path

import pytest

from live_paper_bot import PaperBotConfig, PaperBroker, VolatilityScanner, completed_candles, strategy_signal


def kline(index, close, *, now=10_000_000):
    start = index * 300_000
    return [start, close, close * 1.01, close * 0.99, close, 100, start + 299_999, close * 100]


def candles(values):
    return completed_candles([kline(i, value) for i, value in enumerate(values)], now_ms=100_000_000)


def test_incomplete_candle_is_never_used():
    rows = [kline(0, 100), [99_000_000, 100, 101, 99, 100, 1, 101_000_000, 100]]
    assert len(completed_candles(rows, now_ms=100_000_000)) == 1


def test_strategy_signals_use_completed_history():
    rising = candles([100 + i * 0.1 for i in range(60)] + [120])
    assert strategy_signal("breakout", rising) == "LONG"
    assert strategy_signal("trend", rising) == "LONG"
    falling = candles([100 - i * 0.05 for i in range(60)] + [85])
    assert strategy_signal("mean_reversion", falling) == "LONG"


class FakeClient:
    def exchange_info(self):
        return {"symbols": [{"symbol": "AAAUSDT", "status": "TRADING", "contractType": "PERPETUAL", "quoteAsset": "USDT", "baseAsset": "AAA", "onboardDate": 1}]}

    def book_tickers(self):
        return [{"symbol": "AAAUSDT", "bidPrice": "99.9", "askPrice": "100.1"}]

    def tickers_24h(self):
        return [{"symbol": "AAAUSDT", "quoteVolume": "50000000", "highPrice": "120", "lowPrice": "80", "lastPrice": "100"}]

    def klines(self, symbol, interval, limit):
        return [kline(i, 100 + (i % 3)) for i in range(80)]


def test_scanner_filters_and_scores(monkeypatch):
    config = PaperBotConfig(minimum_listing_days=0, selected_candidates=1)
    monkeypatch.setattr("live_paper_bot.time.time", lambda: 100_000)
    result = VolatilityScanner(FakeClient(), config).scan()
    assert result[0]["symbol"] == "AAAUSDT"
    assert result[0]["volatility_score"] == 1.0


def test_paper_broker_persists_without_credentials(tmp_path):
    config = PaperBotConfig(output_dir=str(tmp_path))
    broker = PaperBroker(config, tmp_path)
    broker.equity = 987.65
    broker.save()
    restored = PaperBroker(config, tmp_path)
    assert restored.equity == pytest.approx(987.65)
    state = json.loads((tmp_path / "state.json").read_text())
    assert "api_key" not in state and "secret" not in state


def test_invalid_strategy_is_rejected():
    with pytest.raises(ValueError, match="strategies"):
        PaperBotConfig(strategies=["real_money"]).validate()
