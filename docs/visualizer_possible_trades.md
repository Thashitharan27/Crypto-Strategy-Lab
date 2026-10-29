# Possible trade ideas in structure replay

Open a Photon mapping-only or automated Photon run in the visualizer and start
**Structure replay** (or **Day replay** for an automated run). Keep the chart at
**15m**, or use 1m / 5m with complete 15m buckets. No new backtest is required.

**Possible trade alerts** watches the same loaded structure map. Choose a pattern,
long/short direction, whether to include early watches, and **Pause on new idea**.
The default pattern is supply/demand reaction. **Next possible setup** advances
the replay clock to the next matching observation; its price details are shown
only after that observation is available. At 1h or higher, switch to 15m or lower
to obtain these 15m candle observations.

| Pattern | What becomes known | Suggested stop |
| --- | --- | --- |
| Structure break | A closed 15m candle confirms BOS or a trend change. This is an early watch for a pullback, not a confirmed entry. | Originating zone boundary, or the known protected swing boundary. |
| Supply / demand reaction | A previously known 15m zone is touched; a later directional close beyond the touch candle upgrades the watch to a confirmed reaction. Returns expire after three hours. | Beyond the zone and the observed reaction extreme. |
| Sweep and reclaim | A wick crosses an internal or swing level known before that 15m candle, then closes back across it. This is a reclaim observation; inspect a later entry break/retest yourself. | Beyond the sweep wick. |

Both directions are supported. Stops include a minimum price epsilon or
**0.05 × the trailing 14-candle mean true range on 15m**, whichever is larger.
This replay suggestion buffer is separate from the automatic strategy's 1m ATR
stop setting. Entry begins as the observation candle close. TP prefers the 15m
midpoint if ahead of entry, otherwise a known 15m swing objective, 4H midpoint,
or 4H swing objective. The card names the chosen target and lists alternatives.
If no forward target or valid stop exists, it says so instead of inventing one.

The card explains opposing/unknown trends, a midpoint behind entry, less than
1R target room, wide stops, repeated/old zones, nearby opposing zones, and
estimated fee/slippage drag relative to stop risk. A confirmed reaction describes
a completed price event, not a recommendation, entry confirmation, or probability.
No 1m confirmation or alignment gate is required by this observation layer.

**Use as editable plan** copies the suggested SL/TP and the latest closed chart
candle's close as the draft entry. It does not fill a trade. Review and adjust
Entry, SL and TP, use the chart position tools if desired, and explicitly choose
**Confirm manual entry**. A candle in the review period must first be closed.
The normal manual-replay validation and position locking still apply. A plan
with no valid levels or one whose stop, target, or source zone has already been
crossed is marked unusable; you can still create your own separate manual plan.

**Skip this idea** records only that idea as skipped and does not close a
position or skip other ideas. Copied suggestions and skip decisions retain
their replay timestamps and frozen evidence. **Export reviews** includes
`opportunityDecisions`; review records include `opportunityOrigins` when an idea
was copied. Save/export before closing if browser storage is unavailable.

Observations are indexed from completed 15m candles. Creation times, completed
snapshots and zone lifecycle clocks determine what is known. Future zone
invalidation never removes an earlier observation. Rewinding hides future ideas;
expiration checks use only subsequent candles already closed at the current
clock. Original trades, strategies, backtest outputs and exchange orders are
unchanged. Multiple observations can describe one market move; counts are not
counts of independent trades. This tool performs no profitability selection.
