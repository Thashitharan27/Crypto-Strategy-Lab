# Candidate historical regression baseline: BTCUSDT 4h / 1m

**Status:** source discovery only; **not** frozen input data, a rerun, or a passing parity comparison.

The existing Crypto Strategy Lab completed-run catalog exposes this verified manifest-backed run:

- Run folder: `BTCUSDT_4h_ad58a712d8e7492380b99ec96c20c80f`
- Run ID: `ad58a712d8e7492380b99ec96c20c80f`
- Symbol: BTCUSDT, USD-M futures
- Requested history: 2020-06-01 00:00 UTC to 2026-09-01 00:00 UTC
- Strategy candles: 4h; intrabar execution: 1m
- Existing completed-run trade count: 79
- Recorded source code commit: `1ad8a2161877260d9f1d790f583a82e065f8730e`
- Reported reproducibility status: `REPRODUCIBLE`
- Verified registered trade CSV: `trade_list.csv`, SHA-256 `14d0577968a9ee50916aa9b4d2431cec238812f5bc290f9b315531ff541eacbe`
- Verified registered parquet trades: `artifacts/trades.parquet`, SHA-256 `736c1673a468501ae42b25e4afdf036dfa8eb8b9c2449406341d3511258202f2`
- Verified registered source-archive provenance: `provenance/source_archives.parquet`, SHA-256 `2dd62b253e59afa83e834b3c62f19de638c86206b149300f238db6fc8f2faffa`
- Verified registered summary: `summary.json`, SHA-256 `42d6a72dd14ebc7f07cb4a19bcc1a600c3f897019d9d5a8abcadc371d32948a9`

## Before treating this as a golden fixture

1. Materialize the immutable strategy and 1m source inputs (or canonical prepared frames) with their hashes, exact source catalog and warmup policy. A run manifest alone is not the candle fixture.
2. Export the complete validated run manifest, config, source archive inventory, trade CSV, parquet legs and summary to an **offline, access-controlled fixture store** (avoid committing large market datasets or user file paths to GitHub).
3. Inspect native paired versus per-leg trade semantics, including actual fill timestamps versus strategy signal time, partial exits, fees, slippage representation, stop/target changes and end-of-data exits.
4. Rerun at the pinned engine commit in an isolated environment against the same input hashes, then compare every supported field and summary metrics with strict causal consistency.
5. Repeat on the current engine only as a separate compatibility measurement, never overwrite the historical source result.
6. Add blocking CI with a documented, small, redistributable fixture after data provenance and distribution rights are verified.

Do not treat the matching `trade_count=79` in other runs as evidence of equality: execution hashes differ. Do not merge held PR #501 or change any live bot or trading path.
