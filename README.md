# Long-Short-Crypto-testing

A modular Python backtesting tool for dual long/short crypto strategies on Binance OHLCV CSV files.

## Features

- Opens one long and one short position per entry signal.
- Independent SL/TP handling for each side.
- Configurable fixed, percentage, or TradingView-style ATR(14) risk distance.
- Configurable SL/TP multiples, Binance maker/taker fees, and slippage.
- Pessimistic, optimistic, and future intrabar same-candle TP/SL policies.
- Entry modes for waiting until closed, every N candles, or isolated custom strategy logic.
- Architecture supports multiple active trade pairs via `max_active_pairs`.
- Exports trade list CSV, summary JSON, equity CSV, and PNG charts.

## Expected CSV columns

```text
timestamp,open,high,low,close,volume
```

## Run

```bash
python main.py --input data/binance_ohlcv.csv --output-dir output
```

Edit `config.py` to change risk, entry, fee, slippage, and tie-policy settings without modifying the engine.
