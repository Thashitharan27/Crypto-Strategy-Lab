# Photon Market Structure — Structure, Premium/Discount and Supply/Demand

**Rule basis:** the chart uses weekly/daily context and close-confirmed swing
breaks without a preceding internal CHoCH requirement on any timeframe. See
[the reference sequences and rule audit](photon_presenter_reference.md) for the
source lesson relationships. Meaningful swing size and zone boundaries use the
explicit mechanical interpretations documented below.

The saved strategy retains its **Parts 1 & 2** name for compatibility. It now
also includes the rules-based mapping tools from the supplied **Premium vs
Discount** lesson. The purpose is applying these rules to crypto; matching the
presenter's exact FX feed or chart markings is not a prerequisite.

## Premium / discount and supply / demand

Each known swing range has a midpoint **EQ = (high + low) / 2**. The context
strip reports the latest known 15m close relative to each timeframe's own
range: discount below EQ, premium above EQ, and EQ at equality. Prices outside
an endpoint are explicitly labelled above/below range. Initial unknown ranges
and stale/missing states remain unknown. These relative locations are not
fundamental valuation or entry signals.

**Premium / discount** shades the selected **4H**, **15m** or **daily** current
range and draws its EQ. Only one range is shaded at a time to keep the chart
readable; the strip keeps the other timeframe locations visible. The shaded
range is a current replay-time reference, not a claim that its final endpoint
was already known throughout its history. Developing run endpoints and
pullback candidates are labelled separately. Range snapshots retain their
knowledge times, so future highs/lows cannot affect earlier replay cutoffs.

**Supply / demand zones** provides independent daily, 4H and 15m switches. The
default overlay shows up to two nearby supply and two nearby demand zones per
enabled timeframe, ordered by distance from the current known price. Daily
zones retain their source identity on the 15m chart. Boxes do not change the
main chart's price scale. Expand the panel and choose a zone to inspect its
origin, structural confirmation, full price bounds, creation/current EQ
location, visits and invalidation. Selecting an older ended zone also allows
explicit inspection; **Include ended zones** adds ended references to the
nearby display. The summary distinguishes nearby zones from those actually in
the visible price/time window. **Focus selected zone** explicitly fits the
zone and visible candles; ordinary zone rendering leaves the price scale
unchanged. Ended zones can also center their historical lifetime, when it is
inside loaded main-chart history. **Reset price** restores normal scaling.
Weekly remains narrative/range context; M1 execution is absent.

### Explicit zone rules

- Only a **close-confirmed BOS or swing change** creates a candidate zone.
  CHoCH alone does not manufacture a supply/demand box.
- Search the originating swing leg from its newly confirmed protected point
  up to, but excluding, the breaking candle. Use the last candle whose **body
  opposes the break direction**: bearish for demand, bullish for supply.
  This candle-colour choice defines zone origins only; structure breaks still
  ignore candle colour. Dojis are not opposing candles.
- Bound the box by that candle's **full low/high wicks**. The breaking close
  must have departed beyond the far side of the origin candle in its break
  direction. Missing origins, zero-width boxes and non-departures create no
  zone. Reusing the same origin for another BOS does not create a fresh copy.
- The box becomes known at the structural breaking candle's close, even
  though its left anchor is the earlier origin. Its creation candle cannot
  retrospectively count as a return visit.
- **Fresh** means no return since creation. A completed canonical **15m**
  candle overlapping either edge or the interior records a **touch**, even for
  a daily/4H zone. Consecutive overlapping candles are one visit; a later
  return after leaving records another. A touch is not an automatic entry or
  a guarantee that all orders in a zone were filled.
- Demand invalidates only on its **own timeframe close below its lower wick**;
  supply invalidates on an own-timeframe close above its upper wick. Equality
  is not invalidation. A lower-timeframe close through a daily zone is not a
  daily invalidation. Wick sweeps alone do not invalidate it.
- A canonical data gap **retires** existing zones with a distinct reason;
  retirement is not a claim that price invalidated them. Ended zones do not
  resurrect on later reactions.

The last-opposing-candle definition is the agreed initial mechanical
interpretation, not a complete supply/demand methodology. It does not infer
every decision zone, opposing-zone failure or liquidity sweep discussed in the
lesson. Premium/discount is descriptive context: valid structural events are
retained in either half, and no premium/discount condition opens or vetoes a
trade. A pullback touching discount is distinct from a later bullish CHoCH
confirmation occurring above EQ. FX pip stops and advertised reward multiples
are not transferred into crypto settings.

