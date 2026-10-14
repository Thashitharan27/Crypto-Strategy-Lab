# Frozen backtest baseline provenance (Phase 1b)

This is preparatory tooling, **not** a captured golden backtest or an assertion of trade parity.

`parity_fixture_manifest.frozen_fixture_manifest` computes SHA-256 hashes of explicitly supplied offline files and records the source commit and execution timeframes. It does not load market history, prove 1-minute coverage, or modify the Python simulator.

## First baseline prerequisites

- Preserve byte-identical offline strategy candles and 1-minute intrabar candles covering a small bounded BTCUSDT date range. Confirm causal warmup and source timestamps independently; freeze their hashes.
- Preserve the exact run configuration snapshot, Python baseline revision, and report outputs. `config/data_lake/BTCUSDT_4H_SMOKE.json` is a pre-existing smoke configuration, **not** itself a market-data fixture.
- Run the existing native engine against offline files; do not download mutable data or use the live trading service.
- Compare actual outputs at pair **and** individual leg level, including fill timestamps and partial exits. Use the read-only schema probe and CSV adapter where fields are genuinely available; do not invent a mapping for absent per-trade slippage.
- Start with a baseline DI run, then EMA and Fibonacci, including pending deeper limit, missing 1m data, and an exit on the fill bar. Any changed trade outcome blocks parity certification.

The manifest records fingerprints of supplied paths using logical file labels only; verify the hash again before comparing an updated implementation. A manifest by itself is not a substitute for frozen candle data, run execution, and comprehensive trade-level result comparisons.
