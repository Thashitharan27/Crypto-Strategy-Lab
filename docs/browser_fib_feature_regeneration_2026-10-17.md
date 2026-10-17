# Original Windows Fibonacci feature regeneration — 2026-10-17

**PASS for existing prepared-feature semantics across eight genuine original
references. Strict raw JSON/dtype equality differs as documented below.
Full historical browser migration certification remains BLOCKED.**

This continues [the retained executor certification](browser_fib_historical_execution_2026-10-17.md)
without repeating its eight-run/35-trade replay. Browser execution and
configuration writes remain disabled. PR #501 remains on HOLD; the PySide6
fallback remains supported.

## Provenance and independent regeneration

GitHub main and the Windows checkout both resolved to
`9ed693210801e3612d2c602381ec27095111b007` before this work. Original manifests
record clean commits `70bf4e134aca45d6ab1cee2ab3aae0ad732558fb` and
`36d3131783c1a98fedb376db15654b8706c77074`.

All eight saved prepared-policy fingerprints reconstruct exactly using their
saved configurations and the historical projection function. They identify
Fibonacci context version **25**. Current preparation uses version **28**.
All 47 retained L2 metadata files were located. Original manifests retain
provider parameters, versions and source datasets; configurations and hashes
stay workstation-local. Resolved historical package versions are not fully
recorded, so exact historical dependency-environment reproduction is not claimed.

The ordinary Data Lake providers have identical source blobs in both original
commits and the candidate. Recorded provider versions include core directional
2, production market context 3, funding 5, basis 3, futures positioning 4,
Ichimoku 1, taker flow 3 and daily state transition 1. The policy-market provider
remains version 1.

Candidate feature computation used commit `d747912921cbfd11eff7a8528654f5bb55a0ef8c`. Subsequent PR #712 changes
affect artifact queries, optional trade aggregation and certification tests;
the feature computations used by these eight configurations are unchanged.
All eight configurations disable trade-flow aggregation.

Regeneration used the existing `load_backtest_bundle`, production feature
registry, `prepared_policy_config` and `from_data_lake_bundle`. L2 loads were
forced to miss and L2/quality stores disabled; the original L3 frame was loaded
only as the independent expected reference. No simulator or reporter ran.
No browser job or saved-configuration write path was used.

The canonical catalog was opened read-only. Canonical rebuilding from raw
archives was prohibited. Current canonical strategy identities and every
materialized original L2 identity match their retained originals. Prepared
timestamps define the original warmed window; all eight current unclamped
warm-up starts also match those original starts. Intrabar execution data is outside this feature gate
and its earlier retained verification was reused.

## Comparison results

Eight references share five distinct prepared inputs. Three comparisons reuse
an already completed regeneration with identical frozen key, effective policy
inputs and feature configuration. This is five independent regenerations,
not eight distinct feature experiments.

| Distinct frame | Prepared rows | Named columns | Existing semantics |
| --- | ---: | ---: | --- |
| 1 | 17,474 | 240 | PASS |
| 2 | 17,378 | 269 | PASS |
| 3 | 26,210 | 269 | PASS |
| 4 | 17,474 | 269 | PASS |
| 5 | 14,240 | 219 | PASS |

**92,776 distinct prepared rows** and
**8,486,781 Fibonacci candidate records** were checked.
Arrays and research blocks are aligned by semantic field names and original row
position; timestamps and candidate lists are not reordered. Numeric equality
uses zero tolerance, and missing-value locations are checked independently.

There are no unexplained feature values, missing-value patterns, column-set
differences or timestamp changes. All original Fibonacci rule/structure arrays,
selected candidate IDs and pre-existing ordered candidate-inventory fields agree.

Two explicit representation/schema differences remain:

1. Fibonacci inventory JSON adds eight versioned diagnostics:
   `structure_class`, `max_internal_retracement_ratio`,
   `structure_quality_mode`, `structure_quality_eligible`,
   `unadjusted_final_score`, `context_eligible`, `context_reason` and
   `context_entry_distance_atr`. Raw JSON strings differ. A separate exhaustive
   comparison removes only these named additions; all original candidate fields
   and candidate order then agree, with no unexpected added keys. New diagnostics
   have no historical oracle and are not presented as historically certified.
