# Consolidated Windows browser/PySide6 certification — 2026-10-19

**Decision: partial certification; production release remains blocked.** This records actual Windows UI execution, not two native/MCP replays. Follow `browser_consolidated_final_certification.md` for outstanding acceptance. PR #501 remains OPEN/DRAFT and held; ordinary browser execution/configuration writes remain disabled. No live bot changes.

## Frozen scope and evidence

The original Windows checkout was fetched and aligned with verified main `13a65de8d9c635ac14fdfa840033345b2c41bc25` (tree `90e9a55b4f873a4cb3f8e5c9f9905e1e46c513da`) before testing. Python 3.10.4, Node v22.18.0, Windows. Detailed private evidence stays in `parity_verification/consolidated_windows_2026-10-19`; isolated writable runs/cache/settings stay outside originals at `C:\CryptoBots\Certification Evidence\csl-consolidated-20261019`.

The complete native config was frozen from original run `BTCUSDT_4h_33b1ccf4866744a3840152dc5184855a`, manifest SHA-256 `c43279177135c552e9eeccb1d1fd75511642810e9447dc49b38f4f99f36f9fbb`; frozen JSON SHA-256 `f243472df894a00532eaa077ce025b16256ce39b8e7caedd08ed5458946df9b4`. All six profiles and nested execution/Fibonacci settings were retained. Only the desktop reporting destination was changed to its separate isolated root.

Pinned request: Binance futures_um BTCUSDT, 4h strategy/1m intrabar, UTC `[2020-06-01, 2020-08-01)`. Independent canonical minute query found **87,840 unique ordered/aligned candles, no gaps**. Existing canonical partitions were hash-checked and copied into isolated caches; missing partitions were configured to refuse rebuilding. No replacement downloads or canonical rebuilds were permitted.

Before/after inventories: **2,836 original config/output files unchanged, no additions/removals; 3,156 frozen original inputs unchanged**. Selected canonical-copy source hashes also remain unchanged. This is not a blanket hash inventory of every unrelated cache file.

## Actual invocation and comparison

- **Browser:** real certification-only React page on loopback, independently authenticated, actual load/save/submit/progress/status/verified-output inspection actions. Existing guarded HTTP integration invoked the real `GuiApplicationService.run`, native runner/engine and reporters. Output: `csl-browser-crash-parity-fixed/BTCUSDT_4h_16b4d46a1b7841a7a59950ee1f11254e` beneath the isolated evidence root.
- **Desktop:** real `app.main()` PySide6 Setup/file picker/Run Backtest UI, same frozen native config and pinned request; completed output and Reports screen inspected. Output: `desktop-runs/BTCUSDT_4h_e4482c39afeb43e6b8482f2429189fbd`. A local harness supplied isolated cache/settings/output ownership and traced the existing service without substituting a runner or triggering Run programmatically.
- Both manifests record executor commit `584e26fb66b6adec3a0c48e6c87679333d13101f`, **`code_dirty=true`**. Retain that provenance limitation: this is a same-workspace UI comparison, not a clean-commit historical replay or final release build certification. Later fixes do not change execution calculations.
- Request fields match exactly. Effective config values match except the required separate destination; **11 native Python int/Qt float representations differ**, e.g. `1`/`1.0`, with exactly equal IEEE-754 values and zero numeric tolerance. Do not claim Python type/byte identity. Authenticated saved JSON matches the complete native JSON-safe serializer, including all profiles.
- **3 ordered trades × 848 columns = 2,544 cells match exactly**, including dtypes, row/column order and all recorded fills, timestamps, quantities, fees, R, P&L and equity. Trade Parquet bytes match: SHA-256 `2d43ae6634bd681b5e9b66ec8075c2897634cde607a38b91417ce114ac103114`. Paths exercised: LONG SL, LONG break-even and LONG END_OF_DATA.
- All **15 cataloged artifacts** independently verify. **13 are byte-identical**, including trades/CSV, summary, signals, source archives and the **1,278 × 423** feature context. Research summary differs only in 12 wall-clock `_seconds` fields. Workbook worksheets and every ZIP member except `docProps/core.xml` match byte-for-byte; that member differs only in created/modified timestamps. Run IDs, output destinations and creation times are intentionally distinct.
- Empty Fibonacci-candidate/rule-trace outputs do **not** certify pending-limit execution or unavailable event histories. Recorded fields matching does not manufacture dedicated slippage or intraminute ordering evidence.

## Gate ledger

All rows use the frozen identities, UI invocation proof and artifact comparison above; local filenames below identify the reproducible evidence. Reviewer: executing operator/agent; **independent release reviewer sign-off remains pending**.

