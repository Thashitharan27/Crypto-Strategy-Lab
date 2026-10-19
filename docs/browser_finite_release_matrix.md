# Browser migration — finite, risk-based release gates

Status: **decision framework, not authorization to enable execution or configuration writes**.
The migrated browser is an interface to the existing authoritative Python engine, not a rewritten trading engine. The PySide6 desktop remains available. Use this checklist to stop treating every possible strategy/filter combination as a release prerequisite.

## Separate milestones

| Milestone | Meaning | Decision rule |
| --- | --- | --- |
| A — read-only browser acceptance | Browse saved runs, configs, Data Lake, charts and research without executing or writing | All A checks PASS; known noncritical display gaps may be accepted and recorded |
| B — guarded execution/config editing | Browser invokes existing run/config owners, without duplicating engine logic | All A and B checks PASS, explicit approval to expose these capabilities, no unresolved high-severity defect |
| C — later enhancements | Additional visualizer controls, uncommon strategies and quality-of-life features | Prioritize after A/B; never implicitly gate A unless they affect safety or correctness |

**No automatic promotion:** passing historical native-engine replay does not pass browser invocation, persistence or write safety. Browser execution and configuration writes remain disabled pending separate B verification and approval. PR #501 remains held until its ownership conflict is resolved.

## Finite acceptance matrix

Status vocabulary: **PASS** (evidence with commit/fixture/log), **FAIL** (reproduced error), **BLOCKED** (necessary evidence or capability unavailable), **LIMITED** (specified coverage exists, no universal claim), **NOT RUN**. A historical gap is not silently relabeled PASS.

| ID | Requirement | Milestone | Required acceptance evidence |
| --- | --- | --- | --- |
| A1 | Read-only browser safety boundary | A | Token/localhost and allowlist route regression tests; forbidden verbs/routes and path escapes rejected; run/config write paths remain inaccessible in read-only/A mode, even if separately implemented for a future guarded B mode |
| A2 | Canonical read-only configuration projection | A | Same JSON-safe config key paths, values and profiles via desktop/native serializer and authenticated browser GET, with representative original saved configs |
| A3 | Saved run/results/visualizer fidelity | A | Representative genuine saved runs, stable run selection/trade IDs, timestamps, chart overlays, summary and payload parity; no mutation of originals |
| A4 | Data Lake and historical artifact provenance | A | Registered hashes and original-file preservation checks; no unapproved canonical rebuild or hidden data download |
| A5 | CI and desktop fallback | A | Raw full pytest 0 failures, required Python safety, browser build, runtime fast-path checks; PySide6 smoke/fallback remains viable |
| B1 | One authoritative execution/config owner | B | Trace browser request to existing native owner; compare normalized effective configs and ensure no second indicator, fill or exit engine |
| B2 | Guarded browser-versus-desktop execution | B | Same pinned config, commit, frozen prepared/source data, and ordered trade output for representative long/short, entry, stop, partial and end-of-data paths; document numeric tolerance or exact equality |
| B3 | Run/write lifecycle and negative cases | B | Explicitly authorized create/save/cancel/restart and rollback behavior; invalid token/input, missing 1m data, interruptions, stale request, duplicate submissions all fail safely |
| B4 | Final security and release switch | B | Auth, allowlists, local binding, no secret exposure, operation audit and explicit release review/approval before enabling capabilities |

A1–A5 and B1–B4 are **finite gates**. For B2, cover distinct underlying execution mechanisms and their risk-sensitive interactions, **not** all cross-products of symbols, timeframes, indicators and strategy options. Use existing engine tests for exhaustive edge-case permutations, and a small set of independent historical references for regression anchors. Changing strategy semantics after a historical save requires version-aware attribution, not automatic declaration of a migration defect.

## Evidence already established (not blanket sign-off)

- Original Fibonacci pending limit: 8 references, 35 native trades matched on frozen prepared inputs. See `browser_fib_historical_execution_2026-10-17.md`.
- Fibonacci feature regeneration: 5 distinct prepared frames, 92,776 rows and 8,486,781 candidate records agree on existing semantics. Raw JSON diagnostics and timezone dtype representations differ as documented in `browser_fib_feature_regeneration_2026-10-17.md`.
- Original break-even: 79 trades × 877 columns matched; 40 genuine BE triggers. See `browser_break_even_historical_execution_2026-10-17.md`.
- TP1: 40 genuine original TP1 exits with matching retained artifacts; the previous replay's clean executor provenance is **not independently established**. Do not upgrade this to an unqualified clean replay PASS without the supporting record.
- Genuine original executed SL1/trailing events, full event histories and dedicated per-trade slippage columns were absent from the inspected 178-run store. Mark **LIMITED/UNOBSERVED** and rely on verified engineering regression tests for *behavioral coverage only*, not historical parity. Do not fabricate events, tick order or trade-level slippage.
- Windows symlink skips due to WinError 1314 are environment-specific; keep the skips reported, do not call them passes.

