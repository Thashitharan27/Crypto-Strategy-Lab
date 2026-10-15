# Browser migration: historical trade-parity evidence gate

**Status:** historical engine replay certified PASS on 2026-10-15. See `docs/browser_historical_replay_certification_2026-10-15.md`. This still does **not** authorize browser-controlled execution.

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

These values identify the frozen baseline. The existing CSL engine replay has now reproduced the source inventory, prepared frame, provider identities and native trades as recorded in `docs/browser_historical_replay_certification_2026-10-15.md`. No browser execution path was used or enabled.

## Required checks before parity can be certified

1. Recover the complete frozen manifest, original strategy configuration and referenced market-data inputs, including all 1m intrabar history and their integrity digests. Record missing inputs explicitly; no synthetic replacements.
2. Verify the archived outputs against the manifest's exact SHA-256 values using an existing completed-run reader / parity adapter; do not add a second trade parser.
3. Replay on a separate output root under the pinned source/data/config/fee/slippage assumptions. The React frontend must not alter engine settings, indicator semantics or execution order.
4. Compare **trade by trade** with the existing native comparison tooling: entries, exits, timestamps, side, quantity, fees, P&L, stops, take profits, exit reason and 1m fill source. Compare aggregate totals only after all rows match.
5. Record every discrepancy by trade ID, identify whether the source is missing data, configuration drift, nondeterminism or an execution change, and fail closed rather than approving tolerances by eye.
6. Check saved configuration schema backward compatibility and ensure current desktop/app output remains usable. Include Windows smoke, Python safety and isolated React build.
7. Attach machine-readable diff, exact revisions and input/output hashes to the certification report; require an explicit **PASS** from the existing parity tooling.

## Execution gating

The historical engine replay gate is complete, but the browser stays strictly read-only until the later guarded-write/browser-execution phases are separately certified. No run creation, trading or configuration writes are authorized by this certificate. PR #501 remains on hold due to its limit-execution overlap. Never deploy changes to the live DMI bot as part of this milestone.


## Native BTCUSDT report-schema audit (read-only)

The archived `trade_list.csv` exposed by the completed-run report reader has **877 columns**. The following are confirmed native column names, not normalized parity mappings:

| Evidence category | Existing native columns |
| --- | --- |
| Identity and side | `pair_id`, `trade_id`, `side`, `result_type` |
| Signal chronology | `signal_candle_time`, `signal_available_at` |
| Entry/exit chronology | `entry_time`, `actual_entry_timestamp`, `exit_time` |
| Entry price | `entry_price`, `actual_entry_price` |
| Pair-level accounting | `pair_total_fees`, `pair_net_pnl`, `pair_net_r` |
| Leg-level accounting | `long_quantity`, `long_total_fees`, `long_net_pnl`, `long_final_exit_reason` (with corresponding side-specific fields only where verified) |
| Partial fills | `long_tp1_exit_time`, `long_tp1_fees`, `long_tp2_exit_time`, `long_stop_exit_time` |

**Blocking mapping distinction:** The strict normalized contract in
`crypto_strategy_lab/trade_parity.py` requires `trade_id`, `side`,
`signal_time`, `entry_time`, `exit_time`, `entry_price`, `exit_price`,
`quantity`, `stop_price`, `target_price`, `exit_reason`, `fees`,
`slippage`, `realized_r`, and `pnl`. Do not silently map pair-level
accounting to leg-level quantities, or use signal candle open time as a
substitute for the actual signal timestamp. A dedicated per-trade
`slippage` column was **not identified** in the sampled report header;
do not construct one from global fee/slippage configuration. Until each
semantic mapping is independently established, the canonical 15-field
trade comparison must fail closed. Pair/leg and partial-exit comparisons
must use the existing native schema probe and trade adapters, not a
parallel parser.

This audit identifies schema evidence only, **not** actual data-file
digest verification, engine replay, or trade parity.


## Full saved source-provenance scan (metadata only)

An exhaustive read of `provenance/source_archives.parquet` in run
`BTCUSDT_4h_ad58a712d8e7492380b99ec96c20c80f` returned all **2,956**
records (not truncated). The `klines` / `1m` subset contains **97** rows
with **97 distinct** `canonical_partition_identity` values. All 97 rows
have a nonempty `raw_archive_fingerprint`, `period_start`, and
`period_end`. The minimum period start is `2020-06-01T00:00:00Z`;
the maximum period end is `2026-09-01T00:00:00Z`.

When ordered by start time, the 1m source-period metadata has no
positive calendar gap between consecutive listed ranges, but it has
**two overlapping ranges**. Such overlap can represent selected archive
partition structure, not necessarily duplicate candles; the raw records
must be independently de-duplicated and validated before replay.
IMPORTANT: `raw_archive_fingerprint` comes from the existing
`data.cache.stat_fingerprint`: SHA-256 of the resolved **local path, size,
and mtime_ns** string, not a digest of archive contents. Therefore even
a matching source fingerprint is only metadata equivalence and cannot
prove byte-identical market data. No raw source file was accessed here. No local archive file was opened or hashed in this scan.

