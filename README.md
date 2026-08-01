# Long-Short-Crypto-testing

A modular Python backtesting tool for dual long/short crypto strategies on Binance OHLCV CSV files.

## Live volatility paper bot

`live_paper_bot.py` is a separate forward-testing tool. It scans active Binance
USD-M USDT perpetual contracts, removes illiquid/new/stablecoin markets, ranks
the remaining contracts by volatility and liquidity, and paper-trades breakout,
trend, and mean-reversion signals in independent $1,000 comparison accounts. It uses public market data only: it has no API
key option and cannot submit a real order.

Run one diagnostic scan:

```powershell
python live_paper_bot.py --config Config/live_paper_bot.json --once
```

Run continuously (leave the terminal open):

```powershell
python live_paper_bot.py --config Config/live_paper_bot.json
```

Forward-test output is written to `paper_output/`: `rankings.csv` is the
point-in-time audit trail, `trades.csv` contains paper opens/closes, and
`state.json` allows the bot to resume. The defaults use a $1,000 paper account,
0.5% risk per trade, at most two positions per strategy, and a 2x notional cap. Stops and
targets are simulated conservatively with taker fees and slippage. Open
positions continue receiving fresh candles even after their symbols drop out
of the top-five volatility ranking.

## Features

- Opens one long and one short position per entry signal.
- Independent SL/TP handling for each side.
- Configurable fixed, percentage, or Wilder ATR risk distance with an ATR multiplier.
- Real position sizing from current equity, risk-per-leg, and stop distance, with optional all-in stop-risk sizing that includes estimated fees and slippage.
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
python gui.py
```

For Command Prompt on Windows:

```bat
.venv\Scripts\activate
pip install -r requirements.txt
python gui.py
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

### Combine monthly or daily Binance downloads

For the easiest Windows workflow, double-click `Combine Binance Data.bat`.
Select the folder containing the ZIP files, choose where to save the combined
CSV, and wait for the completion message. The ZIP files do not need to be
extracted.

You can alternatively use PowerShell. Put the Binance `.zip` or `.csv` files
in one folder, then run:

```powershell
python combine_binance_data.py "data\Combine\1h_2026"
```

This writes `data/binance_ohlcv.csv`, ready for the backtester. Files are
combined by the date in their Binance filenames, repeated headers are removed,
and duplicate candle timestamps are skipped. Both labeled and headerless
Binance kline files are supported. To choose another destination:

```powershell
python combine_binance_data.py "data\Combine\1h_2026" -o "data\BTCUSDT-1h-2025.csv"
```

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

Partial stop loss can be enabled with `enable_partial_stop_loss`. `sl1_r`
closes `sl1_close_pct` of each leg once; the remaining quantity stays open
until the normal take profit or `sl2_r`. For the 0.5R/8R example, use
`sl1_r = 0.5`, `sl1_close_pct = 50`, `sl2_r = 8`, and `tp_mult = 8`.

Partial stop loss and partial take profit can also be enabled together. SL1
and TP1 quantities are percentages of the original position and are capped by
the quantity still open; SL2 and fixed TP2 close all remaining quantity. After
TP1, `KEEP_ORIGINAL_SL` preserves any pending SL1 and SL2 stages.
`MOVE_TO_ENTRY` or `MOVE_TO_R_OFFSET` replaces the pending partial-stop ladder
with that single protective stop for the remainder. The configured tie policy
controls bars that touch favourable and adverse stages at the same time.

