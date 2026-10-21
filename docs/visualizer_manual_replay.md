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

The chart shows entry/stop/target as a fixed-width plan before the outcome is
known; that box width does not represent the eventual trade duration. FVG
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
manual review, with no simulated manual SL/TP outcomes or P&L.

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

The automated entry remains the initial replay anchor. Manual SL/TP outcomes,
fees and P&L are not simulated. At reveal the exit label says **Auto exit**, and
all reported R totals still use original automated results. Export format
version 3 adds the manual plan's `entryTime`, optional `manualEntry` confirmation
and `confirmedManualEntries` count, preserving earlier choice/note/outcome
fields. Unconfirmed plans remain plans, not entered trades.
