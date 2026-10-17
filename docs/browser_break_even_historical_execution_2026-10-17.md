# Original Windows break-even execution parity — 2026-10-17

**PASS — frozen-prepared native execution at main
`01dc80ec9f299ed9e79b4785b069deff45192937` reproduces the independently saved
break-even reference exactly. Full browser migration certification remains blocked.**

Reference: `BTCUSDT_4h_33b1ccf4866744a3840152dc5184855a`, recorded at clean
revision `1ad8a2161877260d9f1d790f583a82e065f8730e`. Windows repository and
canonical Data Lake access were available; the checkout was fast-forwarded to
verified GitHub main before replay.

## Inputs and exact native comparison

The replay used the existing `PreparedRunCache.load`, canonical market-data
reader, `IntrabarExecutionData`, `NativeStrategyPolicy` and `NativeSimulator`.
Original configuration values were retained exactly; the sole added default,
`fib_structure_quality_mode="BASELINE"`, is recorded separately. Original files
were not rewritten. Reporters, browser jobs and configuration writes were not used.

| Check | Result |
| --- | --- |
| Original frozen prepared input | 14,610 rows; shared with the certified TP1 reference |
| Canonical execution window | 3,287,520 ordered, unique, aligned 1-minute rows; complete start/end coverage |
| Original source inventory | 2,956 records; raw stat identities and retained archive hashes agree |
| Native trades | 79 original / 79 replay |
| Native schema | 877 columns; identical column order and persisted dtypes |
| Native values | Exact equality for all 69,283 cells; zero tolerance, zero discrepancies |
| Recorded LONG break-even triggers | 40 / 40, with all trigger timestamps and stop levels present and matching |
| Trigger chronology | All 40 recorded triggers lie between entry and exit; no trigger/exit minute ties |
| Exits among triggered trades | 29 BE, 10 EMA crossover, one END_OF_DATA; all match |
| Accounting | Recorded quantities, entry/exit fees, realized R, gross/net P&L and before/after equity match |
| Trade fingerprint | Original manifest, original artifact and replay agree |

The current executor was not patched or forced into a historical strategy mode.
The recorded strategy is `EMA_9_20_PULLBACK`; its implementation is unchanged
between the original revision and tested main. Later shared scheduling,
checkpoint and S/R-state changes were inspected. They produce no differences
in this fixture's saved native execution evidence. This does not certify every
intermediate strategy state, other strategies or future revisions.

## Available evidence and limits

The authoritative comparison retains the complete native report. The existing
strict 15-field adapter separately reports 79 absent fixed-target prices and
79 absent per-trade slippage fields. Native target fields are blank on both
sides for this EMA-exit strategy; neither target prices nor slippage amounts
were fabricated. A complete 15-field normalized PASS is not claimed.

For the 29 BE exits, generic exit timestamps/prices and recorded leg quantities match.
Dedicated `long_stop_exit_*` fields are blank, as is `long_be_triggered_by_side`;
equality of those blanks is not evidence for unavailable event details.
The 39 untriggered trades are not counted as observed break-even activations.
Original telemetry was disabled and the registered rule trace contains zero
rows. Saved summary timestamps do not prove full intraminute event ordering or
real exchange tick order. No new trace substitutes for missing original history.

## TP1 reuse and preservation

The [existing TP1 certificate](browser_historical_replay_certification_2026-10-15.md)
was reused: its original/replay registered artifacts and fingerprint remain
valid, covering 79 trades including 40 LONG TP1 exits. Its certified executor
revision is `3a4b3cf489a0d0ccf5b2416c928a5f580df78153`; this report does not
renew TP1 against current main. No TP1, Fibonacci pending-limit or feature-
regeneration replay was repeated. The BE and TP1 source-provenance Parquets are
byte-identical, and their data, feature and strategy configurations agree.

All **2,836 original configuration/output files** and **3,156 frozen replay
inputs** remain unchanged, with no saved-output additions. All 2,956 raw archive
hashes match the retained TP1 freeze; all 3,150 inputs shared with the earlier
Fibonacci freeze also agree. Twenty existing exit/risk/telemetry regression
tests pass; synthetic tests are not historical evidence. No production fix was
needed. Only this aggregate report is committed.

Detailed comparisons, effective/original configuration snapshots, hashes,
coverage/missingness tables, candidate trades and orchestration remain local in
`parity_verification/be_historical_execution_2026-10-17`.

Remaining gates require genuine SL1/trailing execution evidence, full event
histories, an auditable per-trade slippage representation and separate guarded
browser-versus-desktop execution verification. **PR #501 remains on HOLD;
browser execution/configuration writes stay disabled and PySide6 remains supported.**
