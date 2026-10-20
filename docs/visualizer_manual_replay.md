# Manual trade replay

Open a completed run in Visualizer V2, select a trade, and click **Trade replay**.
Replay switches to the strategy timeframe and starts at the actual entry time.
Only fully closed candles are shown. The entry candle initially contains an
entry-price point, not its eventual high, low, or close. Indicators are trimmed
to closed candles, and the trade selector hides result-bearing labels.

Review the entry plan, known indicators and saved setup. Write an optional note
and select **Take**, **Skip** or **Unsure** before revealing future candles.
Then use **Next candle**, **Play/Pause** with the speed selector, or **Reveal
result**. Play pauses when the recorded exit has been reached. Judgements and
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
