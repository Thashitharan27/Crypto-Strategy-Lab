# Confluence: sweep, structure, inverse FVG and retracement

Select **Confluence - Sweep + Structure + IFVG + FVG** under Signal strategy. This is a mechanical research interpretation of the five concepts discussed in TJR's [Learn Every Trading Confluence in 18 Minutes](https://www.youtube.com/watch?v=TYbpk7WogHI), not a reproduction of a fully specified discretionary system or a profitability claim.

## Default sequence

1. Confirm a swing with two completed candles on each side. On a later candle, price must strictly cross that swing and close back across it: sweep a low and reclaim for long; sweep a high and reclaim for short. Use the latest intact confirmed swing within the configured lookback. Sweep penetration must be at least the configured minimum depth (default 0.1 ATR measured using ATR at the sweep close; 0 disables this minimum). A crossed level is consumed, preventing repeated entries from the same old liquidity.
2. Freeze the most recent intact opposing swing as the structure level and the most recent still-valid opposing FVG at the sweep. A later close must cross the structure level. A later close beyond the far edge of the opposing FVG confirms its inversion. These confirmations may occur on the same completed candle.
3. Identify a fresh FVG in the trade direction with all three candles starting at or after the sweep. Bullish: candle 3 low is above candle 1 high; bearish: candle 3 high is below candle 1 low. The middle candle must move in the trade direction with body at least 0.5 ATR. Use the latest qualifying gap; previously broken candidates cannot be reused.
4. Once the confirmations are ready, freeze the range from the sweep extreme to the most favorable extreme reached so far. Its midpoint is equilibrium. The FVG must have nonzero overlap below that midpoint for long or above it for short. This overlap is the qualifying entry area. Later extensions do not move the frozen midpoint.
5. On a later candle, price must touch that overlap, form a candle in the trade direction, and close in the correct half of the range. Its body must be at least 50% of its full range by default. Signal only after that candle closes. Enter at the next candle open with configured slippage; reject a gap fill outside the correct half or with invalid stop geometry.

SL is beyond the sweep extreme by the configured stop buffer times ATR frozen at the sweep. Default final target is 3 times actual entry-to-SL distance, adjustable. Existing Minimum reward / risk applies to that target. Position sizing uses the actual stop. There is no session restriction or automatic daily timeout in this preset. The next-open rule is strategy-owned. Other optional generic partial/BE/trailing settings do not change this strategy's native plan.

## Settings

The Risk / Execution panel includes require-structure, require-inverse-FVG and require-equilibrium checkboxes, all on by default. Sweep/reclaim and the fresh FVG retest always remain required. Other controls: swing strength (shared), stop buffer (shared), minimum R (shared), FVG middle-candle displacement, maximum candles from sweep (30), swing/opposing-FVG lookback (64), reversal body percentage (50), and target R (3). A zero reversal body percentage disables only the percentage check; the candle must still be directional and have a positive range.

Setups expire after the maximum wait measured from the sweep, or if price retouches/breaches the sweep extreme. Once armed, a close through the wrong edge of the entry FVG invalidates the setup. Gaps or invalid OHLC reset state. Simultaneous opposing sweeps or confirmations are not resolved using an assumed intrabar path. Pivot confirmations and FVGs never appear before their confirming candles have closed.

## Review and limits

Saved `supply_demand_setup` snapshots include the swept level and its origin, sweep extreme/time and ATR, frozen structure, opposing/inverted FVG and inversion time, entry FVG, confirmation times, frozen range and equilibrium, reversal body percentage, actual SL and final target. The visualizer displays FVG bands and liquidity/structure/midpoint lines with hover prices, plus details in the setup panel.

Strictly requiring every confluence can produce few signals. Disabling a checkbox changes the tested strategy; compare settings on separate data, rather than treating extra confirmations as proof of an advantage. Stops and structure are operational definitions based on candles, not direct observations of resting exchange orders. Target, stop buffer, confirmation rules and expiry are explicit research choices added because the video does not fully specify execution.


## Keeping confirmations valid until entry

**Cancel if confirmed structure / IFVG fails before entry** defaults on. After an upward structure break, a later completed close strictly below the frozen structure level permanently cancels the pending long; reverse for shorts. After a bearish FVG is inverted upward, a completed close below its lower edge cancels the long; after a bullish FVG is inverted downward, a close above its upper edge cancels the short. Equality holds. Only confirmations whose require-checkbox is enabled are enforced, and unconfirmed levels do not cancel a setup. The actual next-open fill, including slippage, is checked against these same boundaries, preventing an overnight/candle gap from bypassing confirmation validity.

This is deliberately strict: ordinary pullbacks across the old structure level are also rejected, even when the entry FVG still holds. The cancellation is permanent; a later recovery does not revive the same sweep setup. Stop, target and sizing rules after entry remain unchanged. To reproduce the previous confirmation/depth behaviour, turn this checkbox off and set **Minimum sweep depth** to **0**. New defaults also apply when an older configuration omits these settings; completed saved-run results are not changed.

The signal audit on `BTCUSDT_15m_d96c3bd4bbee456c913e031b34a3bb71` reproduced its three original signal times with the previous rules. Enabling strict validity removed all three, including the winner. This was a signal comparison, not a portfolio rerun or evidence of better profitability. Filtering can also select a different qualifying sweep at the same eventual signal time, so matching timestamps alone do not prove identical trades.
