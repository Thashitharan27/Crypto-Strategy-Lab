# New York 4h Range Reversal (5m)

Select **New York 4h Range Reversal (5m)** in the strategy selector. The entry
timeframe automatically changes to 5m. In Risk & Execution, **New York range
target (R)** defaults to 2R and may be increased. Existing account risk sizing,
fees, slippage and portfolio limits still apply. Supply/demand minimum-R,
imbalance confirmations and discretionary stop refinements are not part of it.

## Oversized target options

Risk & Execution includes **When target extends too far**:

1. **Default - keep breakout stop** preserves the original strategy. No target
   distance filter applies, including when loading old saved configurations.
2. **Ignore oversized setup** skips the entry if its R target exceeds the allowed
   distance beyond the opposite boundary of the opening range.
3. **Use a confirmed S/R stop** keeps the original stop when the target already
   fits. Otherwise, it tries the existing detector's nearest valid support zone
   for longs or resistance zone for shorts. It uses only the configured S/R
   context available at the signal candle's close, not manually drawn lines.

**Allowed target beyond range (% of 4h height)** defines the allowance. At 0%,
long targets must be at/below the 4h high, and short targets at/above the 4h low.
For a range from 100 to 120 and a 10% allowance, the long ceiling is 122 and the
short floor is 98. The default allowance is 0%; it is used only by options 2/3.

For option 3, S/R calculation is enabled automatically. Its timeframe and detector
settings are the existing configured S/R analysis settings. The stop goes beyond
the zone's outer edge by **Buffer beyond S/R (entry ATR)**, default 0.05 ATR; 0
uses the exact boundary. If zone edges are unavailable, the confirmed level price
is used. The stop must be nearer than the original stop and behind the executable
entry. Broken/absent/wrong-side levels are rejected. If the new R target still
exceeds the allowance, the trade is skipped; there is no oversized fallback.

Every check uses the actual entry including slippage. The target remains the
configured R multiple of the selected stop distance, rather than being clamped
to the range boundary. Native risk sizing uses that new stop distance. Saved
chart evidence records the original stop/target, selected stop source, S/R
boundary/state and allowed target boundary. Completed runs remain unchanged;
rerun to compare the three options on the same data.

This is a mechanical interpretation of the core checklist in
[The BEST 5 Minute Scalping Strategy Ever](https://www.youtube.com/watch?v=O5eC5lY7ZXY).
The video alternates between breakout-extreme stops and discretionary nearby
levels; the baseline consistently uses the full breakout extreme. Its selected
examples and small sample do not establish profitability.

## Session and signals

- Define a New York day using `America/New_York`, including daylight saving.
  The opening range starts at local midnight and lasts **four elapsed hours**.
  It requires all 48 valid 5m candles. The final range candle cannot also be a
  breakout candle, and a partial opening range is never used.
- On ordinary days the range closes at 04:00 New York time. On the spring DST
  transition it closes at 05:00; on the fall transition at 03:00. This is an
  explicit crypto-session convention: changing a chart's display timezone does
  not necessarily re-anchor its exchange-supplied 4h candles to local midnight.
- After the range closes, a 5m **close above the high** arms a short reversal;
  a **close below the low** arms a long reversal. Wicks alone cannot arm a setup.
- Wait for a later candle closing **strictly inside both boundaries**. Equality
  at either boundary does not confirm. No candle-colour or trend filter applies.
- Enter at the following 5m open, including configured slippage. The executable
  entry must still be inside the range and on the same New York day. A return
  candle closing exactly at the next midnight cannot enter.
- Stop at the full excursion high for shorts or low for longs, measured from
  the first outside-close candle through and including the return candle. No
  ATR buffer or substitution with a nearby level is applied. A 2R target is
  calculated from the **actual entry and stop**, avoiding stale target geometry.
- An outside close through the opposite boundary without an inside close does
  not confirm the old setup. It starts a fresh opposite excursion.
- Each excursion is consumed once. Another outside-close/inside-close sequence
  can trade again that day, subject to the configured portfolio limits.

Missing or invalid opening candles invalidate that day's range. A later gap
clears the pending excursion while retaining the completed range. Every New
York midnight resets the range and pending setup. Open positions retain their
SL/TP overnight; the video does not define a mandatory end-of-day exit.

## Execution and chart review

The preset owns its fixed stop and R target; optional partial/BE/trailing/timeout
management is disabled. Signals rejected at the next open identify invalid
geometry or an entry outside the range. Saved evidence contains the session day,
range start/close, breakout and return candle times, exact stop and actual target.
Chart review draws thin range/stop/target lines to preserve candle visibility.

The first research pass should use a broad sample with realistic fees and
slippage. A 2R price target is a gross objective, not a guaranteed net 2R result.
