# Imbalance Origin Retest

Select **Imbalance Origin Retest (JeaFx-inspired)** in the strategy selector.
The initial timeframe is 1h; other timeframes can be tested. Both directions use
mirrored rules. This is a mechanical research interpretation of the video's
imbalance-to-origin idea, not an exact discretionary system or proven edge.

1. The candle immediately before displacement must be opposing or a doji. Its
   full wick range defines origin demand/supply.
2. A directional displacement body must meet Minimum displacement body (ATR)
   and close beyond the preceding `2 × swing strength + 1` candles, including
   the origin. The next candle must confirm a three-candle wick gap.
3. Starting after gap confirmation, wait for a candle touching the origin zone
   and closing directionally outside its near edge. Touching only the gap
   cannot enter. This guarantees a full fill to the gap's far edge.
4. Any wick through the origin's far edge cancels the setup. Expire after
   Maximum wait candles from gap confirmation. A newer same-side setup replaces
   the older one. Each setup signals at most once. Simultaneous opposing signals
   are skipped. Missing or invalid OHLC candles reset pending state.
5. Enter at next open. Stop beyond the origin plus Stop buffer (ATR), measured
   at the rejection candle. Target the displacement/confirmation extreme fixed
   when the gap was confirmed. Reject a next open beyond the origin, invalid
   stop/target geometry, or reward/risk below Minimum R.

Account risk sizing, fees and slippage use the existing backtest execution
settings. Optional trailing/partial/BE management is disabled for this preset.
Chart review uses the saved origin, target range and confirmation timestamps.
Compare against the existing FVG strategy using the same dates, costs and risk;
this change adds the strategy but does not establish profitability.

## Optional inducement and structure confirmation

In Risk & Execution, choose **Inducement + structure confirmation** under
Imbalance entry model. The original **Origin rejection** mode stays available
and remains the default for existing configurations. Choosing the new model
switches a 1h entry timeframe to 15m. Zone timeframe defaults to 60 minutes;
it must be larger than and exactly divisible by the entry timeframe. For example,
use 60m zones with 15m entries, or 240m zones with 15m entries.

This option combines the two video concepts with explicit mechanical rules:

1. Aggregate complete UTC-aligned zone candles from the entry candles. Incomplete
   buckets cannot form zones. A data gap clears pending entry state and breaks
   higher-timeframe trend continuity.
2. Require two confirmed higher highs and higher lows for longs, or two lower
   highs and lower lows for shorts. Pivots use Swing candles on each side; they
   become usable only after their right-hand candles close.
3. The displacement must close through the latest unbroken trend swing and its
   body must meet Minimum displacement body times the preceding 14 completed
   zone candles' mean true range. A wick-only break cannot qualify. The immediate
   opposing/doji origin and subsequent three-candle gap define the zone.
4. Skip a new shallow same-side origin while an older, deeper qualified origin
   and its gap remain unfilled. This is a price-based inducement proxy; it does
   not claim to identify actual institutional orders.
5. After confirmation, wait for a full fill touching the origin. A wick sweep
   is allowed only if the same entry candle closes back within/above demand or
   within/below supply. A close through the far edge cancels the setup.
6. Wait for a lower-timeframe pivot formed at or after the touch to be confirmed,
   then a directional close through it. The immediately preceding candle must
   be opposing/doji; its full wick range defines the refined entry origin.
7. Require a separate later retest of the refined origin and directional close
   away from it. Enter at next open. A wick through the reversal extreme after
   shift cancels; the stop never widens to accommodate it. The retest above/below
   that extreme supplies the higher-low/lower-high confirmation.
8. Stop beyond the touch-to-shift reversal extreme plus the configured entry-ATR
   buffer. Target the known displacement/formation high for longs or low for shorts,
   frozen at gap confirmation before the future pullback. The swing broken by
   displacement confirms structure; it is not reused as the take-profit.
   Recheck minimum R and reject a next-open fill beyond the refined origin's far
   edge. All stages expire Maximum wait zone candles after gap confirmation.

Each setup signals once, with no entry on its shift candle. Simultaneous opposing
or overlapping confirmations are consumed without choosing an intrabar order.
Saved chart evidence includes the original zone, refined origin, structure
break, lower-timeframe shift, reversal extreme and pre-pullback extreme target. The
interpretation remains discretionary-video-inspired; compare both models on
the same data before drawing conclusions about performance.

## Diagnosing few or no trades

Visible chart imbalances are not entry signals. Confirmation mode needs complete
zone candles, a qualified trend break, an origin fill, a lower-timeframe shift,
and a later entry-origin rejection. Minimum reward/risk is then checked using
the next-open entry including configured slippage and the strategy-owned stop.
A 3R minimum can reject otherwise complete patterns with nearby targets.

Rejected imbalance signals distinguish `IMBALANCE_TARGET_NOT_AHEAD`,
`IMBALANCE_INVALID_STOP_GEOMETRY`, and `IMBALANCE_MINIMUM_R_NOT_MET`.
Their saved signal rows include proposed entry, stop and target prices and the
actual setup direction. Existing completed runs retain their original evidence;
rerun to apply corrected targeting and these rejection reasons. Confirmation
targets now use the known formation extreme, rather than the already-broken
structure swing that could end up behind a delayed entry.
