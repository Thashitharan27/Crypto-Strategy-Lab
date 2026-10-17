# Milestone A — Windows read-only acceptance, 2026-10-17

Tested main: `314db5ddb872d48892ef1cac0be19a4746896faa` (PR #716).
GitHub main was fetched and the Windows checkout fast-forwarded before testing;
the remote still named that revision at final verification. No production fix
was required. **Milestone A is not yet ready for sign-off: A3 remains LIMITED.**

| Gate | Status | Evidence and scope |
| --- | --- | --- |
| A1 — Browser security | PASS | Existing production launcher composition served the freshly built browser on `127.0.0.1:8876`; Windows listener inspection confirmed loopback binding. Live anonymous/invalid-token requests returned 401, remote Host/Origin 403, missing IDs and encoded path escapes 404. Execution/write probes returned 404/405, including all four mutation verbs against an existing config ID. The sole visualizer POST remains an authenticated in-memory chart operation. Existing route regressions passed. |
| A2 — Configuration projection | PASS | Both genuine saved files, `Bear_long_BTC_tested_v1` and `BTCUSDT_4H_SMOKE`, passed the existing `browser_saved_config_parity --http` command and independent live authenticated HTTP comparison against the complete native snapshot. Both are V3, with all six execution profiles. Full raw DOM snapshots matched independently calculated typed-JSON hashes; Strategy Designer strategy/features, Research Features and Risk & Execution matched the same selected snapshot exactly for both files. |
| A3 — Results and visualizer | LIMITED | Live authenticated manifest/JSON-safe summary responses matched the native completed-run reader for the original TP1 and BE references, each with 79 trades. The BE UI displayed its native UUID, COMPLETED status and matching rounded saved metrics. Retained V2 `--review-only` passed all nine original chart cases: trades 0/39/78 at 1h/4h/1d, with exact payload equality and recomputed hashes. Live saved-TP1 navigation selected the correct folder and issued the explicit Prepare visualizer action, but session completion and interactive chart behavior were not established before Computer Use was stopped with physical Escape. |
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
it is not a fresh capture or proof of zoom, pan, resize or visible overlays in
this session. Complete the browser-managed V2 session smoke against the same
original TP1 run, checking trade identity/timestamps and visible EMA/entry/exit/
stop/target overlays, before upgrading A3. Compare the essential live payload
with the retained canonical desktop evidence; do not rerun historical engines.
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

Review this finite acceptance result and arrange only the remaining A3 live
visualizer check on Windows. Then record the Milestone A sign-off decision.
Milestone B requires its own disabled-by-default ownership/lifecycle plan,
verification and explicit approval. **PR #501 remains OPEN/draft on HOLD;
browser-controlled execution and configuration writes remain disabled. The
shared Python engine and PySide6 fallback remain supported.**