## Practical release triage

1. **Stop and fix before advancing:** data corruption, authorization bypass, unsafe write/execute route, wrong effective config, wrong results/trade ordering or accounting in a representative pinned browser path, or a failing required CI job.
2. **Document and proceed to the next independent gate:** missing historical evidence for a behavior already protected by regression tests, cosmetic UI variance, absent unused optional integration, or intentional versioned feature-diagnostic differences. State the resulting limitation; do not claim historical certification of it.
3. **Do not expand scope automatically:** new strategy options and extra GUI features belong in separate workstreams. Open a follow-up issue for low-risk discoveries rather than making release certification open-ended.
4. **Release decision:** A can pass and support read-only use without B. B cannot pass on native replay alone; guarded browser calls and write lifecycle must be demonstrated and explicitly approved. Failure to find historical SL1/trailing records is not by itself a reason to keep searching forever or to claim their historical parity.

## Current action queue — after guarded implementation (2026-10-18)

- The guarded integration, native config owner, job lifecycle, read-only saved-output handoff, localhost security and isolated certification CLI are **implemented but not released** as of GitHub main `6ecd75c121145cba57c0b8eabc616f1a20244175` (#799). Reverify the latest main before using this checkpoint. Do not repeat the old implementation-inventory task as unfinished without finding a concrete gap.
- Next independent gate: execute the consolidated **actual browser-UI/HTTP versus PySide6 UI** Windows certification at the verified commit, on identical original frozen inputs, using `docs/browser_consolidated_final_certification.md` §14. Retain existing read-only config/chart parity evidence rather than rerunning already matched historical BE/Fib suites.
- Preserve A3 interactive-chart limitations, TP1 verifier-provenance uncertainty, absent genuine SL1/trailing/per-trade slippage events and Windows symlink privilege skips as documented. A missing historical observation is not a reason to invent new engine behavior.
- Keep draft PR #501 on hold; its separate limit-touch helper is not an approved second execution authority. Keep **normal browser execution/configuration writes server-disabled** until all critical independent gates pass and the user explicitly approves a separately reviewed release switch.

Each completed gate should record: main SHA, source run/config identities, check/test names, actual raw results, known limitations, and a reviewer decision. No claim of 100% strategy correctness is intended.


## B3 cross-process lifecycle limitation (2026-10-18)

The experimental guarded coordinator retains submitted request IDs in memory
only. Its duplicate-ID guarantee holds within one coordinator lifetime, **not**
after an abrupt process crash or a new coordinator instance. Native completed-run
artifact verification is read-only and must not be confused with a durable
submission/idempotency journal. Do not claim replay protection, automatic resume,
safe restart, or B3 acceptance until server-owned durable request identity and
reconciliation have been designed, implemented and tested (including crashed,
incomplete and previously completed native outputs). No browser execution or
configuration writes are authorized by this note.

Final Windows certification remains separate: preserve original files, compare
independently invoked browser and PySide6 native runs on identical frozen inputs
and effective configs, ordered fills/exits/trades/timestamps/fees/P&L/equity,
saved outputs, security and lifecycle; retain A3 chart-interaction limitation,
TP1 verifier provenance caveat and historical SL1/trailing coverage limitation.


## B3 request ownership progress (2026-10-18)

Opt-in guarded execution with a server-owned existing output directory now
atomically reserves a persistent, non-sensitive request-ID claim before queueing
native execution. Reuse of the same ID in another coordinator lifetime fails
closed, including after a crash. Claims are retained intentionally; no automatic
retry or resume is inferred from a claim. This is **not** a complete durable job
journal, a proof of completed native execution, or a cross-process global runner
lock. An administrator must explicitly reconcile interrupted native artifacts
using the existing manifest/hash verifier; no automatic claim deletion is safe.
Independent browser/desktop invocation, write rollback, and interrupted output
recovery certification remain outstanding. Production browser mutations remain
disabled pending the B release review.


## B3 guarded native worker ownership (2026-10-18)

In opt-in execution mode, an atomic exclusive worker-directory claim in the
dedicated server output root prevents two independent guarded coordinators from
running native simulations against that same root concurrently. Normal native completion/failure and pre-start queued cancellation release
worker ownership; permanent request-ID claims remain.
A process crash retains the worker lock and therefore blocks new work until an
operator verifies that the previous process is no longer running and reconciles
artifacts. Never automatically delete an unexplained lock or resume an orphan.
This does not protect unrelated native desktop processes operating on the same
root: provision a dedicated guarded directory. Production browser write/execute
features remain disabled pending complete B certification and explicit approval.


## B3 isolated guarded configuration rollback (2026-10-18)

The opt-in configuration store retains native serializer ownership, flushes the
serialized temporary candidate before atomic replacement, and preserves the
previous saved configuration if serialization, flush or replacement fails.
Isolated regression tests do not certify full OS power-loss durability or
Windows original-file behavior; those remain in consolidated final acceptance.
No normal-user browser configuration writes are enabled.


## B3 missing intrabar negative-path test (2026-10-18)

An isolated guarded HTTP lifecycle test drives the genuine
`GuiApplicationService.run` owner with an injected native runner that raises
when required 1m intrabar candles are unavailable. It asserts the typed native
`ERROR` policy, redacted FAILED status, retained duplicate-ID claim, released
worker ownership and successful next submission under a new request ID.
This is controlled failure injection, **not** proof of original Data Lake
1m-candle gaps or independently executed browser/desktop trade parity.
Those remain in the final frozen-input certification. Production browser
execution/configuration writes stay disabled.


## B4 authenticated request-body boundary (2026-10-18)

The opt-in guarded mutation router authenticates the bearer token **before**
parsing user-supplied JSON. Malformed, scalar or array bodies are rejected
with bounded 422 responses only after authentication, and missing credentials
receive uniform 401 responses with bounded AUTH audit. Native job submission
and config persistence continue to share the existing validation and ownership
paths. This regression does not authorize enabling browser mutations; the
production launcher remains read-only pending explicit approval and
independent browser-versus-desktop certification.


## B3 cross-process configuration write ownership (2026-10-18)

The isolated guarded native-config save wrapper now atomically reserves a
per-configuration-ID directory before serialization and replacement. A second
guarded coordinator cannot silently overwrite the same configuration while the
first is writing. Normal save and failure paths release ownership; unexplained
crash-stale claims reject writes until manual operator reconciliation, with no
automatic lock stealing. Native serialization and the original-file boundary
remain unchanged. This prevents concurrent guarded-writer overlap, not external
desktop edits or physical power-loss faults. Final Windows certification and
explicit release approval are still required before exposing browser writes.


## B4 guarded request annotation regression correction (2026-10-18)

The raw full-suite log for the initial configuration-writer PR identified
16 guarded HTTP failures inherited from the preceding auth-before-JSON change:
the postponed Request annotation was imported only inside the router factory,
so FastAPI interpreted the required request object as a missing query parameter.
The guarded request type is now available at module scope. The original
authentication-order regression and existing guarded HTTP integration tests
must all pass again before merging this correction. An Actions workflow with
continue-on-error is **not** evidence of a passing full pytest suite.


## B3 read-only request inspection following restart (2026-10-18)

In the isolated, opt-in guarded coordinator, status lookup for a persistently
claimed request ID after coordinator restart now returns RECOVERY_UNVERIFIED
rather than implying the request never existed. It does **not** prove the run
completed, passed native manifest validation or is safe to resume. Cancellation,
progress history and result retrieval cannot operate on a lost native Future;
persistent request claims remain non-replayable. Only canonical non-linked
server-owned execution roots and genuine claim directories qualify; unknown,
invalid or symlinked claims do not produce a recovered status. Production
browser mutation routes remain absent, pending complete certification and
explicit approval.


## B1 isolated browser-to-native effective configuration comparison (2026-10-18)

A focused opt-in test independently invokes the native GuiApplicationService
from the desktop-side callable and through authenticated guarded HTTP, using
the same native v3 configuration and a deterministic injected runner. It checks
identical effective native typed configuration serialization, canonical
server-owned output path, native DataRequest parameters and injected-runner
output without implementing another simulation engine. This confirms the
configuration/request delegation contract **only**. Since the injected runner
does not produce real fills or saved manifests, ordered-trade, fee, equity and
artifact parity remain explicitly **NOT RUN** until independent frozen-input
browser-versus-desktop certification. Normal browser mutations remain disabled.


## B1 isolated guarded configuration-save serialization parity (2026-10-18)

An authenticated opt-in HTTP save now has an isolated fixture regression that
compares its persisted JSON **bytes** with independently calling native
`GuiApplicationService.save_config` on the same typed configuration, and loads
the result with `GuiApplicationService.load_config`. No browser-specific JSON
serializer, native-engine replacement, or original-file writes are introduced.
This test does not demonstrate Windows original-configuration parity, frozen
source execution, or trade/output accounting; those stay deferred to final B2
certification. Production browser writes remain disabled pending approval.


## CI gate: full pytest is blocking (2026-10-18)

The `full-suite-observation` GitHub Actions job now fails when its actual
`python -m pytest` execution fails. The prior `continue-on-error` step could
produce a green Python workflow despite genuine failures; this already masked
16 guarded HTTP regressions during B4 development. Required checks plus the raw
full-suite summary are still reviewed before merging. Windows original-file
certification remains separate and is not implicitly promoted by Linux CI.


## B2 isolated native-engine browser invocation regression (2026-10-18)

A guarded HTTP regression now invokes the existing `GuiApplicationService`
with an injected runner that executes the **actual native BacktestEngine** on
frozen synthetic candles. An independently invoked direct native service uses
the same source and config. The test compares full ordered trade frames exactly,
including timestamps, fees, P&L, equity, TP and END_OF_DATA exit behavior,
plus native effective config/request equality. No duplicate fill model is
introduced. The fixture bypasses the live ResearchRunner/Data Lake preparation
and reporter; it is **LIMITED engineering evidence**, not historical B2
certification, and does not establish 1m fill/slippage/partial/short coverage.
The final consolidated original-frozen-input desktop-versus-browser run and
saved manifest/artifact verification remain NOT RUN and release-blocking.
Normal browser execution and configuration writes remain disabled.


## B2 isolated ResearchRunner orchestration parity (2026-10-18)

An opt-in authenticated guarded HTTP test and independent direct native service
now each call the real `ResearchRunner`, driving the existing `BacktestEngine`
on identical frozen synthetic candles. It compares exact ordered trade DataFrames,
TP/end-of-data outcomes, the effective runner inputs, and byte-for-byte output
from the same isolated deterministic CSV reporter. Native `ResearchRunner`
orchestration is exercised; the bundle loader/preparation and reporter are
injected fixtures. Thus it **does not** certify the production Data Lake loader,
production manifest reporter, full 1m execution, or original saved artifacts.
Those remain NOT RUN for consolidated independent desktop-versus-browser B2
certification. Production browser mutation routes remain disabled.


## B2 completed-manifest read and recovered-integrity evidence (2026-10-18)

An isolated regression exercises the **real**, unmocked native
`CompletedRunReader`, `load_completed_manifest`, `artifact_path`, and guarded
read-only recovery verifier against a frozen fixture using the canonical
manifest/research contract and SHA-256 catalog entries. It verifies the summary
and **every** cataloged artifact, then tampers with the trade artifact and
requires `RECOVERY_UNVERIFIED` despite the surviving `COMPLETED` manifest and
valid summary. This covers native artifact reading and fail-closed recovery,
not production `BayesianSamplingCsvManifestReporter` *generation*, Data Lake
loading, or browser-versus-desktop historical saved-run equality. Those remain
NOT RUN for consolidated frozen-input certification. Production browser
mutation capabilities stay disabled.


## B2 production native reporter fixture parity (2026-10-18)

An isolated opt-in guarded HTTP test and an independently invoked native
GuiApplicationService now use the existing ResearchRunner orchestration,
BacktestEngine, and **actual BayesianSamplingCsvManifestReporter** with the
same frozen synthetic candles and prepared-feature fixture. The test compares
ordered trades, native reader summaries, stable request/config/cache/source
provenance, semantic trade fingerprints, and selected cataloged artifact bytes.
All cataloged artifacts are hash-verified with native `artifact_path` and
recovered-run verification. Volatile run IDs, timestamps, local paths, workbook
metadata and performance timings are not assumed equal. The Data Lake bundle
loader/prepared generation remain injected fixtures; therefore genuine
historical source-derived report parity remains **NOT RUN** pending independent
original-frozen-input Windows certification. Browser mutations stay disabled
for ordinary users until explicit release approval.


## B2 genuine isolated Binance ZIP loader and prepared-frame HTTP parity (2026-10-18)

Independent native GuiApplicationService and authenticated opt-in guarded HTTP
calls now exercise the actual `load_backtest_bundle` and `from_data_lake_bundle`
against isolated daily Binance-format ZIP candles. The test compares exact
canonical source identity, loaded candle frames, causal prepared feature
contexts, native request and normalized configuration. No production source
archives or canonical Data Lake are accessed. The downstream simulator and
reporter remain outside this focused loader/preparation test; earlier B2 tests
cover their native paths separately. The **combined full original-data
execution** and final desktop/browser comparison are still NOT RUN and must
remain release-blocking. Guarded mutations stay disabled for normal users.


## B2 combined default-native isolated ZIP execution parity (2026-10-18)

An isolated opt-in browser HTTP regression independently exercises the **default**
`GuiApplicationService` composition: genuine Binance daily ZIP loading, actual
Data Lake feature preparation/cache, `ResearchRunner`, `NativeStrategyPolicy`,
`NativeSimulator` and the production `BayesianSamplingCsvManifestReporter`.
A separate direct native service processes the same frozen temporary source ZIPs
and config. The test compares ordered trade rows, prepared identity, stable
native manifest sections, trade fingerprints, saved summaries and selected
artifact bytes, and verifies all cataloged artifact hashes. It does not touch
original Windows files or the canonical Data Lake; long/short/partial/SL1
representativeness and interactive browser/desktop acceptance remain NOT RUN.
Production guarded routes remain server-disabled for normal users pending
final consolidated certification and explicit release approval.


## B3 authenticated HTTP recovery after restart (2026-10-18)

An isolated regression now submits an opt-in guarded native job via authenticated
HTTP, closes its coordinator, and creates a fresh HTTP app against the same
persistent execution root. With the original request claim retained, the new
status endpoint returns only `RECOVERY_UNVERIFIED`, without inferring native
completion from old process memory. Unknown IDs, unauthenticated status,
orphan progress/cancellation, and replay all fail closed; no native rerun
occurs. This covers one process-restart lifecycle edge, not verified resume,
automated stale-lock reconciliation, crash-during-write durability or Windows
operator recovery. Ordinary browser mutations remain disabled.


## B2 native short-side guarded HTTP execution parity (2026-10-18)

The isolated frozen-candle native `BacktestEngine` regression now independently
invokes the desktop service and opt-in authenticated HTTP with both the earlier
long TP/end-of-data case and its mirrored short-side counterpart. The full
ordered trade DataFrames must match exactly, with direction-specific TP and
end-of-data exits and positive net P&L/equity on the short fixture. This test
uses the existing native engine; it is limited engineering coverage, not
original-history short/stop/partial certification. No normal browser execution
or configuration writes are enabled.


## B2 protective-stop native HTTP parity (2026-10-18)

The native-engine guarded HTTP trade regression now has four finite cases:
LONG/SHORT each taking an isolated +1R TP or protective SL, followed by the
native END_OF_DATA closure. An independently invoked native application service
and authenticated opt-in guarded HTTP must agree exactly on ordered trade rows,
including exit direction, fees, net P&L and equity. The native engine alone
resolves stops and targets; no browser-side fill calculations are added. These
are limited 15m synthetic fixtures, not original-history intrabar stop/slippage
or partial-profit certification. Normal browser mutation routes stay disabled.


## B2 guarded HTTP partial-profit then protective-stop regression (2026-10-18)

The frozen native-engine comparison adds a genuine `TP1_THEN_SL` execution
case through independently invoked direct `GuiApplicationService` and
opt-in authenticated guarded HTTP. The standard native `BacktestEngine`
performs the 50% TP1 and remaining protective-stop execution. Full ordered
trade frames must agree exactly; directional TP1/stop quantities, fee-inclusive
net P&L and exit reason are checked. This supplements native partial-profit
unit tests, but original historical intrabar ordering, slippage, partial-stop
SL1 and break-even variants remain deferred to final consolidated acceptance.
Normal browser mutations remain disabled pending explicit approval.


## B2 guarded HTTP TP1 then break-even exit (2026-10-18)

The isolated native-engine guarded HTTP comparison now additionally covers
`TP1_THEN_BE`: 50% take profit is realized before the remaining position
exits on native break-even protection. Full ordered trade frames, the composite
`long_final_exit_reason`, native TP1/stop quantities and fee-inclusive P&L
must match an independently invoked native service. This extends B2 execution
coverage but does not certify original historical fills, 1m timing, break-even
race conditions or release readiness. Production mutation routes remain off.


## B2 frozen one-minute execution sequences (2026-10-18)

The isolated guarded HTTP regression exercises native `BacktestEngine` on complete,
synthetic 1m candles separately from direct `GuiApplicationService`. The finite
long/short cases include first TP or stop, different-minute TP/SL touch order,
and TP1 followed by later break-even or protective stop, with nonzero configured
slippage. Exact ordered trade DataFrames, source candles, exit timestamps,
partial quantities, fee-inclusive net accounting and native composite exit
reasons are checked. These engineering fixtures do **not** certify original
historical 1m data, live browser UI invocation or original Windows saved
artifacts. Browser mutations remain disabled pending consolidated independent
Windows/desktop-versus-browser certification and explicit release approval.


## B3 crash-stale worker and interrupted request HTTP boundary (2026-10-18)

An isolated opt-in authenticated HTTP regression constructs both a surviving
server-owned request-ID claim and an unexplained native-worker directory claim
to represent the on-disk evidence remaining after an interrupted process.
The historical request is reported only as `RECOVERY_UNVERIFIED`; progress and
cancellation of the lost Future remain unavailable. Fresh submissions are
rejected and do not reserve a new request ID, steal the stale worker lock,
invoke native execution, or change the existing request claim. This is
controlled crash-state injection, not a real OS process-kill, recovered
run certification, or permission to remove stale ownership automatically.
The final Windows operator reconciliation, original artifact validation and
interruption testing remain deferred to consolidated certification. Production
browser execution and configuration writes remain disabled.


## B4 dormant guarded browser control surface (2026-10-18)

A separate React/TypeScript `GuardedRunControls` module prepares native v3
configuration save and guarded run submission, status, progress and cancellation.
Every mutating/inspection call additionally requires an explicit client-side
`enabled === true` argument and bearer token, validates bounded identifiers,
and delegates to the already-existing server-enforced opt-in guarded routes.
**The module is not imported or mounted by the production read-only App**;
there is no release flag, user-visible activation mechanism or background
polling. Server-side authentication and disabled-by-default route installation
remain the actual authorization boundary; client gating is defense in depth.
This is implementation/build coverage only, not independent browser interactive
certification or approval to enable configuration writes or execution. Do not
expose this module to normal browser users before consolidated certification
and explicit approval.


## B4 dormant guarded UI session isolation and request contract (2026-10-18)

The unmounted guarded React controls now associate asynchronous results with the
originating authorization session/epoch, clear stale status and progress on
session changes, and ignore late completions from prior sessions. The exported
request helpers reject disabled sessions and malformed tokens before building
HTTP operations. Node's built-in test runner executes the real TSX helper code
transformed with the existing Vite/esbuild dependency; mocked network tests
cover default denial, all five authenticated guarded API operations, request
bodies and bounded error handling. The browser build executes these tests before
TypeScript compilation. These are controlled client/helper tests, not real
interactive browser certification, OS-level interruption or approval to mount
the module. The production read-only App still does not import it, and server
execution/configuration mutations stay disabled until final certification and
explicit approval.


## B4 existing native configuration edit preparation (2026-10-18)

The dormant guarded React editor now reads a selected original validated saved
configuration through existing authenticated read-only `GET /api/v1/configs/{id}`
and pre-fills native JSON for review/edit before submitting it to the existing
opt-in native guarded config save route. It validates identifiers, refuses
missing/non-object responses and ignores late responses after session changes.
Node client contract tests exercise this read path and malformed payloads.
The production browser workspace still does **not** mount the editor; no normal
browser saves/execution are exposed. This is engineering coverage, not operator
file certification, UI click-through proof or authorization to enable writes.


## B4 config selection response ownership (2026-10-18)

The dormant guarded editor additionally invalidates pending saved-config load
responses when the selected configuration identifier changes. Changing the ID
clears the old editable JSON and suppresses outdated completion, preventing an
old config snapshot from appearing under another save destination. This is a
client-side precaution: server-native schema validation and guarded write locks
remain authoritative. Real interactive browser click-level coverage remains
outstanding; the production browser does not mount the control.


## B4 guarded saved-configuration rename durability (2026-10-18)

The opt-in native-backed configuration store now syncs the containing directory
on POSIX after atomic replacement of the already-fsynced serialized candidate.
An isolated regression verifies file-sync → rename → directory-sync ordering;
a separate injected post-rename sync failure propagates an error, leaves the
already-replaced candidate to be reconciled, and releases the per-ID write claim.
This is not a rollback guarantee or a substitute for actual crash/power-loss
and Windows filesystem verification. Ordinary production browser config writes
remain disabled and original saved configurations are untouched.


## B4 guarded React event-handler integration tests (2026-10-18)

A separate development-only Node test harness exercises the actual dormant
React TSX event handlers with controlled hook state: native config input/load,
selection changes during an in-flight load, edited native JSON save, job
submission, status/progress/cancel actions and token changes during an
in-flight request. The build remains gated on these tests. This is an isolated
simulated-event harness, not an installed interactive browser or an independent
Windows native UI certification. The normal read-only app continues not to
mount these controls and server-enforced guarded routes remain disabled.


## B4 guarded run selection ownership (2026-10-18)

The unmounted guarded React component now binds asynchronous job submit,
status, progress and cancellation result presentation to the job ID and
selection generation originating each request. Changing the selected job
clears prior status, phase and error, and late completions or rejections
cannot annotate a different selected job. Config edit/save/load errors are
similarly scoped to the original config selection. Simulated React event tests
exercise delayed results and ID changes for the four job operations. This
is not actual browser UI certification, not job cancellation of running native
work, and not authorization to expose guarded operations to normal users.


## B4 guarded request body resource boundary (2026-10-18)

The opt-in authenticated guarded HTTP adapter bounds native configuration-save
and job-submission JSON payloads to 4 MiB before decoding. It authenticates
first, rejects oversized declared lengths immediately, and independently counts
bytes received through chunked/streamed bodies so omitting or understating
Content-Length cannot bypass the limit. The 413 response and audit outcome are
sanitized; malformed JSON continues to receive 422. Isolated tests verify
both mutation handlers reject oversized input without invoking their native
owners. The limit applies only to experimental guarded mutations, not to saved
read-only results or original files, and grants no release authorization.


## B3/B4 guarded UI lifecycle outcome semantics (2026-10-18)

The development-only, unmounted React control surface now distinguishes
`ACCEPTED` (not completed), `CANCELLATION_UNAVAILABLE` (no cancellation
confirmed), `COMPLETED` (native worker completion, not verified saved results),
and `RECOVERY_UNVERIFIED` (claim survives but outcome and artifacts remain
unknown). For recovery-unverified requests it suppresses prior phase information
and disables repeat submission, progress and cancellation controls until a
different request is selected. It accepts only bounded enumerated native job
states with a matching request identifier, preventing an unexpected server
payload from being displayed as proof of completion. Simulated event-handler
tests exercise these states. No restart reconciliation or independent desktop-
versus-browser invocation is certified; the normal browser remains read-only.


## B3 verified saved-run inspection handoff (2026-10-18)

The dormant guarded React workspace now offers an explicit saved-run *folder ID*
inspection action, independent of the native guarded request ID. It uses the
pre-existing authenticated `GET /api/v1/runs/{run_id}` endpoint and the native
`CompletedRunReader` verification path; it does not infer an output mapping from
`ACCEPTED`, `COMPLETED` or `RECOVERY_UNVERIFIED` job states. Responses are
bounded to the originating token/session and selected folder, and malformed or
unavailable run payloads do not become successful confirmations. This is a
manually selected, read-only output verification handoff, **not** automatic
job-to-artifact correlation, independent browser UI exercise, a guarantee that
all expected original output files exist, or permission to turn on browser
execution. Complete certification must still compare identical frozen native
and browser invocations, saved manifests, outputs and original artifacts.


## B3 native reporter result to verified output association (2026-10-18)

The native `ResearchRunResult.output_dir` is assigned by the existing
reporter after its final manifest publication. While the original guarded
Future remains available in the same process and reports COMPLETED, the
guarded status owner may expose a bounded `verified_run_folder_id` only if
the native output directory is directly under the configured guarded root,
uses an allowlisted folder name and passes the already-existing full
cataloged-artifact verifier. No client-supplied request ID is used as an
output folder name. When validation fails or the native return does not
provide an output path, COMPLETED remains a *worker state* without a verified
folder field. A restarted process has only a durable request-ID claim and
still returns RECOVERY_UNVERIFIED; no mapping is reconstructed and no replay
is authorized. The dormant React UI offers a separate user-triggered
read-only inspection of the verified folder, not automatic acceptance of its
summary or a second artifact parser. Final independent Windows/browser
invocation and original-file certification remains required. Production
guarded execution/config writes remain disabled.


## Consolidated final operator certification handoff (2026-10-18)

Use `docs/browser_consolidated_final_certification.md` as the single finite
cross-gate checklist for authentic, **independently invoked** PySide6 desktop and
actual browser-UI/HTTP test-only guarded paths. It consolidates established A/B
proof and retained historical caveats rather than restarting historical tests.
The read-only launcher remains unchanged and ordinary guarded mutations remain
server-disabled pending independent Windows evidence and explicit release approval.


## B4 release-preparation hold (2026-10-19)

The independent GitHub review of merged #813–#819 accepts the four Windows
browser/PySide6 comparisons (16 trade rows and 13,274 cells) as **finite**
certification evidence, not as clean-build or universal historical proof.
The original executor manifests report `code_dirty=true`; untracked
harness/research sources, missing genuine TP1→BE and SL1/trailing combinations,
per-trade slippage/tick-order evidence, Windows filesystem-link privilege skips,
and hardware power-loss limits remain explicit release qualifications.

The production browser launcher must remain read-only. B4 preparation adds an
explicit fail-closed production release-request boundary and regression checks
that feature-like environment variables cannot attach guarded API routes.
**This is not a production enablement switch.** A subsequent, separately
reviewed authorization/composition change would require an explicit owner
approval, dedicated non-original execution/configuration roots, authenticated
loopback-only routing, bounded audit, real UI smoke on a clean release checkout,
raw full pytest and all required CI checks, and preservation of PySide6 fallback.
PR #501 stays held. Neither approval to prepare B4 nor passing this preparation
PR authorizes guarded browser execution or configuration writes.


## B4 Phase 3: review-only production composition (2026-10-19)

The new `compose_b4_review_only` entrypoint assembles a real, authenticated
**read-only** local browser app using the sole production launcher, after
verifying separate candidate configuration/execution roots through the existing
B4 preflight. It **does not** instantiate `BrowserGuardedIntegration`, mount
any `/api/v1/guarded/*` route, serve the certification-only React build, or
change the normal production launch command. Explicit `release_requested`
activation attempts are rejected before composing the service. Environment
values claiming release approval have no authority. Dedicated candidate roots
remain empty, original files and canonical Data Lake untouched.

This is a preparatory integration contract, **not** an enabled guarded production
composition or proof that a clean release build has passed final acceptance.
The separately isolated certification server remains the only working guarded
entrypoint. A distinct, reviewed activation PR would have to bind both the
server side and a conditional production UI, include fail-closed authorization,
audit/security gates and an isolated clean-checkout release smoke, then seek
fresh explicit user permission **before activation**. Keep #501 held and PySide6
fallback supported.


## B4 Phase 4: clean-checkout read-only release smoke (2026-10-19)

Run `python -m crypto_strategy_lab.browser_release_smoke` from an
**actual clean Git checkout** with optional FastAPI/TestClient dependencies
installed. The smoke rejects a dirty or untracked worktree before any HTTP
composition. It creates only disposable isolated fixture roots, assembles the
real production read-only FastAPI app through the reviewed Phase 3 composition,
and checks token denial, loopback Host restriction, read-only health, five
unavailable guarded write/job/status/progress/cancel routes and unchanged
fixture bytes. It prints the actual commit and bounded non-sensitive results.
This is an isolated application smoke, **not** the certified original Windows
data/browser-versus-PySide6 replay or a claim of hardened production activation.
Missing optional dependencies are errors for the operator smoke (while fixture
pytest tests may skip optional FastAPI-only coverage).

Any future production guarded server/UI composition remains a **separate**
reviewed implementation requiring explicit release owner approval, trusted
isolated writable roots, dedicated audit and a genuine Windows browser smoke.
No ordinary browser write or execution capability is enabled by this phase.


## B4 clean-checkout smoke CI gate (2026-10-19)

The Python tests workflow now runs the **actual** `python -m
crypto_strategy_lab.browser_release_smoke` command in a separate blocking
`b4-clean-checkout-release-smoke` Linux job, after checking out the PR
head and installing browser/API dependencies. It checks clean Git status,
reports the exact commit, exercises the production *read-only* FastAPI
composition with isolated fixtures and rejects every guarded operation.
This verifies the real release-smoke command at a clean CI checkout;
it does **not** repeat original Windows trading-parity certification or
authorize any production write/execute route. The PySide6 fallback remains
unchanged, and a separate release activation approval is still mandatory.


## B4 production static asset separation (2026-10-19)

The normal production launcher refuses a caller-selected static root named
`dist-certification` (including a filesystem alias resolving to that
directory) before constructing a native read service or FastAPI app.
This closes an accidental packaging path where the operator-only React
certification controls could otherwise appear in the normal read-only
browser, despite guarded API routes remaining disabled. Only the separate
opt-in certification server may serve the certification build. Existing
production `dist` and independently tested static fixtures remain
supported. This is a UI/release isolation guard, **not** user approval
or an implementation of guarded production activation.


## B4 cross-platform clean-checkout release smoke (2026-10-19)

The existing blocking `windows-smoke-safety` job now runs
`python -m crypto_strategy_lab.browser_release_smoke` against the exact
clean Windows Actions checkout, after installing the optional HTTP test
dependencies and before executing the existing Windows safety tests.
This complements the already-blocking Linux clean-checkout smoke and verifies
that real Windows path handling, local-only authentication, read-only mode,
missing guarded routes, and temporary-fixture preservation behave consistently.
It does **not** certify the workstation's original files or physical Windows
process interruptions again. Production guarded execution/configuration
writes stay disabled until an independent release approval.
