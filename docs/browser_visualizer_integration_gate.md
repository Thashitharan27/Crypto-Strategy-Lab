# Browser migration — existing Strategy Visualizer integration gate

**Status (2026-10-16):** read-only browser-managed visualizer launch and localhost guards are implemented. The active visualizer is V2 (operator selection in #588), and the frozen BTCUSDT 4h chart-payload comparison is **operator-reported PASS (9/9)**. Independent inspection of the retained local `summary.json` and raw payloads remains **PENDING**; browser-controlled execution and configuration writes remain disabled.

## Reuse decision

The browser migration must **reuse** the existing `CompletedRunVisualizer` model in
`crypto_strategy_lab/strategy_visualizer.py`. The active browser surface is
`StrategyVisualizerV2BrowserServer` and its `build_v2_diagnostic_payload` / `/api/payload`
contract, as selected in #588. The fuller original visualizer remains source-only
for compatibility and reference, not an active parity target. Retain the verified
completed-run loading, local session lifecycle and read-only service delegation.

No React implementation of candle aggregation, entry/SL/TP geometry, Fibonacci
overlays, strategy indicators, rule inspection, provenance checking or trading
statistics should be introduced.

## Required runtime composition

1. Resolve a run ID only against the existing `OUTPUT_DIR / "data_lake_v2"`
   completed-run root (or its established configured override). Never accept
   an arbitrary filesystem path or follow a symlink outside that root.
2. Validate the saved completed run using the canonical
   `CompletedRunReader`, including its manifest/artifact allowlist and
   completion checks. Reject missing, partial, or malformed runs.
3. Construct `CompletedRunVisualizer.load(existing_application_service,
   run_dir, validated_manifest)`, preserving the canonical market-data store,
   partition verification, provider identities, trade annotations and existing
   chart loading rules. Do not create an independent Data Lake store/reader.
4. Reuse the active `StrategyVisualizerV2BrowserServer` / `build_v2_diagnostic_payload`
   implementation. If adapting the shared localhost server, delegate to the
   existing model methods; do not fork chart computation or relocate visualizer
   state into React.
5. Browser session creation must be an explicit, authenticated user action.
   It must not occur on GET requests, React render, page refresh or speculative
   prefetch. Any session-start operation is **not** trading execution or a
   persisted configuration write, but it requires a separately reviewed
   lifecycle/security contract before it is exposed.
6. Session URL/token handling must be local-only and protected against remote
   hosts, malicious origins, cross-user session leakage, and unrelated browser
   requests. Keep session credentials separate from the main browser token.
   Limit active sessions and enforce deterministic stop/cleanup on replacement,
   server shutdown and failures.
7. Keep the existing visualizer self-contained on a random loopback port unless
   same-origin serving has been proven necessary and safe. Avoid creating a
   second long-lived browser-control API service solely for chart rendering.

## Certification tests before enabling the UI entry

- Existing completed run and manifest accepted; arbitrary path traversal,
  symlink escapes, incomplete runs and missing artifacts rejected.
- Same saved run has identical trade selection, chart window/candle timestamps,
  entry/exit/SL/TP annotations, Fibonacci zones, EMA overlays, inspector
  payloads and source-provenance verification as the existing desktop-launched
  visualizer.
- Browser session starts **only** after an explicit authenticated user action;
  cannot be triggered by a cross-origin request.
- Session token is unpredictable and scoped to the visualizer session; URL
  handling does not expose the main application bearer token.
- Shutdown and replacement stop the old loopback server and release its port.
- Linux tests, Windows launcher smoke, and React build pass at the PR head.
  Existing run configs, caches, native trade artifacts and live bot stay
  byte-for-byte untouched.

## Current scope boundary

The browser supports authenticated read-only completed-run summaries,
configuration inspection, capability metadata and an explicit verified-run
visualizer launch. The chart remains the existing Python visualizer. This milestone does **not**
enable run creation, research execution, strategy evaluation, trading, or
configuration writes. PR #501 remains on hold until its pending-limit
execution overlap is resolved.

## Remaining operator-local parity evidence

The in-process and loopback tests confirm delegation and protocol/lifecycle behavior,
not numerical parity on a real BTCUSDT historical run. Before calling the browser
visualizer certified, run the same completed run and trade selection through the
existing desktop-launched visualizer and the new browser action against the
frozen canonical Data Lake source. Compare selected trade, displayed candle
open timestamps, timeframe switching, full-run/selected view, EMA/Fibonacci/SR
layers, markers, entry/stop/target geometry, and inspector payloads. Record
immutable source and prepared-data identities and any differences. Do not
change the backtest engine to make a chart match.

## V2 primary decision (2026-10-15)

The operator selected the existing **V2 diagnostic visualizer** as sufficient for current use. The browser session owner now launches `StrategyVisualizerV2BrowserServer`, and the desktop sidebar exposes one visualizer entry that also launches V2. The fuller original browser visualizer remains in source temporarily for compatibility and possible feature reference, but is no longer the active UI. Do not migrate its S/R, VWAP, or inspector features automatically; implement individual capabilities only when requested. V2 parity certification must use `build_v2_diagnostic_payload` and its `/api/payload` endpoint; the original `/api/inspect` parity requirement is no longer a launch gate for the selected V2 scope. The 2026-10-16 frozen-run command is operator-reported **PASS (9/9)** for trades
0, 39 and 78 at 1h, 4h and 1d, as documented in
`docs/browser_chart_payload_parity_operator_gate.md`. Independent review of the
retained workstation `parity_verification/v2_historical_chart/summary.json` and
raw captures remains pending. Neither the operator-reported result nor this
status correction authorizes write/execution endpoints.
