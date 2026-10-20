# Reject EMA 100 inside the profit box

For either FVG strategy, open **Risk & Execution → Profit Target** and enable
**Reject trades with EMA 100 between entry and TP**. Save the configuration and
run a new backtest. The option is off by default.

The filter compares EMA 100 from the last completed strategy candle with the
inclusive price interval between the actual planned entry and final TP. On the
15m strategy this is the 15m EMA 100, not a 1m EMA. It uses no future candle data.

Longs and shorts are rejected when EMA is inside the box or on either boundary.
EMA above or below the entire box is allowed. Missing EMA values reject the setup
while the option is enabled. Rejection reasons are `FVG_EMA100_INSIDE_TP_BOX` or
`FVG_EMA100_UNAVAILABLE` in the saved signal decisions.

The check runs after directional confirmation, stop validation and target
selection. It includes entry slippage and supports fixed-R, opposing-HTF targets
and the fixed-R fallback. It checks the actual TP, not the swing extreme used
for the fixed-R room check. It does not predict later EMA movement or check
whether the EMA crosses the box during the trade.
