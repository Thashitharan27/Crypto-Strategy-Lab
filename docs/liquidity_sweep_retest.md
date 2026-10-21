# Liquidity Sweep — Trend + Zone Retest

Research preset based on [TradingLab: I Found The Secret to Technical Analysis](https://www.youtube.com/watch?v=p-HKL7NmDxs&t=328s),
particularly the strategy and examples from 6:26 onward. The video combines a
trend, equal-level liquidity, a sweep against that trend, a supply/demand zone
retest, a stop beyond the zone and a target at the original move's extreme.

The following are explicit mechanical choices for testing discretionary parts
of the video. They are not a claim to reproduce its hand-selected examples.

## Setup and settings

Select this preset in Strategy Builder. Explicit selection starts at 1h with
next-open execution. Other strategy timeframes are supported; each uses its own
completed candles and ATR. Intrabar data resolves exits through the native engine.
Risk & Execution exposes:

- Swing confirmation: 2 candles each side by default (1–20).
- Equal-high/low tolerance: 0.15 × ATR at pool confirmation.
- Minimum displacement body: 1 × ATR on the displacement candle.
- Maximum zone base: 3 preceding candles, starting no earlier than the sweep.
- Maximum wait: 20 candles from sweep to displacement, and another 20 from zone
  formation to retest. Each stage has its own expiry.
- Stop buffer: 0.05 × ATR at signal; minimum actual reward/risk: 1R.

## Mechanical sequence

1. Confirm strict pivot highs/lows only after all right-hand bars close. Two
   higher highs and higher lows establish LONG bias; two lower highs and lower
   lows establish SHORT bias. Structure remains biased until a close breaks its
   protected low/high. A wick sweep alone cannot reverse it. Same-direction
   structural updates can advance the protected level and trend extreme.
2. Two consecutive confirmed lows/highs within tolerance define a liquidity
   pool. Discovery and pool freshness are bounded to 64 strategy candles.
3. In LONG bias, require a later wick below both equal lows and a close above
   both. SHORT bias mirrors this above equal highs. The pool must have been
   confirmed before the sweep candle opened. Consume a pool on its first sweep.
4. A later directional candle must have the minimum body size and close beyond
   the entire preceding base range. That range defines demand/supply. Freeze TP
   at the pre-sweep confirmed trend extreme; later highs/lows do not move it.
5. A still later candle must overlap the zone and close in the trade direction.
   A close through the far edge invalidates it. Enter at the next open with
   slippage. A missing next candle does not defer entry to a later bar.

A zone gets one qualifying retest attempt, including when account limits or
filters reject the entry. Missing/nonfinite candles reset structure and setup
state. Entries with unavailable ATR, stops on the wrong side, targets on the
wrong side or insufficient reward/risk are rejected. SL is beyond the far zone
edge with its ATR buffer. Native account-risk sizing and leverage caps apply.
Optional trailing, partials, break-even, timeout and generic stop multipliers are
overridden. Explicit selection disables daily scheduling and unrelated ladder/
confirmation options. Existing market permissions and entry/veto rules apply.

## Review evidence

Saved `supply_demand_setup` has `strategy=LIQUIDITY_SWEEP_RETEST`, equal-level
evidence, sweep time, displacement/zone confirmation, retest and frozen target.
The visualizer displays the zones and sweep/displacement/retest labels. Review
setup and manual replay read saved evidence, without reconstructing future swings.

Existing Supply & Demand — 1h Swing Retest retains its separate rules. Restart
the tool and run a new backtest to select this preset. Sparse results are possible
with these strict starting thresholds; they do not establish profitability.
