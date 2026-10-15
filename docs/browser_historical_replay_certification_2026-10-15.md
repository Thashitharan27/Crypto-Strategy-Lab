# Historical replay certification — BTCUSDT 4h / 1m baseline

**Certification date:** 2026-10-15  
**Baseline completed run:** `BTCUSDT_4h_ad58a712d8e7492380b99ec96c20c80f`  
**Original code revision:** `1ad8a2161877260d9f1d790f583a82e065f8730e`  
**Certification scope:** existing CSL engine/data/output reproducibility only. This does **not** authorize browser-controlled execution.

**Replay run:** `BTCUSDT_4h_11564c0a851e446fa2afeb3aa628a612`  
**Replay engine revision:** `3a4b3cf489a0d0ccf5b2416c928a5f580df78153`  
**Provenance verifier revision after hardening:** `62bf3157f92ed64d0b2e430be2ddbc23c63b745d`  
**Machine-readable certificate:** `docs/certification/browser_historical_replay_2026-10-15.json`

## Result

**PASS — historical replay reproduced the original baseline exactly at the prepared-feature and native-trade levels.**

The replay used the existing CSL engine and existing canonical Data Lake/cache path. No second market-data loader, strategy implementation, execution engine, report parser, or browser-controlled run path was introduced.

## Frozen evidence

| Evidence | Expected / observed result |
| --- | --- |
| Saved trade CSV SHA-256 | `14d0577968a9ee50916aa9b4d2431cec238812f5bc290f9b315531ff541eacbe` verified |
| Original source archive inventory | 2,956 records |
| Source archive identity comparison | 2,956 / 2,956 matched |
| Prepared frame shape | 14,610 rows × 464 columns |
| Prepared frame comparison | exact value match for all 14,610 × 464 cells |
| Native trade frame shape | 79 rows × 877 columns |
| Native trade comparison | exact value match for all 79 × 877 cells |
| Original/replay trade fingerprint | exact match |
| Feature-provider identity count | 12 |
| Feature-provider identities | 12 / 12 matched |
| Strategy configuration identity | exact match |
| Data configuration identity | exact match |
| Execution configuration identity | exact match |
| Feature configuration identity | differs only by current default `fib_structure_quality_mode="BASELINE"` |
| Effective feature/trade behavior | exact prepared-frame and native-trade match |
| Original prepared-cache identity | `d4d7338ecf880e9e47385cd8eac01265aa3b69235eb9100ebb73523f454337d5` |
| Replay prepared-cache identity | `7b2c962a3b8ba5d636363a62a7b3fd7644ad1c988b5f6f457dac289b1e648c88` |
| Original/replay trade fingerprint | `b02ff222d0337b3ddf950fd23372a92d81320704ea032805a121c47b71ddf94c` |

The feature-config hash difference is an explicitly classified backward-compatible default addition. It is not accepted by tolerance or visual inspection: the replay still produced an exact prepared frame and exact native trade frame, which proves the added default did not change this baseline's effective feature values or executions.

## Source-provenance reproduction

Use the existing full-scope catalog freeze and provenance verifier documented in:

- `docs/browser_catalog_parity_freeze.md`
- `docs/browser_parity_provenance_crosscheck.md`

The certified replay requires `--include-all-saved-datasets` and the original saved provenance. A passing run must report the complete 2,956-record source inventory; partial 4h/1m verification is insufficient.

The source identity verifier compares dataset, interval, frequency, UTC period bounds, source identity, size, modification time, and the frozen archive content-hash contract. Timezone-equivalent source periods are normalized as UTC instants; actual timestamp drift still fails closed.

## Prepared-frame reproduction

The replay prepared frame was exported from the existing prepared-backtest path and compared column-for-column, row-for-row and cell-for-cell with the original prepared frame using `parity_verification/compare_prepared_frames.py`. The original/replay prepared-cache identities are recorded above. A separate dataframe content-hash command was not run, so this certificate does not invent one; the evidence is the exact value comparison plus the retained operator-local cache artifacts.

Certified expectation:

```text
Original prepared rows: 14610
Replay prepared rows: 14610
Original columns: 464
Replay columns: 464
Columns only in original: []
Columns only in replay: []
RESULT: EXACT PREPARED-FRAME MATCH
```

