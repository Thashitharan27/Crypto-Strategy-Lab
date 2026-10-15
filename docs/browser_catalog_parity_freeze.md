# Catalog-backed freeze for the 79-trade browser parity baseline

This operator step freezes the original market-data bytes selected by the **existing Crypto Strategy Lab Data Lake catalog**. It does not refresh archive discovery, download replacement candles, create another cache, or execute a strategy.

For the current BTCUSDT candidate baseline, run this on the Windows workstation that owns the original Binance archives and the existing CSL cache:

```powershell
python tools/freeze_browser_parity_catalog_inputs.py `
  --raw-root "C:\CryptoBots\Binance Market Data" `
  --cache-root ".\cache" `
  --manifest-json "<separate-safe-location>\btc79-source-freeze.json" `
  --commit-sha 1ad8a2161877260d9f1d790f583a82e065f8730e `
  --strategy-source-start 2020-01-01T00:00:00Z `
  --expected-strategy-records 102 `
  --expected-intrabar-records 97
```

The utility asks the existing DuckDB catalog for the BTCUSDT 4h sources covering the 2020-01-01 warmup through 2026-09-01, and 1m sources covering the 2020-06-01 trading start through 2026-09-01. Each source file must still exist and match the catalog-recorded size, mtime and existing `stat_fingerprint`. Only then are the actual file bytes hashed with the existing parity fixture SHA-256 contract.

The output manifest contains no local paths. It records portable content hashes and the catalog selection metadata needed to diagnose a mismatch. Any missing file, changed source, unexpected record count or catalog mismatch fails closed.

This freeze is evidence preparation only. It does **not** certify the 79-trade replay, enable browser-controlled backtesting, resolve PR #501, or modify the live DMI bot.


## Original 4h warmup selection

The original 79-trade run's data-quality report shows that its 4h input includes earlier warmup history (from 2020-01-01) even though trading starts on 2020-06-01. When the corresponding original catalog archives are present, add `--strategy-source-start 2020-01-01T00:00:00Z` to freeze those 4h sources without extending the requested 1m intrabar execution window. This selection changes only source inventory, not the requested trading start or the engine configuration. Retain the exact 4h and 1m expected archive counts from the saved provenance; fail closed if counts differ, and run the separate saved-run provenance cross-check afterward. The warmup date must be confirmed from saved-run evidence and is not a backtest replay certificate.


## Follow-up identity verification

After generating this frozen manifest, run `tools/verify_browser_parity_provenance.py` with the original saved `provenance/source_archives.parquet` as described in `docs/browser_parity_provenance_crosscheck.md`. The verifier now checks each selected archive's saved size and mtime against the catalog metadata and hashed byte count; regenerate any pre-#558 freeze manifests lacking those fields. This remains source-evidence collection, not certification of any trade replay.


## Optional full saved-run inventory freeze

The baseline run lists 2,956 selected source archives spanning nine dataset/interval groups. To hash and verify all of them against the original saved-run provenance, add `--include-all-saved-datasets` to the existing freeze command. This opt-in reuses the same catalog, original raw files and content-hash contract. It fails closed if the additional 2,757 source records are unavailable; no replacement data is downloaded. Run `verify_browser_parity_provenance.py` afterward with the same original saved Parquet file to verify all 2,956 metadata identities and size/mtime attributes. This does not establish candle-level or 79-trade replay parity. Leave the flag off for the prior 199-source-only workflow.
