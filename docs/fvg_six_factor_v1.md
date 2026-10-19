# FVG six-factor preset, version 1

Select **Fair Value Gap - Six Factors (v1)** in Strategy Builder, save the
configuration, and run a new backtest. Open that completed run in Visualizer V2.
Existing completed runs do not acquire these signals or annotations.

This is an explicit research interpretation of the TradingLab video
https://www.youtube.com/watch?v=ZTMregh_428, not a claim of exact discretionary
replication or a validated trading edge. The original First Revisit strategy
is unchanged. All six checks are required in this initial preset.

## Decision rules

- A bullish gap is the space between candle 1's high and candle 3's low;
  bearish is mirrored. A gap becomes available after candle 3 closes.
- Only its first later touching candle is eligible. Touches consume gaps even
  when the other checks fail; entire-candle gaps through the zone invalidate it.
- A bullish revisit must close at or above the gap's bottom; bearish must close
  at or below its top. Wicks through the zone are allowed.
- Structure uses strict confirmed pivots with the existing FVG Structure Swing
  Strength control (default two bars on each side). A close crossing the latest
  confirmed high/low establishes a directional break, including a change of
  character. A gap needs a same-direction break known by formation close.
- S/R confluence means a confirmed pivot or the broken structure level overlaps
  the gap, allowing 0.1 formation ATR tolerance. This is a simple local level
  interpretation, separate from the Lab's full S/R-zone detector.
- Rank untouched gaps sharing the same side and break event. Prefer the lowest
  bullish gap or highest bearish gap; ties prefer the earlier formation.
- The impulse starts at the opposite confirmed pivot known at the break. Its
  extreme extends through candles before the revisit. The gap midpoint must be
  in the lower half for longs or upper half for shorts. The revisit's own high
  or low cannot change the midpoint used to authorize that revisit.
- Simultaneous qualifying long and short setups produce no signal. Multiple
  qualifying same-side setups from different impulses prefer the oldest gap.
- Stop is beyond the middle/displacement candle's low/high, with the existing
  0.05 signal ATR buffer. Use next-candle-open entry (the GUI default). Existing
  execution controls and optional lower-timeframe confirmation still apply.
- Target uses the configured reward/risk multiple, only if it fits before the
  pre-revisit impulse extreme minus the existing target ATR buffer. The target
  is not automatically the full swing extreme. A large configured R can reject
  otherwise valid setups for insufficient room.

## Visual review

The trade stores the gap boundaries, formation and signal timestamps, impulse
origin/extreme/midpoint, broken level, confluence level, stop boundary, and all
six passing checks. V2 displays the gap, midpoint, structure/confluence levels,
and checklist alongside the normal entry/exit and risk/reward boxes. Switching
chart timeframe retains these saved decisions; annotations are not recalculated.
The overlay describes the selected accepted trade; rejected gaps are not shown.

Feedback should identify the run and trade number, expected gap, expected swing
anchors, and which confirmation or entry/stop rule should behave differently.
