# Photon supply and demand lesson options

These optional controls are in **Risk Execution → Photon — supply & demand
lesson**, visible for the mapping-only strategy and automated Photon strategy.
The mapping-only strategy continues to place no automatic trades. Zone
construction and evidence appear in its visualizer. Checked requirements also
filter automated zone-reversal entries, in both original and pullback modes.
They are not a new claim that candle patterns identify institutional orders.

The source lesson is *Master Institutional Supply and Demand Trading (ULTIMATE
STRATEGY GUIDE)*, supplied with a transcript in this task. Its zone construction
is discussed at 08:35–12:24, quality confluences at 12:24–16:09, entry approaches
at 16:13–16:39 and fixed-R exits at 16:48–17:11. Some checks are discretionary
in the lesson. The rules below are explicit, testable price-based interpretations.
No requirement is silently enabled just because the lesson discusses it.

## Zone construction

`execution.photon_zone_model` accepts:

| Value | Definition |
|---|---|
| `LEGACY` (default) | Existing last opposing-body candle in the originating swing leg, admitted only by a confirmed BOS / swing change. Full wick bounds. |
| `PIVOT` | One candle of either colour, followed immediately by a completed thrust candle closing above its high for demand or below its low for supply. |
| `PIVOT_TWO` | The union of the two preceding candles' full low/high bounds; the next completed candle must close outside that union. Either colour is allowed. |
| `RANGE` | A base of N consecutive completed candles with a common price overlap, followed by a completed departure close beyond the full base low/high. N is `photon_range_base_bars`, default 3, permitted 2–12. |

New-model zones become known at the departure close, not at the earlier origin.
Missing candles cannot form a base. There is no invented displacement threshold
or discretionary wick refinement. Choosing a new model replaces that model's
zone definitions; it does not combine duplicate legacy and lesson zones.
Own-timeframe close invalidation and data-gap retirement remain unchanged.

## Quality requirements and evidence

All requirements default to `false`. Absent or unknown required evidence fails
closed. Each zone's evidence is recorded at creation and at subsequent return
closes. Replay filters evidence by its knowledge time. The chart explains which
checks were observed and whether the selected requirements passed at that
recorded instant; it does not present that old snapshot as a current assessment.

| JSON execution field | Mechanical definition |
|---|---|
| `photon_fresh_zone_only` | Only the first return visit qualifies. Consecutive overlapping candles are one visit; leaving and returning creates another. A first mitigation is allowed; a second visit is rejected. |
| `photon_require_zone_bos` | The zone has a known same-direction swing BOS / trend change whose originating swing leg contains the zone origin. New pivot/range zones may acquire this evidence after birth, but not before that structural close. |
| `photon_require_flip` | Opposing same-timeframe supply/demand was previously touched, then invalidated by its own timeframe close during the new zone's initiation leg. A trend change alone is insufficient. This is an interaction/failure proxy, not a complete discretionary failed-lower-low / failed-higher-high pattern. |
| `photon_require_sweep` | The origin's wick bounds straddle the appropriate internal swing level already known before the origin: a low for demand, a high for supply. The departure then leaves the origin range. |
| `photon_require_inducement` | Before the return candle, an already known internal pivot formed after zone birth lies strictly between the zone's near edge and approaching price. Completed own-timeframe candles after the pivot must not already have swept it. This is a visible-liquidity proxy, not order-book evidence. |
| `photon_require_stacking` | An active, same-side zone on another timeframe strictly overlaps the zone in price. Either a higher or lower timeframe can supply the second zone; a Daily zone is not rejected merely because Weekly zones are not drawn. Boundary equality alone is not overlap. |
| `photon_require_zone_value` | The full demand box was below its own timeframe's known equilibrium at creation, or the full supply box above it. A zone straddling EQ or with unknown range fails. |
| `photon_require_4h_alignment` | The completed 4H swing trend agrees at the entry decision. |
| `photon_require_daily_alignment` | The completed Daily swing trend agrees at the entry decision. This is distinct from merely touching a Daily zone. |
| `photon_require_weekly_alignment` | The completed Weekly swing trend agrees at the entry decision. |
| `photon_require_15m_internal_alignment` | Completed 15m internal structure agrees at the entry decision. |

