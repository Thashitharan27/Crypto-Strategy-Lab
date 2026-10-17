# Milestone B — guarded browser integration plan

## Milestone B — guarded integration design (preparation only; not an authorization)

Baseline: Milestone A's finite gate remains binding, and A3 must be resolved or explicitly accepted before sign-off. This proposal changes no runtime code, API route, saved config, or engine execution. The current runtime is React/TypeScript -> authenticated localhost FastAPI -> BrowserReadOnlyService -> existing GuiApplicationService/catalog/completed-run readers. `browser_launcher.py` and `browser_http.py` remain read-only, aside from the separately authorized in-memory visualizer-session POST. Do **not** extend that POST to trading execution.

### Existing authoritative owners

- **Configuration schema, load and normalization:** `data_lake_config.py` ResearchRunConfig/StrategyConfig/FeatureConfig/ExecutionConfig and the existing `browser_config.read_research_config` read path; identify and call the native desktop persistence/validation method in `gui/v2_controller.py` rather than writing JSON from the FastAPI adapter.
- **Research setup, validation, execution, cancellation and run bookkeeping:** existing `gui/v2_controller.py` GuiApplicationService/GuiResearchRequest, native run lifecycle and `output_manager.py`/`run_manifest.py`; retain native source/cache identity, snapshots and event ordering. Do not implement a second backtester, pending-limit executor, candidate selector or fill-time calculator.
- **Completed results:** existing saved-run reader and V2 visualizer contracts, which do not imply write or execution authorization.
- **Overlap:** PR #501 remains OPEN/draft and **HOLD**. Its limit-touch helper must not become a new execution authority.

### Required, disabled-by-default implementation sequence

1. After Milestone A sign-off, trace the exact native desktop config save and research-run invocation methods, validation, cancellation and restart ownership in source; record call graph, effective config serialization, side effects and error behavior. No new public routes yet.
2. Add a distinct guarded service boundary that delegates to those methods, with a hard-off feature flag whose disabled state is enforced server-side (not just by hiding buttons). Retain current A-only route inventory and test that all future mutation routes are absent or rejected in A mode.
3. Implement negative and lifecycle contract tests on isolated temporary directories and frozen source frames: missing token, wrong host/origin, tampered ID, invalid schema, path escape, stale/duplicate submission, missing 1m data, interrupted process, cancellation, restart, atomic save and rollback. No Data Lake rebuild or market download.
4. Independently compare browser-invoked normalized effective configuration and ordered trades against the desktop-native owner on pinned representative long/short/entry/stop/partial/end-of-data cases; verify immutable snapshot, manifest, fees, slippage and accounting without broad strategy cross-product certification. Differences fail B2 until investigated.
5. Conduct operator-local Windows proof on original file paths **only after isolated CI safety passes**, preserve all saved artifacts, and obtain explicit release approval for B before enabling either execution or configuration writes. Keep PySide6 fallback intact.

### Exit criteria

B1: one authoritative execution/config owner and call graph; B2: browser-vs-desktop frozen trade and effective-config parity; B3: safe lifecycle and negative-case tests; B4: authenticated localhost/allowlist/audit review and explicit user approval. Any A3 unresolved status blocks A sign-off but does not block this documentation-only preparation. Avoid rerunning historical engines solely to refresh already verified A1/A2/A4/A5 evidence.
