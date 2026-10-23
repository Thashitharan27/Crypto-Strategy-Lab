# EMA 20/100 cost-cover cycles

In Risk / Execution → Entry Execution, select an EMA 20/100 Cross trade plan and
enable **At 1R cover costs + break-even; repeat re-entry while EMA trend holds**.
The option is off by default and applies to the EMA 9/20 strategy's cross plans.
Use one active trade, without a daily schedule or DI ladder.

For a long entered at 100 with SL 90:

1. At 110, close enough quantity to offset the configured entry fee, the partial
   exit fee, and the estimated fee/slippage on the remaining quantity exiting at
   entry. Move the remaining SL to 100.
2. If stopped at 100, watch 110 again. Re-enter only while the latest completed
   strategy candle still has EMA 20 above EMA 100. Use 100 as the new SL.
3. The new position's own 1R is 120. Repeat the same process without a cycle limit.
4. The completed bearish crossover closes the runner at the next strategy open
   and cancels any pending re-entry. A fresh bullish crossover starts a new chain.

Short plans reverse the prices and EMA alignment. Every re-entry is a separate
trade, sized using current equity and the configured sizing budget and leverage
limits. Entry filters and market permissions are checked again, without requiring
a fresh same-direction EMA cross. Gaps receive the actual gap fill and configured
slippage; the previous entry remains the stop and the new 1R is recalculated.

This option owns optional position management: other partial-profit, break-even,
trailing and timeout settings do not govern these positions. There is no fixed TP.
Here 1R means the actual initial entry-to-protective-SL price distance for each
position, including a configured wider stop; it is not a separate sizing-R unit.

The partial quantity is solved from the native simulator's fee/slippage cashflows,
not a fixed percentage. If 1R profit cannot fund costs while leaving a runner,
retain the original stop and record `ema_cycle_cost_cover_rejected`. Zero-cost
runs move SL at 1R without needing a partial. Funding is accounted for in final
results but future funding cannot be guaranteed covered by this action. A gap
through the break-even stop can likewise produce a net loss.

Use complete 1-minute data for ordering. Missing data follows the configured
missing-data policy; strategy-candle fallback is marked on the position. Existing
stops take precedence over targets within an ambiguous OHLC candle. The new BE
stop and a pending re-entry become eligible on the next execution candle, not
earlier in the same candle. For entries triggered inside a candle, do not credit
another favourable target in that candle; protective stops are pessimistic.

Result rows include `ema_cost_cycle_enabled`, `ema_cycle_number` (initial=0),
`ema_cycle_parent_id`, `ema_cycle_root_id`, `ema_cycle_trigger`,
`ema_cycle_cost_cover_fraction`, and `ema_cycle_cost_cover_rejected`, alongside
the existing TP1, remaining-quantity, fees, exit-reason and net-P&L fields.

Deep Research's direction-neutral market-grid report removes strategy selection
rules, so the EMA cycle option is inactive there and must not impose portfolio
limits on those independent observations. Strategy-specific independent sampling
(including paired walk-forward samples) cannot represent sequential re-entry
chains: that optional report is marked unavailable in the manifest with an
explanation. The normal portfolio trade and performance artifacts remain intact.

## Optional wider-EMA re-entry filter

Enable **Re-enter only with a wider EMA gap; track phantom checkpoints otherwise**
under the cost-cover cycle option. It defaults off and affects re-entries only.
The EMA gap is `abs(EMA20 - EMA100)` in price units, using the latest completed
strategy candle. Save that gap at every actual entry. A re-entry requires a
strictly larger gap than the previous actual entry; equality also fails.

After entry 100 / SL 90 is cost-covered and stopped at 100, check 110. If the gap
is not wider, record a phantom checkpoint without placing an order. Check again
at 120, then 130, etc., in the same original 10-price-unit steps. If 120 qualifies,
enter with SL 110. That position's own 1R is then 130. Actual fills still use the
configured slippage and gap policy.

Rejected checkpoints never replace the reference EMA gap, affect equity, charge
fees, or count as trades. Only an actual new entry resets the baseline. The
opposite EMA cross cancels monitoring. Several rejected levels crossed in one
execution candle are recorded separately using the same already-known EMA gap.
There is no intrabar recalculation from an unfinished strategy candle.

Trade rows save `ema_cycle_entry_ema_gap`, `ema_cycle_reference_ema_gap`,
`ema_cycle_reentry_checkpoint`, `ema_cycle_widening_enabled`,
`ema_cycle_phantom_count`, and `ema_cycle_phantom_records` (JSON). Phantom records
belong to the stopped parent trade, including when no later real entry occurs;
they contain the checkpoint time, hypothetical entry / stop, EMA comparison and
rejection status, without hypothetical P&L being mixed into portfolio results.
