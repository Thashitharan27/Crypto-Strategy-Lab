# Supply & Demand — 1h Swing Retest

Research preset based on [TradingLab: How To Find PERFECT Entries](https://www.youtube.com/shorts/tS9o8aQjADY).
The video leaves mechanical swing selection and invalidation unspecified. These
are explicit rules for a first test, rather than a claim to reproduce discretion.

Select this preset in Strategy Builder. It sets the strategy timeframe to 1h.
Risk & Execution exposes swing strength (default 2 candles each side, range 1–20),
stop buffer (default 0.05 × strategy ATR, zero for exact zone edge), and minimum
reward/risk (default 1R).

A pivot must be strictly above/below all N neighbours on each side. Equal highs
or lows do not qualify. It becomes known only after the right-hand candles close.
The pivot candle's full range defines its zone. Confirmation candles cannot count
as prior touches. Only the latest confirmed zone on each side is retained.

1. A subsequent candle overlaps the zone, including a wick.
2. Demand produces a close above its top; supply produces a close below its bottom.
   The first-touch candle can also establish this bounce.
3. A later candle overlaps the zone and closes bullish for demand, bearish for
   supply. Dojis fail; the close can be inside the zone.
4. Enter at the immediately next open, including slippage. Missing next candles
   cannot defer entry to a later hour.

SL is beyond the entry zone's far edge with the ATR buffer. TP is the opposing
confirmed swing high for longs, low for shorts, frozen at entry. Reject wrong-side
targets, entries beyond the stop, unavailable ATR and insufficient reward/risk.
Account-risk sizing uses actual stop distance and existing leverage limits.

A close through the far edge invalidates a zone. Missing or nonfinite candles
reset all state. New pivots replace same-side zones. The first directional retest
consumes a zone even if no opposing target exists or profile/account rules reject
the attempt. Simultaneous opposite signals are skipped. There is no age expiry.
Trailing, partials, break-even, timeout and generic stop multipliers are overridden.
Explicit selection disables daily scheduling. Market permissions, entry/veto
rules, fees, account risk and active-trade limits still apply.

Saved trades contain `supply_demand_setup`: pivot and confirmation times, touch,
bounce, retest and opposing-zone evidence. The visualizer reads these saved zones
without recalculating swings, with setup review and manual replay. Restart the
tool and run a new backtest; existing runs and other presets retain their rules.
