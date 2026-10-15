# Phase 4 Integrations — ownership and safety gate

Status: inventory and implementation gate, **not** certification that an integration is connected.

## Existing owners (reuse; do not duplicate)

| Capability | Existing code owner | Browser Phase 4 boundary |
| --- | --- | --- |
| ChatGPT / credential configuration | `crypto_strategy_lab/openai_credentials.py`, `crypto_strategy_lab/gui/chatgpt_connection_impl.py` | Desktop-owned. Do not expose secrets, API keys, environment variables, token previews, or browser credential editing. |
| Desktop auto-start / install wiring | `crypto_strategy_lab/gui/chatgpt_autostart_install.py`, `crypto_strategy_lab/openai_strategy_install.py` | Preserve native operations; do not launch installations or mutate configuration from read-only browser. |
| MCP/control integration | `docs/backtest_control_mcp.md` and existing control service | Maintain existing authenticated control-plane ownership; browser must not duplicate it or provide indirect execute/write routes. |
| Market-data integration | Existing `GuiApplicationService`, catalog, Data Lake paths and cache | Already projected through read-only browser catalog/coverage API. No second downloader, catalog writer, or Binance credentials. |
| Portfolio | Existing `portfolio_replay.discover_resilience_runs` through `BrowserReadOnlyService` | Only verified finalized-run metadata, authorized GET and bounded response. No replay or trading. |

## Browser Integrations section — initial scope

A read-only informational view may explain each integration's owner and whether the browser exposes a corresponding **read-only capability**. Do not infer actual connection/credential health from a listed Python module or a generic localhost health check.

If runtime integration statuses are later added, they must be obtained from an existing explicit provider with narrowly scoped metadata (e.g. capability name and supported read-only operations). No secrets, paths, connection strings, installed-service details, or live bot controls may cross the browser API.

## Release checks

1. Confirm launch/composition wiring separately from component-level tests: actual localhost binding, static assets, ephemeral bearer token, config/run allowlists and read-only fallback.
2. Preserve the fail-closed API route inventory (including the portfolio GET route); unexpected API methods/routes and mounts must fail tests.
3. Validate browser reconnect and session expiry handling without leaking prior integration state.
4. Do not introduce account linking, credential storage, plugin installation, automated execution, portfolio replays or trading actions until separately approved in Phase 5.
5. Keep PR #501 on hold until overlapping execution ownership is resolved.

This document does not change the native PySide6 application, Data Lake, serialized run configs, tests, existing results, or DMI live bot.
