# Browser UI foundation

Read-only React/TypeScript shell for the local browser migration. The browser runtime reuses the existing CSL Python application/read services, Data Lake/cache, completed-run reader, and configuration reader. It does not expose backtest execution or configuration writes.

Build and launch the local read-only workspace:

```text
cd browser_ui
npm install
npm run build
cd ..
python -m pip install -r browser_ui/requirements.txt
python -m crypto_strategy_lab.browser_launcher
```

The launcher binds only to `127.0.0.1`, creates a fresh per-launch bearer token, serves `browser_ui/dist`, and prints the local URL and token in the terminal. Enter that token into the browser shell's local-session field. The token is never placed in the URL.

Environment overrides intentionally reuse the existing control-plane contracts:

- `CRYPTO_STRATEGY_LAB_RAW_ROOT`
- `CRYPTO_STRATEGY_LAB_CACHE_DIR`
- `CRYPTO_STRATEGY_LAB_OUTPUT_DIR`
- `CRYPTO_STRATEGY_LAB_CONFIG_DIR`

Reuse the existing browser trade visualizer instead of rebuilding its rendering and chart data model. Do not distribute this local server, bind it to a remote interface, or connect it to live trading. Browser-controlled execution remains disabled.
