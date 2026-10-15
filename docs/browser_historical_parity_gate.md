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

## Completed certification checks

The seven checks previously listed here were completed on 2026-10-15. The exact replay run/revision, source-freeze path, configuration hashes, trade fingerprint, prepared-cache identities, exact comparison dimensions and retained comparator paths are recorded in `docs/browser_historical_replay_certification_2026-10-15.md` and `docs/certification/browser_historical_replay_2026-10-15.json`.

The prepared dataframe was verified by exact row/column/cell comparison rather than by a separately computed dataframe content hash; the certificate records that fact explicitly instead of inventing a hash. Persisted original report artifacts retain their SHA-256 values, and the exact native trade comparison has a deterministic original/replay trade fingerprint. Any future renewal must fail closed on a discrepancy.

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

This schema audit was an intermediate pre-certification step. By itself it did **not** establish data-file integrity, engine replay or trade parity; those later checks are recorded in the 2026-10-15 replay certificate.


## Pre-certification saved source-provenance scan (historical record)

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
and mtime_ns** string, not a digest of archive contents. Therefore this metadata scan alone could not prove byte-identical market data.

**Completion record (2026-10-15):** the later operator-local freeze used `--include-all-saved-datasets`, selected all **2,956** saved source records (including **2,757** context records), hashed the actual local archive bytes under the existing freeze contract, and retained the manifest as `parity_verification/btc79-source-freeze.json`. The subsequent provenance comparison matched all 2,956 source records. No replacement candles were substituted.


## Offline file-content freeze procedure used for certification

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

The snippet above remains an illustrative API example. The actual certification used the catalog-backed freeze/verification tools rather than hand-maintained path labels. Its retained operator-local manifest is `parity_verification/btc79-source-freeze.json`, covering all 2,956 saved inputs. Any future missing archive, mismatched content, unexpected partition, or unknown mapping still blocks renewal. The pinned Git SHA describes the archived run and is distinct from the replay revision recorded in the certificate.


## Complete saved-run source inventory: dataset-scope check completed

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

By default, `freeze_browser_parity_catalog_inputs.py` and `verify_browser_parity_provenance.py` verify **only the 199 4h/1m kline archive records**. Default-mode success must **never be interpreted as verification of the full 2,956-record original source set**. For this certification the explicit `--include-all-saved-datasets` path was used: all **2,956** original saved source identities were selected and their actual local archive bytes were covered by the freeze contract. The later prepared-frame comparison then matched all **14,610 × 464** values exactly, which independently verifies the effective prepared feature result for the replay. Source-inventory coverage and trade parity remain separate evidence classes in the certificate.


### Confirmed original feature dependencies (from saved run manifest)

The original `run_manifest.json` feature-provider provenance explicitly lists `basis_context` using `klines`, `mark_price_klines` and `index_price_klines`; `funding_context` using `klines` and `funding_rate`; `futures_positioning` using `klines` and `metrics`; and `taker_flow_context` using `klines` (its provider parameter specifies `5m`). Other saved feature providers include core directional, 1D Ichimoku, support/resistance, and daily state transitions. This established that the baseline **prepared feature set** referenced several non-4h/1m datasets. The certification therefore did not reduce the freeze scope: it used the full saved source inventory. The replay subsequently matched all 12 feature-provider identities, all 14,610 × 464 prepared values and all 79 × 877 native trade values exactly.
