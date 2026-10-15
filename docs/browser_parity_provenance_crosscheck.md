# Saved-run archive provenance cross-check

Read-only operator verification of a **locally frozen** Data Lake selection against the **original saved completed-run** `provenance/source_archives.parquet`. Uses existing frozen JSON fields, DuckDB Parquet loading, and pandas DataFrames; does not create a new cache or trading engine.

After completing `tools/freeze_browser_parity_catalog_inputs.py` on the workstation that owns the original archives, export the exact `provenance/source_archives.parquet` from run `BTCUSDT_4h_ad58a712d8e7492380b99ec96c20c80f` to a local private location and run:

```powershell
python tools/verify_browser_parity_provenance.py `
  --freeze-json "C:\CryptoBots\btc79-source-freeze.json" `
  --saved-provenance-parquet "C:\CryptoBots\btc79-original-source-archives.parquet"
```

For the default `execution_klines_only` freeze, compares 4h and 1m kline source **multisets** by interval, frequency, UTC period start/end and the saved stat fingerprint. For a freeze created with `--include-all-saved-datasets`, its `selection.source_scope` is `all_saved_datasets`, and the same verifier instead compares all **2,956** original source records, including each dataset, interval (including null), frequency and source identity. It additionally checks each source's original size and nanosecond modification time, and confirms catalog size matches the content-hashed file byte count. Manifests generated before the additional stat fields were introduced must be regenerated using the existing freeze tool. Rejects a missing archive, unexpected archive, duplicated record, wrong period or changed catalog metadata. The default partial manifest excludes other datasets intentionally and must never be reported as a complete inventory check. The opt-in full manifest validates the saved source inventory across all nine dataset/interval groups. This still does not establish which feature inputs affected trade outcomes or certify the original 79-trade replay.

**Important:** the stat fingerprint is based on original source path, size and mtime, not raw archive bytes. Passing this step does not prove archive content, candle chronology, original engine replay or trade parity. Do not switch on browser execution on the basis of this utility. Keep PR #501 on hold.
