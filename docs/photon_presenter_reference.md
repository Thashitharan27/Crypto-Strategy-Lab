# Photon presenter reference and implementation audit

## Scope and evidence

This is the reference for reproducing the presenter's reading, before changing
the mapping algorithm again. It records narrated events from both supplied
transcripts, checked against selected frames of the local videos. It is not a
claim of full audiovisual or candle-by-candle OHLC verification. All times below
are **video times**, not market timestamps. No prices or candle timestamps have
been inferred from unreadable chart text.

The objective is historical structure analysis, with no entries: preserve the
larger swing, smaller swings inside it, internal phase changes, and the evidence
available at each replay cutoff. Matching an attractive zigzag is insufficient.

## Part 1: single-timeframe replay, 31:25–34:12

The chart is EURUSD on 4H. A/B/C below name structural references, not prices.

| Video time | Observation / reference event | State knowable then | Confirmation still missing |
| --- | --- | --- | --- |
| 31:25 | Downward swing BOS; A is the high that caused the break. | Bearish swing; A is the protected high. | Final location of the developing low B. |
| 31:31 | Presenter explicitly says the swing low is not yet known. | Downward run is developing. | A pullback identifying the run's endpoint. |
| 31:43–32:06 | Inside bar fails to take the preceding low; downward continuation then establishes a minor high C. | A minor counter reaction occurred; C becomes the bullish internal-break reference. | C has not yet broken; the inside bar alone is not bullish CHoCH. |
| 32:13 | C breaks upward: bullish CHoCH. | Possible start of a swing pullback; swing still bearish. | Break of A required for a bullish swing change. |
| 32:20–33:08 | Bullish internal movement within A/B range. | Countertrend pullback inside a bearish swing. | Pullback high is not yet a confirmed swing lower high. |
| 33:13–33:24 | Internal low breaks downward: bearish CHoCH. | Internal direction realigns with bearish swing; possible pullback completion. | Downward swing continuation has not been established merely by this CHoCH. |
| 33:31–33:43 | Internal bearish continuation fails; internal lower high breaks upward. | Bullish CHoCH warns the expected bearish continuation may fail. | Larger swing remains bearish until A breaks by its swing-break rule. |
| 34:01–34:12 | Larger high A breaks; presenter identifies bullish trend change. | Larger swing changes bullish. | Subsequent continuation remains a future possibility. |

The close requirement for the final swing break comes from the explicit general
rule in Part 1, 22:37–25:24; the exact closing candle has not been independently
matched to source OHLC. The two intermediate CHoCH events must remain visible
in history even though one anticipated continuation fails.

## Part 2: multi-timeframe replay, 50:45–56:35

| Video time | Reference event | 4H context | 15m state / meaning |
| --- | --- | --- | --- |
| 50:50–51:07 | 4H upward BOS; 15m also bullish. | Bullish; pullback anticipated. | Bullish until protected swing low breaks. |
| 51:30–51:37 | Wick below minor 15m internal low. | Pullback may be starting. | Bearish CHoCH; not yet bearish swing change. Presenter explicitly says close unnecessary here. |
| 52:21–52:35 | Downward candle run continues. | Possible pullback. | Track the minor high that must break for bullish CHoCH; do not invent a bullish shift just because demand is reached. |
| 52:41–52:46 | Close below 15m swing low. | Still bullish swing; bearish 15m supports pullback interpretation. | Confirmed bearish swing change. |
| 53:24–53:34 | Minor high breaks upward. | Pullback developing. | Bullish internal CHoCH, suggesting a pullback inside bearish 15m swing. |
| 54:33–54:38 | Minor low breaks downward. | Pullback developing. | Bearish internal CHoCH; possible 15m pullback completion. |
| 56:29–56:35 | Presenter describes later bullish CHoCH and bullish switch. | Possible 4H higher low / renewed continuation. | Bullish realignment; distinguish internal CHoCH from swing change. |

