# Browser configuration parity — operator gate

Status (2026-10-16): browser read-only config projections and repository synthetic/committed-fixture API parity tests exist; **operator-local saved-config/UI parity remains PENDING**. No browser configuration editing or backtest execution is authorized by this document.

## Canonical comparison

For an existing v3 saved config file, compare the complete value returned by the validated Python reader `crypto_strategy_lab.browser_config.read_research_config(path)` with the `config` object returned by the authenticated localhost `GET /api/v1/configs/{id}` endpoint for the same saved ID.

The browser Configurations page, Strategy Designer, Research Features, and Risk & Execution views must derive from that same returned config object, **not** a copy of independent browser defaults. Retain original raw JSON inspection. Compare original nested sections `data`, `features`, `strategy`, `execution` wherever present.

## Local authenticated HTTP parity without starting a server

On the original Windows workstation, the existing saved-config parity CLI supports
an optional in-process check of the **actual** authenticated FastAPI route:

```powershell
python -m crypto_strategy_lab.browser_saved_config_parity --http ".\\config\\data_lake\\SAVED_ID.json"
```

Use the path to an actual native saved configuration within the established
configuration folder; replace the sample name with the real file. This starts
no browser listener and accesses no Data Lake. It checks that an unauthenticated
request is rejected, compares the full native reader snapshot against the
authenticated endpoint response, and verifies unchanged source bytes. It prints
only file basename and hashes, not configuration values or tokens.

This automated HTTP check **does not** replace the operator's browser UI
projection inspection in Configurations, Strategy Designer, Research Features,
and Risk & Execution, or the live browser session check. Do not infer them from
an in-process HTTP PASS.

## Evidence requirements

1. Record Git commit, saved configuration ID, config version, canonical source path, and SHA-256 of the normalized **full** JSON object (sorted keys, deterministic separators, no NaN or Infinity). Do not upload personal/private config values or local tokens.
2. Confirm endpoint identity, existing file/path allowlist and authorization. Never compare two unrelated IDs or report PASS when a section is missing unexpectedly.
3. Compare complete nested structures, scalar types, booleans, arrays, all profile keys, unknown/legacy-field behavior where supported, and historical Fibonacci option keys. Do not silently normalize or rename fields in the browser.
4. Inspect browser projections on Strategy Designer (strategy and feature-owned eligibility), Research Features (feature config) and Risk & Execution (execution config). Each must reference the same snapshot already inspected in Configurations; no save or execution buttons.
5. Record results by fixture: a minimal native config, a stored production config using feature flags, all six strategy profiles with execution settings, and a historical Fibonacci config if available. Verify both clean and missing/invalid-ID failure behavior.
6. Record **PASS** only for exact serialized equality of full JSON and unchanged UI projection source. This gate does not certify trade-by-trade execution, which remains a separate Phase 5 requirement.

## Safety

Preserve existing v2 GUI compatibility, native v3 serialization and PySide6 fallback. Do not write to saved configs, manifests, output directories or Data Lake. Never expose localhost tokens in parity evidence. Hold PR #501 until the overlapping execution ownership is resolved.
