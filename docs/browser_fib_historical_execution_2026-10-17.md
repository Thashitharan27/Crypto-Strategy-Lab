# Original Windows Fibonacci execution evidence — 2026-10-17

Candidate implementation: main `2f51ca1d37f92fba4a7fc343ac22a7fb424c72f9`.
The checkout was fast-forwarded to that revision before the comparisons.

**PASS for frozen-prepared native executor replay; full historical migration
certification remains BLOCKED.** No synthetic fixture is used as historical
evidence, and no browser execution or configuration write is enabled.

## Genuine original references located

The original completed-output store contains eight completed Fibonacci runs
with **35 saved `FIB_DEEPER_LIMIT_FILLED` trade rows**. Their original manifests
record clean source commits and predate the migration hardening. They include
quarterly 15-minute runs and a six-year 4-hour run, **23 LONG and 12 SHORT** rows.
Thirty entries occur inside their strategy candle rather than at its open;
three saved trades enter and exit in the same minute.

All 178 saved trade artifacts were examined: 150 contain execution scheduling
metadata and 28 are empty. Eight contain actual executed pending-limit rows.
Two other configurations enable the legacy pending-limit flag but their saved
trades executed NEXT_CANDLE_OPEN instead; these are not pending-fill references.
One additional enabled configuration has no completed trades and is not an
executed-fill reference either.

Two independently saved original references have identical execution inputs
but different source commits; their complete native values agree. One candidate
replay was reused for those exact identical inputs, explicitly recorded in the
local evidence. Eight original references therefore cover seven distinct
candidate replay input identities, not eight distinct configurations or 35
necessarily distinct market opportunities.

This corrects the earlier evidence gap: genuine historical pending-limit
executions exist in saved run manifests and artifacts even though no separate
historical pending-limit JSON file was found in the saved-config folder.

## Replay boundary and input protection

The replay reused `PreparedRunCache.load`, `MarketDataStore.load_execution_klines`,
`IntrabarExecutionData`, `NativeStrategyPolicy.bind` and `NativeSimulator.run`.
No alternative indicator, strategy, entry/fill, cost or exit implementation was
introduced. Reporters and browser job execution were not invoked. New replay
files were written only to a separate ignored local evidence directory.

For each reference:

- The existing completed-run reader and registered artifact hashes validate
  the saved manifest, trades, CSV and source-provenance artifacts.
- Original configuration snapshots and hashes are retained. The native loader
  preserves every saved JSON value; compatibility defaults for newer absent
  fields are recorded separately with the effective configuration hash. Original
  configuration files and manifests are not rewritten.
- Saved raw archive stat identities must match the canonical catalog and disk.
  Raw archive bytes, original prepared Parquet/metadata and selected canonical
  minute partitions are content-hashed and retained locally.
- The selected current 1-minute canonical partition identities must equal the
  original saved set. Complete expected minute counts, boundaries, uniqueness,
  order and alignment are required. Canonical rebuilding from raw archives is
  prohibited; missing or invalid cache inputs fail closed.

The 2,956 archive hashes shared with the earlier retained full source freeze
all agree. That crosscheck reused retained evidence; it did not rerun the prior
browser/chart certification.

**Important scope:** the candidate executor consumes the original frozen
prepared facts. This does not certify regeneration of strategy/features with
the current provider versions or a browser-controlled run path.

## Comparative results

| Check | Result |
| --- | --- |
| Original versus candidate completed rows | 35 versus 35 across all eight references |
| Complete native field values | Zero discrepancies; no missing or extra native columns |
| Native dtypes | Zero discrepancies after reading both persisted Parquet artifacts |
| Existing completed-trade fingerprint | All eight original manifest, original artifact and candidate fingerprints agree |
| Chronology and fills | Signal, scheduled/actual entry and exit fields agree; original row order is retained |
| Risk and accounting | Quantities, initial risk, stops/targets, full exits, fees, gross/net P&L, realized R and saved equity fields agree |
| Normalized active-leg comparison | All 14 represented fields agree at zero tolerance; the missing slippage field is reported for each of the 35 rows |
| Frozen input preservation | All 3,242 hashed input files unchanged |
| Original config/output preservation | All 2,836 files unchanged by before/after SHA-256 inventory; no additions or removals |

Columns are aligned by their existing names; trade rows are never reordered.
Five raw replay exports differ in column order, so byte-identical CSV/Parquet
exports or ordered-column serialization parity are not claimed. Numeric values
use zero tolerance; equivalent timestamp instants are compared in UTC. The
existing native fingerprint is corroborating evidence for its defined subset,
not a substitute for the complete field comparison.

The existing `inspect_native_trade_columns` probe and strict `compare_trades`
utility were reused. The latter correctly reports missing per-trade slippage
for all 35 rows. A configuration-wide slippage rate is not fabricated into a
trade field. Machine evidence retains `historical_execution_certified: false`.

Detailed run IDs, input hashes, configuration snapshots, original/replay paths,
full discrepancy reports, schema comparisons, fingerprints and orchestration
remain workstation-local. Captured original data and private configuration
values are not committed.

## Remaining certification blockers

1. None of the eight original references has an executed TP1 or SL1 partial
   exit. Equality of unexecuted/empty partial fields does not certify partial
   execution. Genuine historical partial-exit references are still required.
2. No full execution telemetry/event-history artifact is retained for these
   runs. Final trade fields and the three same-minute exit outcomes do not prove
   complete BE/trailing/partial activation order, nor real tick order inside
   1-minute OHLC. Do not infer missing events or silently choose an ordering.
3. The original native reports have no dedicated per-trade slippage field.
   Fill-price and realized accounting equality are established, but the strict
   15-field comparison is not a complete PASS.
4. Current feature/strategy regeneration and guarded browser-versus-desktop
   execution remain separate gates. Reusing the frozen prepared facts is
   intentional execution isolation, not certification of those other paths.

No production engine change was needed to reproduce these available original
executions. Next, obtain genuine partial-exit/event-history references and an
auditable slippage representation, then close those gates and independently
verify current feature preparation before any Phase 5 release decision.

**PR #501 remains on HOLD. Browser execution and configuration writes remain
disabled, and the PySide6 fallback remains supported.**

## Feature-regeneration follow-up (2026-10-17)

Independent regeneration now passes for all existing feature semantics across
these eight references, with explicit additive JSON and timezone-display
differences. See [the feature-regeneration report](browser_fib_feature_regeneration_2026-10-17.md).
The original 35-trade executor replay was reused without repetition. Remaining
SL1/trailing/event-history/slippage and guarded browser execution gates stay
blocked; PR #501 remains held.
