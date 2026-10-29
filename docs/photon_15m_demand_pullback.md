# Photon 15m demand pullback (test option)

Load `config/data_lake/Photon_15m_Demand_Pullback_1m.json`, or select
**Photon — Automated Trades / 1m Confirmation** and enable the long demand
pullback option in **Risk Execution → Supply & demand retest**. Restart the
application after updating code so the new control is loaded. Use actual 1m
strategy candles. The mapping-only Photon strategy continues to map only.

- Require the latest completed 4H swing trend to be bullish.
- Arm on a fresh confirmed bullish 15m swing trend change; existing alignment
  alone does not arm a campaign.
- Wait for a later candle to touch an active, previously confirmed 15m demand
  zone. Use the newest eligible zone if several overlap.
- If 1m internal structure becomes bearish during the pullback, require its
  later change back to bullish and a close above demand. If it remains bullish,
  require a later close above both demand and the touch candle's high.
- Enter at the next 1m open. Freeze TP at the **15m swing range midpoint (50%)**
  known at confirmation. Place SL below the touched demand zone's lower wick
  boundary by the configured 1m ATR buffer (default 0.05 ATR).
- Apply the configured minimum reward/risk (default 1R) at confirmation and
  actual fill including slippage. Reject fills at/beyond SL or TP.
- One signal attempt per 15m change. Cancel an unfinished setup on opposing or
  unknown 4H/15m trend, stale context, zone retirement/invalidation, a price wick
  below the demand boundary after touch, a data gap, or confirmation expiry.

This option takes precedence over the older Photon entry-model checkboxes.
Older fixed-R and trend-hold exits do not override its midpoint TP. There are no
short entries. It uses the app's existing close-confirmed Photon swing, internal
structure, and mechanical full-wick demand definitions. It is a backtest option;
no exchange orders are submitted. Sequence and engine tests validate behavior,
but do not establish profitability.
