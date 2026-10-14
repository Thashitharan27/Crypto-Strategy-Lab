# Browser UI foundation

Read-only React/TypeScript shell for the eventual local browser migration. Run `npm install` then `npm run build` from this directory. Dev server binds to `127.0.0.1` only. This shell deliberately does not start the FastAPI app or expose any backtest/write controls. Reuse the existing browser trade visualizer instead of rebuilding its rendering and chart data model. Do not distribute the dev server or connect it to live trading.
