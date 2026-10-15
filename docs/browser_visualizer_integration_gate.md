# Browser migration — existing Strategy Visualizer integration gate

**Status:** design and acceptance gate; browser-managed visualizer launch is not yet implemented or authorized.

## Reuse decision

The browser migration must **reuse** the existing `CompletedRunVisualizer` model in
`crypto_strategy_lab/strategy_visualizer.py` and the existing full browser visualizer in
`crypto_strategy_lab/strategy_visualizer_browser.py`. The desktop's
`StrategyVisualizerBrowserLauncher` already loads that model using a verified
completed run and serves read-only chart payload/inspector APIs from a short-lived
loopback-only session. The minimal V2 visualizer is a diagnostic, **not** a
replacement for the production chart.

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
4. Reuse the existing `StrategyVisualizerBrowserServer` or its
   rendering/payload contract. If integrating it into the shared localhost
   server, use an explicit adapter over the existing model methods; do not
   fork the JavaScript chart implementation or relocate visualizer state into
   React.
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

The browser currently supports authenticated read-only completed-run summaries,
configuration inspection and capability metadata. This milestone does **not**
enable run creation, research execution, strategy evaluation, trading, or
configuration writes. PR #501 remains on hold until its pending-limit
execution overlap is resolved.
