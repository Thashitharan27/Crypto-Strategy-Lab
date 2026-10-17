# Milestone B — guarded browser integration plan

## Milestone B — guarded integration design (preparation only; not an authorization)

Baseline: Milestone A's finite gate remains binding, and A3 must be resolved or explicitly accepted before sign-off. This proposal changes no runtime code, API route, saved config, or engine execution. The current runtime is React/TypeScript -> authenticated localhost FastAPI -> BrowserReadOnlyService -> existing GuiApplicationService/catalog/completed-run readers. `browser_launcher.py` and `browser_http.py` remain read-only, aside from the separately authorized in-memory visualizer-session POST. Do **not** extend that POST to trading execution.

### Existing authoritative owners

- **Configuration schema, load and normalization:** `data_lake_config.py` ResearchRunConfig/StrategyConfig/FeatureConfig/ExecutionConfig and the existing `browser_config.read_research_config` read path; identify and call the native desktop persistence/validation method in `gui/v2_controller.py` rather than writing JSON from the FastAPI adapter.
- **Research setup, validation, execution, cancellation and run bookkeeping:** existing `gui/v2_controller.py` GuiApplicationService/GuiResearchRequest, native run lifecycle and `output_manager.py`/`run_manifest.py`; retain native source/cache identity, snapshots and event ordering. Do not implement a second backtester, pending-limit executor, candidate selector or fill-time calculator.
- **Completed results:** existing saved-run reader and V2 visualizer contracts, which do not imply write or execution authorization.
- **Overlap:** PR #501 remains OPEN/draft and **HOLD**. Its limit-touch helper must not become a new execution authority.

### Required, disabled-by-default implementation sequence

1. During development (without waiting for consolidated Windows certification), trace the exact native desktop config save and research-run invocation methods, validation, cancellation and restart ownership in source; record call graph, effective config serialization, side effects and error behavior. No new public routes yet.
2. Add a distinct guarded service boundary that delegates to those methods, with a hard-off feature flag whose disabled state is enforced server-side (not just by hiding buttons). Retain current A-only route inventory and test that all future mutation routes are absent or rejected in A mode.
3. Implement negative and lifecycle contract tests on isolated temporary directories and frozen source frames: missing token, wrong host/origin, tampered ID, invalid schema, path escape, stale/duplicate submission, missing 1m data, interrupted process, cancellation, restart, atomic save and rollback. No Data Lake rebuild or market download.
4. Independently compare browser-invoked normalized effective configuration and ordered trades against the desktop-native owner on pinned representative long/short/entry/stop/partial/end-of-data cases; verify immutable snapshot, manifest, fees, slippage and accounting without broad strategy cross-product certification. Differences fail B2 until investigated.
5. Conduct operator-local Windows proof on original file paths **only after isolated CI safety passes**, preserve all saved artifacts, and obtain explicit release approval for B before enabling either execution or configuration writes. Keep PySide6 fallback intact.

### Exit criteria

B1: one authoritative execution/config owner and call graph; B2: browser-vs-desktop frozen trade and effective-config parity; B3: safe lifecycle and negative-case tests; B4: authenticated localhost/allowlist/audit review and explicit user approval. An unresolved A3 status prevents claiming A sign-off, but does not block isolated guarded development or tests while the normal browser remains read-only. Avoid rerunning historical engines solely to refresh already verified A1/A2/A4/A5 evidence.

## Source-verified integration contract (main `314db5ddb872`)

Inspection of the actual repository owners establishes these entry points:

| Concern | Native callable / current behavior | Guarded browser implication |
| --- | --- | --- |
| Native execution | `GuiApplicationService.run(request: GuiResearchRequest, config: ResearchRunConfig)` calls `config.validate()`, may consume a previously validated catalog snapshot, creates its existing `ResearchRunner` via `_runner(Path(config.reporting.output_dir))`, delegates to `runner.run(request.to_data_request(), config, ...)`, reports progress, and clears the store observer in `finally` | Delegate to the existing application service; never call another simulator directly. Preserve the validated-catalog optimization, reporting directory and progress observer lifecycle; isolate concurrency before exposing jobs |
| Configuration persistence | `GuiApplicationService.save_config(path, config)` validates then writes `json.dumps(config.to_dict(), indent=2)`. `GuiApplicationService.load_config(path)` delegates to `load_data_lake_config(path)` | Use native typed configuration validation and serialization. **Existing save is not atomic**: introduce a reviewed transactional wrapper, temp-file validation and replacement in an isolated approved directory before exposing the browser. Do not label existing direct save crash-safe |
| Existing browser runtime | `browser_launcher.build_browser_readonly_runtime` creates a shared `GuiApplicationService` in `BrowserReadOnlyService`, passes it to `BrowserVisualizerCoordinator`, and creates FastAPI via `create_browser_app`; runner is not invoked | Preserve current default path and route inventory. Do not route execution via the chart session coordinator |
| Existing HTTP permissions | `browser_http.create_browser_app` currently exposes authenticated read-only GET endpoints and only the explicit same-origin V2 visualizer-session POST | New capability routes must be wholly absent in A mode; separately gate *every* mutation action server-side, with least-privilege origin/host, tokens and operation audit |
| Existing read semantics | `BrowserReadOnlyService.research_config` delegates to `read_research_config`, and `completed_run` delegates to `read_completed_run` | Read and edit should share the native typed schema; never duplicate React defaults or parse stored results independently |

### Engineering sequence and bounded verification

1. Implement isolated native-owner adapter and typed request/config validation first. Preserve *default-disabled* operation through an explicit server policy not supplied by the web client. Add tests proving the read-only launcher never constructs a mutation-capable API route and client-supplied flags cannot override this policy.
2. Add transactionally safe config writes using the existing native serializer and approved config root, with atomic rename/rollback and original-file unchanged assertions on denied/error paths. Guard against existing-file symlink swaps, duplicate IDs and concurrent writes. Do not alter native serialized values or historical field names.
3. Implement bounded run-job lifecycle by calling the same `GuiApplicationService.run` path. Serialize incompatible use of its shared `store.progress_callback`; never concurrently mutate an application service's observer. Use isolated output directories, immutable effective-config snapshots and idempotent submit/cancel semantics.
4. Test negative auth/origin/Host, path escapes, bogus schema, missing 1m, injected runner failure, duplicate/stale submissions and restart behavior on frozen temporary fixtures. Keep the public launcher in read-only mode while building these tests.
5. Defer workstation-only original-data/browser-vs-desktop full run comparisons to consolidated certification. Do not use two direct native MCP invocations as evidence of independently tested browser handling. The user must approve release enablement explicitly.

### Known design hazards to resolve in code review

- The native `save_config` writes directly to the destination rather than through atomic replacement. A browser write endpoint must not invoke it on original saved paths without an additional safe transaction boundary.
- The native `run` assigns an observer to `self.store.progress_callback` and clears it in `finally`; concurrent jobs sharing that service could corrupt progress attribution.
- A browser feature flag hidden solely in TypeScript would not protect HTTP mutation paths; default-disabled policy must be enforced on the server regardless of UI.
- No live config-write/backtest HTTP route exists today. Guarded implementation must not weaken the existing exact route-inventory regression tests.

**Development-first release policy:** targeted tests on every change; actual full-suite raw pytest and required CI before each merge. Comprehensive Windows original-file certification is consolidated near final release, not required after every development PR. Safety and correctness failures remain immediate blockers; PR #501 remains held.