**Next blocking check:** identify and open the 97 actual local source
archives under a server-owned data root, verify each file against the recorded stat fingerprint and expected
size where the original path is known; additionally compute and freeze
real content hashes (using existing `parity_fixture_manifest.file_fingerprint`)
from the actual archive bytes. Confirm timestamp/candle coverage and
overlap handling, then freeze the complete 1m/4h inputs before replay. Do not substitute newly downloaded candles for missing archives.


## Offline file-content freeze procedure (operator-owned local data)

The completed-run connector exposes `provenance/source_archives.parquet`,
but **does not expose the raw Binance ZIP inputs**. Do not infer local
paths from the report, fetch replacement candles, or certify integrity
from `raw_archive_fingerprint`.

On a machine with the original 1m and 4h archive files, construct an
explicit mapping of stable logical labels to local archive paths. Use
existing utilities without a new archive reader:

```python
from crypto_strategy_lab.parity_fixture_manifest import (
    frozen_fixture_manifest, verify_frozen_fixture_files,
)
# Substitute the actual original paths; these are illustrative labels only.
files = {
    "BTCUSDT_1m_partition_0001": "/original/data/partition-0001.zip",
    "BTCUSDT_4h_partition_0001": "/original/data/4h-partition-0001.zip",
}
manifest = frozen_fixture_manifest(
    commit_sha="1ad8a2161877260d9f1d790f583a82e065f8730e",
    files=files,
    strategy_timeframe_minutes=240,
    intrabar_timeframe_minutes=1,
)
verify_frozen_fixture_files(manifest["files"], files)
```

This is an API usage example, **not** an executed verification. An
operator must include the complete, provenance-matched source set, use
the true paths, persist the manifest to a separate immutable artifact,
and confirm 1m coverage, duplicate handling and configured policies.
Any missing archive, mismatched content, unexpected partition, or
unknown mapping blocks replay certification. The pinned Git SHA
describes the archived run; it must not be mistaken for a check that
the source code checkout is currently at that revision.


## Complete saved-run source inventory: outstanding dataset-scope check

A fresh full read of the original `run_manifest.json` catalog and all 2,956 rows of `provenance/source_archives.parquet` confirms the following saved-run inputs, **not just** the 4h/1m strategy/execution candle archives:

| Dataset / interval | Original source records |
| --- | ---: |
| klines / 4h | 102 |
| klines / 1m | 97 |
| klines / 1h | 98 |
| klines / 5m | 98 |
| index_price_klines / 4h | 98 |
| mark_price_klines / 4h | 98 |
| premium_index_klines / 4h | 98 |
| funding_rate / n/a | 76 |
| metrics / n/a | 2,191 |
| **Total** | **2,956** |

By default, `freeze_browser_parity_catalog_inputs.py` and `verify_browser_parity_provenance.py` verify **only the 199 4h/1m kline archive records**. Default-mode success must **never be interpreted as verification of the full 2,956-record original source set**. With the explicit `--include-all-saved-datasets` freeze option and the subsequent saved-provenance cross-check, the tools can verify **all 2,956 original source metadata identities** and hash their actual local archive bytes. This does **not** by itself certify prepared features, candle data, or 79-trade replay parity. Before replay certification, inspect the original run configuration and prepared feature dependencies to classify the other 2,757 source records as required, unused, or conditionally used, and freeze all **required** inputs using the existing catalog and file-hash contracts; do not automatically exclude higher-timeframe/context/funding/metrics datasets. Keep the source-inventory coverage certificate distinct from the trade-parity certificate. If any required source remains unidentified, local or browser replay certification is blocked.


### Confirmed original feature dependencies (from saved run manifest)

The original `run_manifest.json` feature-provider provenance explicitly lists `basis_context` using `klines`, `mark_price_klines` and `index_price_klines`; `funding_context` using `klines` and `funding_rate`; `futures_positioning` using `klines` and `metrics`; and `taker_flow_context` using `klines` (its provider parameter specifies `5m`). Other saved feature providers include core directional, 1D Ichimoku, support/resistance, and daily state transitions. This is evidence that the baseline **prepared feature set** referenced several non-4h/1m datasets; it is not yet proof that every provider changed one of the 79 trade outcomes.

Classify dependency relevance using the pinned configuration and original feature-provider graph before reducing the freeze scope. Preserve existing feature caches and canonical loader behavior. If verifying the exact original prepared frame, include every archive required to reproduce it, even if a particular execution rule would not directly use every feature.