| Gate | Outcome | Evidence and limit |
| --- | --- | --- |
| A1 read-only boundary | PASS | Live HTTP: missing/wrong token 401; foreign Host/Origin 403; invalid ID/traversal 404; invalid JSON 422; >4 MiB 413. Normal launcher composition guarded GET/PUT/POST routes absent (404). `security_and_roundtrip.json`, `http_trace.jsonl`. Production remains read-only. |
| A2 config projection | PASS | Original full native JSON/authenticated GET and actual isolated browser save roundtrip exact as JSON-safe values; six profiles retained. Prior representative saved-config HTTP CLI checks reused. Python int/float representation difference explicitly bounded above. |
| A3 results/visualizer | PASS, scoped | Actual saved-run selection → existing V2 launch; first/middle/last trade 4h HTTP chart payloads match independent native canonical model **3/3 exactly**, zero exclusions. Candles, EMA/RSI, trade labels, wheel zoom, drag pan, fit/center observed. Retained original V2 `--review-only` **9/9 PASS**. Prior operator resize confirmation reused with unchanged V2 source; no new resize claim. Run-timeframe-only UI is intentional. `live_chart_capture/summary.json`, `retained_v2_review.log`. |
| A4 integrity | PASS | `original_before.json`, `frozen_before.json`, `preservation.json`; counts/hashes above. Isolated caches and explicit no-rebuild guard. |
| A5 CI/desktop | PASS | Real desktop Run/Reports completed. Full Windows 2,128 passed/22 skipped, exit 0 without manual cleanup; Linux 2,149 passed/1 skipped; all eight CI checks pass. Windows link-privilege skips remain skips. |
| B1 native owner | PASS | `browser_native_trace.jsonl`, `desktop_native_trace.jsonl`, authenticated HTTP trace and independently saved output manifests prove both actual interfaces use the existing native owner. No parallel engine. |
| B2 execution parity | LIMITED | Exact actual-UI long/SL/BE/end-of-data comparison above. Separate short/TP1/pending-limit dual-UI finite cases remain outstanding. Prior historical/native regression evidence is retained as an anchor, not substituted for browser invocation. |
| B3 lifecycle | LIMITED | Actual isolated save, accepted/running/completed/failed states, verified-output inspection, duplicate 409, missing-data refusal, running cancellation unavailable. **Physical Windows kill/restart subgate PASS** below. Concurrent config-writer/storage-failure/post-rename durability and remaining lifecycle races have regression evidence, not complete physical/UI acceptance. |
| B4 release | BLOCKED | Safety checks passed within scope, but B2/B3 and independent final review remain incomplete; no explicit production enablement approval. Default deny is preserved. |

The live negative job used unavailable future history and failed without inventing/downloading data; it does not prove a specifically missing original 1m partition. That narrower failure path remains engineering-test coverage.

## Physical Windows interruption

The separate persistent root `csl-browser-crash-forced` carried the exact required `.csl-browser-crash-test-only` marker. Actual browser submission entered the real native service in PID 34696, with RUNNING status and persistent request/worker claims. The actual running Windows process was terminated; the **same** root was restarted in PID 21620 with a fresh token.

Old token: 401. Status: **RECOVERY_UNVERIFIED**, never reconstructed COMPLETED. Cancel: 404 unknown job. Duplicate request and new work: 409. Stale worker lock retained; new request not claimed. Actual restarted browser showed the warning and disabled submission/progress/cancel. No automatic replay or deletion/reconciliation of stale ownership occurred. `crash_before.json`, `crash_after.json` and native/HTTP traces retain proof; the interrupted root is preserved for review.

## Reproducible fixes and validation

1. PR [#813](https://github.com/Thashitharan27/Crypto-Strategy-Lab/pull/813), merged: Windows read-only temporary descriptor caused `os.fsync`/`_commit` EBADF and browser save 503. Use a writable descriptor before replacement. Also ensure privilege-dependent pytest skips occur outside native Future exception handling and keep absent-run checks active. Linux raw full pytest **2,147 passed**. Windows assertions **2,125 passed, 22 skipped**, but shutdown needed manual removal of the owned orphan Git helper tree; that is **not** an unassisted clean shutdown PASS.
2. PR [#814](https://github.com/Thashitharan27/Crypto-Strategy-Lab/pull/814), merged as `23c2297704c97baecce21ebd72f190b8df3da120`: bound Windows Git timeout cleanup, terminate its owned descendant tree, and avoid delivering Qt signals after owner deletion. Genuine inherited-pipe child-process regression plus focused checks: **23 passed**. Exact PR head `e4bccfcdd993124f8d19cb1ab473e1f6bf54f7c4`: full Windows **2,128 passed, 22 skipped, 169 warnings in 374.07s, exit 0 without manual cleanup**; Linux raw full CI **2,149 passed, 1 skipped, zero failures** and all eight CI checks passed. No unresolved review threads were present at the verified head.

Raw local logs/JUnit are `pytest_final.*`, `pytest_shutdown_fixed.*`, `git_worker_focused.log`; shutdown stack/process evidence is retained privately. Windows filesystem-link privilege limitations are not remedied by granting privileges or relabeling skips. Original historical Fibonacci/feature-regeneration/79-trade BE suites were not rerun. TP1 clean-replay provenance remains LIMITED; genuine original SL1/trailing/per-trade slippage/full event-order evidence remains UNOBSERVED.

## Exact next checkpoint

Execution code checkpoint: main `23c2297704c97baecce21ebd72f190b8df3da120` after both verified Windows fixes. Complete the remaining **finite actual browser/PySide6 short, TP1 and pending-limit cases**, with original version-aware configurations and existing frozen inputs, plus the remaining physical writer/storage negative cases. Reuse the preserved completed pair and crash evidence rather than repeating them. Obtain independent reviewer sign-off on the complete ledger before any separate production-release approval. No release switch, PR #501 merge or original-data changes are authorized by this report.
