# EMA 100/300 — Two-Candle Reversal (1R)

Choose **EMA 100/300 — Two-Candle Reversal (1R)** in Strategy Builder.
Choose the data period, strategy timeframe, intrabar detail and account risk,
then run a new backtest. The automatic execution plan is shown in Risk &
Execution. Save the configuration to reuse the preset.

The screenshot's indicator sources are used: EMA 100 of candle lows and EMA
300 of candle highs, both on the selected strategy timeframe. Both are calculated
with the native CSL causal EMA formula and use completed candles only.

- Short: EMA 300 is strictly above EMA 100, followed by the consecutive pattern
  green → red → red. Enter at the open immediately after the second red candle
  (the third candle after the original green).
- Long: EMA 300 is strictly below EMA 100, with red → green → green. Enter at
  the next open after the second green.

The actual next-open entry, including entry slippage, must be **strictly above
both EMAs for a short** or **strictly below both EMAs for a long**. Entries between
the lines or exactly on either required boundary are rejected, with reason
`EMA100_300_ENTRY_POSITION_REJECTED`. EMA values come from the last completed
signal candle; the future entry candle's final EMA values are not used.

Green means close > open, red means close < open. A doji breaks the pattern.
The EMA order is checked on the last completed confirmation candle; the signal
does not require an EMA crossover. Missing strategy candles break the pattern.

TP is the EMA 100 (low) value from that last completed candle, frozen at entry.
SL is reflected around the actual entry: `SL = 2 × entry − TP`.
Entry includes configured slippage. Reject the setup when the target is not
strictly below a short entry or strictly above a long entry, including after
an opening gap. This is 1R before fees and exit slippage, not guaranteed 1R net.

The preset owns its fixed stop, target and stop-based position sizing. It ignores
profile stop/R multipliers, separate sizing-stop overrides, partial exits,
break-even, trailing, timeout and TP extension. Account risk multipliers,
market permissions, entry/veto rules, fees and leverage caps still apply.
Only fresh complete patterns can enter; a third consecutive red/green candle
does not itself repeat the original setup. Existing active-trade limits apply.

Completed trades save `ema100_low`, `ema300_high` and `ema_reversal_target_r`.
New runs also save `ema_reversal_entry_position_rule` to identify this rule.
Older completed runs keep their original trades; run a new backtest to apply
the corrected position requirement.
The V2 visualizer starts with EMA 100 (low) in blue and EMA 300 (high) in red.
Other strategies retain their close-price EMA calculations. Selecting another
chart timeframe recalculates those displayed EMAs on that chart timeframe;
persisted entry, TP and SL remain the strategy's recorded values.


### Minimum EMA separation

Risk & Execution exposes **Minimum EMA gap**, default **0.5 × ATR**.
At the signal candle close, require `abs(EMA100(low) - EMA300(high)) >= minimum * ATR`.
ATR is the strategy engine's configured strategy-timeframe ATR. Equality passes;
smaller gaps are rejected with `EMA100_300_GAP_TOO_SMALL`. A positive threshold
also rejects unavailable or nonpositive ATR. Set the threshold to **0** to disable.
The check uses only the completed signal candle, alongside the existing entry
position and EMA-order checks, and affects only this preset. This is an adjustable
starting threshold, not a demonstrated performance improvement. Rerun backtests
when changing it; completed runs retain their original trades.