Trailing stop management is independent of the fixed exit ladders. Enable it
with one activation trigger: `PRICE_REACHES_R`, `AFTER_TP1`, `AFTER_SL1`, or
`AFTER_TP1_OR_SL1`. It applies to the quantity still open, only tightens the
active protective stop, and never removes the fixed TP2 or SL2 boundary.
Post-TP1 stop management is also independent: keeping the original stop
preserves the current SL ladder, while moving to entry or an R offset replaces
pending stop stages for the TP1 remainder. Older saved
`TRAILING_AFTER_TP1` configurations are migrated automatically to an
`AFTER_TP1` trailing trigger with fixed TP2 retained.
- `risk_per_leg = 0.005`
- `enable_bb_width_filter = False`
- `bb_width_filter_mode = BBWidthFilterMode.DISABLED`
- `bb_width_minimum = 0.012` (raw width; 1.2%)
- `enable_skip_monday_entries = False`
- `skip_monday_timezone = "UTC"`
- `enable_remaining_leg_timeout_after_first_sl = False`
- `remaining_leg_timeout_after_first_sl_minutes = 240`
- `enable_remaining_leg_timeout_profit_extension = False`
- `remaining_leg_timeout_profit_threshold_r = 10.0`
- `enable_reentry_gate_after_remaining_leg_timeout = False`
- `enable_remaining_leg_checkpoint_score_extension = False`
- `checkpoint_score_use_profit = True`; `checkpoint_score_min_profit_r = 0.85`
- `checkpoint_score_use_atr_pct = True`; `checkpoint_score_max_atr_pct = 0.08`
- `checkpoint_score_use_directional_di = True`; `checkpoint_score_min_directional_di = 2.3`
- `checkpoint_score_use_bb_width_pct = True`; `checkpoint_score_max_bb_width_pct = 0.349`
- `checkpoint_score_min_conditions = 3`
- `enable_first_sl_survivor_partial_close = False`
- `first_sl_survivor_partial_close_pct = 25.0`
- `enable_checkpoint_zero_score_confirmation = False`
- `checkpoint_zero_score_confirmations_required = 2`
- `checkpoint_zero_score_recheck_minutes = 120`

Validation enforces positive initial equity, positive ATR multiplier, non-negative fees/slippage, and `0 < risk_per_leg < 1`.

### Entry filters from the one-minute analysis

Both filters are disabled by default and can be enabled independently. To require at least 1.2% Bollinger Band width at entry, enable the existing Bollinger-width filter, choose `Minimum Width`, and set `bb_width_minimum` to `0.012`. Bollinger width is stored as a raw decimal, so 1.2% is `0.012`, not `1.2`. The GUI labels and help text show this conversion. CLI users can pass `--enable-bb-width-filter --bb-width-filter-mode "Minimum Width" --bb-width-minimum 0.012`.

The Monday filter rejects a new entry when its actual execution timestamp falls on Monday in `skip_monday_timezone`. It does not close or otherwise alter an already-open trade. This rule is applied consistently to continuous, random, and daily-scheduled entries. Enable it with `enable_skip_monday_entries = True`, or pass `--enable-skip-monday-entries`; use `--skip-monday-timezone UTC` or another valid IANA timezone to define Monday explicitly.

### Remaining Leg Timeout After First SL

This optional rule is disabled by default. When enabled, the first leg that exits specifically at its normal `SL` records its side and exact exit timestamp and starts a separate timer for the still-open opposite leg. A TP, break-even, trailing-stop, partial-TP, both-open-timeout, or other special exit never starts the timer. The remaining leg keeps its target and active stop throughout the waiting period, so it may still close naturally at TP, SL, break-even, or trailing stop before the deadline.

The deadline is the first normal-SL timestamp plus `remaining_leg_timeout_after_first_sl_minutes`. If the leg is still open, intrabar execution uses the open (with normal direction-specific exit slippage and fees) of the first intrabar candle at or after the exact deadline. Without usable intrabar data, execution uses the first strategy-candle open at or after the deadline and records the normal 15-minute fallback source and reason. If data ends before the deadline, the ordinary `END_OF_DATA` exit remains in force. Break-even-after-opposite-SL can run alongside this timer, while the existing both-open timeout stops applying as soon as either leg closes.

An optional profit-extension rule can turn the deadline into a repeating checkpoint. When `enable_remaining_leg_timeout_profit_extension` is enabled, the engine calculates the surviving leg's unrealized price R at each checkpoint open. If it is at least `remaining_leg_timeout_profit_threshold_r`, the leg receives another full timeout interval and is checked again. If it is below the threshold, it closes at that checkpoint using the normal timeout execution rules. For example, with a four-hour interval, a 10R threshold, and a 13R TP, a surviving leg at or above +10R remains open for another four hours; a leg below +10R is closed.

