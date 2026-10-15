# Browser read-only integration audit

**Audit date:** 2026-10-15  
**Scope:** browser shell → localhost HTTP adapter → existing CSL application/read services and completed outputs.  
**Result:** **PASS for read-only integration. Browser-controlled execution remains disabled.**

## Architecture verified

The browser migration currently follows one composition chain:

```text
React/TypeScript browser shell
  -> authenticated localhost GET API
  -> BrowserReadOnlyService
  -> existing GuiApplicationService / CatalogStatusService
  -> existing MarketDataStore / CacheLayout / DuckDB catalog
```

Completed-run and configuration reads delegate to the existing readers:

- `read_completed_run`
- `read_research_config`

The browser facade does not implement a second market-data store, archive discoverer, prepared-feature builder, strategy evaluator, execution engine, configuration schema, or report parser.

## Data Lake ownership

`build_browser_readonly_service` resolves the same runtime raw/cache roots as the existing desktop/control plane and constructs the existing `GuiApplicationService`. The browser receives that application's existing catalog facade.

Therefore:

- raw archives remain external/read-only,
- the canonical cache remains the existing `CacheLayout`,
- DuckDB catalog ownership remains unchanged,
- catalog refresh/discovery is not exposed by the browser facade,
- historical results are read, not rewritten.

## HTTP surface

The current API route inventory is locked by regression test to:

| Route | Method | Owner |
| --- | --- | --- |
| `/api/v1/health` | GET | local adapter |
| `/api/v1/catalog/symbols` | GET | existing catalog service |
| `/api/v1/catalog/coverage` | GET | existing catalog service |
| `/api/v1/runs/{run_id}` | GET | existing completed-run reader |
| `/api/v1/configs/{config_id}` | GET | existing config reader |

There are no browser API routes for run creation, engine execution, configuration writes, delete/update operations, trading, promotion, or live-bot actions.

`tests/test_browser_http.py::test_browser_api_route_inventory_is_read_only` fails if the API method/path inventory changes without an explicit test update.

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

## Execution gate

This audit certifies only **read-only composition**. It does not authorize adding POST/PUT/PATCH/DELETE routes or invoking the research/backtest engine from the browser.

Before browser-controlled execution can be enabled, Phase 5 must add guarded writes/job lifecycle and demonstrate frozen-fixture browser-vs-desktop configuration and trade parity through the existing engine.

PR #501 remains on hold until its pending-limit execution overlap is resolved.
