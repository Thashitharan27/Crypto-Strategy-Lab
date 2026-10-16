# Original-file browser certification — Windows, 2026-10-16

Base: GitHub main `0e620371f1c94906ebb2509be09278a1ad0e9469`, fetched and
fast-forwarded before certification. The local implementation adds the two
identity fixes below; the market-data engine and saved artifacts are unchanged.

## Completed checks

| Gate | Evidence and result |
| --- | --- |
| Retained V2 historical evidence | `browser_v2_historical_parity --review-only`: PASS, 9 cases, 79 trades, trades 0/39/78 at 1h/4h/1d. Recomputed payload hashes and exact equality; retained files were not rewritten. |
| Original saved V3 configurations | `browser_saved_config_parity --http`: PASS for both existing native saved files. Native serialization, browser reader and authenticated HTTP hashes agree; unauthorized requests are rejected; original bytes are unchanged. |
| Live configuration projections | PASS for both original configs: Configurations raw snapshot, Strategy Designer strategy/features, Research Features and Risk & Execution retain exact JSON values from the same selected snapshot, including six execution profiles. No save or execution controls were enabled. |
| Original completed outputs | PASS: all 178 completed runs read successfully through the existing native service and authenticated HTTP, with exact expected JSON-safe summary projection. No run was rejected. |
| Original Portfolio discovery | PASS: 129 verified Every Viable Entry runs, 6,867 candidate rows; HTTP matches the first 100 native projections under its existing response bound. No portfolio replay was executed. |
| Live Portfolio navigation | PASS after fixing native UUID versus folder ID: the frozen run opens as COMPLETED with 79 trades and the existing saved metrics. |
| Historical 1-minute coverage | PASS: 3,287,520 unique, ordered, minute-aligned canonical candles from 2020-06-01 inclusive to 2026-09-01 exclusive, with no leading, trailing or internal gaps. Existing loader reused canonical partitions; rebuilding from raw archives was prohibited during this check. |
| Saved entry/exit chronology | PASS for the 79-trade frozen output: no exit-before-entry, entry-before-signal-availability, actual-entry mismatch or missing entry candle. One terminal exit is exactly at the end-exclusive boundary and explicitly marked END_OF_DATA; it is not claimed as a minute candle. No unexplained missing exit candle. |
| Real Windows junction containment | PASS: an actual directory junction escaping a temporary completed-run root returns HTTP 404 without calling the saved-run reader; Portfolio excludes it. |
| React build | PASS: TypeScript and Vite production build. |
| Local consolidated regressions | 354 passed, 9 skipped, exit 0. Skips concern filesystem symlinks unavailable without the local Windows privilege. |
| Original-file preservation | PASS: before/after SHA-256 inventories match for all 2,836 files in the configuration and output roots, with no additions, removals or byte changes. |

Original files and captured payloads remain workstation-local. Detailed CLI logs,
JUnit results, discovery and chronology reports, and before/after preservation
inventories are retained in the ignored local certification evidence directory.

The test process also printed a Qt background GitHub worker teardown error
(`Signal source has been deleted`) after its passing summary. This is an
existing desktop worker lifetime issue, not a failing parity assertion; preserve
it as a separate follow-up rather than silently declaring a clean desktop log.

## Reproducible migration fixes

1. The retained original manifest and V2 payload use the native run UUID, while
   the review gate previously required the prefixed output-folder ID. The gate
   now recognizes only the two exact frozen identities and enforces the
   BTCUSDT/4h metadata for the native UUID, the 79-trade count, selected trade,
   timeframe and full required matrix. It does not rename original evidence.
2. Portfolio displayed native manifest IDs and incorrectly reused those IDs as
   completed-run folder lookups. The facade now exposes the basename of the
   already verified run directory as `run_folder_id`. The UI uses that field
   for navigation, preserves the displayed native `run_id`, and exposes no
   absolute artifact path. Existing HTTP path containment remains authoritative.

## PR #501 overlap: HOLD

The draft helper remains an isolated, non-executing first-touch proposal alongside
the existing pending-limit candidate/schedule helpers and the native Fibonacci
pending-order lifecycle. It has not been merged or enabled.

A local probe of the actual `_has_missing_intrabar` used by the draft confirmed
that missing first minute, missing last minute, duplicate timestamps and
off-grid minute timestamps are all accepted. Its current inter-row gap check
cannot establish complete eligible-candle coverage. The draft tests mock that
checker and therefore do not close the defect.

The frozen chronological audit establishes persisted timestamp ordering and
canonical minute availability. It does **not** establish price-event order
inside one minute's OHLC or prove equivalent pending-limit execution, collisions,
partials, stops, fees and slippage. Those remain explicit release gates.

## Remaining limits and next task

