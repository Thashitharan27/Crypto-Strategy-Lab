# Long-Short-Crypto-testing

A modular Python backtesting tool for dual long/short crypto strategies on Binance OHLCV CSV files.

## Features

- Opens one long and one short position per entry signal.
- Independent SL/TP handling for each side.
- Configurable fixed, percentage, or Wilder ATR risk distance with an ATR multiplier.
- Real position sizing from current equity, risk-per-leg, and stop distance.
- Binance maker/taker fee modelling by entry/exit notional plus configurable slippage.
- Pessimistic and optimistic same-candle TP/SL policies with ambiguity flags.
- Entry modes for waiting until closed, every N candles, or isolated custom strategy logic.
- Architecture supports multiple active trade pairs via `max_active_pairs`.
- Exports trade list CSV, summary JSON, equity CSV, and PNG charts.

## Windows setup

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt pytest
```

On macOS/Linux use `python -m venv .venv`, `source .venv/bin/activate`, then install the same requirements.

## CSV placement and supported columns

By default the program reads:

```text
data/binance_ohlcv.csv
```

Binance spot/futures kline CSV exports are supported directly. No manual column renaming is required when the file contains:

```text
open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore
```

The loader normalizes headers to lowercase with underscores, treats `open_time` as Unix milliseconds by default, renames the detected time column internally to `timestamp`, keeps only `timestamp,open,high,low,close,volume`, ignores extra Binance columns, converts OHLCV values to numeric, removes invalid rows and duplicate timestamps, sorts chronologically, validates OHLC consistency, detects missing 15-minute candles, and prints a loading summary.

Accepted timestamp aliases are `timestamp`, `open_time`, `time`, `datetime`, and `date`.

## Configuration defaults

Defaults live in `config.py` and can be overridden from the CLI:

- `input_csv = Path("data/binance_ohlcv.csv")`
- `timestamp_unit = "ms"`
- `initial_equity = 1000.0`
- `risk_mode = RiskMode.ATR`
- `atr_period = 14`
- `atr_multiplier = 1.0`
- `sl_mult = 2.0`
- `tp_mult = 3.0`
- `risk_per_leg = 0.005`

Validation enforces positive initial equity, positive ATR multiplier, non-negative fees/slippage, and `0 < risk_per_leg < 1`.

## Position sizing and PnL

For each new pair:

```text
R = selected risk distance
stop_distance = sl_mult × R
risk_amount_per_leg = current_equity × risk_per_leg
quantity = risk_amount_per_leg / stop_distance
```

The same risk amount and quantity formula is used for the long and short legs.

Gross PnL is calculated with quantity:

```text
long_gross_pnl = (exit_price - entry_price) × quantity
short_gross_pnl = (entry_price - exit_price) × quantity
```

Fees are calculated from notional:

```text
entry_fee = entry_price × quantity × entry_fee_rate
exit_fee = exit_price × quantity × exit_fee_rate
```

Equity updates only after both legs in a pair are closed.

## Same-candle ambiguity

If a candle touches both TP and SL for the same leg, `ambiguous_candle` is written as `True` in `output/trade_list.csv`.

- `--tie-policy PESSIMISTIC` chooses SL on ambiguous candles.
- `--tie-policy OPTIMISTIC` chooses TP on ambiguous candles.
- `INTRABAR` remains reserved for future lower-timeframe resolution.

Trades opened at a candle close are not tested against that same candle's high or low. SL/TP checks begin on the next candle to avoid look-ahead bias.

## CLI examples

Run with defaults:

```bash
python main.py
```

Run the uploaded Binance CSV and write outputs:

```bash
python main.py --input data/binance_ohlcv.csv --output-dir output
```

Override risk, fees, slippage, and tie handling:

```bash
python main.py \
  --input data/binance_ohlcv.csv \
  --output-dir output \
  --risk-mode ATR \
  --atr-period 14 \
  --atr-multiplier 1.0 \
  --sl-mult 2.0 \
  --tp-mult 3.0 \
  --risk-per-leg 0.005 \
  --initial-equity 1000 \
  --maker-fee 0.0002 \
  --taker-fee 0.0005 \
  --slippage 0.0001 \
  --tie-policy PESSIMISTIC \
  --entry-mode WAIT_UNTIL_CLOSED \
  --entry-interval 1 \
  --max-active-pairs 1
```

Additional risk modes:

```bash
python main.py --risk-mode FIXED --fixed-r 100
python main.py --risk-mode PERCENT --percent-r 0.01
```

## Output files

The output directory contains:

- `trade_list.csv` — detailed pair-level and leg-level results including quantity, risk amount, notionals, SL/TP, exit reason, gross/net PnL, gross/net R, fees, equity, holding time, and ambiguity flags.
- `summary.json` — total pairs, wins/losses/flats, win/loss rates, average/median/total net R, profit factor, ending equity, total return percentage, drawdown, streaks, average holding time, total fees, ambiguity count, and exit-reason combination groups.
- `equity_curve.csv` — equity and drawdown after each fully closed pair.
- `equity_curve.png`, `r_distribution.png`, `holding_time_distribution.png`, `monthly_returns.png`, `yearly_returns.png` — charts when matplotlib is installed.

## Tests

```bash
pytest -q
```

The tests use small artificial datasets covering Binance loading, millisecond timestamps, ignored extra columns, 15-minute gaps, Wilder ATR, position sizing, notional fees, long/short TP and SL, same-candle tie policies, end-of-data closure, net R after fees, equity, and drawdown.

## Remaining limitations

- `TiePolicy.INTRABAR` is intentionally not implemented without lower-timeframe data.
- Missing candle detection assumes a 15-minute input timeframe.
- Chart generation requires matplotlib.