Any missing/extra column, dtype/semantic substitution, row-order change, or value difference invalidates the certificate.

## Native trade reproduction

The existing native trade outputs were compared directly with `parity_verification/compare_native_trades.py`, without mapping them into a reduced browser-specific schema. The deterministic content fingerprint for both native trade frames is `b02ff222d0337b3ddf950fd23372a92d81320704ea032805a121c47b71ddf94c`.

Certified expectation:

- 79 original native trade rows.
- 79 replay native trade rows.
- 877 native columns on both sides.
- Exact equality for all native values after the established deterministic normalization used by the parity comparison.
- Exact original/replay trade fingerprint equality.
- Saved registered trade CSV SHA-256 remains `14d0577968a9ee50916aa9b4d2431cec238812f5bc290f9b315531ff541eacbe`.

This native comparison is authoritative for this certificate because it retains the complete existing report schema, including pair/leg accounting and persisted execution diagnostics.

## Configuration and provider identity

The replay must compare the persisted configuration identities and feature-provider provenance rather than reconstructing settings from browser controls.

Certified result:

- Strategy hash, original/replay: `90ab9c0e19b0be2e5b16bf25750a44b10a5e39d633af02ea0bcf444b1c3d9187`.
- Data hash, original/replay: `142277ae839bee3413470fda14a24eb565b2e9cfc65784159d255d09b327629d`.
- Execution hash, original/replay: `c6a2434728ee6be91dc2c70308e4451c7875f86b18784c8a770ef9562c139a59`.
- All 12 feature-provider identities: match.
- Original feature hash: `cd903c010da0694003100010e6c2dc18891ef74d4d88019ef1939fb728c65c2f`.
- Replay feature hash: `49aa0e4fc94670169e3fac82b4fb14e2ef6a7da5950c53a0c77b3f61ed992872`.
- Feature hash has one known structural difference only — the current serializer includes `fib_structure_quality_mode="BASELINE"`, which did not exist in the historical snapshot.
- No other configuration difference is accepted.

If any future default addition changes prepared values, provider identity, trade rows, or execution fingerprints, this certification no longer passes.

## Browser migration consequence

This certificate closes the historical **engine replay** gate needed by the browser migration plan. It does **not** certify a browser execution path, because no browser run-creation/execution endpoint is enabled.

The browser remains read-only until later migration phases independently verify:

1. browser-to-existing-service configuration projection,
2. guarded write/job lifecycle,
3. browser-vs-desktop configuration roundtrip,
4. browser-triggered execution against frozen fixtures,
5. exact trade-level parity through the same engine,
6. explicit release approval.

PR #501 remains on hold until its pending-limit execution overlap is resolved.

## Fail-closed renewal rule

Re-run this certification after any change that can affect:

- Data Lake archive selection or canonical cache construction,
- feature providers or prepared feature schema,
- strategy selection/rules,
- intrabar fill ordering,
- fees/slippage/sizing,
- configuration serialization/default semantics,
- report/native trade serialization.

A renewed certificate is **PASS** only when the full source inventory, prepared frame, native trade frame, provider identities, and allowed configuration classification all reproduce the expectations above.

## Retained reproducibility artifacts

The local replay working set used during certification is identified by these paths:

- `parity_verification/btc79-source-freeze.json` — full 2,956-record catalog freeze with archive content hashes.
- `parity_verification/btc79-replay-result.json` — replay result metadata.
- `parity_verification/replay_outputs/btc79_current_main/BTCUSDT_4h_11564c0a851e446fa2afeb3aa628a612` — replay output directory.
- `parity_verification/compare_prepared_frames.py` — exact prepared-frame comparator.
- `parity_verification/compare_native_trades.py` — exact native trade comparator.

Those workstation artifacts are not duplicated into Git because they include local cache/output material. The repository-level machine-readable evidence summary is `docs/certification/browser_historical_replay_2026-10-15.json`; it records the exact run/revision identifiers, hashes/fingerprints, comparison dimensions, and the explicit absence of a separately computed prepared-dataframe content hash.
