# Browser migration — shared Data Lake resolution audit

Status: repository-grounded audit, 2026-10-15. This does not enable browser-controlled backtesting.

## Confirmed ownership

- Raw Binance archives remain external and read-only. The existing default root is `C:\CryptoBots\Binance Market Data`; the user's monthly BTCUSDT 1m/4h archives remain beneath that tree.
- `MarketDataStore` is the single market-data store. It owns the existing `CacheLayout`, DuckDB catalog, normalized Parquet cache and data-quality cache.
- The active desktop shell composes `GuiApplicationService`, which composes `MarketDataStore` and `CatalogStatusService`.
- Browser read-only catalog access delegates to the same `CatalogStatusService`; it does not discover raw archives or implement a second loader.
- The MCP/control plane already supports `CRYPTO_STRATEGY_LAB_RAW_ROOT` and `CRYPTO_STRATEGY_LAB_CACHE_DIR`.

## Audit finding

Desktop defaults previously imported `MARKET_DATA_ROOT` and `CACHE_DIR` directly while the MCP/control entrypoint independently resolved the same two environment overrides. Browser read-only services were dependency-injected in tests but had no canonical composition helper tying them to the desktop application service.

That left configuration ownership correct at the class level but duplicated at process composition.

## Resolution

`crypto_strategy_lab.paths.resolve_data_lake_runtime_paths` is the single runtime root resolver for raw data and cache. Existing constant names remain for compatibility and now reflect the same environment override contract already used by the control plane.

`build_browser_readonly_service` composes the browser facade through the existing `GuiApplicationService`, therefore reusing its `MarketDataStore`, `CacheLayout`, DuckDB catalog and catalog facade.

No new cache directory, catalog database, raw-data loader, strategy code, execution engine or result format is introduced.

## Safety gates retained

- Browser API remains read-only.
- Browser-controlled execution remains disabled until frozen historical parity, including the 79-trade BTCUSDT baseline, is certified.
- PR #501 remains blocked pending the pending-limit execution overlap review.
- Live DMI bot code is outside this change.
