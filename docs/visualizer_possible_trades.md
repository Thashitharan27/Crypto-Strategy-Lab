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

## Signal quality score

Each idea shows **Signal quality at detection · 0–100** and a **Why this score?**
breakdown. The fixed `STRUCTURE_QUALITY_V1` checklist awards:

| Evidence | Maximum points |
| --- | ---: |
| 4H alignment | 15 |
| 15m alignment | 10 |
| Daily alignment | 3 |
| Weekly alignment | 2 |
| Completed 15m reaction / reclaim | 15 |
| Known aligned 1m internal structure | 5 |
| Target room | 20 |
| Zone freshness | 10 |
| 15m premium / discount location | 10 |
| Clear path before known opposing 15m zones | 5 |
| Estimated fees / slippage relative to stop risk | 5 |

A completed zone reaction earns 15 confirmation points; a completed reclaim earns
12; an early watch earns zero. Room earns 20 at >=2R, 15 at >=1.5R, 10 at >=1R,
otherwise zero. A known zone on its first visit or unvisited, <=24 hours old,
earns 10; other known zones earn 5. Cost estimates <=10% of stop risk earn 5,
above 10% but below 20% earn 3; otherwise zero. Unknown evidence earns no points.
Premium/discount includes the midpoint. Path points require a known forward
target with no active opposing 15m zone before or at it.

The score is capped at 59 for early watches, opposing 4H/15m trends, costs >=20%
of stop risk, or stops wider than 3 x 15m ATR. Less than 1R target room caps it at
39. Missing/invalid entry-SL-TP geometry forces zero. The breakdown shows all
applicable ceilings. Labels are Strong (80–100), Moderate (60–79), Weak (40–59),
and Low (0–39); incomplete geometry is labelled Incomplete.

Scores are frozen using evidence known at the observation's timestamp, and
exported with the idea and its breakdown. An expired idea retains its original
score and is explicitly labelled expired. Copying or editing a manual plan does
not change the original signal score. This is a manually chosen evidence rubric,
not a calibrated win probability, profit forecast, outcome-fitted model, or an
automatic entry gate. Entry and Skip remain your decisions.