Select **Photon Market Structure — Parts 1 & 2 (mapping only)** in Strategy
Builder, or load `config/data_lake/Photon_Structure_Parts_1_2.json`. Use a 15m
dataset, choose a historical period, run the analysis, then open **Strategy
Visualizer**. The structure overlay opens automatically. Use Structure replay to
advance candle by candle; weekly, daily, 4H and 15m share the replay clock.

The context strip sits above the main chart. Each timeframe has its own swing
direction, internal phase and qualified relationship to its parent. Opposing
directions mean a **possible** parent pullback, never a forced trend reversal.
Unknown structure stays unknown. Expand **Weekly / daily context** for the
larger structure on a separate price scale; its shaded interval follows the
main chart window. Click a period within the loaded main-chart history to
inspect it. Earlier context remains visible but requires a run covering that
period for detailed 4H/15m inspection.

**Inspect event** offers the last 80 known BOS/CHoCH events on the selected
timeframe. The explanation identifies the wick/close rule, level price, origin
time and knowledge time. Selecting a 4H/15m event centers and highlights it
when it lies in loaded chart history. **Next structure event** advances an
active structure replay to the next known-by-then event across UTC day boundaries.
It does not preview future event names, directions or prices.
**Next candle**, **Play**, and event stepping continue until the loaded history
ends. The date follows the latest revealed candle; previous/next day and the
date picker remain navigation shortcuts. **Restart replay** returns to the
chosen starting day, and **Reveal remaining history** reveals through the loaded
history end. Other strategies retain their day-bounded manual trading review.

The **View** selector offers **Candles**, **Structure lines**, and **Candles +
structure lines**. Photon opens in **Structure lines** with both traces overlaid
on one price/time chart: **white for 4H**, **blue for 15m**. Both histories stay
visible together when scrolling or replaying. **Break levels** optionally adds
BOS/CHoCH, protected-range and internal references; it defaults on for study.
The line view hides the candles
and grid for a diagram-like display, fitting the loaded period so larger swings
are visible. Zoom remains available and the replay position is preserved.
Each solid line connects **BOS-confirmed swing points only**, independently on
its own timeframe. Internal CHoCH remains phase evidence and is neither required
for a swing break nor sufficient to add a solid point. On an upward swing break, the broken high and the lowest pullback point
that produced the break become confirmed anchors. On a downward break, the
broken low and the highest pullback point become confirmed anchors. Opposite
swing breaks confirm a trend change under the same close rule. Internal CHoCH
does not add solid swing anchors.

Consecutive same-direction closing breaks extend the run from its existing
protected origin; the breaking candle's opposite wick is not automatically a
new HL/LH. An intervening candle between the run extreme and break allows the
existing pullback-origin search. If a continuation candle crosses both swing
boundaries, matching complete lower-timeframe candles must establish the order
of its high and low before a new opposite origin is admitted. Missing or
same-child extreme ordering retains the protected origin and records ambiguity.
Ordered child extreme times are used for geometry; confirmation remains at the
parent close. This applies to both directions in the shared mapping function.

**Unconfirmed leg (dashed)** defaults on. It shows the developing run extreme
and subsequent reaction to the latest completed candle, rather than one direct
line from the last anchor to the latest close. It remains provisional.
Hover a solid swing dot to see the BOS confirmation time, not the earlier date
at which its candidate pivot formed. Historical raw-pivot traces are ignored.

Each path uses only events known at the current replay clock. Consecutive same-
side points simplify to the more extreme point; data gaps split the paths.
Two genuine opposing swing origins sharing a candle retain both confirmed price
levels at that timestamp, with a short dashed vertical connector to indicate
unknown intrabar order. They do not erase adjacent history. Only a real missing
candle or invalid data resets/splits the history. This display
preserves the no-entry gate.

This is structure analysis, not an entry strategy. The engine refuses entries
and direct pair opening in this mode, regardless of Entry/Veto/Flip rules or
market permissions. No M1 execution, supply/demand entry zones, stops, targets,
or profitability claims are included. Other strategy configurations are unchanged.

## Rules taken from the lessons

- Map structure from wick extremes. A swing break requires a strict candle close
  beyond its level on that timeframe. Equality is a touch, not a break.