2. Some aware research timestamp columns loaded from Parquet display
   `Asia/Colombo`, while freshly computed arrays display `UTC`. Their instants,
   missingness and timestamp units agree exactly. Dtypes agree after explicit
   UTC normalization; raw timezone dtype labels are not claimed identical.

Comparison is of decoded native feature arrays. Byte-identical exports and
newly persisted L3/CSV/Parquet serialization are outside this gate. The machine
report retains `strict_raw_dtype_and_json_equality: false` and
`historical_execution_certified: false`.

## Reproducible defects fixed and validation

PR #712 fixes three issues found during certification:

- Fibonacci preparation consumed six options absent from the L3 identity.
  Changing them could reuse stale prepared facts. The relevant inputs now
  participate when Fibonacci features are required; original caches still load.
- Research artifact validation used the workstation timezone for mixed
  TIMESTAMP/TIMESTAMPTZ joins and rejected valid UTC evidence. Artifact
  connections now explicitly use UTC; corruption checks remain strict.
- Trade-aggregate period keys and SQL sessions depended on local timezone.
  Bounds and sessions now use UTC. Existing local legacy-offset partitions have
  a validated read-only fallback, with a test proving their bytes are preserved.

Synthetic regressions reproduce the defects before the fixes and pass after;
they are software validation, not historical execution certification.
The Windows output-folder assertion now compares resolved path identity across
Qt slash conventions. The merge-marker test scans versioned text instead of
reading ignored multi-gigabyte Data Lake caches and retained evidence.

Final code Windows suite: **1,925 passed, 10 skipped, zero failed**.
Raw CI full-suite pytest result: **1,935 passed, zero failed**; all eight CI
checks pass. A green observation job alone was not accepted as evidence.
The ten Windows skips are symlink-dependent tests. A fresh temporary permission
probe confirms **WinError 1314: required privilege not held**. Repository and
canonical Data Lake folder access work normally. No elevation was requested.

## Preservation and genuine exit evidence

All **2,836 original configuration/output files** and all **3,242 previously
frozen inputs** remain unchanged. The broader before/after protected inventory
contains **6,043 files** with no changes or additions;
canonical partitions read during regeneration retain their hashes.
The previous executor evidence is reused without modification.

The original completed-run store contains 178 trade artifacts. A read-only
inventory and registered artifact-hash validation found two additional genuine,
non-pending-Fibonacci references: **40 executed LONG TP1 rows** with timestamps,
prices, quantities, fees and P&L, and **40 LONG break-even triggers** with trigger
timestamps and stop prices. These are retained originals, not generated fixtures.
Their existence is established; no new execution-parity certificate is claimed
for them here.

Both original references also pass the current read-only research-artifact
query service after the UTC fix, returning 79 trades each. Temporary query
spill files were redirected into the new evidence directory.

No executed SL1 rows, trailing activations or dedicated per-trade slippage
columns were found in that store. No complete execution event-history artifact
was found. Final summary flags cannot prove full activation/event order, and
1-minute OHLC cannot establish real intraminute tick order. A configured
slippage rate is not substituted for missing historical per-trade evidence.

Detailed hashes, run IDs, discrepancy counts, original feature versions,
configuration lineage, source identities and local orchestration are retained
under `parity_verification/fib_feature_regeneration_2026-10-17`. Original executor
evidence remains under `parity_verification/fib_historical_execution_2026-10-16_234001`.
No raw data, private configuration snapshots or saved outputs are committed.

Next milestone: use the genuine TP1/BE references for the remaining scoped
execution gates, reusing already completed TP1 evidence where applicable;
obtain independent SL1/trailing/event-history/slippage evidence before closing
those gates. Guarded browser-versus-desktop execution remains separate.
PR #501 and browser execution/configuration writes stay on hold.