Non-trend quality requirements apply at the context touch before candidate
selection. Alignment requirements are checked at the confirmed entry decision.
Qualified trades save `lessonEvidence` and their required/optional checks in
`supply_demand_setup`. A selected timeframe or quality setting does not itself
convert the mapping-only strategy into an automated entry strategy.

## True fixed-R exits

Enable `execution.photon_fixed_target_enabled` and set
`execution.photon_fixed_target_r` (default 3). This is an exact price target:

- Long TP = actual entry + R × (actual entry − original SL).
- Short TP = actual entry − R × (original SL − actual entry).

The calculation uses the actual simulated fill, including entry slippage, not
the planned signal price. Exit costs mean realized net account R can be lower
than the configured gross price multiple. Stops stay at the chosen structural
level. Targets are recalculated at fill and saved with `targetMode=FIXED_R`.
This is different from `sd_minimum_r`, which only checks eligibility.

An exact fixed-R TP cannot coexist with the early 15m trend exit or holding
beyond TP. Selecting fixed-R in the GUI turns those two options off; selecting
either trend exit turns fixed-R off. JSON configurations combining them fail
validation before execution. Fixed R must meet the minimum reward/risk setting.

## Compatibility and limits

Legacy construction, all quality requirements off, and fixed-R off preserve
the historical algorithms. Defaults do not enforce all lesson factors at once.
The manual mapping view still supports manual simulated entries; the existing
automated confirmation models remain separate. Direct-at-zone limit and
reversal-candlestick automatic entry models are not added by these controls.
The automated zone-reversal model still uses its selected original/current
entry sequence, 4H value logic, structural stops and other existing constraints.
These settings do not establish profitability or reproduce every discretionary
zone in the video. Saved manifests include the chosen options for reproducibility.

## Lesson drawings on the chart

Use the mapping-only strategy, open **Strategy Visualizer**, and choose
**Candles + structure lines**. Expand **Supply / demand zones · layers and
inspection**, select a zone, and enable **Lesson drawings for selected zone**.
Use **Focus selected zone** to include its prices. Choose PIVOT, PIVOT_TWO or
RANGE in Risk Execution before generating a mapping run to inspect those bases.

The selected zone can show its pivot/range base, departure close, broken
structure level, liquidity sweep, liquidity ahead of the zone, failed opposing
zone, overlap on another timeframe, and first mitigation/subsequent return.
Only evidence actually found is drawn; a departure is not labelled a BOS.
The selected zone's lesson captions take priority over nearby-zone captions.
Replay hides evidence until its knowledge time. An origin before loaded candles
requires a run covering that earlier period for the full sequence.

This is a chart inspection aid. It neither enables automatic trades nor changes
the existing swing/BOS/CHoCH algorithm. Discretionary markings in the presentation
may still differ from these documented mechanical definitions.


## Compact chart workspace

Photon charts open with candles and structure lines, a compact timeframe trend
row, and a docked **Chart inspector**. Long explanations, zone selection, entry
checks and event inspection live in its **Details** tab. **Layers & labels**
controls presentation independently of the strategy settings. Only one of the
chart inspector and trade workspace is open at a time. On narrow screens the
inspector overlays the chart rather than squeezing its width.

- **Clean**: candles with the optional Photon overlays off.
- **Structure**: structure and break-level drawings, zones and recent BOS text.
- **Lesson**: structure, zones and selected-zone lesson drawings; opens Details
  so a zone can be chosen.
- **All details**: all label families and visible event history.

BOS text, internal CHoCH text, trend-change banners, swing names, and zone/EQ
text have separate switches. Text switches do not remove the underlying lines
or boxes. Break-level drawings and the unconfirmed leg have separate controls.
Recent density keeps up to three events of each type per displayed timeframe,
plus an explicitly selected event. Banner collisions can suppress a caption;
use Details to inspect its event text. Lesson captions retain priority.

**Chart only** closes both side panels and toggles the compact trend row.
Visibility choices are remembered in browser storage when available; they do
not edit a report, strategy configuration or trade calculation.
