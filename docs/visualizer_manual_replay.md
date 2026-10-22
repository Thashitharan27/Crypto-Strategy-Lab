# Manual trade replay

Open a completed run in Visualizer V2, select a trade, and click **Trade replay**.
Replay switches to the strategy timeframe and starts at the actual entry time.
Only fully closed candles are shown. The entry candle initially contains an
entry-price point, not its eventual high, low, or close. Indicators are trimmed
to closed candles, and the trade selector hides result-bearing labels.

Review the entry plan, known indicators and saved setup. Write an optional note
and select **Take**, **Skip** or **Unsure** before revealing future candles.
Then use **Next candle**, **Play/Pause** with the speed selector, or **Reveal
result**. Replay can continue past the automatic exit to review a later manual
entry. Judgements and
pre-entry notes lock as soon as any future candles are revealed. **Restart at
entry** hides the result again but retains the original judgement and marks it
as previously reviewed. Selecting another trade keeps replay active and starts
that trade at entry. Turning replay off restores the normal completed-run view.

The manual entry/stop/target box grows to the latest replay candle; once a
confirmed position closes it ends at that exit candle. Unconfirmed boxes remain
previews and do not trigger TP/SL exits. FVG
evidence is shown only after its confirmation candle closes. Fib geometry is
shown only when the saved swing-end timestamp establishes it was known; legacy
Fib geometry without that timestamp is omitted while blind. Alternate chart
timeframes are disabled in replay to avoid showing unfinished aggregated bars.

After a result is revealed, the status compares the original trade result with
the saved manual choice and shows sums for the reviewed automatic trades versus
the subset marked Take. These are sums of saved net R, not a portfolio
resimulation: skipping trades does not recompute position overlap, sizing,
compounding or newly available entry opportunities. Unsure is kept separately.

Use **Export reviews** to download a JSON report of this run's choices, notes,
revealed results and comparison totals. Browser storage is best effort and is
scoped to the current local server address; restarting the visualizer may use
a different address. Export before closing if you want to retain the review.
The backtest's trade records, configuration and execution logic are unchanged.
Returning to the normal view also counts as revealing the result and locks any
existing judgement. Exported records flag whether the trade had already been
shown in normal view before that judgement was recorded.

This is a visual review aid. Completed-run data is loaded locally; it is not a
secure examination mode. Outcomes already seen before entering replay cannot
be made unseen. Keep replay active when selecting subsequent trades for a
cleaner comparison.

## Manual entry, SL and TP plans

## Drawing tools and smooth playback

Use the vertical drawing toolbar on the left of the chart for trend lines, rays, horizontal/vertical
lines, rectangles, Fibonacci retracements, price/time measurements and text
notes. Select a tool and click one anchor for a horizontal/vertical line or
note, or two anchors for other tools. Enter note text before placing a note.
The mouse previews the second anchor. Escape cancels the unfinished drawing.
Open **Drawing settings** (gear icon) for color, note text, saved drawing
selection, redraw, delete, clear and export. Close the panel to regain chart
space. The active icon is highlighted; an on-chart hint explains the next
anchor click. Choose a color before drawing. Drawings stay attached to time and price while
panning, zooming or changing chart timeframe.

Select an item under **Saved drawings** to delete it or use **Redraw selected**
to replace its anchors, color and note. **Undo drawing** reverses the last
creation, edit, deletion or clear in this session. Drawings are saved locally
for this run/symbol; export them with **Export drawings** before closing if
you want a portable JSON copy. Browser storage uses the local server address,
so a newly launched visualizer on a different port may need a fresh drawing
session. Export is archival; drawing import is not currently provided.
Replay-created drawings are hidden when restarting before their creation time.
Drawings are annotations; they do not change strategy decisions or order levels.

**Next candle** and **Play** update existing chart series rather than rebuilding
the chart. Price zoom/pan and RSI settings remain stable. **Follow replay**
slides the time window by each newly added candle; turn it off to hold the time
window fixed. Use **Reset price** or **Center selected** when you want to refit
the chart. Switching days, trades, timeframes or indicators can still rebuild
the chart as those change its context or series layout.

## Review days without automatic trades

Select **Day replay** to review any available UTC day independently of the
automatic trade list, including days with no generated trades. Use **Previous
day**, **Next day** or the date picker. Navigation moves to the start of the
chosen day; missing-data days are skipped by the navigation buttons. Click
**Day replay** again to return to the normal trade view.

Use **Next candle** or **Play** freely while looking for a setup. Future candles
remain hidden; playback stops at the day's end. **Reveal day** shows only that
day through its end, not later days. **Restart day** restarts that date while
retaining saved review history. The previous complete day's high/low and older
confirmed outside swings are drawn when available from the loaded history.
Automatic setup drawings and trade outcomes are excluded from this mode.

Choose LONG or SHORT, edit the starting Entry/SL/TP placeholders, and use
**Move box** to select an entry candle. Choose **Take** when you find a setup,
then **Confirm manual entry** after the chosen candle closes and reaches your
price. One review/confirmed setup is stored per day, separately from automatic
trade reviews; return to that date to inspect its saved plan. History records
whether candles had already been advanced before planning. This remains a
manual review. Confirmed positions can close manually or at replay TP/SL levels,
with gross R recorded separately from automatic results.

**Export reviews** includes these records with `reviewType: manual-day`, the UTC
`day`, plan history and optional manual entry confirmation. `manualDayReviews`
counts them; they do not contribute to automatic-trade R totals.

## Edit a replay plan

