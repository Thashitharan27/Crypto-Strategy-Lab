# Milestone A — Windows read-only acceptance, 2026-10-17

Tested main: `314db5ddb872d48892ef1cac0be19a4746896faa` (PR #716).
GitHub main was fetched and the Windows checkout fast-forwarded before testing;
the remote still named that revision at final verification. No production fix
was required. **Milestone A is not yet ready for sign-off: A3 remains LIMITED pending independent live browser-managed V2 payload comparison.**

| Gate | Status | Evidence and scope |
| --- | --- | --- |
| A1 — Browser security | PASS | Existing production launcher composition served the freshly built browser on `127.0.0.1:8876`; Windows listener inspection confirmed loopback binding. Live anonymous/invalid-token requests returned 401, remote Host/Origin 403, missing IDs and encoded path escapes 404. Execution/write probes returned 404/405, including all four mutation verbs against an existing config ID. The sole visualizer POST remains an authenticated in-memory chart operation. Existing route regressions passed. |
| A2 — Configuration projection | PASS | Both genuine saved files, `Bear_long_BTC_tested_v1` and `BTCUSDT_4H_SMOKE`, passed the existing `browser_saved_config_parity --http` command and independent live authenticated HTTP comparison against the complete native snapshot. Both are V3, with all six execution profiles. Full raw DOM snapshots matched independently calculated typed-JSON hashes; Strategy Designer strategy/features, Research Features and Risk & Execution matched the same selected snapshot exactly for both files. |
| A3 — Results and visualizer | LIMITED | Live authenticated manifest/JSON-safe summary responses matched the native completed-run reader for the original TP1 and BE references, each with 79 trades. The BE UI displayed its native UUID, COMPLETED status and matching rounded saved metrics. Retained V2 `--review-only` passed all nine original chart cases: trades 0/39/78 at 1h/4h/1d, with exact payload equality and recomputed hashes. Live saved-TP1 navigation selected the correct folder and issued the explicit Prepare visualizer action. Subsequently the operator confirmed that the original TP1 run's first, middle and last 4h trades load; zoom, pan and resize work; candles, EMA lines and trade markers render correctly. This is **operator-reported visual smoke evidence**, not an independently captured payload equality check. The chart intentionally remains on the run's 4h timeframe; 1h/1d switching is not part of this viewer and is not a defect. |
| A4 — Original-file integrity | PASS | Before/after SHA-256 inventories preserve all 2,836 original config/output files and 3,156 frozen inputs, with no changes, additions or removals. Canonical Data Lake catalog access and BTCUSDT discovery succeeded (61 symbols). The browser evidence harness opened the existing catalog read-only and prohibited canonical adapter rebuilds for chart loading; no data download or engine replay was requested. |
| A5 — CI and desktop fallback | PASS | Actual Windows pytest: **1,926 passed, 10 skipped, zero failures**, 415.94 seconds. Fresh TypeScript/Vite production build passed. All eight PR #716 checks passed, including Windows smoke and runtime fast-path; actual main full-suite log reports **1,936 passed**, zero failures. The actual PySide6 `app.main()` workstation shell launched visibly and Setup/Review & Run navigation operated. Settings were isolated and optional post-show background connections disabled for this smoke; saved-run loading and integration autostart were not claimed. |

## Finite coverage and limitations

The two existing saved configurations cover minimal/production nested values,
arrays, booleans, defaults, Fibonacci compatibility keys and all six profiles.
No additional original historical Fibonacci file exists in the established saved
configuration root; completed Fibonacci configuration/execution evidence is
reused separately, without manufacturing or saving another fixture. No browser
save or backtest controls were enabled.

The ten Windows skips are filesystem symlink/directory-link privilege limits
(WinError 1314), not passing assertions. Existing real Windows junction evidence
from the original-file certification remains applicable; current Linux route
regressions cover the unavailable symlink cases. Windows security settings were
not changed. The earlier untracked local checkpoint is stale and was preserved.

Retained chart review authenticates consistency of the saved payload pairs;
it is not a fresh live payload capture. Following that review, the operator
confirmed first/middle/last trade loading at 4h, zoom, pan, resize, candles,
EMA lines and trade markers in the original TP1 visualizer. This independently
reported visual smoke closes the previously unobserved interaction check, but
does not prove byte/semantic parity for the **current browser-managed V2 payload**
against the retained canonical desktop evidence. Preserve A3 as LIMITED until
that read-only comparison confirms trade IDs/timestamps and essential overlay
payload fields. A 4h run staying at 4h is intended, not missing functionality.
Do not rerun historical engines or assert unsupported overlay checks.
The source-only retired visualizer's inactive extras are outside Milestone A.

Completed Fibonacci pending-limit, feature-regeneration, BE and TP1 artifact
checks were not rerun. The TP1 replay's previously documented dirty-checkout
provenance limitation remains; unavailable historical SL1/trailing/slippage and
intraminute event history are not invented and do not expand this read-only gate.

Detailed HTTP results, native snapshot hashes, DOM comparison record, pytest
log/JUnit, isolated desktop log and preservation inventories remain local under
`parity_verification/milestone_a_2026-10-17`. No tokens, raw configs, payloads or
saved trades are committed. Certification listeners were stopped after testing.

## Next GitHub task

Compare the live browser-managed V2 payload of the original TP1 run against
retained canonical desktop chart evidence using existing read-only tooling,
without repeating visual smoke or historical engine runs. Record actual
comparison counts, fields, mismatches and a preservation check, then decide
whether A3 and Milestone A can be signed off. Current A1/A2/A4/A5 are PASS;
A3 is LIMITED pending that final independent payload check.
Milestone B requires its own disabled-by-default ownership/lifecycle plan,
verification and explicit approval. **PR #501 remains OPEN/draft on HOLD;
browser-controlled execution and configuration writes remain disabled. The
shared Python engine and PySide6 fallback remain supported.**

## GitHub verification and A3 disposition — 2026-10-17

Reviewed existing PR #717 (head `2c6259640628c9114c947b60c6a2a5ce3d4722ff`) against unchanged main `314db5ddb872d48892ef1cac0be19a4746896faa`. No submitted reviews, inline review threads or PR comments were present. PR #717 changes this report only. GitHub PR-head runs: Browser UI build, Runtime fast-path safety, and Python tests all **success**. The PR-head `full-suite-observation` job's **raw pytest log** reports `1936 passed, 52 warnings in 82.97s`; the Windows-smoke-safety job is **skipped** in that PR run, rather than claimed PASS. The separate original Windows full-suite evidence remains `1926 passed, 10 skipped, zero failures` (WinError 1314 symlink privileges).

The existing `browser_v2_historical_parity` capture implementation compares the canonical desktop `build_v2_diagnostic_payload` against the V2 loopback `/api/payload` response with `compare_payloads` and canonical SHA-256; its retained `--review-only` validation confirms nine matching capture pairs, run identity, trade indices 0/39/78 and the 1h/4h/1d matrix. This **does not** independently establish the live browser *launcher-managed* chart session's current payload equality: the capture starts `StrategyVisualizerV2BrowserServer` directly instead of capturing the operator's current launcher-managed session. The documented operator smoke confirms rendering/interactions only. Existing local payload evidence is unavailable through the GitHub checkout and must not be invented or uploaded. Therefore A3 remains **LIMITED**, Milestone A **not signed off**, and PR #717 remains **draft/unmerged** pending a single read-only launcher-managed payload comparison or an explicit reviewer determination that the already certified V2 server boundary suffices for A3. Do not recertify the historical engine or original files unnecessarily.

For the final comparison, use the existing original TP1 run and canonical chart payload. Check first/middle/last selected trade IDs and UTC timestamps, strategy 4h candles, EMA overlays, entry/exit markers and selected trade bounds; compare complete JSON values/hashes where available. Record actual counts and mismatches without publishing raw payloads or tokens. Recheck original-file SHA-256 inventory after any fresh capture. Keep B execution/config writes disabled and PR #501 on hold; no historical parity gap is permission to enable these.
