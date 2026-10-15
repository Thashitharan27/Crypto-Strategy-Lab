# Historical Strategy Visualizer chart payload parity (operator-local gate)

The **engine** replay for frozen BTCUSDT 4h/1m has already passed. That does not establish chart parity between the desktop-initiated and browser-initiated visualizer sessions. No frozen operator-local Data Lake artifacts are committed or downloaded by CI.

## Frozen run

Use the completed run `BTCUSDT_4h_ad58a712d8e7492380b99ec96c20c80f` and the original output/source hashes recorded in `docs/browser_historical_parity_gate.md` and `docs/certification/browser_historical_replay_2026-10-15.json`. Verify the manifest, source partition identities, saved trade fingerprints, and Data Lake cache provenance before collecting chart evidence.

## Capture

Both desktop and browser already invoke **the same** `CompletedRunVisualizer` model and `StrategyVisualizerBrowserServer`. Do not create new EMA/Fibonacci/inspector calculations for the comparison.

Open the run in the existing desktop Strategy Visualizer and collect the JSON from its loopback session `/session/<token>/api/payload` for an explicit, recorded query: trade index, chart timeframe, visible candles, full-run mode and rejection display. Use the new browser workspace's **Prepare visualizer session** button for the *same run*, and collect the corresponding JSON from that loopback session using the identical query.

The captured JSON must represent the **whole** payload, not cropped screenshots or selected indicators. Save both to local files outside the repository (for example `parity_verification/desktop_chart.json` and `parity_verification/browser_chart.json`). Do not commit session tokens, links, caches, trades, user paths or other credentials.

Run:

```powershell
python -m crypto_strategy_lab.browser_chart_parity parity_verification/desktop_chart.json parity_verification/browser_chart.json
```

The comparator exits 0 only on **exact structural and value equality** and prints two canonical SHA-256 hashes. Mismatches identify JSON paths (candle timestamps, overlays, Fibonacci geometry, EMA values, trade markers, risk/target boxes and all inspector fields). No numeric tolerance or omitted keys is silently permitted. If the payload includes non-finite JSON values, first fix the source serialization rather than hiding them in the comparator.

Repeat across: selected and all-trade views; 1h/4h/1D where available; first, middle and last trade; long and short where present; EMA and Fibonacci examples; SR and inspector timestamps. Chart UI/DOM rendering, zoom/pan behavior and on-screen geometry still require separate browser-level verification—equal JSON alone cannot certify pixel-level rendering or interaction.

## Certification decision

Until the frozen real-run captures and view-level comparisons are attached as **locally retained, verifiable evidence**, historical browser chart parity stays **UNVERIFIED**. This tool introduces no run creation, backtest execution, config write, canonical data/cache modification or permission to merge PR #501.
