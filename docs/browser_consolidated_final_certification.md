# Crypto Strategy Lab — consolidated browser-versus-desktop final certification

**Prepared:** 2026-10-18. **GitHub preparation checkpoint:** `main` `6ecd75c121145cba57c0b8eabc616f1a20244175` (through PR #799). This is an **execution plan, not a certification result** or release authorization. Reverify `main`, open PRs, required CI, and original Windows file inventory before collecting final evidence. Keep PR #501 on hold until its native limit-fill ownership conflict is independently resolved.

## 1. Scope and source of truth

Use the established native `ResearchRunConfig` serializer, `GuiResearchRequest`, `GuiApplicationService`, canonical Data Lake readers, native `ResearchRunner`/`BacktestEngine` and existing `CompletedRunReader` plus visualizer. The browser is a client of those Python owners. Do not implement a parallel strategy/execution/reporting stack or claim that two MCP/native runs constitute independent browser invocation parity.

The target operating system is the original Windows `C:\CryptoBots\Crypto Strategy Lab` environment in the **separate CryptoBots Desktop project**. Do not download replacement history, rebuild the canonical data, or alter the original saved configurations/runs as a side effect of certification. Write fresh execution outputs **only** to separate, explicitly approved isolated test roots. Do not touch DMI-Trend-Bot or its deployed shared core.

Normal browser use remains **read-only**. Guarded configuration writes, submission and lifecycle APIs are server-denied or unmounted by default and must stay so until every required acceptance condition passes and the user explicitly approves release. Test-only opt-in is not release approval.

## 2. Freeze and provenance before running

Capture immutable Git commit/tree, Python/Node/dependency versions, OS version, environment path mappings, original frozen config IDs, serialized complete JSON hashes and original byte hashes; preserve all six strategy/execution profiles and existing Fibonacci keys. Identify canonical source partitions and independent 1m candle coverage. Record output-root selection, configuration schema version, fee/slippage conventions, backtest dates (UTC; end exclusive), intrabar policies, and strategy/timeframe/symbol. Hash the original file inventory before starting.

Retain the already established evidence and limitations in:
- `docs/browser_original_file_certification_2026-10-16.md` and PR #717 (Milestone A evidence; read-only acceptance is not B sign-off).
- `docs/browser_configuration_parity_operator_gate.md` (native v3 versus authenticated config GET and the actual browser projections).
- `docs/browser_chart_payload_parity_operator_gate.md` (active V2 chart payload and interactive visualizer).
- `docs/browser_finite_release_matrix.md` (A1–A5 and B1–B4, including unknown coverage).

Known original-evidence caveats: TP1 replay provenance was not fully independently established, genuine saved SL1/trailing events and per-trade slippage evidence were absent from the inspected originals, A3 interactive chart acceptance was limited, and Windows privilege-dependent symlink tests were skipped. Do not silently mark these PASS.

## 3. Independent invocation: required test configuration

Create **two isolated invocations from the same immutable frozen config and canonical inputs**:

1. **Desktop:** launch the actual PySide6 desktop setup/Run UI (not an MCP `GuiApplicationService.run` substitute), load the original v3 config through its existing adapter, inspect effective settings and execute into dedicated desktop output.
2. **Browser:** from a distinct authorized **test-only** local `127.0.0.1` session, mount the dormant guarded React interface only in an explicitly isolated certification build/fixture. Use real click/input interactions in the browser and actual authenticated FastAPI POST/PUT/GET calls into the existing guarded integration and native worker. Configure the test-only server with its own dedicated saved-config/output directories and independent per-launch token. Do **not** modify the normal production launcher, publish its opt-in mode to regular users, expose a remote host/tunnel, or enable ordinary users.

Preserve an invocation trace: UI action, request ID, authenticated HTTP request/response (credentials redacted), server audit outcome, validated effective native configuration identity, native service invocation, worker status/progress, resulting `ResearchRunResult.output_dir`, and final manifest/verified artifact IDs. It is a **failure** if only the native controller or MCP path is exercised twice while the browser component is not mounted.

The current dormant UI has simulated React event-handler tests, **not** real browser click-through with a live local server. Building the isolated certification harness, if missing, is a functional prerequisite. Keep it out of production composition. Verify the local desktop work can access original directories before treating this part as runnable.

## 4. Finite parity cases (not a strategy cross-product)

Use the existing pinned reference cases and native fixture evidence for:
- Base long and short full stop / TP with independently ordered 1m fills.
- Stop-versus-target touches in distinct intrabar minutes and same-bar tie/priority semantics when the prepared fixtures provide evidence.
- Genuine available partial TP1 → protective stop and TP1 → break-even paths; do not assert independent TP1 replay provenance beyond retained evidence.
- Pending-limit/Fibonacci historical cases with existing candidate-selection and fill-order sources.
- One explicit missing intrabar-input or incomplete coverage case that refuses execution safely.
- End-of-data/equity accounting where the existing engine and saved original case support it.

Compare independently invoked desktop and browser effective configuration **deeply** (all nested fields, types, profiles, defaults and original semantic keys), and compare exact ordered signals, candidate decisions, trades, entry/exit/fill/stop/target timestamps, direction, quantities, partial legs, maker/taker fee rates, slippage, gross/net P&L, R, equity and final completion manifest. Record exact equality where technically meaningful; otherwise state a field-specific numeric tolerance and why it is safe. Include sanitized report/canonical manifest hashes and every cataloged output's integrity and row counts. Preserve nonmatching outcomes as FAIL with source record IDs.

Do not accept native-to-native replay alone as browser invocation evidence; do not fabricate absent real historical SL1/trailing event samples. Such cases remain LIMITED/UNOBSERVED and are supplemented by verified mechanism tests only.

## 5. Separate negative/security and lifecycle acceptance

From the **actual test browser UI and HTTP** paths, verify:
- Unauthenticated/wrong/expired token rejection; Host/Origin/DNS rebinding/path traversal/absolute/symlink/non-allowlisted ID rejection; JSON upload limits and sanitized error/audit.
- Full native configuration load/edit/save/roundtrip; concurrent per-ID writer conflict; storage failure, uncertain post-rename sync and crash-stale config lock **without clobbering originals**.
- Submit once with persistent request claim and serialized native worker; duplicate request, cross-coordinator contention, disabled mode, missing 1m history and invalid dates. Verify request claims persist but no invalid claim confers execution rights.
- Progress and statuses `ACCEPTED`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLATION_UNAVAILABLE`, `CANCELLED`, `RECOVERY_UNVERIFIED`. Cancellation of running native execution is not claimed. A restart must **not** reconstruct completion or auto-replay from a directory claim.
- In the same coordinator process, an optional verified output folder is allowed only when the native result's `output_dir` is under the approved root and every cataloged artifact passes the existing verifier. After restart, never infer a request-to-folder mapping from IDs or surviving claims.
- Session changes, stale UI responses and rejected operations do not leak prior run/config information. Full browser visualizer click, chart payload/trade linkage, zoom/pan and labels must be inspected as actual browser behaviors.
- No external bind, CORS bypass, credential exposure, silent data downloads or canonical source writes. PySide6 remains operational and normal production browser reads remain possible with all guarded routes inaccessible.

A real forced-kill/OS crash and permission-protected Windows filesystem behavior must be validated in the Desktop project. Synthetic claim-directory injection alone is LIMITED rather than proof of crash recovery.

## 6. Evidence ledger and decision

For each A1–A5/B1–B4 gate record:
`gate | outcome (PASS/FAIL/BLOCKED/LIMITED/NOT RUN) | frozen commit | input/config IDs | desktop invocation proof | browser invocation proof | exact command/session evidence | raw pytest/CI | ordered trade/result hash comparison | original-file hash comparison | reviewer | limitation`.

Preserve separate original-file inventories before/after and immutable desktop/browser output bundles. Review failures before advancing. A gate is PASS only with reproducible evidence, not a green CI job or the absence of observed anomalies. If local originals, privilege, live UI or broker-specific evidence are inaccessible in the current project, mark the precise item BLOCKED or LIMITED and continue independent development; **do not** relabel certification as complete.

**Release decision:** require all critical safety, integrity and independently invoked execution gates PASS, explicit acknowledgement of bounded historical coverage limitations, independent full raw pytest on the final commit with zero failures, required CI checks and a reviewer sign-off. **Only after explicit user approval** may a separately reviewed server-side guarded release switch and UI composition be considered. No code changes in this certification plan enable that switch.


## 7. Isolated test-only browser artifact (prepared, not certified)

An independent React entrypoint lives in `browser_ui/certification/index.html`
and `browser_ui/certification/main.tsx`. Its guarded controls are initially
disabled and require the operator to enter a test token and explicitly arm the
page. The dedicated Vite config writes to `browser_ui/dist-certification`,
**not** the production `browser_ui/dist`, and Git excludes the former from
source control. The normal `npm run build` compiles both targets separately
to catch certification-page regressions without serving certification controls
through the read-only launcher. Direct development-only compilation is
`cd browser_ui; npm run build:certification`.

This prepares a real browser-renderable frontend, but **does not yet provide
an approved real-browser certification invocation**: the production FastAPI
launcher continues to mount only `browser_ui/dist` and never opts into
guarded routes. Before B2/B3 acceptance, the CryptoBots Desktop test process
must explicitly compose `create_browser_app` with the separate
`dist-certification` static root, a test-only enabled guarded integration,
dedicated **empty isolated** saved-config/output roots, fresh session token,
loopback-only binding and an operator-reviewed test harness. That isolated
test process must not reuse original config/output write roots. Test both
ordinary read-only composition (no guarded routes) and the explicit
certification composition. No run of that harness or real browser click-through
is claimed in this document.


## 8. Isolated FastAPI test composition prepared

`crypto_strategy_lab.browser_certification.isolated_browser_certification`
is a context-managed **explicitly opted-in** factory. It accepts an injected
existing native application service and the canonical, separate
`dist-certification` static bundle; generates a fresh high-entropy token,
creates brand-new temporary config/run directories, composes the existing
authenticated FastAPI read/guarded endpoints, and removes the temporary
directories after closing native jobs. The ordinary read-only launcher is not
modified. Its tests cover missing opt-in, wrong static bundle, absent native
owner, denied unauthenticated mutations, authenticated native save/submit,
isolated output binding and source-file nonmutation.

The factory itself does **not** listen on a network port, automatically opt in
from environment variables, or independently exercise a graphical browser.
For Windows operator certification, use this factory in a deliberate local-only
test process with FastAPI TestClient or a separately reviewed temporary
`uvicorn` binding to `127.0.0.1`; launch a real browser against that process,
enter its fresh token in the separate certification page and execute the
frozen test case. Retain actual browser/desktop invocation traces before
claiming a B2/B3/B4 PASS. The in-process regression test is development
evidence only, and the production launcher still mounts no guarded routes.


## 9. Local certification server runner (test-only)

For real browser observation the existing factory is now callable through
`crypto_strategy_lab.browser_certification.serve_isolated_browser_certification`.
The calling Windows test harness must inject the existing native
`GuiApplicationService`, pass the canonical separate
`browser_ui/dist-certification` directory, an explicit local port, and
`acknowledge_test_only=True`. The runner creates isolated temporary output
and config roots, starts FastAPI **only on 127.0.0.1**, and prints its
per-session token only to the operator terminal. It has **no automatic CLI**,
persistent release toggle, environment opt-in or production launcher path.
When the test server exits, its temporary roots are destroyed.

This runner supports the next real-browser test but **has not executed**
an actual browser/UI interaction or a Windows original-file parity run.
The operator must launch the test page in a browser, explicitly arm it,
capture the resulting authenticated native invocations and inspect saved
outputs before recording B2/B3/B4 evidence. Real native runs must use the
already approved frozen input set and must never write to the canonical
Data Lake, original saved files or live bot directories.


## 10. Explicit operator command for an isolated certification session

After building the certification-only assets (`cd browser_ui; npm run
build:certification`), the Windows CryptoBots Desktop operator may start the
separate test-only service with an **explicit acknowledgement**:

```powershell
python -m crypto_strategy_lab.browser_certification_cli `
  --acknowledge-test-only `
  --static-root "C:\CryptoBots\Crypto Strategy Lab\browser_ui\dist-certification" `
  --port 8919
```

The entrypoint constructs the **existing** native application using the
established Data Lake environment paths and hands it to the opt-in
`serve_isolated_browser_certification` factory. Configurations and results
created by this test server use temporary isolated write roots, not the
canonical originals. The server binds only to `127.0.0.1`, prints its
session token to the operator terminal, and requires a manually armed
certification-only browser page. The normal `browser_launcher` does not
import or call this entrypoint and still exposes zero guarded routes.

**No actual browser or desktop run has been executed by adding this CLI.**
The operator must capture the real browser UI/HTTP trace and separately
launch the PySide6 UI on matching frozen inputs, compare results and record
Windows acceptance. Do not use the CLI for production, external listeners,
live trading, or automatic release.


## 11. Optional preservation of isolated browser evidence

The certification-only operator command can retain its test-session artifacts
when the user explicitly supplies **a new, nonexistent, absolute directory**
whose leaf name starts with `csl-browser-evidence-`. Example:

```powershell
python -m crypto_strategy_lab.browser_certification_cli `
  --acknowledge-test-only `
  --static-root "C:\CryptoBots\Crypto Strategy Lab\browser_ui\dist-certification" `
  --port 8919 `
  --evidence-root "C:\CryptoBots\Certification Evidence\csl-browser-evidence-run01"
```

The factory exclusively creates that new evidence directory and rejects
existing names, relative paths and symlinked ancestors. **It never overwrites
a previous evidence directory or original saved files.** After the guarded
native worker closes, it copies only the session's temporary `configs` and
`runs` trees into the new evidence directory before cleaning up the
temporary working roots. This makes it possible to compare saved manifests,
ordered trades, fees, slippage and equity *after* closing the local server.

If the option is omitted, the previous temporary-delete behavior remains.
A copied output, including an incomplete one, is **not** automatically
verified or approved; validate it with existing native manifest/artifact
readers, inventory hashes and the independently invoked PySide6 reference.
The operator must keep the evidence directory private and choose a
dedicated location outside original configuration, result and Data Lake
folders. Actual Windows permissions, free space, crash interruption and
desktop-versus-browser parity still require separate operator certification.


## 12. Isolated Data Lake cache during certification

The operator CLI resolves the established canonical **raw** market-data root but
constructs the existing native application with a separate, freshly created
temporary cache directory for the full localhost certification session. Any
prepared/feature/catalog caches written during the test cannot mutate the
ordinary workstation cache. This isolated cache is removed even when the
test-only listener exits exceptionally. Do not mistake cold-cache runtime or
cache provenance for an engine change: retain the same frozen raw inputs,
original config and effective execution settings for the desktop/browser
comparison. No Data Lake downloader, replacement archive or canonical cache
rebuild is authorized by certification. The browser mutation outputs remain
isolated independently as documented above.


## 13. Read-only original configuration import into test workspace

The certification-only CLI optionally accepts
`--frozen-config "C:\CryptoBots\Crypto Strategy Lab\config\data_lake\SAVED_ID.json"`.
This is **not** a writable source path: the factory requires an absolute,
canonical, symlink-free native `.json` filename with a safe saved ID,
loads/validates it via the existing `GuiApplicationService.load_config`,
and copies its unchanged bytes into the temporary certification config
directory. The original file remains untouched. The isolated browser can
then enter `SAVED_ID` and use its existing authenticated "Load saved native
configuration" action to test the exact source parameters. The standalone
read-only original is never exposed by absolute path over HTTP.

Do not manually reconstruct the config in frontend defaults. Record the
original SHA-256 before/after, compare full native/browser normalized values
and use this seeded file for the browser invocation. Execution still requires
an explicit job ID and guarded test-only opt-in; this option neither starts a
run nor grants normal browser write permissions. Independently inspect the
PySide6 effective configuration for the same frozen original. The final
Windows interaction and parity gates remain NOT RUN until performed.


## 14. Development-complete GitHub checkpoint and Windows operator handoff (2026-10-18)

The verified GitHub preparation checkpoint is `6ecd75c121145cba57c0b8eabc616f1a20244175` (PR #799). At that commit, guarded routes remain absent from the normal read-only launcher. Test-only configuration loading/editing/saving, native job submission/status/progress/cancel, durable request-ID claims, completed-manifest inspection, local-origin enforcement and isolated temporary native cache/output roots are implemented. Recent release-boundary corrections include #791–#799; see their merged changes rather than reimplementing those guards. PR #501 remains **HELD**. PR #717 remains **OPEN**, with A3 interactive chart coverage LIMITED. The last observed exact-PR-head blocking Linux full pytest for #799 was **2,104 passed, 52 warnings, zero failures**, with the required browser build, runtime fast-path, Python safety and Windows CI smoke successful. This is **engineering evidence only**, not a Windows original-file result.

For the **separate CryptoBots Desktop project** at `C:\CryptoBots\Crypto Strategy Lab`, use the following finite acceptance sequence, preserving evidence in new isolated directories:

1. Verify local Git commit against this handoff (or record a newer reviewed baseline), exact native config file bytes/hash, six profiles, source partitions and 1m coverage; hash existing original configs, outputs and source inputs before any invocation. If the source originals are absent, mark the specific case **BLOCKED** without generating substitute history.
2. Build the existing certification-only React target (`cd browser_ui; npm run build:certification`). Start the existing explicit loopback-only `python -m crypto_strategy_lab.browser_certification_cli --acknowledge-test-only --static-root <absolute dist-certification> --port 8919 --frozen-config <absolute original native JSON> --evidence-root <new absolute csl-browser-evidence-* directory>` in the operator's separate Windows environment. Replace placeholders with actual verified local paths, never guessed identifiers. Keep the bearer token in the operator terminal, not evidence, URLs or screenshots.
3. Exercise real browser **click/input** operations: load the original frozen native JSON, inspect effective settings, perform an expressly authorized test-only save to the isolated root, submit the pinned job, follow status/progress and inspect only a native-verified output folder. Capture redacted UI → HTTP → native job traces and resulting artifacts. An MCP/native-to-native comparison does **not** meet this requirement.
4. Independently open the real PySide6 setup/Run UI for the same frozen config/input, record effective settings and run to a **different dedicated output root**. Use the existing native readers and execution engine; do not compare an injected fixture runner with a real UI invocation and call them equivalent.
5. Compare complete effective configuration **field by field**, accounting explicitly for the expected, server-owned and separate desktop/browser `reporting.output_dir` roots; record both actual roots and require equality of the remaining execution-affecting settings rather than demanding identical writable destination strings. Compare exact ordered signals, candidate decisions, trade/leg IDs, UTC times, quantities, stop/TP/partial fills, fees, slippage, R, gross/net P&L and equity; compare manifests, artifact catalog hashes, row counts, run provenance and original-file hashes before/after. Record any deliberately field-specific numeric tolerances and their reasons, and distinguish expected run-specific manifest identity/timestamps from accounting mismatches. Use the finite cases in §4, not a combinatorial strategy sweep.
6. In actual Windows/browser sessions, verify invalid-token and previous-session-token rejection (tokens are session-specific, not time-expiring), plus cross-origin rejection, filesystem path/ID handling, duplicate requests, missing 1m inputs, cancellation unavailable while running, isolated evidence retention and PySide6 fallback. **Do not use the temporary-root CLI as proof of crash/restart recovery:** each invocation creates a fresh temporary execution directory, and an OS kill skips the evidence-copy cleanup; the next invocation cannot see the prior claim or worker lock. For the forced-kill/restart B3 gate, the separate Windows operator must use a separately reviewed, dedicated **persistent isolated execution-root harness** that reuses the *same* owned root across processes, preserves request/worker claim directories without replay, and checks `RECOVERY_UNVERIFIED` plus fail-closed stale ownership. Never repurpose original output or canonical Data Lake directories. Until that independent harness and physical crash evidence are available, record B3 crash/restart **BLOCKED**, not PASS. Synthetic claim-directory injection also remains LIMITED.
7. Complete A1–A5 and B1–B4 evidence ledger fields in §6. Preserve TP1 replay provenance as LIMITED, unavailable genuine SL1/trailing/per-trade slippage samples as UNOBSERVED, WinError 1314 privilege skips as skips, and A3 chart interactivity as LIMITED until independently verified. **Do not enable normal-user guarded routes or configuration writes.** A final explicit user release approval is separately required after acceptance.

This handoff records **what to perform**, not that the Windows desktop/browser certification has been performed. It does not grant a production enablement switch or alter any existing original saved file, canonical Data Lake input/cache, or live trading bot.

**New test-only persistent-root crash harness (development preparation):** To run a real Windows B3 process-kill/restart test, the operator must prepare a new, dedicated, canonical absolute directory named `csl-browser-crash-*` outside every original configuration, report, Data Lake and cache root. Place a regular marker file named `.csl-browser-crash-test-only` containing exactly the ASCII bytes `CSL_BROWSER_CRASH_CERT_V1` (no newline). Never use junctions or symlinks in the directory's ancestor chain or contents. For the certification-only CLI, explicitly add `--persistent-execution-root <approved absolute csl-browser-crash-* path>` alongside `--acknowledge-test-only`. The option is never a production launcher flag; it is incompatible with `--evidence-root`, and normal CLI sessions continue to use disposable roots. Reuse the **same** marker-protected root and a **new** local token when restarting the process. Do not remove crash-stale request claims or `.guarded-native-worker.lock`: verify `RECOVERY_UNVERIFIED`, denial of cross-session/duplicate requests, and fail-closed new work. Retain the directory for independent inspection and record source/input hashes. GitHub isolated-fixture coverage of this harness is *engineering evidence*, not physical Windows UI parity. The B3 forced-kill acceptance remains **NOT RUN/BLOCKED** until the Desktop project independently performs and records the actual process interruption. Do not enable normal-user execution.

**Crash-specific gate clarification:** The documented `--evidence-root` option copies test-session files only during normal context cleanup; it is not a durable native execution root, nor a crash journal. Only the separately marked opt-in crash-test mode retains the execution root across launches; regular test CLI sessions still cannot preserve it. Do not infer automatic resume, recovered completion, preserved worker locks, or persisted job-to-output mapping after an abrupt kill of that CLI.
