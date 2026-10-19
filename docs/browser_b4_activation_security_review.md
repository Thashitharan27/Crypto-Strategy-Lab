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
