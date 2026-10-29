# Photon browser · Binance Futures

Launch **Photon Browser.bat** from the repository, or run:

```text
python -m crypto_strategy_lab.photon_live
```

This opens a separate browser workspace at a loopback address. The research
desktop application does not need to run; the browser service does not import
PySide6. Keep the launcher running while using the chart. Port 8917 is the default;
`--port` overrides it. `--symbol ETHUSDT` changes the initial market.

The light workspace places symbol/timeframe controls and Replay at the top,
drawing tools on the left, optional Photon and manual-trade panels on the right,
replay controls at the bottom, and range shortcuts/UTC clock below the chart.
It uses TradingView's open-source Lightweight Charts (with its attribution),
not the proprietary TradingView application or its logo.

## Market data and mapping

Public Binance USDⓈ-M Futures klines seed the chart. A browser WebSocket updates
the current candle. Closed-candle REST refreshes recover missed messages and
refresh structure. The connection status distinguishes streaming, polling and
errors. No account credentials are needed and no exchange orders are supported.

The same Photon close-confirmed mapping, ranges, zones, event inspector and
replay knowledge-time filters are reused. Unfinished live candles update price,
but cannot confirm structure. Replay retains its loaded snapshot and clock;
**Live** leaves replay and fetches current history again.

Initial history is bounded: 60 days of 15m source for 15m/4H mapping, 730 daily
candles for daily/weekly context, and three days of actual minute candles loaded
on demand for 1m. Therefore early structure and 1m state can differ from a
historical run seeded with a longer warmup. Missing earlier evidence stays
unknown. Daily zones born before the available 15m history are omitted because
their earlier visits cannot be established. Public candles are cached locally
under `cache/photon_browser`; closed structure is rebuilt from those candles.
Range shortcuts fit available history; they do not download additional
years. This is not a six-year backtest viewer.

## Included tools

Candles/structure/both views, developing legs, BOS/trend changes, internal
structure, strong/weak levels, premium/discount, supply/demand inspection and
lesson drawings, weekly/daily overview, layer/label controls, drawing tools,
manual replay plans and simulated trades, journal and JSON exports are retained.
Manual simulation uses the existing closed-candle replay rules and does not
represent exchange fills. Use Replay to enter and manage simulated positions.

EMA/RSI, possible-trade ideas, suggested setup plans and signal scores are hidden
and disabled in this workspace. Generic editable replay position boxes retain
their existing initial placeholder levels; set your own Entry/SL/TP before
confirming. Live order placement is absent.

Drawings and reviews are stored in this browser's local storage per symbol.
Use the same host/port and browser to retain them; exporting reviews/drawings
provides a portable copy. Clearing browser storage removes local records.
Binance and the pinned chart-library CDN must be reachable. A connection error
is shown instead of fabricated market data.

Binance stream reference:
https://developers.binance.info/docs/derivatives/usds-margined-futures/websocket-market-streams/All-Market-Mini-Tickers-Stream