The last row is a narrated recap, not a separately verified exact replay candle.
Do not assign both events the same market timestamp on that evidence alone.
The broader narrated context is a bearish weekly/daily swing with a bullish 4H
movement facilitating the daily pullback. These selected events do not establish
new weekly or daily breaks.

## Audit of the current implementation

Reviewed `crypto_strategy_lab/photon_structure.py` and
`crypto_strategy_lab/visualizer_photon.py`.

| Requirement | Current implementation | Assessment |
| --- | --- | --- |
| Swing breaks use own-timeframe close beyond wick extreme. | `map_structure` uses strict close comparisons against eligible swing levels. | Rule matches; correctness of selected levels remains unverified. |
| Internal CHoCH may use wick penetration. | Internal breaks use high/low, independently of close. | Rule matches; internal reference selection still needs walkthrough validation. |
| A single opposite swing break changes direction. | Emits `TREND_CHANGE` when eligible opposite range level closes through. | Rule matches, conditional on correct range. |
| Internal reversal does not automatically reverse swing. | Separate `internal` and `trend` states; phase is qualified as possible. | Rule matches. |
| Preserve failed internal shifts. | CHoCH event history exists; CHoCH does not add solid swing anchors. | Event retention exists. A BOS-only trace alone does not communicate the complete process. |
| Meaningful swing pullback matches presenter. | Strict two-left/two-right pivots qualify weak extremes. | Unvalidated implementation assumption, not a lesson rule. |
| Pullback origin correctly includes/excludes opposite wick of broken pivot candle. | Search starts strictly after broken pivot candle. | Implementation convention. Video does not establish a universal exclusion rule; intrabar ordering can be unresolved. |
| Distinguish developing structure from confirmed structure. | Trace admits points at BOS; optional dashed leg ends at last close. | Causal timestamps exist, but a last-close segment is not a complete developing run/pullback map. |
| Weekly/daily narrative above 4H/15m. | `build_mapping` produces only 4H and 15m. | Missing. Mockup is not an implemented Lab feature. |
| Timeframe relationships allow exceptions. | Maps 4H and 15m independently. | Good foundation; no explicit multi-level narrative yet. |
| Replay uses information available then. | Events use `availableAt`; complete 4H buckets only. | Covered by prefix tests; does not prove presenter equivalence. |
| No orders. | Hard entry and direct-opening gate. | Covered by existing tests. |

## Acceptance criteria for the next mapping revision

1. Label the source examples first. Each label needs timeframe, reference
   extreme, break candle, wick/close rule, source timestamp and confidence.
2. Keep both origin time and knowledge time. A later BOS can confirm an earlier
   origin; historical replay must not show the confirmation early.
3. Reproduce the ordered sequences above, including the failed bearish
   continuation in Part 1 and CHoCH-before-swing-change in Part 2.
4. Show established swing anchors, developing run/pullback candidates, and
   internal reference levels as distinct things. CHoCH alone must not promote
   every minor pivot to a confirmed swing.
5. Preserve separate weekly, daily, 4H and 15m states. Narrative relationships
   are qualified interpretations, not forced one-to-one event equivalences.
6. Use completed UTC daily/weekly buckets for crypto. Document weekly alignment
   and source-feed/session differences when comparing against FX examples.
7. Keep order gates and causal prefix checks intact.

## Remaining evidence and limits

The videos provide reference event order, but not a complete mechanical swing
qualification rule. Part 1 around 30:47–30:53 qualifies an approximately 40-pip
4H pullback "for me"; this is not a universal threshold transferable to BTC.
Part 2 around 35:22–35:34 similarly rejects a very minor pullback.

Exact engine-versus-presenter verification requires readable candle labels and
matching EURUSD feed/history (or explicitly documented approximation). Synthetic
OHLC scenarios can test wick/close semantics and causality but cannot establish
that the algorithm chose the same swings on the actual chart. No such exact
match, trading advantage, or BTC validation is claimed by this reference.

The next implementation should first expose manually reviewable candidate
selection and those unresolved choices, rather than replace one arbitrary
pivot threshold with another and describe it as the presenter's method.
