# 15m candle pullback to previous low / high

Select **Photon — Automated Trades / 1m Confirmation** and enable
**4H trend → 15m pullback → first red short / first green long; TP previous low / high**
in **Risk Execution → Supply & demand retest**. This option takes precedence over
older Photon entry-model checkboxes. Run on actual 1m strategy data; decisions
use completed 15m candles.

## Rules

- **Short:** confirmed bearish 4H trend; at least one closed green 15m pullback
  candle; enter after the **first closed red 15m candle**.
- **Long:** confirmed bullish 4H trend; at least one closed red 15m pullback
  candle; enter after the **first closed green 15m candle**.
- A fresh 15m swing trend change, 15m swing alignment, and 1m CHoCH are not
  required. The completed candle-colour return is the trigger.
- Fill at the next 1m open, including configured slippage and costs. No supply /
  demand touch, lower-high filter, or 1m structure change is required.
- Freeze TP at the last known swing range low (short) or high (long), from the
  selected **Previous low / high timeframe**, before the first pullback candle
  opened. Default is 15m; 4H is available as a separate comparison. Later swing
  changes do not move that target.
- SL is beyond the entire observed 15m pullback extreme, including the trigger
  candle, plus the configured **1m ATR** buffer (default 0.05 ATR).
- A doji never triggers. Cancel on missing/stale 4H context, data gaps, lost
  4H alignment, expiry, or a later pullback candle reaching the frozen TP before
  entry. The selected target must be known when arming the pullback. The first
  matching-colour close consumes the pullback even when geometry or the optional
  R filter rejects it; later same-colour candles do not retry it.
- Skip when the frozen target is not ahead of entry, or the actual next-open
  fill is at/beyond TP or SL. Minimum-R filtering is **off by default**; enable
  the separate checkbox to apply the existing minimum reward/risk setting.
- Exit at the frozen TP or SL. Older Photon fixed-R, midpoint, and trend-hold
  settings do not override this mode. Existing profile market permissions and
  the engine's one-position-at-a-time rule still apply.

A red/green candle is confirmed only at its close. Historical tests therefore
enter at the next 1m open rather than during a forming candle. SL includes only
pullback/trigger extremes known by that close; a higher/lower wick from a later
candle cannot be included retroactively.

## Historical runs and rule version

New setups save `entryRule: FIRST_COLOUR_RETURN` and `entryRuleVersion: 2`.
Completed runs made before this update retain their original swing-change
entries. Rerun the backtest to obtain the earlier colour-return entries. The
visualizer labels old records as historical swing-change triggers and new ones
as first red/green close confirmation; neither is labelled 1m CHoCH or a supply /
demand entry zone. The shaded area is the observed 15m pullback range.

The reported 1 June 2026 example now confirms the 17:30–17:45 UTC red candle
and becomes eligible at 17:45, instead of waiting for the 19:15 swing change.
Its stop boundary is the then-known 71,761.1 high, not the later 71,788.5 high.
Actual portfolio fills remain subject to existing one-position-at-a-time,
entry-window, price geometry, and optional minimum-R rules.

Ready-to-load presets, both enabling bullish and bearish trades:

- `Photon_15m_Candle_Pullback_15m_Target_1m.json`
- `Photon_15m_Candle_Pullback_4H_Target_1m.json`

Restart the application and reopen the visualizer after updating. Saved setup
metadata includes the frozen target's known time, pullback start, candle-colour confirmation,
trigger OHLC, planned R, SL source and selected target timeframe. These are
backtest rules; they do not send exchange orders.
