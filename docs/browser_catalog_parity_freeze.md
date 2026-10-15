# Catalog-backed freeze for the 79-trade browser parity baseline

This operator step freezes the original market-data bytes selected by the **existing Crypto Strategy Lab Data Lake catalog**. It does not refresh archive discovery, download replacement candles, create another cache, or execute a strategy.

For the current BTCUSDT candidate baseline, run this on the Windows workstation that owns the original Binance archives and the existing CSL cache:

```powershell
python tools/freeze_browser_parity_catalog_inputs.py `
  --raw-root "C:\CryptoBots\Binance Market Data" `
  --cache-root ".\cache" `
  --manifest-json "<separate-safe-location>\btc79-source-freeze.json" `
  --commit-sha 1ad8a2161877260d9f1d790f583a82e065f8730e `
  --expected-strategy-records 102 `
  --expected-intrabar-records 97
```

The utility asks the existing DuckDB catalog for the BTCUSDT 4h and 1m records covering 2020-06-01 through 2026-09-01. Each source file must still exist and match the catalog-recorded size, mtime and existing `stat_fingerprint`. Only then are the actual file bytes hashed with the existing parity fixture SHA-256 contract.

The output manifest contains no local paths. It records portable content hashes and the catalog selection metadata needed to diagnose a mismatch. Any missing file, changed source, unexpected record count or catalog mismatch fails closed.

This freeze is evidence preparation only. It does **not** certify the 79-trade replay, enable browser-controlled backtesting, resolve PR #501, or modify the live DMI bot.