- A single opposite swing break changes the swing direction. A continuation
  break confirms the originating swing point: the lowest point since the broken
  high for an upward break, or the highest point since the broken low for a
  downward break. It becomes the strong/protected side of the range.
- Internal CHoCH uses strict wick penetration of the opposing internal point.
  Candle colour is irrelevant. Inside bars can start a counter run.
- Distinguish swing direction from internal direction. Internal disagreement is
  a possible pullback; realignment is a possible continuation. Neither predicts
  that a future swing break will occur.
- Map 4H and 15m independently. Their disagreement is a possible 4H pullback,
  not an automatic 4H reversal. A pullback can happen without a 15m swing trend
  change. No forced one-to-one match exists between HTF CHoCH and LTF BOS.

## Explicit implementation choices

The pullback-origin search starts strictly after the broken pivot's candle.
This is an implementation convention, not a general rule established by the
videos. The opposite wick's chronological relationship to the pivot extreme
can require intrabar evidence; excluding it universally remains unvalidated.

The videos do not mechanically define a meaningful swing pullback. The chart
now uses `CHOCH_PULLBACK`: observed candle runs establish internal references;
a counter-direction CHoCH makes the current weak run extreme eligible for a
subsequent swing break. Eligibility is **not** BOS confirmation. Initial range
levels come from observed internal runs; initial swing direction remains
unknown until a close breaks that range. This removes fixed two-bar pivot
qualification from the chart. The legacy `map_structure` default retains
`PIVOT` qualification for existing direct callers and comparison tests.

This event-based qualification is still an interpretation: some internal
reactions may be smaller than the presenter would accept as swing pullbacks.
It must not be described as an exact mechanical reproduction. Developing
extremes are separate from BOS-confirmed protected points and solid anchors.

Internal turning points follow runs of candles extending the previous candle's
high/low. Failure to extend starts the opposing run. A candle extending both
ends of the previous candle has unknown intrabar order, so does not update the
internal run. A candle crossing both internal reference levels emits an
ambiguity record instead of assigning a CHoCH direction. The new model clears
internal direction until another unambiguous break. Penetrated internal levels
are retired even during continuation, preventing an old already-broken level
from falsely making a later opposite break ambiguous.

The 4H candles are built from **all sixteen consecutive 15m candles**, using UTC
boundaries. Partial, duplicate, invalid and gapped buckets are excluded. A 4H
snapshot becomes available only at the 4H close. Structure resets after a data
gap; stale protected levels are not carried across it. The visualizer uses up
to 730 calendar days of preceding canonical 15m history for daily/weekly
context, subject to available canonical coverage. Daily buckets start at UTC
midnight; weekly buckets start Monday 00:00 UTC and require all 672 consecutive
15m candles. No partial week or day is exposed. The detailed 4H/15m maps and
main chart retain 60 days of preceding history, so adding weekly/daily context
does not compress the main chart to two years. That detail history is included
in the Photon chart so both historical traces
have a visible timeline, even for a short selected analysis period. Other
strategies keep their normal selected-period chart bounds.

The display provides per-timeframe direction, internal phase, strong/weak range
levels, HH/HL/LH/LL (and equal-point) labels, BOS, trend changes and CHoCH.
All replay display is filtered by confirmation time, not by the origin time of
a pivot. A blank/unknown state means insufficient confirmed structure.

## Validation

`tests/test_photon_structure.py` checks every historical prefix against the full
result, including completed 4H aggregation, wick versus close rules, gaps,
bull/bear symmetry, strategy persistence, visualizer source loading and the
hard no-entry gate. Chart computation is independent of trade outcomes.

`tests/test_photon_presenter_sequences.py` adds authored, normalized OHLC
scenarios for the reference event relationships: inside-bar reaction versus
CHoCH, wick-only CHoCH before swing change, failed continuation, causal replay,
developing extremes, independent narrative and complete daily/weekly buckets.
These are **not extracted video candles** and cannot prove source-feed matches.

`tests/test_photon_value_areas.py` checks independent range math, snapshot
knowledge times, origin selection, birth visibility, return-visit counting,
own-timeframe invalidation versus 15m touches, wick/equality cases, data-gap
retirement, price symmetry, nearby selection and complete prefix equivalence
of the added zone/lifecycle payloads. Tests do not measure trading performance.
