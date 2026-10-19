# B4 guarded browser activation review — preparation only

**Decision: NOT AUTHORIZED.** This is a security/rollback design for a later
separately reviewed release. It does not create a production enablement route,
accept an environment switch as approval, or authorize work on original files.

## Existing authoritative components

- Normal `browser_launcher.build_browser_readonly_runtime`: loopback-only,
  read-only API and ordinary React bundle. Explicit release request is denied.
  Certification-only static bundle selection is rejected.
- `browser_release_preflight`: require distinct existing canonical directories
  outside protected source, static, Data Lake, config and output trees.
- `browser_guarded_integration` and `browser_guarded_http`: already exercise
  native `GuiApplicationService` and native serialization, request ownership,
  authenticated guarded routes and sanitized bounded audit in a **separate
  operator-only certification composition**. Do not duplicate execution logic.
- `browser_release_smoke`: clean Git checkout, real read-only FastAPI,
  authentication, foreign Host/Origin, cross-port Origin, guarded route denial
  and untouched isolated fixtures. Blocking Linux and Windows CI jobs.

## Required separate activation change

1. Obtain explicit release-owner approval **after** reviewing this design.
   A ChatGPT message permitting *preparation* is not activation approval.
   No environment variable, browser query parameter, UI checkbox or token
   alone can confer release ownership.
2. Implement a separate production composition with server-owned authorization;
   refuse unsafe/absent approval **before constructing guarded services or
   mounting guarded routes**. Keep the existing read-only entrypoint default.
   Do not serve the certification React bundle as production UI.
3. Use the existing guarded native owners only, with distinct verified
   non-original writable configuration/execution roots and a loopback-bound
   per-session bearer token; no HTTP-supplied filesystem destinations.
4. Require bounded operation/outcome audit without credentials, configuration
   contents, request payloads, private paths, P&L or unredacted native
   exceptions. Treat missing audit persistence as a separately reviewed
   release-blocking decision, rather than silently claiming durable audit.
5. Preserve persistent request-ID and worker claims, fail-closed
   RECOVERY_UNVERIFIED behavior, no automatic retry/replay, and the
   CANCELLATION_UNAVAILABLE contract after a native worker starts.
6. Provide a reviewed production UI that displays actual server-advertised
   capabilities only after authentication, and invalidates state on token
   changes. Client-side gating is never server authorization.
7. Security review must cover unauthorized/previous-session token, foreign
   Host/Origin/cross-port, body size and malformed JSON, path traversal,
   symlink/junction cases, concurrent writers, process interruption, audit
   sanitization, normal read-only fallback, original data hashes and PySide6.

## Rollback and release hold

- Before any later activation, hash/freeze originals and record commit, source
  inputs, native configuration, isolated roots, smoke outputs and operator.
- No activation from this document or B4 preparation CI alone. A final clean
  release binary/worktree smoke and explicit approval remain necessary.
- On a suspected authorization or integrity defect, **stop accepting new
  guarded work** while preserving in-flight worker ownership and claims.
  Do not kill native work and then infer cancellation, remove stale locks,
  auto-replay jobs, or destroy evidence. A reviewer must reconcile artifacts
  using the native manifest/hash verifier.
- Restore the normal read-only launcher, retain PySide6 fallback, and verify
  original-file hashes before/after. Keep production guarded routes inaccessible
  until another explicit release decision.
- PR #501 remains HELD. No live trading bot changes.

## Accepted finite certification limitations

The four actual Windows browser/PySide6 UI pairs matched 16 trade rows and
13,274 cells, and physical/controlled lifecycle checks were recorded. The
executor worktree was dirty owing to untracked harness/research sources;
historical combined TP1→BE, executed SL1/trailing, full tick-order and
per-trade slippage were not independently observed. Windows symlink-privilege
skips and hardware power-loss limits remain qualifications, not universal
passes. See `browser_consolidated_windows_certification_2026-10-19.md`.


## Preparation integration: authenticated disabled-by-default capability contract

The production FastAPI app now exposes authenticated
`GET /api/v1/release/capabilities`, returning exact booleans
`{"execution": false, "configuration_editing": false}`.
It is intentionally **not** configurable by an environment flag, request,
or locally displayed checkbox. It never constructs guarded native services,
mounts guarded HTTP routes or creates writable files.

The ordinary React app reads these booleans along with its existing authenticated
health/catalog capability reads. It invalidates the advertised release state
on token change or failed reconnect, and mounts the already existing
`GuardedRunControls` only if *both* server booleans are exactly `true` and
the session is connected. Client-side visibility is **not authorization**;
the native server's independent guarded router/ownership gates still govern
every write and run.

Current production always advertises both as `false`. This integration
prepares the UI/server handshake for later approval, without enabling it.
The separate certification-only React app remains restricted to its own
operator-approved isolated server. A later activation implementation must
undergo a new independent review and receive explicit user authorization.


## Guarded server candidate implementation (2026-10-19)

