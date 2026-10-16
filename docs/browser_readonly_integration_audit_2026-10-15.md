# Browser read-only integration audit

**Audit date:** 2026-10-15  
**Scope:** read-only browser components and their service boundaries: React client contract, localhost HTTP adapter, BrowserReadOnlyService, existing CSL application/read services, and completed-output readers.  
**Result:** **PASS for component-level read-only boundary reuse. Production browser composition/wiring is not yet certified, and browser-controlled execution remains disabled.**

## Architecture verified

The intended read-only composition chain is:

```text
React/TypeScript browser shell
  -> authenticated localhost GET API (and explicit in-memory V2 session launch)
  -> BrowserReadOnlyService
  -> existing GuiApplicationService / CatalogStatusService
  -> existing MarketDataStore / CacheLayout / DuckDB catalog
```

Completed-run and configuration reads delegate to the existing readers:

- `read_completed_run`
- `read_research_config`

The audited components do not implement a second market-data store, archive discoverer, prepared-feature builder, strategy evaluator, execution engine, configuration schema, or report parser.

**Current-state correction (2026-10-15):** `crypto_strategy_lab/browser_launcher.py` now provides `build_browser_readonly_runtime` and `run_browser_readonly`, composing the existing read service, authenticated HTTP adapter, visualizer coordinator, static browser assets and runtime token. `tests/test_browser_launcher.py` covers service composition, configured paths, loopback-only binding and an authorized read-only API/static test. This supersedes the earlier statement that the repository lacks an entry point. **It does not certify end-to-end execution on the user's Windows installation**, representative local saved-run/portfolio behavior, or visual/browser parity; those remain separate operator gates.

## Data Lake ownership

`build_browser_readonly_service` resolves the same runtime raw/cache roots as the existing desktop/control plane and constructs the existing `GuiApplicationService`. The browser receives that application's existing catalog facade.

Therefore:

- raw archives remain external/read-only,
- the canonical cache remains the existing `CacheLayout`,
- DuckDB catalog ownership remains unchanged,
- catalog refresh/discovery is not exposed by the browser facade,
- historical results are read, not rewritten.

## HTTP surface

The current API is composed with optional dependencies. The read-service GET route inventory is asserted exactly by `tests/test_browser_http.py::test_browser_api_route_inventory_is_read_only` (without a visualizer coordinator). When a coordinator is wired, `tests/test_browser_http_visualizer.py::test_visualizer_route_is_the_only_explicit_non_get_api_operation` now asserts the complete authorized inventory, including the one permitted visualizer-session POST, and rejects unreviewed coordinator-only GET additions:

| Route | Method | Owner |
| --- | --- | --- |
| `/api/v1/health` | GET | local adapter |
| `/api/v1/capabilities` | GET | authoritative strategy/feature registry projection |
| `/api/v1/catalog/symbols` | GET | existing catalog service |
| `/api/v1/catalog/coverage` | GET | existing catalog service |
| `/api/v1/portfolio/candidates` | GET | existing verified resilience-run discovery, metadata projection only |
| `/api/v1/runs/{run_id}` | GET | existing completed-run reader |
| `/api/v1/configs/{config_id}` | GET | existing config reader |
| `/api/v1/visualizer/sessions/{run_id}` | POST (optional) | explicitly authorized, same-origin in-memory V2 session launch via existing coordinator; **not research execution** |

There are no browser API routes for research/backtest run creation, engine execution, configuration writes, stored-run mutation, trading, promotion, or live-bot actions. The optional POST starts a *read-only visualizer HTTP session* for an already verified completed run; it is not a research job or write endpoint. It additionally requires a runtime bearer token and exact same-origin `Origin`. A supplied `Sec-Fetch-Site` header must equal `same-origin`, but clients omitting that optional header are accepted; the header is not a mandatory authorization condition. Its session is stopped on replacement or application shutdown.

Both route inventories are exact: the read-service-only app and the coordinator-enabled app. Any new route requires explicit test review and certification.

## Local security boundary

The adapter retains:

- high-entropy runtime bearer token requirement,
- localhost/127.0.0.1 Host restriction,
- local HTTP Origin restriction,
- no OpenAPI/docs routes,
- path allowlists for run/config identifiers,
- bounded supported market/timeframe inputs,
- client-side read-only path allowlist,
- `cache: no-store`,
- omitted browser credentials,
- redirect rejection.

These controls protect the read-only local interface; they are not a substitute for future write-operation authorization.

## Existing-output compatibility

The browser completed-run path delegates to `read_completed_run` and does not reinterpret the native 877-column trade schema. Configuration reads delegate to the current ResearchRunConfig-compatible reader. The historical replay certificate separately proves that the current engine/data path can reproduce the original 79-trade BTCUSDT baseline.

## Remaining integration and execution gates

This audit certifies only the **read-only component boundaries and reuse contracts** listed above. The repository now includes `browser_launcher.py` and `tests/test_browser_launcher.py`, which cover runtime composition, static assets, token-authenticated read-only API operations and loopback binding. These tests **do not** establish operator-local historical browser certification or authorize any additional POST, PUT, PATCH or DELETE operations, configuration writes, or research/backtest execution. The sole currently permitted POST is the already-tested, in-memory, read-only visualizer session launch described above.

The next gate is to run the **existing** V2 historical chart parity command described in `docs/browser_chart_payload_parity_operator_gate.md` against the canonical saved workstation run and inspect its evidence, alongside a practical browser session check for saved configurations and finalized-run Portfolio discovery. Do not duplicate the existing launcher, historical parity comparator, or Data Lake readers.

Phase 5 guarded writes/job lifecycle remains blocked pending explicit authorization and complete browser-versus-desktop parity certification through the existing engine.

PR #501 remains on hold until its pending-limit execution overlap is resolved.
