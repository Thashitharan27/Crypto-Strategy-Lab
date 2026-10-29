# 15m candle pullback to previous low / high

Select **Photon — Automated Trades / 1m Confirmation** and enable
**4H trend → 15m pullback / trend change → red short or green long; TP previous low / high**
in **Risk Execution → Supply & demand retest**. This option takes precedence over
older Photon entry-model checkboxes. Run on actual 1m strategy data; decisions
use completed 15m candles.

## Rules

- **Short:** confirmed bearish 4H trend; at least one closed green 15m pullback
  candle; a fresh confirmed bearish 15m swing trend change; a closed red 15m
  trigger candle. The change candle qualifies when red, otherwise wait for the
  first later red candle while the 15m swing remains bearish.
- **Long:** confirmed bullish 4H trend; closed red 15m pullback; fresh confirmed
  bullish 15m swing trend change; closed green 15m trigger candle.
- Fill at the next 1m open, including configured slippage and costs. No supply /
  demand touch, lower-high filter, or 1m structure change is required.
- Freeze TP at the last known swing range low (short) or high (long), from the
  selected **Previous low / high timeframe**, before the first pullback candle
  opened. Default is 15m; 4H is available as a separate comparison. Later swing
  changes do not move that target.
- SL is beyond the entire observed 15m pullback extreme, including the trigger
  candle, plus the configured **1m ATR** buffer (default 0.05 ATR).
- A doji never triggers. Cancel on missing/stale 4H/15m context, data gaps, lost
  4H alignment, an opposing 15m change after confirmation, expiry, or a later
  pullback candle reaching the frozen TP before entry. One attempt per pullback.
- Skip when the frozen target is not ahead of entry, or the actual next-open
  fill is at/beyond TP or SL. Minimum-R filtering is **off by default**; enable
  the separate checkbox to apply the existing minimum reward/risk setting.
- Exit at the frozen TP or SL. Older Photon fixed-R, midpoint, and trend-hold
  settings do not override this mode. Existing profile market permissions and
  the engine's one-position-at-a-time rule still apply.

A swing trend change means the chart's confirmed `TREND_CHANGE` event, not an
internal CHoCH or a candle-colour change alone. A red/green candle is confirmed
only at its close, so historical tests do not enter on an unconfirmed colour.
A fresh 15m trend change may occur after the old 15m low/high has already been
broken; that setup is correctly skipped rather than moving TP to a future low.
Use the 4H target choice to test the broader level definition explicitly.

Ready-to-load presets, both enabling bullish and bearish trades:

- `Photon_15m_Candle_Pullback_15m_Target_1m.json`
- `Photon_15m_Candle_Pullback_4H_Target_1m.json`

Restart the application and reopen the visualizer after updating. Saved setup
metadata includes the frozen target's known time, pullback start, 15m change,
trigger OHLC, planned R, SL source and selected target timeframe. These are
backtest rules; they do not send exchange orders.
