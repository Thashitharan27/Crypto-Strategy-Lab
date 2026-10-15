# Historical replay certification — BTCUSDT 4h / 1m baseline

**Certification date:** 2026-10-15  
**Baseline completed run:** `BTCUSDT_4h_ad58a712d8e7492380b99ec96c20c80f`  
**Original code revision:** `1ad8a2161877260d9f1d790f583a82e065f8730e`  
**Certification scope:** existing CSL engine/data/output reproducibility only. This does **not** authorize browser-controlled execution.

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

The feature-config hash difference is an explicitly classified backward-compatible default addition. It is not accepted by tolerance or visual inspection: the replay still produced an exact prepared frame and exact native trade frame, which proves the added default did not change this baseline's effective feature values or executions.

## Source-provenance reproduction

Use the existing full-scope catalog freeze and provenance verifier documented in:

- `docs/browser_catalog_parity_freeze.md`
- `docs/browser_parity_provenance_crosscheck.md`

The certified replay requires `--include-all-saved-datasets` and the original saved provenance. A passing run must report the complete 2,956-record source inventory; partial 4h/1m verification is insufficient.

The source identity verifier compares dataset, interval, frequency, UTC period bounds, source identity, size, modification time, and the frozen archive content-hash contract. Timezone-equivalent source periods are normalized as UTC instants; actual timestamp drift still fails closed.

## Prepared-frame reproduction

The replay prepared frame must be exported from the existing prepared-backtest path and compared column-for-column and row-for-row with the original prepared frame.

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

Compare the existing native trade outputs directly, without mapping them into a reduced browser-specific schema.

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

- Strategy hash: match.
- Data hash: match.
- Execution hash: match.
- All 12 feature-provider identities: match.
- Feature hash: one known structural difference only — the current serializer includes `fib_structure_quality_mode="BASELINE"`, which did not exist in the historical snapshot.
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
