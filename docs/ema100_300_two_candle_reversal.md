# EMA 100/300 — Two-Candle Reversal (Custom R)

Choose **EMA 100/300 — Two-Candle Reversal (Custom R)** in Strategy Builder.
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
SL distance is `abs(TP − entry) / reward_risk`, placed opposite the target.
The reward/risk setting defaults to 1R.
Entry includes configured slippage. Reject the setup when the target is not
strictly below a short entry or strictly above a long entry, including after
an opening gap. The selected ratio is before fees and exit slippage.

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


### Entry distance from EMA 300

Risk & Execution also exposes **Minimum entry distance from EMA 300**, default
**0.5 × ATR**. Require `abs(actual entry - EMA300(high)) >= minimum * ATR`,
using the slippage-adjusted next-open entry price and the last completed signal
candle's EMA and strategy ATR. Equality passes. A closer entry is rejected with
`EMA300_ENTRY_TOO_CLOSE`; unavailable or nonpositive ATR also fails when enabled.
Set **0** to disable this distance check independently of the EMA-to-EMA gap.
Both filters must pass, along with EMA ordering and entry outside both lines.
The default is a starting point for testing; no performance gain is established.
Restart the tool and run a new backtest to apply the setting to new trades.


### Custom reward/risk (EMA target unchanged)

Risk & Execution → EMA 100/300 trade settings → **Reward / risk** accepts positive
custom values (default **1R**). TP remains the last completed signal candle's EMA
100 (low), fixed at entry. Actual SL distance is `abs(TP - entry) / reward_risk`.
At 2R the stop is half the entry-to-target distance; at 3R it is one-third.
The stop is placed opposite the target for both directions. Position sizing uses
this actual stop distance and account risk; higher ratios therefore increase
position size subject to existing leverage limits. Fees/slippage can make net
outcomes differ from the configured gross ratio. Other geometry/management
controls remain overridden by this preset. Saved trades record the selected
`ema_reversal_target_r`. Existing runs remain unchanged and new backtests use
the selected ratio.
