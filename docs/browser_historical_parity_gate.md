# Browser migration: historical trade-parity evidence gate

**Status:** incomplete. This is a verification checklist, not a parity certificate or authorization to turn on browser-controlled execution.

## Candidate frozen run

- Candidate: `BTCUSDT_4h_ad58a712d8e7492380b99ec96c20c80f`
- Market/timeframe: BTCUSDT 4h strategy, 1m intrabar
- Historical window: 2020-06-01 through 2026-09-01
- Existing saved report: 79 trades; net P&L 495.7499228872264; ending equity 1495.7499228872264
- Pinned source revision from run manifest: `1ad8a2161877260d9f1d790f583a82e065f8730e` (manifest reports CLEAN_COMMIT, code_dirty=false)
- Saved trade CSV SHA-256: `14d0577968a9ee50916aa9b4d2431cec238812f5bc290f9b315531ff541eacbe`
- Saved trade Parquet SHA-256: `736c1673a468501ae42b25e4afdf036dfa8eb8b9c2449406341d3511258202f2`
- Saved summary SHA-256: `42d6a72dd14ebc7f07cb4a19bcc1a600c3f897019d9d5a8abcadc371d32948a9`

- Manifest catalog snapshot digest: `7b4858b0bc87b5abcfd433b4a3fd71b0b68e25384901ea3f228bb3bbcb699dac` (2,956 selected archives)
- 1m kline source signature: `466d8df2c10428df799fe90086f1ba3b3ae281265366703a7048ea82241bbbcd` (97 partitions)
- 4h kline source signature: `d1f459840ec70ad205e61af6c3a4cbf4d5414d8ebbf7bc9f7149bfa4b056d146` (102 partitions)
- Saved configuration schema: v3, including 1m intrabar ERROR-on-missing policy

These values identify existing evidence; they **do not** demonstrate reproduction on the migrated browser stack.

## Required checks before parity can be certified

1. Recover the complete frozen manifest, original strategy configuration and referenced market-data inputs, including all 1m intrabar history and their integrity digests. Record missing inputs explicitly; no synthetic replacements.
2. Verify the archived outputs against the manifest's exact SHA-256 values using an existing completed-run reader / parity adapter; do not add a second trade parser.
3. Replay on a separate output root under the pinned source/data/config/fee/slippage assumptions. The React frontend must not alter engine settings, indicator semantics or execution order.
4. Compare **trade by trade** with the existing native comparison tooling: entries, exits, timestamps, side, quantity, fees, P&L, stops, take profits, exit reason and 1m fill source. Compare aggregate totals only after all rows match.
5. Record every discrepancy by trade ID, identify whether the source is missing data, configuration drift, nondeterminism or an execution change, and fail closed rather than approving tolerances by eye.
6. Check saved configuration schema backward compatibility and ensure current desktop/app output remains usable. Include Windows smoke, Python safety and isolated React build.
7. Attach machine-readable diff, exact revisions and input/output hashes to the certification report; require an explicit **PASS** from the existing parity tooling.

## Execution gating

Until the above is complete, the browser stays strictly read-only. No run creation, trading or configuration writes. PR #501 remains on hold due to its limit-execution overlap. Never deploy changes to the live DMI bot as part of this milestone.
