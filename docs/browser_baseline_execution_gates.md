# Browser migration: existing execution regression gates

This CI-only increment puts existing causal limit-order and pending-limit lifecycle tests into the blocking strategy-profile safety job. It reuses the tested Python execution path without rewriting the engine or duplicating Fibonacci limit handling.

The following pre-existing tests are intentionally added:
- `tests/test_engine_limit_entry_candidate.py`: pending limit price and expiration behavior;
- `tests/test_engine_limit_fill_schedule.py`: signal and fill index metadata, non-executing scheduling;
- `tests/test_engine_pending_limit_lifecycle.py`: pending candidate lifecycle.

These focused regressions **are not golden historical backtest results**. The next milestone requires a frozen BTCUSDT dataset with 1-minute execution files, canonical config/commit/data hashes and known trade outputs. Before parity certification, compare scheduled and actual entry timestamps, every leg and partial exit, fee model, reason codes and account R.

Do not merge PR #501 until the existing Fibonacci pending-limit machinery is checked for overlap and causal equivalence.


## PR #501 overlap audit (2026-10-16; still held)

The draft introduces `BacktestEngine._first_intrabar_limit_touch`, an isolated non-executing helper, while the active engine already owns `_limit_entry_candidate`, `_resolve_pending_limit_candidate`, `_limit_candidate_fill_schedule`, and the separate FIFO-like intrabar exit processing path. Do not turn the draft helper into a second entry/fill authority.

Concrete unresolved coverage defect: `_first_intrabar_limit_touch` selects `[strategy_start, strategy_end)` minute rows and calls `_has_missing_intrabar`. The current `_has_missing_intrabar` checks only timestamp differences **between returned rows**; a missing first or last minute can pass without a detected gap. The draft tests mock `_has_missing_intrabar`, so they do not verify complete coverage of the eligible candle.

Before resolving the overlap, independently test and establish:

1. Complete expected minute-grid coverage from candle start through end (including leading/trailing gaps, duplicates, and non-aligned timestamps), with fail-closed missing coverage; do not weaken the existing intrabar missing-data policy.
2. Exactly one authoritative pending-limit lifecycle: signal bar ineligible, expiration respected, first eligible minute, gap-through-open fill-price rules, and direction/flip semantics shared with the existing `entry_plan` helpers.
3. Deterministic within-minute collision policy for candidate entry versus pre-existing exits, TP/SL, partials, trailing stops, fees, and risk/accounting; do not infer a sequence from minute OHLC that cannot establish it.
4. Historical 1m source coverage, full native-trade output and entry/exit timestamp parity against frozen workstation artifacts in the separate CryptoBots Desktop project. CI unit tests are insufficient for release certification.

No browser-controlled execution or configuration writes are authorized; PR #501 remains on hold. This audit is not a decision to merge the draft or change live fill behavior.

## Native pending-limit ownership hardening

The active Fibonacci two-hold/deeper-limit path remains the execution owner for
that strategy. Its first-touch scan now requires an exact intrabar timestamp grid
for the whole eligible strategy candle whenever intrabar execution is enabled.
Missing leading, trailing or interior minutes, duplicate timestamps and off-grid
timestamps fail closed before any candidate touch is accepted. This reuses
`entry_plan.has_complete_intrabar_window`; it does not adopt PR #501's separate
first-touch helper and does not expose a browser execution API.

This closes the **minute-grid completeness** defect for the native Fibonacci
pending-fill owner. It does not by itself establish within-minute event-order
equivalence for every exit mode or historical trade-level parity. Those remain
release gates before browser-controlled execution or configuration writes.


## Fill-minute ordering regression (CI-only)

The native Fibonacci pending-limit executor clamps the favorable extreme to the
actual fill price on the fill minute, for both LONG and SHORT directions, while
retaining the adverse extreme for stop handling. A regression now checks that
behavior at a non-opening-minute touch, its timestamp, and the restoration of
ordinary ranges from the next minute onward. This protects a conservative
OHLC ambiguity policy; it does **not** prove the ordering of stops, profit
partials, trailing activations, fees, and position accounting. End-to-end
minute-collision equivalence and original-file execution replay remain blocked.

## Original Windows executor evidence (2026-10-17)

Genuine saved pending-limit outputs were located and replayed at main
`2f51ca1d37f92fba4a7fc343ac22a7fb424c72f9` using their original frozen prepared
inputs and canonical minute partitions: eight original references, 35 saved
trade rows, zero native-value discrepancies. See
`docs/browser_fib_historical_execution_2026-10-17.md` for the exact scope and
preservation evidence. This closes the available **frozen-prepared native
executor comparison** increment, not full historical migration certification.
Original executed partial exits, complete event histories, an explicit
per-trade slippage representation and current feature regeneration remain
uncertified. PR #501 remains held and browser writes/execution remain disabled.