The internal `compose_b4_guarded_candidate` factory prepares an **in-process
candidate**, not a production listener or startup flag. It defaults to denying
every call unless an explicit trusted Python caller supplies literal
`approval_granted=True`. Approval-like environment variables cannot enable it.
It requires a callable audit callback, the existing native service, validated
isolated writable roots and a strong session token before composing the
existing `BrowserGuardedIntegration` and `create_browser_app` guarded routes.
The candidate has no network listener and its integration must be closed by
the caller. The normal browser launcher remains read-only and does not invoke
this factory; its authenticated UI capability flags remain hard-OFF.

This is engineering preparation; simply passing the flag in fixture tests is
**not release-owner permission to activate**. Do not add a public CLI flag,
environment approval or automatic bootstrap. A later reviewed release change
must supply an authenticated, durable operation audit and explicit approval
records, and verify rollback before opening a production listener.


## B4 per-session audit journal preparation (2026-10-19)

`browser_release_audit.B4AuditJournal` provides an **optional, isolated,
operator-owned journal callback** for the unlaunched B4 candidate. It requires
a canonical, symlink/junction-free pre-existing audit directory and an
exclusive-create safe session filename. Each accepted event is a bounded JSON
line containing *only* an allowlisted operation and outcome. Writes flush
with `os.fsync`; reopening the same session filename fails instead of
overwriting existing evidence. Fixture tests cover duplicate journals,
private paths, malformed/sensitive event fields, link rejection, write failure
and actual authenticated guarded HTTP audit delivery.

**Important release blocker:** `browser_guarded_http` presently catches and
suppresses audit-callback exceptions so that a log-storage error cannot alter
native operations. This journal does not change that contract: its existence
is **not proof of fail-closed durable operation auditing**. Before any future
production activation, separately review whether to fail closed on journal
failure, how to reconcile an operation that commits before an audit failure,
how to manage disk-full/restart/rotation, and how to provision independent
audit-root ACLs and per-session ownership. Do not present an isolated
`fsync` success as hardware power-loss certification. The ordinary production
launcher remains read-only; PR #501 stays held.


## Candidate pre-operation audit admission (2026-10-19)

The internal B4 candidate opts into `guarded_require_audit_admission=True`.
Before calling the native save, run submission or cancel method, the HTTP router
must persist an allowlisted `ATTEMPT` record through its injected journal.
Missing or failing audit admission returns a sanitized 503 **before** invoking
native mutation. An audit failure on a later outcome also latches the candidate
to deny further mutations. The ordinary production browser still omits guarded
routes, and the separate certification harness retains its previous default
router behavior.

**Bounded guarantee:** a native mutation may already have committed by the
time its `SUCCESS` outcome audit fails. The response to that mutation is not
proof of rollback; preserve request/worker claims and verify native artifacts
before any manual resolution. Subsequent mutation requests fail closed.
Auditor filesystem durability, concurrency with in-flight work, host power loss
and restart reconciliation still require an independent final release review.


## B4 read-only request recovery evidence (2026-10-19)

`inspect_b4_recovery` reads a canonical isolated native execution root and
reports the presence/unknown state of the persistent request claim and native
worker lock. It **never** deletes locks, rewrites claims, replays a request,
resumes work, or labels the persisted request COMPLETED. When the operator
explicitly supplies a separate native saved-run folder ID, it calls the
existing native manifest/artifact hash verifier; even an
`ARTIFACTS_VERIFIED` result does **not** establish that the saved run belongs
to the named request. The association remains `UNVERIFIED`, and the request
remains `RECOVERY_UNVERIFIED`.

Inaccessible or unsafe roots/claims fail closed to unknown rather than
implicitly absent. This is read-only investigative evidence, **not** an
automated recovery API or permission to clear stale worker ownership. Audit
records deliberately omit request IDs, so they also cannot independently
establish request-to-run mapping. Keep rollback manual and fail closed until
independent native artifact reconciliation can supply stronger provenance.


## Read-only journal evidence verification (2026-10-19)

`inspect_b4_audit` validates the existing per-session journal's exact bounded
JSONL event schema from a canonical, unlinked directory. It rejects oversized,
empty, truncated, noncanonical, malformed and unexpected records, returning
`AUDIT_UNVERIFIED` without editing or repairing the file. A verified journal
reports only record and `ATTEMPT` counts and whether the last record was an
attempt without a recorded outcome. It does not contain request identifiers,
prove persistence through a hardware interruption, prove that an outcome was
recorded for every native commit, or associate a saved run with an in-flight
request. `AUDIT_VERIFIED` is **record-format verification only**, not release
approval, request completion, or ownership reconciliation.

Keep the read-only claim inspection from #832 authoritative for surviving
request/worker claims. Treat ambiguous native state as RECOVERY_UNVERIFIED,
preserve evidence, never replay automatically and never clear stale locks.


## B4 Windows blocking recovery/audit regression gate (2026-10-19)

The existing Windows CI safety job now also runs the real guarded HTTP,
native completed-manifest recovery, candidate composition, bounded audit
writer/verifier and read-only claim-reconciliation pytest modules. This
exercises Windows file and path semantics, exclusive audit creation, missing
or linked evidence, audit-admission refusal before mutations and preservation
of stale native worker/request claims using **temporary fixtures only**.

This is not new original-workstation parity certification or permission to
release the guarded server. The normal production launcher remains read-only;
physical interruption, power-loss durability and request-to-run provenance
limitations remain qualified. Do not automatically reclaim native locks.
