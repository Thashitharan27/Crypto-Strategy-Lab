# Higher-timeframe FVG take profit

For Fair Value Gap or Fair Value Gap — Six Factors, open **Risk & Execution →
Take Profit** and set **FVG Target Method → Opposing Higher-Timeframe FVG**.
Select a target timeframe (1 hour, 4 hours or 1 day), a minimum target reward/risk,
and a policy for when no opposing FVG exists. The default target mode remains
Fixed R; existing saved configurations retain their behavior.

The new mode identifies gaps using three consecutive, complete higher-timeframe
candles, constructed from the strategy candles. The higher timeframe must be
larger than and an exact multiple of the strategy timeframe. A gap becomes
available only when its third candle closes. A wick touch consumes it; a gap
through it invalidates it. Incomplete source buckets do not create a gap.

- Long: choose the nearest untouched bearish FVG entirely above entry and put TP
  below its lower edge by the configured signal-ATR buffer.
- Short: choose the nearest untouched bullish FVG entirely below entry and put
  TP above its upper edge by that buffer.

Selection uses the actual entry price, including confirmation and slippage.
Zones touched during the confirmation window are already consumed. A target
inside an opposing zone, or nearer than the minimum reward/risk, rejects the
trade. It does not search past a nearer obstacle to obtain a larger R target.

Minimum R is the gross price distance to TP divided by the actual stop distance;
fees and exit slippage reduce realized net R. The chosen target stays fixed
throughout the trade. It replaces the fixed-R/swing-extreme target calculation;
the original swing extreme is not an additional cap in this mode.

If there is no opposing target zone, **Skip Trade** rejects the setup.
**Use Fixed R With Swing-Room Check** instead applies the existing fixed-R rule
and its original swing-room requirement. This fallback does not bypass an
opposing gap that is too close or contains the entry.
The fixed-R fallback must also meet the selected minimum reward/risk.

Run a new backtest after selecting the mode. Completed trades record the target
mode and exact chosen zone in `fvg_target_htf_zone`, including its boundaries,
timeframe and confirmation time. Six-factor visualizer setup details show this
zone as a purple target band. The existing TP line, trade box and replay use
the recorded actual target.

This mode does not require enabling the separate higher-timeframe entry-context
filter. It neither changes that filter nor waits for a new gap after entry.
