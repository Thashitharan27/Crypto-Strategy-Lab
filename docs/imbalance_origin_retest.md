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
