# Photon: 4H trend with 1m confirmation

Select **Photon — 4H Trend / 1m Confirmation**, or load
`config/data_lake/Photon_4H_Trend_1m.json`. This is a separate backtest strategy;
the existing mapping-only strategy remains available. Selecting it sets the
primary candles to actual 1m data. Completed 15m, 4H, daily and Monday-based
weekly candles are derived from those minutes, using UTC boundaries. Missing
minutes retire zones and pending setups rather than bridging the gap.

## Entry sequence

1. Wait for a known, confirmed 4H swing trend. Longs require bullish 4H;
   shorts require bearish 4H. Daily and weekly provide saved narrative context,
   without requiring all four timeframes to point the same way.
2. Observe a later reaction into an already known 4H or 15m demand zone in
   4H discount for longs, or supply in 4H premium for shorts.
3. Subsequently confirm aligned 15m structure (BOS, swing change, or CHoCH
   with the 15m swing already aligned). An opposing-swing CHoCH alone does not
   establish the new swing trend.
4. Wait for a subsequent pullback into known 15m demand/supply within the
   discount/premium half of both current 4H and 15m ranges.
5. Wait for a subsequent directional 1m CHoCH. Select the last opposing-body
   candle from the internal reaction extreme to the break, excluding the break
   candle. The confirming close must depart that candle's full wick range.
6. Arm a limit at that 1m origin's proximal edge: high for demand, low for
   supply. Only a later minute can fill it. Skip if this entry is outside either
   value half or fails the minimum reward/risk requirement.

Shorts mirror longs. The existing lesson-derived mapping controls reference
levels: an eligible swing continuation needs a body close through its level;
internal wick breaks signal CHoCH, and protected-swing breaks change swing
direction. A wick touching the protected boundary cancels a trade setup
conservatively; this cancellation does not itself assert a trend reversal.

## Stops, targets and simulation

The stop is beyond the most adverse 1m reaction extreme since the 15m zone
touch, also covering the entry-origin wick, plus a configurable 1m ATR buffer.
The default buffer is **0.05 ATR**, and minimum gross reward/risk is **1R**.
The default target is the latest confirmed 15m swing extreme, frozen when the
order is armed. An optional setting instead selects the confirmed 4H extreme.
There are no automatic partial exits, break-even moves or trailing stops in
this first version, even if inherited profile settings enable them.

Context confirmation expires after **1,440 minutes**, and the armed origin
retest after **60 minutes**. Unknown/stale context, a changed 4H direction,
breached 4H protection, lost 15m alignment, invalidated parent/context zone,
data gap, or target reached before entry cancels the relevant pending setup.
One order is allowed per 15m zone; a rejected, expired or consumed first order
does not repeatedly re-arm that zone. Orders cannot fill outside the run's
entry window or while another trade is active.

An opening gap beyond the stop invalidates the order without a fill. Otherwise
a crossed limit receives opening-price improvement before configured slippage.
The shared account-risk sizing, leverage limits, fees and slippage apply. The
preset keeps the account defaults (1% risk per trade, 0.05% taker fee, 0.02%
maker fee and 0.05% slippage); the account controls remain editable. Entry-minute
stops count, while entry-minute profits are deferred because 1m OHLC cannot
establish whether the favorable extreme preceded the limit fill. Stop and
target remain fixed; an open position is closed at the backtest's end as usual.

## Reviewing a trade

The chart's setup details show the saved 4H reaction, 15m alignment, subsequent
zone touch, 1m CHoCH, origin limit, stop and target. The overlay includes the
saved 4H/15m range bounds and 50% midpoints. Evidence is frozen at the decision;
later candles cannot rewrite it.

The same chart also includes the full 4H/15m structure overlay, BOS/CHoCH levels,
developing legs, weekly/daily narrative and zone inspector, even for zero-trade
runs. It defaults to candles plus structure lines; the View selector also offers
lines alone. Trading charts derive structure from the engine's actual 1m source
and identical warmup boundary, rather than independently seeding a longer 15m
history. The mapping-only strategy retains its own analysis history and controls.

The sequence follows the supplied walkthroughs, adapted to crypto data. The
last-opposing-candle zone selection, strict simultaneous value filters, expiry
times, ATR buffer, minimum R and single-target execution are explicit mechanical
research choices, rather than numerical rules claimed to come from the presenter.
No profitability tuning or live exchange execution is included.
