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
number of rules. Legacy profile filters are migrated into this table when
loaded.

## Independent direction voting

The **DI Direction Selection** tab can replace DI-only direction choice with a
majority vote. The five independently configurable voters are DI pressure,
high/low market structure, momentum, volume-weighted candle pressure, and a
completed higher-timeframe trend. Each voter returns Long, Short, or Abstain.
The side with more votes is selected; tied votes and winners below the
configured minimum vote count are skipped.

ADX, DI spread, ATR, and Bollinger width remain entry-quality filters rather
than direction votes. Trade output records each individual vote plus the Long,
Short, and Abstain totals so every decision can be audited.

## Start the application

On Windows, double-click:

```text
Open Backtester.bat
```

Or launch it from a terminal:

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
3. Use **Download / Update Binance Dataset** to create or extend both matching CSV files.
4. Configure Bull Long, Bull Short, Bear Long, Bear Short, Sideways Long, and Sideways Short under **Strategy Profiles**.
5. Save the configuration and run the backtest.
6. Review the Summary, Trades, Charts, and generated output folder.

Public Binance Spot candle downloads require no API key. Existing datasets are updated incrementally, incomplete current candles are excluded, and files are replaced atomically only after a successful update.

## Portfolio workflow

The **Portfolio** tab accepts a dynamic list of assets. Each enabled asset uses its own saved strategy configuration while sharing one account.

- Base risk is configured per asset.
- Maximum Total Portfolio Risk is a hard entry limit and defaults to 5%.
- Entries that would exceed that limit are blocked and reported.
- Portfolio output includes accepted trades, blocked candidates, realized equity, mark-to-market equity, monthly/yearly results, and component contribution.

## Project structure

```text
Open Backtester.bat       Windows launcher
app.py                    Desktop application entry point
cli.py                    Optional command-line backtest entry point
crypto_strategy_lab/      Installable application package
  gui/                    Interface, profile editor, and background workers
  config.py               Backtest configuration model
  engine.py               Trade simulation engine
  portfolio.py            Shared-equity portfolio replay
  strategy_profiles.py    Six market-regime strategy profiles
  binance_data.py         Binance Spot candle downloader/updater
  loader.py               OHLCV loading and validation
  output_manager.py       Reports and run-folder management
Config/                   Saved user strategy configurations
data/                     Local market data (ignored by Git)
output/                    Generated backtest results (ignored by Git)
tools/                     Offline import and migration utilities
tests/                     Automated regression suite
```

Older user-generated artifacts were preserved under `output/legacy_artifacts/`. New application results also use `output/`.

## Supported CSV format

The loader requires timestamp, open, high, low, close, and volume. It accepts these timestamp headers:

```text
timestamp, open_time, time, datetime, date
```

Raw Binance files with additional columns are supported. Extra fields such as close time, quote volume, trade count, and taker volume are ignored.

Use **Validate Data** before a run to check timeframe, coverage, duplicates, invalid candles, and missing candles.

## Offline utilities

The desktop downloader is the normal data workflow. Historical Binance ZIP/CSV archives can still be combined when needed:

```powershell
.\.venv\Scripts\python.exe -m tools.combine_binance_data "path\to\archive-folder" -o "data\BTCUSDT_1h.csv"
```

Other maintenance utilities are kept in `tools/` and should be run as modules from the repository root.

## Tests

```powershell
$env:QT_QPA_PLATFORM="offscreen"
.\.venv\Scripts\python.exe -m pytest tests -q
```

Market data, generated reports, virtual environments, and Python caches are intentionally excluded from version control.
