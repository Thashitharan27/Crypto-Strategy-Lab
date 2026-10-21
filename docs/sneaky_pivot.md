# Sneaky Pivot — All Day (15m)

Select this strategy under **Strategy & Markets**. It selects 15m strategy
candles and 1m execution data. Run a backtest and open the completed run in the
visualizer; **Review setup** shows the initial level test, reversal, defended
range, breakout trigger and fixed target. Trade replay uses the saved evidence.

The chart shows four named horizontal levels: previous UTC-day high and low
(solid), older swing high and low (dashed). They are saved at setup time on new
runs. Older runs reconstruct missing display context from the same warmup,
strictly before setup, and label that source in setup details; saved outcomes
and entry decisions are unchanged. Missing outer swings are explicitly marked
unavailable instead of duplicating a range boundary. Reset price fits all known
levels; manual zoom can still move a level off screen. UTC midnight separators
and date labels are enabled by default and can be toggled with **UTC days**.

This is the all-day mechanical interpretation of
[The Rumers' Sneaky Pivot video](https://www.youtube.com/watch?v=zspMXJVbfAY),
not a reproduction of its discretionary stock-market results.

## Rules

- Any 15m candle, including weekends, can start a setup. No session window.
- Support/resistance: the previous complete UTC day's low/high, plus the most
  recent older confirmed swing beyond each boundary. Swings use two candles
  on each side by default; only confirmed information is used. A missing candle
  clears context; incomplete days cannot provide levels.
- Initial red candle testing the previous-day low for long; initial green testing
  the previous-day high for
  short. Body at least 50% of candle range and 0.5 prior ATR(14). Its extreme
  must touch/cross that day boundary and lie within 0.30 ATR of it. An older
  swing alone is not an entry-test level.
- Wait for the first opposite-color candle within three subsequent bars.
  Cancel if the older swing stop is touched before entry, including ambiguous
  1m candles touching both the stop and breakout trigger.
- Enter only if the following 15m candle breaks the reversal high (long) or
  low (short). Use the first crossing 1m candle, including an adverse gap.
  An unfilled order expires after that one bar. Complete 1m coverage is required.
- Stop below the saved older confirmed swing low for longs, or above the swing
  high for shorts, by `sd_stop_buffer_atr × setup ATR` (default 0.05).
  Set the buffer to zero for the exact swing price. The swing is outside the previous-day range. Skip setups without that swing
  or whose initial/reversal candle already touches it. Freeze this anchor and preceding completed candle ATR at
  the initial test; do not replace it with a later swing or candle low/high.
  TP is the opposite
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
wait, holding minutes and swing strength. The shared zone stop-buffer setting
does not apply to this strategy. The body/range threshold
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

Completed runs retain their original trades and stops. Rerun the strategy to
use the previous-day-test / older-swing-stop rules. The visualizer labels
older saved setups without a stop source as using the legacy defended-level rule.