When `enable_reentry_gate_after_remaining_leg_timeout` is enabled, a checkpoint-closed leg is tracked virtually after its real market exit. Replacement entries remain blocked until later market data touches that leg's saved TP or active SL. The gate releases immediately on the boundary-touch candle, matching the normal no-checkpoint behavior where a naturally closed pair can be replaced on that same strategy candle. The trade list records the saved side, TP, SL, gate start, release time, and whether TP or SL released it.

The optional checkpoint score extension evaluates profit, ATR as a percentage of price, direction-adjusted DI, and Bollinger width using the last completed strategy candle. Each condition can be enabled independently and its threshold edited. The remaining leg receives another full timeout interval when at least `checkpoint_score_min_conditions` enabled conditions pass. Choose either this score extension or the legacy profit-only extension, not both. The default experimental values are 0.85R minimum profit, 0.08% maximum ATR, +2.3 minimum directional DI, 0.349% maximum Bollinger width, and three required conditions.

The optional first-SL survivor partial close realizes a configurable percentage of the still-open opposite leg at the market price that triggered the first normal SL, including normal directional slippage and fees. The remaining quantity keeps its original TP and active SL. It cannot be combined with the separate partial-take-profit ladder.

Consecutive zero-score confirmation can be enabled with the checkpoint score extension. A zero score increments the pair's warning streak. Before the required count is reached, the leg stays open and is checked again after `checkpoint_zero_score_recheck_minutes`; any passing score resets the streak and restores the normal checkpoint interval. The leg closes only when the configured consecutive zero count is reached.

The desktop GUI exposes the duration in Minutes or Hours but stores and serializes it in minutes. CLI users can pass `--enable-remaining-leg-timeout-after-first-sl --remaining-leg-timeout-after-first-sl-minutes 240 --enable-remaining-leg-timeout-profit-extension --remaining-leg-timeout-profit-threshold-r 10`.

## Position sizing and PnL

For each new pair:

```text
R = selected risk distance
stop_distance = sl_mult × R
risk_amount_per_leg = current_equity × risk_per_leg
quantity = risk_amount_per_leg / stop_distance
```

The same risk amount and quantity formula is used for the long and short legs.

By default, `risk_per_leg` is a price-risk budget: a stopped leg is expected to lose the configured price distance before execution costs, so net account loss will be larger after entry fees, stop-exit fees, and slippage. Set `position_sizing_mode = ALL_IN_STOP_RISK` or pass `--all-in-risk-sizing` to reduce quantity so the estimated stop loss including those costs stays near `risk_per_leg`. Trade output records both `configured_price_risk_percentage` and `estimated_all_in_stop_risk_percentage`.

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

## Desktop GUI

Run the PySide6 desktop interface separately from the CLI:

```bash
python gui.py
```

The GUI uses the same loader, `BacktestEngine`, statistics, and plotting modules as `python main.py`. It provides configuration, summary, trade-list, chart, and log tabs, saves/loads JSON configurations, and keeps the backtest worker on a `QThread` so the window remains responsive.

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
  --position-sizing-mode PRICE_RISK \
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

- `trade_list.csv` — detailed pair-level and leg-level results including quantity, risk amount, configured price-risk percentage, estimated all-in stop-risk percentage, notionals, SL/TP, exit reason, gross/net PnL, price-distance R, account-risk R, fees, equity, holding time, and ambiguity flags.
- `trade_list_column_metadata.json` — tooltip-style definitions for every R and risk-percentage column in `trade_list.csv`.
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

## 15-Minute Strategy Candles With 1-Minute Exit Resolution

The backtester now separates strategy data from intrabar exit data. Use `strategy_csv` / `--strategy-input` for 15-minute candles and `intrabar_csv` / `--intrabar-input` for optional 1-minute candles. ATR, entry timing, raw entry price, stop-loss, and take-profit levels are calculated only from the completed 15-minute strategy candle. The 1-minute file is used only after entry to determine which exit barrier was touched first.

