# Historical Strategy Visualizer V2 chart payload parity (operator-local gate)

The **engine** replay for frozen BTCUSDT 4h/1m has already passed. That does not by itself establish that the active V2 browser path returns the exact same historical chart payload as the canonical completed-run visualizer model. No frozen operator-local Data Lake artifacts are committed or downloaded by CI.

## Frozen run

Use completed run `BTCUSDT_4h_ad58a712d8e7492380b99ec96c20c80f` and the output/source identities recorded in `docs/browser_historical_parity_gate.md` and `docs/certification/browser_historical_replay_2026-10-15.json`.

The capture command below uses the existing completed-run reader and `CompletedRunVisualizer.load` on the canonical Data Lake. Those loaders fail closed if the run, manifest, source provenance, cache coverage, or required chart data cannot be verified. Do not substitute downloaded replacement candles or a second chart-data implementation.

## Active V2 scope

The V2 decision in PR #588 makes `StrategyVisualizerV2BrowserServer` the sole active visualizer. Parity therefore covers `CompletedRunVisualizer.build_v2_diagnostic_payload` and V2 `/api/payload` only.

The retired full visualizer's `/api/inspect`, S/R, VWAP and other inactive extras are **not** part of this gate. Add individual capabilities to V2 only when requested and certify each addition separately.

## Automated local capture

From the repository root on the workstation that holds the original saved run and canonical Data Lake:

```powershell
python -m crypto_strategy_lab.browser_v2_historical_parity
```

The command defaults to the frozen 79-trade BTCUSDT run and the established completed-run root (`CRYPTO_STRATEGY_LAB_OUTPUT_DIR` when set, otherwise `output/data_lake_v2`). An explicit root may be supplied only for the established local completed-run store:

```powershell
python -m crypto_strategy_lab.browser_v2_historical_parity `
  --run-id BTCUSDT_4h_ad58a712d8e7492380b99ec96c20c80f `
  --output-root ".\\output\\data_lake_v2" `
  --evidence-dir ".\\parity_verification\\v2_historical_chart"
```

The capture compares two independently loaded views of the same verified run:

1. the canonical desktop-side `CompletedRunVisualizer.load(...)` payload, and
2. the browser adapter + active V2 loopback HTTP `/api/payload` response.

It uses the existing strict comparator from `browser_chart_parity.py`; there is no numeric tolerance, field omission, or indicator reimplementation.

The representative matrix includes:
- first, middle and last trade;
- the first LONG and first SHORT as additional representatives when either side is not already covered;
- 1h, 4h and 1d where available, always including the strategy timeframe.

V2 always returns full-run candles together with the selected-trade view bounds, so a separate obsolete `full_run` query is not required.

## Evidence and PASS rule

Local evidence is written beneath `parity_verification/v2_historical_chart` by default:
- `desktop_trade_<index>_<tf>.json`;
- `browser_trade_<index>_<tf>.json`;
- `summary.json`.

Do **not** commit captured payloads, session URLs/tokens, local paths, caches, trades or other operator-local evidence.

Each case records canonical SHA-256 values for the desktop and browser payload. A PASS requires exact structural and value equality for every case. Any mismatch, unavailable required source, non-finite JSON value, malformed run, or provenance verification failure blocks certification.

Payload equality certifies the historical V2 data/geometry contract. Visual browser interaction (zoom, pan, resize and visible overlay behavior) still needs the already performed operator smoke checks and any future feature-specific UI checks.

## Certification decision

Historical browser chart parity remains **UNVERIFIED** until the frozen workstation command above returns PASS and the local `summary.json` evidence has been reviewed. This gate introduces no run creation, backtest execution, config write, canonical data/cache modification or permission to merge PR #501.