Replay includes **My plan** with editable Entry, SL and TP prices. Type prices
or press **Pick entry**, **Pick SL** or **Pick TP**, then click the chart at the
desired price. The risk/reward box previews the proposed levels and shows their
reward/risk ratio. **Use auto levels** restores the automated prices as a draft.
Long plans require SL < entry < TP; shorts require TP < entry < SL. All prices
must be positive and finite. Editing prices pauses playback.

Select Take, Skip or Unsure to save the initial plan with your judgement, or
press **Save plan** for later adjustments. Advancing, revealing, exporting,
switching trades or leaving replay also saves a valid draft for an existing
judgement. Unsaved edits are identified in the plan status. Each changed plan
adds a timestamped revision with the replay candle/time and a flag indicating
whether future candles had already been viewed. The original automated plan,
first manual plan and judgement remain available in the export. Repeated saves
of identical prices and entry candles do not duplicate history. Plans lock after
explicitly revealing the full result or confirming a manual entry; restarting
retains the saved history and confirmation.

Use **Move box**, then click a visible candle at or after the automatic entry.
The whole risk/reward box moves horizontally to that candle while preserving
your Entry, SL and TP prices. The selected candle time appears beside the button
and is included in each saved revision. Advance replay to select later candles.
Older reviews without an entry candle default to the original entry candle.

After choosing **Take**, use **Confirm manual entry** to record that you would
have entered on the selected candle. It must be fully closed in replay, and its
low/high range must include your entry price. Otherwise the tool explains why it
cannot confirm; advance, move the box or adjust the price and try again.
Confirmation saves and locks the plan. It records the candle OHLC, selected
prices, confirmation time, replay time and whether results had already been
seen. A candle range validates price reachability, not an exact intrabar fill
sequence or order execution. Later plans remain visibly tagged as made after
advancing; this is not a blind prospective execution backtest.

The automated entry remains the initial replay anchor. Automatic comparison
totals still use original automated results. Export format
version 3 adds the manual plan's `entryTime`, optional `manualEntry` confirmation
and `confirmedManualEntries` count, preserving earlier choice/note/outcome
fields. Unconfirmed plans remain plans, not entered trades.

## Close and track a manual position

After **Confirm manual entry**, **Close manual position** records the latest
fully closed candle's closing price. **Pick exit** lets you select another
visible, fully closed candle and a price within its range, at or after the
entry candle. A closed position cannot be closed or edited a second time.

Advancing replay also checks confirmed positions against their saved TP and SL.
The first subsequent closed candle that touches either closes the position and
pauses playback. An opening gap beyond a level exits at that opening price.
When both levels are touched inside one candle, SL wins conservatively unless
the opening price establishes that TP occurred first. Automatic checks skip the
entry candle because its full OHLC cannot establish which extremes preceded
the manual entry; a same-candle user-picked exit is retained with that ambiguity.
Confirming a historical entry after advancing checks all already-known later
candles and may immediately record the earlier TP/SL hit.

The risk/reward box expands through the latest replay candle while open and
freezes at the recorded exit candle. Green becomes darker when the latest price
is on the profit side of entry; red becomes darker on the loss side, with the
direction reversed for shorts. After closure the color uses the exit price.

The status shows exit price/time, percentage return and **gross R**, calculated
against the initial entry-to-stop distance. Fees, slippage, portfolio sizing
and position overlap are excluded. Reviews export `manualExit` evidence,
exit reason/method and gross R, plus a separate `manualResults` total. Existing
automatic `netR` and Take-only comparison totals are unchanged. Browser storage
and export preserve both user closes and TP/SL exits across review sessions.

Manual position resizing: drag the dashed entry, SL or TP edge before confirming
entry. After confirmation, entry stays fixed; SL and TP remain draggable while
open. The SL to break-even button uses the original entry price. Changes are
saved in positionHistory with old/new levels and replay time, apply only to
subsequent candles, and are included in exported reviews. Stops may lock in profit,
but SL and TP must bracket the current closed price. R always uses initial risk.
Rewinding shows the levels known then; advance to the latest saved change before
editing again. Closed positions cannot be resized.

Previous-day support/resistance: enable Previous-day S/R in the chart toolbar.
A complete previous UTC day on a 1h-or-lower chart is required. Strict swing
pivots use two candles on each side, all from that previous day; daily high/low
are included. Bands use 1%, 2%, or 4% of that day's range as their base width.
Nearby pivots merge with bounded clustering; up to eight bands prioritize daily
extremes then number of pivot levels. Bands have no visible labels; hover over a band for its price range. Bands start on the selected UTC day and
remain fixed throughout its replay. Colors describe their previous-day origin,
not a prediction of future reactions. This display does not change automatic
entries or exits; use manual TP resizing or closing to record your decision.

Replay timeframe views: chart timeframe remains selectable during Trade replay
and Day replay. Switching pauses Play and keeps the exact strategy replay cutoff,
judgement, manual plan, and confirmed position. Chart candles and indicators are
clipped to what was closed at that cutoff; an entry-only placeholder never exposes
an unfinished candle's final high/low/close. Next candle and Play advance one candle of the selected chart timeframe.
Move box selects a closed candle on the current chart timeframe. Enter at current
candle sets the entry price to the latest closed candle close; choose Take, check
SL/TP and confirm. The confirmed position records its candle timeframe/interval,
which remains fixed for management when the chart view changes. Its candles load
automatically when restoring a saved review. Pick exit uses that entry timeframe;
break-even and Close work from any chart view once entry is confirmed. Timeframe loading failures retain the replay state.

Manual entry confirmation rejects prices outside the selected candle's range and
shows that range in the error. It does not silently move your entry to another
candle. Break-even and Close require a confirmed, still-open position; disabled
button tooltips explain the requirement. Automatic TP/SL detection continues to
start after the confirmed entry candle and uses its recorded timeframe.
