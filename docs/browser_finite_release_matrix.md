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

## Current action queue

- First check the operator-local browser configuration and chart/run projection gates; reuse existing `browser_configuration_parity_operator_gate.md` and `browser_chart_payload_parity_operator_gate.md` evidence instead of rewriting it.
- Resolve or clearly bound the TP1 verifier provenance discrepancy from retained records only; no need to rerun already matched BE/Fib suites.
- Inventory browser execution/config ownership and prepare a *disabled-by-default*, testable guarded integration plan; **do not enable** it in this phase.
- Keep draft PR #501 on hold; its separate limit-touch helper is not an approved second execution authority.

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
