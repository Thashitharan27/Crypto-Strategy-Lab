# Crypto Strategy Lab

Desktop research and backtesting application for directional cryptocurrency strategies using Binance OHLCV data.

## Filtered direction flip

The DI Direction Selection panel includes **Flip direction after filters pass
(Long ↔ Short)**. Filters are evaluated against the original DI-selected
direction. When the signal passes, the backtester opens only the opposite side.

Example: enable DI-direction selection with Preferred Side Only execution, set
the ADX filter to `ADX <= Maximum` with a maximum of `10`, then enable the flip.
An eligible DI Long becomes a Short; an eligible DI Short becomes a Long.

Each strategy profile has one **Entry Rules** table. Every row chooses an
action (Flip or Reject), indicator, Inside/Outside condition, and range. Flip
and Reject groups each have an Any (OR) / All (AND) selector. Reject rules are
evaluated first, followed by Flip rules; signals matching neither trade in the
normal DI direction. Use **Add rule** or **Remove selected** to manage any
number of rules.

## DI Direction & Pressure

DI direction selects Long when +DI is above -DI and Short when -DI is above
+DI. The optional pressure analysis records whether the selected directional DI
is expanding, contracting, or mixed over a configurable lookback. This is
record-only telemetry and never filters a trade.

DI spread acceptance remains configured separately in **Strategy Profiles →
Rules → DI Spread**. The indicator analysis workbook includes direction,
regime, pressure-state, and DI-spread-change performance tables.

## Start the application

On Windows, double-click the normal no-console launcher:

```text
Crypto Strategy Lab.vbs
```

It starts `.venv\Scripts\python.exe app.py` from the project directory and asks
Windows Script Host to keep the process window hidden. This uses the same Python
runtime as the terminal launch, including when the directory path contains spaces.
Startup errors are displayed in a GUI dialog. `Debug Launcher.bat` is available
for troubleshooting only; it intentionally opens a console so Python diagnostics
remain visible.

Or launch the same runtime from a terminal:

```powershell
.\.venv\Scripts\python.exe app.py
```

For a new environment:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt pytest
python app.py
```

## Main workflow

1. In **Backtest Setup**, choose the Binance pair and strategy timeframe.
2. Enable intrabar data when lower-timeframe exit ordering is required.
3. Use the separate `C:\CryptoBots\Binance Data Hub` application to create or update shared candle files.
4. Configure Bull Long, Bull Short, Bear Long, Bear Short, Sideways Long, and Sideways Short under **Strategy Profiles**.
5. Save the configuration and run the backtest.
6. Review the Summary, Trades, Charts, and generated output folder.

Crypto Strategy Lab reads Binance USD-M Futures candles from `C:\CryptoBots\Binance Market Data\futures\usdm`. Downloading is handled by the separate Binance Data Hub so it can continue in the background and serve every bot. The older Spot cache is kept isolated and is not selected.

## Portfolio workflow

The **Portfolio** tab accepts a dynamic list of assets. Each enabled asset uses its own saved strategy configuration while sharing one account.

- Base risk is configured per asset.
- Maximum Total Portfolio Risk is a hard entry limit and defaults to 5%.
- Entries that would exceed that limit are blocked and reported.
- Portfolio output includes accepted trades, blocked candidates, realized equity, mark-to-market equity, monthly/yearly results, and component contribution.

## Project structure

```text
.github/                  GitHub Actions workflows
.vscode/                  Repository-local editor settings
config/                   Current saved strategy configurations
crypto_strategy_lab/      Installable application package
  gui/                    Interface, profile editor, and background workers
  config.py               Backtest configuration model
  engine.py               Trade simulation engine
  portfolio.py            Shared-equity portfolio replay
  strategy_profiles.py    Six market-regime strategy profiles
  loader.py               OHLCV loading and validation
  output_manager.py       Reports and run-folder management
docs/                     Implementation and design documentation
mcp_server/               Read-only report MCP server
tests/                    Automated regression suite
tools/                    Offline import and maintenance utilities
Crypto Strategy Lab.vbs   Normal no-console Windows launcher
Debug Launcher.bat        Console launcher for debugging only
app.py                    Desktop application entry point
cli.py                    Optional command-line backtest entry point
requirements.txt          Python dependencies
```

Local market data is stored outside the repository workflow and generated backtest results use `output/`, which is ignored by Git.

## Supported CSV format

The loader requires timestamp, open, high, low, close, and volume. It accepts these timestamp headers:

```text
timestamp, open_time, time, datetime, date
```

Raw Binance files with additional columns are supported. Extra fields such as close time, quote volume, trade count, and taker volume are ignored.

Use **Validate Data** before a run to check timeframe, coverage, duplicates, invalid candles, and missing candles.

## Offline utilities
