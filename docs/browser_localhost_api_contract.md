# Phase 3: localhost read-only API contract

Status: design proposal, **not** an HTTP server or authorization to enable trading.

## Reuse
Build the future HTTP adapter against `BrowserReadOnlyService` (PR #514) and its existing catalog, verified completed-run reader and validated configuration loader. Do not create parallel manifest, strategy, or configuration parsers. Existing run and GUI formats remain authoritative.

## Proposed read-only endpoints
- `GET /api/v1/health`: application version and status only, no filesystem paths or secrets.
- `GET /api/v1/catalog/symbols?market=futures_um`: existing catalog symbols.
- `GET /api/v1/catalog/coverage`: validated request routed to existing catalog coverage logic.
- `GET /api/v1/runs/{run_id}`: verified completed manifest and summary from a *server-resolved* run directory under an explicitly configured output root; never accept a client filesystem path.
- `GET /api/v1/configs/{config_id}`: validated canonical v3 config from a *server-resolved* allowlisted configuration directory; never accept a client filesystem path.

## Safety requirements before enabling HTTP
- Listen only on `127.0.0.1`, with no `0.0.0.0`, remote tunnel or permissive CORS defaults.
- Require a per-launch non-static authorization token or equivalent origin/CSRF defense for reads of user files; reject untrusted Origin/Host and prevent DNS rebinding. Do not place secrets in URL parameters.
- Resolve run/config identifiers to server-owned paths; reject separators, traversal, symlinks escaping allowed roots, and missing/unfinished manifests. Validate resolved paths against allowed roots.
- Return bounded sanitized errors, strict typed responses, pagination and size limits. Do not leak absolute local filesystem paths, API keys, credentials or raw exception messages.
- Keep `POST`, `PUT`, `PATCH`, `DELETE`, catalog refresh, research runs, order placement and all live-bot operations inaccessible.
- Preserve `ResearchRunConfig` v3 and legacy load adapters; browser must not rewrite inputs when reading.
- A future FastAPI dependency must be isolated to the optional browser entrypoint, not pulled into the shared core or live bot.
- Before allowing any new execution capability, require real, frozen historical candle and 1-minute data plus full multi-leg trade parity evidence (timestamps, fees, stops, targets and account P&L).

## Verification plan
Use FastAPI's in-process test client for health, positive results, missing resources, and traversal/symlink/host/origin rejection. Prove no writes or engine/run calls using mocks. Include Windows smoke and Linux CI before merge.