Binance `open_time` is the candle start time. A 15-minute row with `open_time = 10:00` is considered complete at `10:15`, so the internal `strategy_entry_time` is the 15-minute candle open time plus 15 minutes. This avoids look-ahead bias: the entry uses the 15-minute close, and the high/low of that just-completed candle are not used after the entry.

You can provide warm-up history before the trading window. Use `--data-start` to choose the first candle loaded for indicators and `--trading-start` to choose the first eligible entry time. For example, start the 15-minute data on `2026-05-25`, then set `--trading-start 2026-06-01 --trading-end 2026-06-30`. Warm-up candles seed Wilder ATR but do not generate trades.

Fees remain charged on full notional, not margin. Leverage changes required margin but does not reduce trading fees, so small ATR values can create large notional sizes under account-risk sizing. Optional leverage caps (`--max-leverage-per-leg` and `--max-combined-leverage`) reduce quantities explicitly and mark trades with `leverage_capped` instead of silently changing size.

Trade output separates price-distance R from account-risk R. Price R is price movement divided by the ATR-based R distance. Account R is cash PnL divided by planned cash risk per leg. This makes pairs such as one TP and one SL easier to interpret when SL and TP multiples differ.

The optional zero-cost comparison (`--zero-cost-comparison`) reruns the same strategy with zero fees and zero slippage and stores side-by-side metrics in `summary.json`, helping identify whether execution costs are overwhelming the raw setup.

### GUI

```powershell
.venv\Scripts\activate
pip install -r requirements.txt
python gui.py
```

The GUI includes separate selectors for the 15-minute strategy CSV and 1-minute intrabar CSV, a checkbox for 1-minute exit resolution, ATR controls, trading date filters, leverage caps, missing intrabar policy, and zero-cost comparison.

### CLI

```powershell
python main.py ^
  --strategy-input data/BTCUSDT_15m.csv ^
  --intrabar-input data/BTCUSDT_1m.csv ^
  --use-intrabar
```

Additional CLI options include `--strategy-timeframe`, `--intrabar-timeframe`, `--atr-period`, `--atr-multiplier`, `--data-start`, `--trading-start`, `--trading-end`, `--max-leverage-per-leg`, `--max-combined-leverage`, `--intrabar-missing-policy`, and `--zero-cost-comparison`.

## Reproducible random-entry timing experiment

Random timing is opt-in and is active only when both **Enable Random Entry Timing** is checked and **Entry Timing Mode** is `RANDOM_AFTER_PAIR_CLOSE`. `CURRENT` (or a disabled checkbox) follows the original entry path and does not instantiate or consume a random generator.

The random sequence is intentionally narrow:

1. The engine finishes processing exits for a 15-minute strategy candle and confirms every quantity on every enabled leg is closed.
2. The candle in which that happened is never reused for an entry. At the next eligible candle open, the engine uses indicators from the preceding completed candle only.
3. Exactly one value is drawn from a dedicated `random.Random(Random Seed)` instance. A value **strictly below** Entry Probability is `OPEN`; a value equal to or above it is `SKIP`.
4. `OPEN` sends the existing configured direction mode through the normal pair creation, sizing, risk, fees, stops, targets, partial/trailing, break-even, timeout, telemetry, and equity paths. In `BOTH`, one draw opens both legs; direction is never randomized.
5. A positive Maximum Random Wait forces an entry on the eligible candle after that many consecutive skips. The forced candle still has one audit draw but is recorded as `FORCED_OPEN`, not Heads. Zero never forces.

Because execution occurs at the eligible candle's open, its open is the unslipped strategy entry price and its high, low, and close are not used for entry. `NEXT_FULL_CANDLE_AFTER_PAIR_CLOSE` is the default. With this event loop both start modes advance to a later strategy candle; the full-candle mode explicitly prohibits close-and-reopen in the candle that resolves the prior pair.

Single runs write `random_entry_decisions.csv`, `random_entry_analysis.csv`, and `random_vs_baseline_comparison.csv`. Trade rows contain the decision id/draw/time, wait, prior close, forcing flag, seed, probability, and effective timing mode. Batch mode resets the engine, starting equity, and seeded generator for every seed, then writes `random_entry_batch_summary.csv` and `random_entry_batch_statistics.csv`.