- File-symlink checks require a Windows symlink privilege unavailable in this
  session (WinError 1314). Real directory-junction containment was separately
  exercised successfully. Do not change Windows security settings to bypass it.
- Only two original saved V3 files exist in the established configuration root.
  They cover minimal and production configurations with all six profiles; no
  separate original saved historical Fibonacci pending-limit fixture was
  available there. Synthetic repository fixtures are not original-file evidence.
- Review-only chart certification checks retained data consistency, not a new
  engine replay or interactive zoom/pan/resize certification.

Next: establish one authoritative pending-limit execution owner with complete
minute-grid coverage and explicit within-minute collision policy, then certify
historical execution/configuration parity before Phase 5 writes or execution.
Keep browser execution and configuration writes disabled, PySide6 fallback
supported, and PR #501 on hold.

## CI verification and merge decision

PR #688 implementation commit `0f9da3fca3a529db7633575b988afa103823e974`
passed the React build, Windows smoke and all blocking Python/Data Lake/runtime
safety jobs. The full-suite job's green conclusion is insufficient: its
`continue-on-error` step actually reported **20 failed, 1,868 passed**.

The full-suite log for the PR #687 head merged as the requested main revision
reported **the same 20 failing test IDs**, with 1,866 passed. The two additional
passing tests are this PR's regressions. No new failing test ID was introduced,
but the repository-wide suite remains unverified as a clean PASS. The failures
span desktop autostart/connections, DI ladder, EMA/FVG/funding, S/R, volume
profile and walk-forward tests. Detailed comparisons remain local.

**PR #688 remains open and unmerged** under the full-verification requirement.
Resolve those baseline failures without weakening execution invariants, then
rerun the full suite and required checks before merging. Do not treat the
workflow's success status as a passing full suite. PR #501's separate execution
overlap hold remains unchanged.


## Post-certification status correction and Windows execution-parity handoff (2026-10-16)

**Historical note:** the CI/merge section above records the original checkpoint
*at the time of the Windows certification* and is no longer the current merge
decision. The 20 baseline full-suite failures were subsequently repaired;
PRs #688 and #689 were merged after actual raw pytest logs passed, and the
native pending-limit certification increments #690–#700 have also been merged.
The verified #700 head ran **1,903 passed, zero failed, 45 warnings** before
merge as main commit `183a0ccd737df1c5d6ec57fac4cb98333a2a8590`.
Do not reinterpret the original Windows certification as having run on this
later revision or as having certified price-event order.

### Remaining original-file execution parity protocol

Work exclusively in the separate CryptoBots Desktop Windows project, using the
canonical Data Lake and already frozen original output **read-only**. Do not
rebuild archives, mutate configurations, overwrite completed runs, regenerate
expected values from the candidate-under-test, or enable browser execution.

1. Freeze the exact repository revision, strategy configuration JSON and SHA-256,
   canonical minute-data content manifest/hash, symbol, timeframe, start/end
   bounds and taker/maker/slippage values before comparing execution.
2. Choose a genuinely original **saved executed** Fibonacci pending-limit
   fixture if one becomes available. The two original V3 config files and the
   previously audited 79-trade 4h result do not establish that fixture. If no
   native historical Fib pending-limit output exists, explicitly report
   `ORIGINAL_FIB_EXECUTION_FIXTURE_MISSING`; never promote synthetic CI
   regressions into original-file parity evidence.
3. Compare immutable trade/leg identities and direction, signal index/time,
   scheduled and actual entry index/time, initial/fill-adjusted price, size,
   initial risk and SL/TP, then every partial SL1/TP1/TP2 and trailing/BE event
   with effective timestamp, fill price, quantity and reason. Compare all
   entry/exit fees, gross/net P&L, net R, account equity and terminal
   END_OF_DATA handling. Use explicit numerical tolerance and explain any
   mismatch; never count missing fields as equal.
4. Verify each execution minute's full time grid, leading/trailing boundaries,
   first eligible touch and gap-through-open policy. Record ambiguity where
   1-minute OHLC cannot establish whether a favorable and adverse extreme
   preceded/followed a fill; require a documented deterministic conservative
   policy rather than inferring unavailable tick order.
5. Produce a read-only discrepancy report with counts, earliest mismatched
   timestamp, fieldwise expected/actual values and evidence paths, plus a
   before/after SHA-256 inventory of all original configuration/output roots.
   An exact match of prepared indicators or chart payloads is **not** a pass
   for execution equivalence.

Only after both native-owner overlap resolution (PR #501 remains on HOLD)
and signed-off original trade-by-trade equivalence may the Phase 5 browser
execution/config-write release gates be reconsidered. Until then, preserve
the PySide6 fallback and disabled browser controls.
