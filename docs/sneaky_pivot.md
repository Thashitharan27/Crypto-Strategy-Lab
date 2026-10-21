# Sneaky Pivot — All Day (15m)

Select this strategy under **Strategy & Markets**. It selects 15m strategy
candles and 1m execution data. Run a backtest and open the completed run in the
visualizer; **Review setup** shows the initial level test, reversal, defended
range, breakout trigger and fixed target. Trade replay uses the saved evidence.

This is the all-day mechanical interpretation of
[The Rumers' Sneaky Pivot video](https://www.youtube.com/watch?v=zspMXJVbfAY),
not a reproduction of its discretionary stock-market results.

## Rules

- Any 15m candle, including weekends, can start a setup. No session window.
- Support/resistance: the previous complete UTC day's low/high, plus the most
  recent older confirmed swing beyond each boundary. Swings use two candles
  on each side by default; only confirmed information is used. A missing candle
  clears context; incomplete days cannot provide levels.
- Initial red candle near support for long; initial green near resistance for
  short. Body at least 50% of candle range and 0.5 prior ATR(14). Its extreme
  must lie within 0.30 ATR of the nearest qualifying level.
- Wait for the first opposite-color candle within three subsequent bars.
  Cancel on a breach beyond the defended initial/level extreme plus 0.05 ATR.
- Enter only if the following 15m candle breaks the reversal high (long) or
  low (short). Use the first crossing 1m candle, including an adverse gap.
  An unfilled order expires after that one bar. Complete 1m coverage is required.
- Stop beyond the initial candle, reversal candle and defended level, with
  0.05 ATR buffer. Freeze the initial ATR and geometry. TP is the opposite
  previous-day boundary. Reject wrong-side targets/stops and direction flips.
  No extra minimum-R filter applies. Size risk using the actual stop distance.
- One open position; discard setups starting during an earlier position.
  If several initial candles confirm together, use the earliest one. Each
  initial candle has one attempt. A later new candle may start a new setup.
- Close unresolved positions at the first execution bar at/after 1,440 minutes
  from the initial candle. Normal data-end closure still applies. Optional
  trailing, partial exits, break-even and TP extensions are disabled.

## Settings

Risk & Execution exposes level tolerance, minimum body in ATR, confirmation
wait, holding minutes, swing strength and stop buffer. The body/range threshold
stays 50%. Holding minutes must cover the entire confirmation/breakout window.
Default entry selection disables daily scheduling and other confirmation
presets. Existing explicit Entry/Veto rules and market permissions still apply.

Use the app's ordinary account risk, leverage, fees and slippage settings.
Profitable extremes on the entry minute are deferred until the next minute
because OHLC cannot establish ordering; stops remain possible. The native
engine's pessimistic tie policy and timeout-at-next-open handling can differ
from the earlier exploratory script's minute-close holding cap. Native ATR,
warmup, sizing and account execution also apply, so rerun results supersede
the exploratory trade list rather than modifying it.

Prior-day levels, strong-body thresholds, proximity, waiting window and hold
limit are explicit research choices where the video uses judgment. No settings
were optimized against the historical sample.
