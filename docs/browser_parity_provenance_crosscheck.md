# Saved-run archive provenance cross-check

Read-only operator verification of a **locally frozen** Data Lake selection against the **original saved completed-run** `provenance/source_archives.parquet`. Uses existing frozen JSON fields, DuckDB Parquet loading, and pandas DataFrames; does not create a new cache or trading engine.

After completing `tools/freeze_browser_parity_catalog_inputs.py` on the workstation that owns the original archives, export the exact `provenance/source_archives.parquet` from run `BTCUSDT_4h_ad58a712d8e7492380b99ec96c20c80f` to a local private location and run:

```powershell
python tools/verify_browser_parity_provenance.py `
  --freeze-json "C:\CryptoBots\btc79-source-freeze.json" `
  --saved-provenance-parquet "C:\CryptoBots\btc79-original-source-archives.parquet"
```

Compares both 4h and 1m source **multisets** by interval, frequency, UTC period start/end and the saved stat fingerprint. It additionally checks each source's original size and nanosecond modification time, and confirms catalog size matches the content-hashed file byte count. Manifests generated before the additional stat fields were introduced must be regenerated using the existing freeze tool. Rejects a missing archive, unexpected archive, duplicated record, wrong period or changed catalog metadata. Other datasets in the full provenance inventory are excluded intentionally; they are not claims of verified equality.

**Important:** the stat fingerprint is based on original source path, size and mtime, not raw archive bytes. Passing this step does not prove archive content, candle chronology, original engine replay or trade parity. Do not switch on browser execution on the basis of this utility. Keep PR #501 on hold.
